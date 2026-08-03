"""
공통 분석 라이브러리
------------------------------------------------------------------
ua_entropy_composite_index.py, ua_regression_analysis.py, FastAPI 서버(app/main.py)가
모두 이 모듈의 함수를 가져다 쓴다. 로직을 한 곳에만 두어 (1) CLI 스크립트로 돌리는
결과와 (2) 웹에서 보여주는 결과가 서로 어긋나지 않도록 한다.
"""

import os
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FINAL_CSV = os.path.join(BASE_DIR, "data", "daegu_final_dataset.csv")
CENTROID_CSV = os.path.join(BASE_DIR, "data", "dong_centroids.csv")

INDEX_INDICATORS = ["전체_커버율", "체육밀도"]


# ============================================
# 데이터 로드
# ============================================
def load_base_df() -> pd.DataFrame:
    df = pd.read_csv(FINAL_CSV)
    df["체육밀도"] = df.apply(
        lambda r: (r["체육시설수"] / r["유아인구_3_6세"] * 1000) if r["유아인구_3_6세"] > 0 else 0,
        axis=1,
    )
    return df


def load_with_centroids() -> pd.DataFrame:
    """지도 표시용: 좌표까지 합쳐진 전체 데이터"""
    df = compute_entropy_composite(load_base_df())["df"]
    centroids = pd.read_csv(CENTROID_CSV)
    merged = df.merge(centroids, on=["시군구명", "읍면동명"], how="left")
    return merged


# ============================================
# 6장: Min-Max 정규화 + 엔트로피 가중치 + 종합지수
# ============================================
def minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(0.5, index=series.index)
    return (series - lo) / (hi - lo)


def entropy_weights(norm_df: pd.DataFrame) -> pd.Series:
    n = len(norm_df)
    k = 1 / np.log(n)
    eps = 1e-9
    shifted = norm_df + eps
    p = shifted / shifted.sum(axis=0)
    e_j = -k * (p * np.log(p)).sum(axis=0)
    d_j = 1 - e_j
    w_j = d_j / d_j.sum()
    return w_j


def sensitivity_analysis(norm_df: pd.DataFrame, base_weights: pd.Series,
                          n_trials: int = 200, perturb: float = 0.2, seed: int = 42):
    rng = np.random.default_rng(seed)
    base_index = (norm_df * base_weights).sum(axis=1)
    base_rank = base_index.rank()
    corrs = []
    for _ in range(n_trials):
        factors = rng.uniform(1 - perturb, 1 + perturb, size=len(base_weights))
        perturbed = base_weights.values * factors
        perturbed = perturbed / perturbed.sum()
        trial_index = (norm_df * perturbed).sum(axis=1)
        corrs.append(base_rank.corr(trial_index.rank(), method="spearman"))
    return float(np.mean(corrs)), float(np.min(corrs))


def compute_entropy_composite(df: pd.DataFrame) -> dict:
    """
    df에 인프라지수/사분면 컬럼을 추가해서 돌려준다.
    군위군(8장 원칙)은 지수·중앙값 계산에서 제외하고 별도 표기만 한다.
    반환값: {"df": ..., "weights": {...}, "diagnostics": {...}}
    """
    df = df.copy()
    is_gunwi = df["시군구명"] == "군위군"
    core = df.loc[~is_gunwi].copy()

    work = core[INDEX_INDICATORS].copy()
    for col in INDEX_INDICATORS:
        cap = work[col].quantile(0.99)
        work[col] = work[col].clip(upper=cap)

    norm = pd.DataFrame({col: minmax(work[col]) for col in INDEX_INDICATORS})
    weights = entropy_weights(norm)

    equal_weights = pd.Series(1 / len(INDEX_INDICATORS), index=INDEX_INDICATORS)
    entropy_index = (norm * weights).sum(axis=1)
    equal_index = (norm * equal_weights).sum(axis=1)

    method_corr = float(entropy_index.corr(equal_index, method="pearson"))
    rank_corr = float(entropy_index.rank().corr(equal_index.rank(), method="spearman"))
    mean_sens, min_sens = sensitivity_analysis(norm, weights)

    df["정규_전체_커버율"] = np.nan
    df["정규_체육밀도"] = np.nan
    df["인프라지수_엔트로피"] = np.nan
    df["인프라지수_단순평균"] = np.nan
    df.loc[core.index, "정규_전체_커버율"] = norm["전체_커버율"]
    df.loc[core.index, "정규_체육밀도"] = norm["체육밀도"]
    df.loc[core.index, "인프라지수_엔트로피"] = entropy_index
    df.loc[core.index, "인프라지수_단순평균"] = equal_index

    price_col = "평균제곱미터당가격_만원"
    has_price = df[price_col].notna() & (~is_gunwi)
    df["정규_집값"] = np.nan
    df.loc[has_price, "정규_집값"] = minmax(df.loc[has_price, price_col])

    infra_median = df.loc[~is_gunwi, "인프라지수_엔트로피"].median()
    price_median = df.loc[has_price, "정규_집값"].median()

    def quadrant(row):
        if row["시군구명"] == "군위군":
            return "군위군(별도사례)"
        if pd.isna(row["정규_집값"]):
            return "가격데이터없음"
        infra_high = row["인프라지수_엔트로피"] >= infra_median
        price_high = row["정규_집값"] >= price_median
        if infra_high and not price_high:
            return "2사분면(가성비最)"
        elif infra_high and price_high:
            return "1사분면(프리미엄)"
        elif not infra_high and not price_high:
            return "3사분면(정책개입)"
        else:
            return "4사분면(학군편중?)"

    df["사분면"] = df.apply(quadrant, axis=1)

    return {
        "df": df,
        "weights": weights.to_dict(),
        "diagnostics": {
            "method_correlation_pearson": method_corr,
            "method_correlation_spearman": rank_corr,
            "sensitivity_mean_rank_corr": mean_sens,
            "sensitivity_min_rank_corr": min_sens,
            "n_gunwi_excluded": int(is_gunwi.sum()),
            "infra_median": float(infra_median),
            "price_median": float(price_median) if not pd.isna(price_median) else None,
        },
    }


