"""
7장 회귀분석 CLI — "우리 지수가 임의가 아님을 증명"하는 검증 도구
------------------------------------------------------------------
실제 계산 로직은 analysis_lib.compute_regression_models()에 있다 (FastAPI 서버와 공유).
이 스크립트는 결과를 사람이 읽기 좋은 텍스트로 정리해 콘솔 출력 + 파일 저장만 한다.

모델 A: 전체_충원율 ~ 영유아인구_0_6세 + 체육시설수 + 고용률(맞벌이비율 근사치)
모델 B: 평균제곱미터당가격_만원 ~ 체육시설수 + 학원정원합계 + 전체_커버율 + 수성구더미

공통 원칙(8장): 군위군은 도심과 성격이 다른 극단치라 회귀에서도 제외한다.

사용법: python ua_regression_analysis.py
"""

import os
from analysis_lib import load_base_df, compute_regression_models

OUTPUT_TXT = "data/daegu_regression_result.txt"


def format_model(result: dict) -> str:
    lines = [f"\n{'='*70}", result["label"], "=" * 70]
    lines.append(f"표본 수(결측 제거 후): {result['n_obs']} / 전체 {result['n_total']}")
    lines.append(f"\n[회귀식] {result['formula']}")
    lines.append(f"\nR² = {result['r_squared']:.4f}  (조정 R² = {result['r_squared_adj']:.4f})")
    lines.append(f"F검정 p-value = {result['f_pvalue']:.4g}")

    lines.append(f"\n{'변수':<20}{'계수(B)':>14}{'표준화계수(β)':>16}{'p-value':>12}{'유의성':>8}")
    for c in result["coefficients"]:
        p = c["p_value"]
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
        lines.append(f"{c['variable']:<20}{c['coef']:>14.5f}{c['standardized_coef']:>16.4f}{p:>12.4g}{sig:>8}")
    lines.append(f"{'(절편)':<20}{result['intercept']:>14.5f}")
    lines.append("\n(*** p<0.01, ** p<0.05, * p<0.1. 표준화계수 β는 절대값이 클수록 상대적 영향력이 크다는 뜻)")

    lines.append("\n[다중공선성 점검 VIF] (10 이상이면 문제 소지)")
    for col, v in result["vif"].items():
        lines.append(f"  {col}: {v:.2f}")

    lines.append(f"\n[참고] {result['caveat']}")
    return "\n".join(lines)


def main():
    df = load_base_df()
    results = compute_regression_models(df)

    report = ["대구 영유아 돌봄 인프라 분석 — 회귀분석 결과 (군위군 제외, 도심 7개 구 기준)"]
    report.append(format_model(results["model_a"]))
    report.append(format_model(results["model_b"]))

    text = "\n".join(report)
    print(text)

    os.makedirs(os.path.dirname(OUTPUT_TXT), exist_ok=True)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\n[완료] 회귀분석 결과를 '{OUTPUT_TXT}'에 저장했습니다.")


if __name__ == "__main__":
    main()
