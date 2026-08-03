"""
일반현황(파일 다운로드) 통합 + 진짜 정원 기반 미스매치 분석 스크립트
------------------------------------------------------------------
이 파일 다운로드 버전은 API와 달리 진짜 "정원"과 "위도/경도"를 포함합니다.

처리 순서:
  1) 여러 공시차수(20231~20261) CSV를 하나로 합치고, 유치원별 최신 공시차수만 남김
  2) 정원/현원 합계 계산 + 진짜 충원율(현원/정원) 계산
  3) 좌표 -> 행정동 역조회 (카카오 API, merge_kinder_population.py와 캐시 공유)
  4) 행정동 단위로 집계 후 인구 데이터와 병합
  5) 커버율(정원/인구) 계산 + 미스매치 4분면 진단

사용법:
  1. KAKAO_API_KEY 입력
  2. INPUT_PATTERN 이 실제 파일 위치와 일치하는지 확인
  3. python final_mismatch_analysis.py 실행
  4. daegu_최종_미스매치_결과.csv 로 저장
"""

import pandas as pd
import requests
import time
import json
import os
import re
import glob

# ============================================
# 0. 설정
# ============================================
KAKAO_API_KEY = "860588e2100897c43eb155016f51d129"

INPUT_PATTERN = "data/ua_data/일반 현황_*.csv"          # 7개 공시차수 파일 전부 매칭
POPULATION_CSV = "data/ua_data/filtered_결과.csv"        # csv_viewer.py 결과 (0-6세 인구)

OUTPUT_CSV = "data/ua_data/daegu_최종_미스매치_결과.csv"
DEBUG_CSV = "data/ua_data/일반현황_통합_유치원별.csv"     # 유치원별 최신 데이터 확인용
REGION_CACHE_PATH = "data/ua_data/region_cache.json"     # merge_kinder_population.py와 캐시 공유


# ============================================
# 1. 여러 공시차수 파일 통합 + 최신값만 남기기
# ============================================
def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc, on_bad_lines="skip", engine="python")
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def combine_and_dedup(pattern):
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"'{pattern}' 패턴에 맞는 파일이 없습니다.")

    dfs = []
    for f in files:
        df = load_csv_auto(f)
        # 파일명에서 공시차수 추출 (예: 일반_현황_20261_대구광역시.csv -> 20261)
        m = re.search(r"(\d{5})", os.path.basename(f))
        df["_공시차수"] = int(m.group(1)) if m else 0
        dfs.append(df)
        print(f"[정보] {os.path.basename(f)} -> {len(df)}행 (공시차수 {df['_공시차수'].iloc[0]})")

    combined = pd.concat(dfs, ignore_index=True)
    print(f"\n[정보] 전체 합친 행수(중복포함): {len(combined)}")

    # 유치원명+주소를 키로, 공시차수가 가장 큰(최신) 행만 남김
    combined = combined.sort_values("_공시차수")
    dedup = combined.drop_duplicates(subset=["유치원명", "주소"], keep="last").copy()
    print(f"[정보] 유치원별 최신값만 남긴 행수: {len(dedup)}")
    return dedup


# ============================================
# 2. 정원/현원 합계 + 진짜 충원율 계산
# ============================================
def compute_real_fill_rate(df):
    capacity_cols = ["3세정원수", "4세정원수", "5세정원수", "혼합정원수", "특수학급정원수"]
    enrolled_cols = ["만3세원아수", "만4세원아수", "만5세원아수", "혼합원아수", "특수원아수"]

    df["정원_합계"] = df[capacity_cols].sum(axis=1, skipna=True)
    df["원아수_합계"] = df[enrolled_cols].sum(axis=1, skipna=True)

    # 인가총정원수(공식 총정원)와 연령별 합산 정원이 다를 수 있어 둘 다 남김 (교차검증용)
    df["충원율_실제"] = df.apply(
        lambda row: (row["원아수_합계"] / row["정원_합계"]) if row["정원_합계"] > 0 else None,
        axis=1,
    )
    return df


# ============================================
# 3. 좌표 -> 행정동 역조회 (기존 캐시 재사용)
# ============================================
def load_cache(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def coord_to_dong(lat, lng, api_key, cache):
    key = f"{lat},{lng}"
    if key in cache:
        return cache[key]

    url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"x": lng, "y": lat}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()
        documents = data.get("documents", [])
        h_doc = next((d for d in documents if d.get("region_type") == "H"), None)
        if h_doc:
            result = {"구군": h_doc.get("region_2depth_name"), "읍면동": h_doc.get("region_3depth_name")}
        else:
            result = {"구군": None, "읍면동": None}
    except Exception as e:
        print(f"[경고] 역지오코딩 실패 ({lat},{lng}): {e}")
        result = {"구군": None, "읍면동": None}

    cache[key] = result
    return result


def add_dong_column(df, api_key):
    cache = load_cache(REGION_CACHE_PATH)
    gu_list, dong_list = [], []
    total = len(df)

    for i, row in enumerate(df.itertuples(), start=1):
        lat, lng = getattr(row, "위도", None), getattr(row, "경도", None)
        if pd.isna(lat) or pd.isna(lng):
            gu_list.append(None)
            dong_list.append(None)
            continue
        result = coord_to_dong(lat, lng, api_key, cache)
        gu_list.append(result["구군"])
        dong_list.append(result["읍면동"])
        if i % 20 == 0 or i == total:
            print(f"[역지오코딩 진행] {i}/{total}")
        time.sleep(0.05)

    save_cache(REGION_CACHE_PATH, cache)
    df["구군_행정"] = gu_list
    df["읍면동_행정"] = dong_list
    return df