# ============================================
# 7장: 회귀분석 (모델 A, 모델 B)
# ============================================
def _compute_vif(X: pd.DataFrame) -> dict:
    Xc = sm.add_constant(X)
    return {
        col: float(variance_inflation_factor(Xc.values, i + 1))
        for i, col in enumerate(X.columns)
    }


def _run_ols(df: pd.DataFrame, y_col: str, x_cols: list) -> dict:
    data = df[[y_col] + x_cols].dropna()
    y = data[y_col]
    X = data[x_cols]

    X_std = (X - X.mean()) / X.std()
    y_std = (y - y.mean()) / y.std()

    model = sm.OLS(y, sm.add_constant(X)).fit()
    model_std = sm.OLS(y_std, sm.add_constant(X_std)).fit()

    coefficients = []
    for col in x_cols:
        p = float(model.pvalues[col])
        coefficients.append({
            "variable": col,
            "coef": float(model.params[col]),
            "standardized_coef": float(model_std.params[col]),
            "p_value": p,
            "significant_at_0.05": p < 0.05,
        })

    return {
        "formula": f"{y_col} ~ " + " + ".join(x_cols),
        "n_obs": int(len(data)),
        "n_total": int(len(df)),
        "r_squared": float(model.rsquared),
        "r_squared_adj": float(model.rsquared_adj),
        "f_pvalue": float(model.f_pvalue),
        "intercept": float(model.params["const"]),
        "coefficients": coefficients,
        "vif": _compute_vif(X),
    }


def compute_regression_models(df: pd.DataFrame) -> dict:
    """
    군위군은 8장 원칙에 따라 회귀에서도 제외.
    모델 A: 충원율 ~ 영유아인구 + 체육시설수 + 고용률(맞벌이비율 근사치)
    모델 B: 집값 ~ 체육시설수 + 학원정원합계 + 전체_커버율 + 수성구더미 + 합계출산율_2025

    [팀 병합 노트] 팀원이 만든 ua_regression_and_quadrant.py에는 모델 A/B 모두에
    '합계출산율_2025'가 들어있었다. 실제로 두 모델에 각각 추가해 비교한 결과:
      - 모델 A: R² 변화 거의 없음(0.0805->0.0806), 출산율 계수 p=0.92(전혀 유의하지 않음)
        -> 추가하지 않음
      - 모델 B: R² 0.439->0.470, 조정R² 0.422->0.451로 유의미하게 개선, 출산율 계수 p=0.005
        -> VIF도 전부 2 미만이라 다중공선성 문제 없음 -> 채택
    합계출산율_2025는 구 단위 통계(9개 구·군이 각각 1개 값을 공유)라는 점은
    고용률과 동일한 한계이며, 발표 시 함께 명시할 것.
    """
    df = df[df["시군구명"] != "군위군"].copy()
    df["수성구더미"] = (df["시군구명"] == "수성구").astype(int)

    model_a = _run_ols(df, "전체_충원율", ["영유아인구_0_6세", "체육시설수", "고용률"])
    model_b = _run_ols(df, "평균제곱미터당가격_만원",
                        ["체육시설수", "학원정원합계", "전체_커버율", "수성구더미", "합계출산율_2025"])

    return {
        "model_a": {
            **model_a,
            "label": "모델 A - 충원율 회귀 (돌봄 이용에 영향을 주는 요인)",
            "caveat": "고용률은 구 단위 통계로, 동 단위 맞벌이비율 데이터가 없어 사용한 근사치입니다.",
        },
        "model_b": {
            **model_b,
            "label": "모델 B - 집값 회귀 (미취학 인프라 vs 학군 프리미엄 분리)",
            "caveat": "수성구더미 계수는 인프라와 무관한 '학군 지역 자체' 프리미엄을 나타냅니다. "
                      "합계출산율_2025은 구 단위 통계(고용률과 동일한 한계)입니다.",
        },
    }


