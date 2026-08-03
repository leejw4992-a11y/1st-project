"""
6장 지수 산출 CLI — Min-Max 정규화 + 엔트로피 가중치 + 종합지수 + 민감도 분석
------------------------------------------------------------------
실제 계산 로직은 analysis_lib.compute_entropy_composite()에 있다 (FastAPI 서버와 공유).
이 스크립트는 그 결과를 CSV로 저장하고 콘솔에 보기 좋게 출력하는 역할만 한다.

사용법: python ua_entropy_composite_index.py
"""

import os
from analysis_lib import load_base_df, compute_entropy_composite, generate_quadrant_chart

OUTPUT_CSV = "data/daegu_entropy_index_result.csv"
OUTPUT_CHART = "data/daegu_quadrant_chart.png"


def main():
    df = load_base_df()
    print(f"[정보] {len(df)}개 읍면동 로드")

    result = compute_entropy_composite(df)
    out_df = result["df"]
    weights = result["weights"]
    diag = result["diagnostics"]

    print(f"[정보] 군위군 {diag['n_gunwi_excluded']}개 면 지역 -> 종합지수 산출은 도심 7개 구 기준, "
          f"군위군은 별도 극단사례로 표시")

    print("\n=== 엔트로피 가중치 ===")
    for col, w in weights.items():
        print(f"  {col}: {w:.4f}")

    print(f"\n[검증] 엔트로피 지수 vs 단순평균 지수 상관계수: "
          f"{diag['method_correlation_pearson']:.3f} (순위상관: {diag['method_correlation_spearman']:.3f})")
    print("      -> 1에 가까울수록 '가중치 산정 방법과 무관하게 결론이 안정적'이라는 근거")

    print("\n=== 사분면 분포 ===")
    print(out_df["사분면"].value_counts())

    print(f"\n[민감도 분석] 가중치 ±20% 무작위 흔들기 200회 -> "
          f"평균 순위상관: {diag['sensitivity_mean_rank_corr']:.3f}, "
          f"최소 순위상관: {diag['sensitivity_min_rank_corr']:.3f}")
    print("      -> 0.9 이상이면 '가중치를 상당폭 바꿔도 취약지역 순위는 거의 변하지 않는다'로 해석")

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    out_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}' 저장 ({len(out_df)}행)")

    chart_path = generate_quadrant_chart(df, OUTPUT_CHART)
    print(f"[완료] 사분면 차트를 '{chart_path}'에 저장했습니다.")

    print("\n=== 인프라지수(엔트로피) 하위 10개 동 (도심 7개 구 기준, 취약지역 후보) ===")
    is_gunwi = out_df["시군구명"] == "군위군"
    print(out_df.loc[~is_gunwi].nsmallest(10, "인프라지수_엔트로피")[
        ["시군구명", "읍면동명", "전체_커버율", "체육밀도", "인프라지수_엔트로피", "미스매치_유형"]
    ].to_string(index=False))
    print(f"\n[참고] 군위군은 '인프라 사각지대 극단사례'로 별도 표기했으며 위 순위·중앙값 계산에서 제외했습니다.")


if __name__ == "__main__":
    main()