# ============================================
# 4. 이름 정규화 (매칭용)
# ============================================
def normalize_name(name):
    if pd.isna(name):
        return None
    name = str(name).replace("·", ".").replace(" ", "")
    return re.sub(r"[().]", "", name)


# ============================================
# 5. 미스매치 4분면 진단
# ============================================
def classify_mismatch(row, cover_median, fill_median):
    # 유치원이 아예 없는 지역은 "판정불가"가 아니라 가장 심각한 카테고리인 "완전공백"으로 별도 표시
    if row["유치원수"] == 0:
        return "완전공백"
    if pd.isna(row["커버율"]) or pd.isna(row["충원율_동단위"]):
        return "판정불가"
    cover_high = row["커버율"] >= cover_median
    fill_high = row["충원율_동단위"] >= fill_median
    if cover_high and fill_high:
        return "양호"
    elif cover_high and not fill_high:
        return "질적미스매치"
    elif not cover_high and fill_high:
        return "물리적부족"
    else:
        return "이중취약"


# ============================================
# 6. 메인
# ============================================
def main():
    if KAKAO_API_KEY == "여기에_카카오_REST_API_키_입력":
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(POPULATION_CSV):
        print(f"[오류] 파일 없음: {POPULATION_CSV}")
        return

    # 1) 통합 + 중복 제거
    print("[1단계] 공시차수 통합 및 최신값 추출...")
    kinder = combine_and_dedup(INPUT_PATTERN)

    # 2) 정원/현원/충원율 계산
    print("\n[2단계] 정원/현원 합계 및 충원율 계산...")
    kinder = compute_real_fill_rate(kinder)
    print(f"[정보] 충원율_실제 평균: {kinder['충원율_실제'].mean():.1%}, "
          f"중앙값: {kinder['충원율_실제'].median():.1%}")

    # 디버그 저장
    kinder.to_csv(DEBUG_CSV, index=False, encoding="utf-8-sig")
    print(f"[정보] 유치원별 통합 결과를 '{DEBUG_CSV}'에 저장했습니다.")

    # 3) 좌표 -> 행정동
    print("\n[3단계] 좌표 -> 행정동 역조회...")
    kinder = add_dong_column(kinder, KAKAO_API_KEY)
    n_failed = kinder["읍면동_행정"].isna().sum()
    print(f"[3단계 완료] 행정동 매칭 실패: {n_failed} / {len(kinder)}")

    # 4) 행정동 단위 집계
    print("\n[4단계] 행정동 단위 집계 및 인구 데이터 병합...")
    kinder["_구군_norm"] = kinder["구군_행정"].apply(normalize_name)
    kinder["_읍면동_norm"] = kinder["읍면동_행정"].apply(normalize_name)

    agg = kinder.groupby(["_구군_norm", "_읍면동_norm"]).agg(
        유치원수=("유치원명", "count"),
        정원_합계=("정원_합계", "sum"),
        원아수_합계=("원아수_합계", "sum"),
    ).reset_index()
    agg["충원율_동단위"] = agg["원아수_합계"] / agg["정원_합계"]

    population = load_csv_auto(POPULATION_CSV)
    population["_구군_norm"] = population["시군구명"].apply(normalize_name)
    population["_읍면동_norm"] = population["읍면동명"].apply(normalize_name)

    merged = population.merge(agg, on=["_구군_norm", "_읍면동_norm"], how="left")
    merged["유치원수"] = merged["유치원수"].fillna(0)
    merged["정원_합계"] = merged["정원_합계"].fillna(0)
    merged["원아수_합계"] = merged["원아수_합계"].fillna(0)

    # 5) 커버율 계산 (드디어 진짜 공급/수요)
    merged["커버율"] = merged.apply(
        lambda row: (row["정원_합계"] / row["영유아인구_0_6세"]) if row["영유아인구_0_6세"] > 0 else None,
        axis=1,
    )

    # 6) 미스매치 4분면 (전체 중앙값 기준)
    # 중앙값은 "유치원이 있는 지역"만 기준으로 계산 (완전공백 지역까지 포함하면 0이 많아져 중앙값이 왜곡됨)
    has_kinder = merged["유치원수"] > 0
    cover_median = merged.loc[has_kinder, "커버율"].median()
    fill_median = merged.loc[has_kinder, "충원율_동단위"].median()
    print(f"\n[정보] 커버율 중앙값(유치원 있는 지역 기준): {cover_median:.3f}, "
          f"충원율 중앙값: {fill_median:.3f}")
    merged["미스매치_유형"] = merged.apply(
        lambda row: classify_mismatch(row, cover_median, fill_median), axis=1
    )

    merged = merged.drop(columns=["_구군_norm", "_읍면동_norm"])
    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행)")
    print("\n=== 미스매치 유형 분포 ===")
    print(merged["미스매치_유형"].value_counts())


if __name__ == "__main__":
    main()