# ============================================
# 사분면 산점도 PNG 생성
# ------------------------------------------------
# [팀 병합 노트] 팀원의 ua_regression_and_quadrant.py에 있던 matplotlib/seaborn
# 시각화를 그대로 가져오되, 인프라지수는 단순평균(50:50)이 아니라 6장의 엔트로피
# 가중치 지수(compute_entropy_composite)를 사용하도록 통일했다. 대시보드(FastAPI)는
# 인터랙티브 지도를, 이 함수는 발표/보고서에 바로 붙일 수 있는 정적 이미지를 만든다.
# ============================================
QUADRANT_COLORS = {
    "1사분면(프리미엄)": "#2E8B57",
    "2사분면(가성비最)": "#4169E1",
    "3사분면(정책개입)": "#FF4500",
    "4사분면(학군편중?)": "#A9A9A9",
}


def _set_korean_font():
    """Windows(Malgun Gothic)/Mac(AppleGothic)/Linux(Noto Sans CJK) 순서로 사용 가능한 한글 폰트를 찾는다."""
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    available = {f.name for f in fm.fontManager.ttflist}
    for candidate in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans CJK JP"]:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def generate_quadrant_chart(df: pd.DataFrame, output_path: str = "daegu_quadrant_chart.png") -> str:
    import matplotlib.pyplot as plt
    import seaborn as sns

    result = compute_entropy_composite(df)
    plot_df = result["df"]
    plot_df = plot_df[~plot_df["사분면"].isin(["가격데이터없음", "군위군(별도사례)"])].copy()

    diag = result["diagnostics"]
    infra_med = diag["infra_median"]
    price_med = diag["price_median"]

    _set_korean_font()
    plt.figure(figsize=(10, 7))
    sns.scatterplot(
        data=plot_df, x="정규_집값", y="인프라지수_엔트로피",
        hue="사분면", palette=QUADRANT_COLORS, s=70, alpha=0.85,
    )
    plt.axvline(x=price_med, color="gray", linestyle="--", linewidth=1)
    plt.axhline(y=infra_med, color="gray", linestyle="--", linewidth=1)
    plt.title("대구시 읍면동별 인프라지수(엔트로피 가중) vs 아파트 집값", fontsize=14, pad=12)
    plt.xlabel("아파트 ㎡당 평균 가격 (Min-Max 정규화)", fontsize=11)
    plt.ylabel("돌봄·체육 인프라 종합지수 (엔트로피 가중, Min-Max 정규화)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ============================================
# 인구이동(MDIS) 기반 추가 인사이트
# ------------------------------------------------
# [출처] 통계청 국내인구이동통계 마이크로데이터(MDIS) 2023~2025년, 대구 관련
# 940,045건 전수 분석 (별도 팀원 산출물 PDF에서 반영).
#
# 이 인사이트의 정원/현원 수치는 본 프로젝트의 '통합_정원'/'통합_현원'(유치원+
# 어린이집, 학원 제외)과 4개 동(성내3동/고성동/범어1동/평리5동) 전부 소수점까지
# 정확히 일치함을 교차검증했다 — 같은 최종 CSV 위에서 인구이동 데이터를 추가
# 결합해 만든 분석임을 확인.
#
# 인구이동 원자료(MDIS)와 2SFCA 반경 커버율 계산 자체는 이 프로젝트 코드베이스에
# 포함되어 있지 않다 (팀원이 별도로 수행). 아래는 그 결과 수치를 그대로 옮겨
# 담은 것이며, 원자료를 공유받으면 동 단위로 전체 파이프라인에 결합할 수 있다.
# ============================================
MIGRATION_INSIGHTS = {
    "source": "통계청 국내인구이동통계 마이크로데이터(MDIS) 2023~2025, 대구 관련 940,045건 전수 분석",
    "insight_1": {
        "title": "영유아 가구는 집을 보고 움직입니다 — 그 결과가 돌봄 공백입니다",
        "reason_table": [
            {"사유": "주택", "영유아동반이동": 0.478, "전체이동": 0.278, "배율": 1.72},
            {"사유": "가족", "영유아동반이동": 0.246, "전체이동": 0.263, "배율": 0.94},
            {"사유": "직업", "영유아동반이동": 0.103, "전체이동": 0.252, "배율": 0.41},
            {"사유": "교육", "영유아동반이동": 0.078, "전체이동": 0.067, "배율": 1.16},
        ],
        "top4_net_inflow": [
            {"동": "고성동", "구": "북구", "순유입_3년": 1122},
            {"동": "성내3동", "구": "중구", "순유입_3년": 1083},
            {"동": "평리5동", "구": "서구", "순유입_3년": 939},
            {"동": "범어1동", "구": "수성구", "순유입_3년": 864},
        ],
        "note": "이 4개 동은 동시에 대구에서 커버율이 가장 낮은 동네(18.3~47.0%)입니다. "
                "전입사유는 주된 사유 1개만 기재되므로 이 수치만으로 부모가 돌봄 인프라를 "
                "고려하지 않았다고 단정할 수는 없으나, 결과로 보면 돌봄 인프라가 주거지 "
                "선택에 반영되지 않고 있다는 뜻입니다.",
        "quote": "아이를 데리고 이사한 가구의 47.8%가 주택을 주된 이유로 꼽았고, 직업은 "
                 "10.3%뿐입니다. 그런데 가장 많이 이사해 들어간 네 동네가 하필 대구에서 "
                 "어린이집 자리가 가장 없는 곳입니다.",
    },
    "insight_2": {
        "title": "정책 우선지역 4곳 — 3년간 아이가 늘었는데 자리는 그대로입니다",
        "priority_dongs": [
            {"동": "성내3동", "구": "중구", "인구_0_6세": 1545, "정원": 283, "현원": 282,
             "충원율": 0.996, "순유입_3년": 1083, "주택사유비율": 0.861, "아파트연식": 3},
            {"동": "고성동", "구": "북구", "인구_0_6세": 1608, "정원": 579, "현원": 548,
             "충원율": 0.946, "순유입_3년": 1122, "주택사유비율": 0.740, "아파트연식": 3},
            {"동": "범어1동", "구": "수성구", "인구_0_6세": 1313, "정원": 617, "현원": 597,
             "충원율": 0.968, "순유입_3년": 864, "주택사유비율": 0.490, "아파트연식": 5},
            {"동": "평리5동", "구": "서구", "인구_0_6세": 1188, "정원": 288, "현원": 241,
             "충원율": 0.837, "순유입_3년": 939, "주택사유비율": 0.821, "아파트연식": 3},
        ],
        "note": "행정동 경계를 넘는 통원을 반영한 반경 커버율(거리감쇠 2SFCA, 1km)로 "
                "보정해도 4곳 모두 100% 미만(56.5~71.5%)으로 물리적 부족 판정이 유지됩니다.",
        "quote": "성내3동에는 0~6세가 1,545명 삽니다. 정원은 283석이고, 그 283석에 282명이 "
                 "다닙니다. 남은 자리는 한 자리입니다.",
    },
    "insight_3": {
        "title": "남는 자리를 줄이면 안 되는 곳이 있습니다",
        "groups": [
            {"갈래": "유출 심화", "동수": 28, "순이동률_3년": -0.400, "유휴정원": 8158,
             "아파트연식": 28, "처방": "감축 · 기능 전환"},
            {"갈래": "유입·보합", "동수": 11, "순이동률_3년": 0.024, "유휴정원": 3889,
             "아파트연식": 23, "처방": "유지 (감축 금지)"},
        ],
        "examples": [
            {"동": "신암1동", "구": "동구", "순이동률_3년": 0.475, "아파트연식": 2,
             "충원율": 0.304, "설명": "지금은 텅 비어 보이지만 신축 입주 중이라 정원을 "
             "줄이면 3년 뒤 성내3동이 됩니다."},
            {"동": "대명11동", "구": "남구", "순이동률_3년": -0.917,
             "설명": "3년간 영유아가 91.7% 빠져나간 곳으로, 정원 감축을 검토할 수 있습니다."},
        ],
        "quote": "정원이 남는다고 줄이면 안 됩니다. 신암1동은 지금 충원율 30%지만 3년 만에 "
                 "아이가 47% 늘고 있는 신축 지역입니다. 줄이는 순간 3년 뒤 성내3동이 됩니다.",
    },
    "policy_recommendations": [
        "의무설치 정원 기준을 세대수가 아닌 실제 영유아 밀도로 상향",
        "고지가 지역 국공립 임차료 보조로 민간 진입 장벽 완화",
        "유출 심화 28개 동은 감축이 아닌 기능 전환, 유입 11개 동은 현행 유지",
    ],
    "caveat": "본 분석은 상관관계이며 인과관계가 아닙니다. '집값이 높아서 어린이집이 "
              "부족하다'가 아니라, 재개발이라는 공통 요인이 가격 상승과 영유아 유입을 "
              "동시에 일으키고 시설 공급만 뒤처진 구조로 해석하는 것이 타당합니다.",
}


def get_migration_insights() -> dict:
    return MIGRATION_INSIGHTS
