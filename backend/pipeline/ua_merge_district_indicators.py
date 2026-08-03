"""
구·군 단위 사회지표를 읍면동 단위 최종 결과에 병합
------------------------------------------------------------
daegu_최종_통합결과_체육시설포함.csv(152개 동)에, 구·군 단위 사회지표
(daegu_구군별_사회지표_통합.csv, daegu_구군별_영유아인구_연도별추이.csv)를
'시군구명' 기준으로 병합한다. 같은 구 안의 모든 동은 그 구의 값을 그대로 공유한다.
(주의: 동 단위로 세분화된 값이 아니라 구 전체 대표값이 반복되는 것 -> 발표 시
"이 지표들은 구 단위 참고값"이라고 명시할 것)

출력:
  - data/ua_data/daegu_최종_통합결과_전체.csv

사용법:
  python ua_merge_district_indicators.py
"""

import pandas as pd
import os

INPUT_DIR = "data/ua_data"

DONG_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_체육시설포함.csv"
GUGUN_SOCIAL_CSV = f"{INPUT_DIR}/daegu_구군별_사회지표_통합.csv"
GUGUN_AGE_TREND_CSV = f"{INPUT_DIR}/daegu_구군별_영유아인구_연도별추이.csv"

OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_전체.csv"


def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def main():
    for p in [DONG_CSV, GUGUN_SOCIAL_CSV, GUGUN_AGE_TREND_CSV]:
        if not os.path.exists(p):
            print(f"[오류] 파일 없음: {p}")
            return

    dong = load_csv_auto(DONG_CSV)
    social = load_csv_auto(GUGUN_SOCIAL_CSV)
    age_trend = load_csv_auto(GUGUN_AGE_TREND_CSV)

    print(f"[정보] 동 단위 데이터 {len(dong)}행, 구군 사회지표 {len(social)}행, "
          f"구군 영유아추이 {len(age_trend)}행 로드")

    # 매칭 전 이름 일치 여부 확인 (둘 다 짧은 구군명이라 그대로 매칭되어야 함)
    dong_gugun = set(dong["시군구명"].unique())
    social_gugun = set(social["구군"].unique())
    not_matched = dong_gugun - social_gugun
    if not_matched:
        print(f"[경고] 사회지표에 없는 구군: {not_matched}")

    merged = dong.merge(social, left_on="시군구명", right_on="구군", how="left")
    merged = merged.merge(age_trend, left_on="시군구명", right_on="구군", how="left", suffixes=("", "_dup"))

    # 중복된 '구군' 컬럼 정리 (병합 키로만 쓰고 원래 시군구명이 있으니 제거)
    drop_cols = [c for c in merged.columns if c == "구군" or c.endswith("_dup")]
    merged = merged.drop(columns=drop_cols)

    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행, {len(merged.columns)}열)")

    # 매칭 안 된 행 확인 (구군 사회지표 컬럼 중 하나라도 NaN인 경우)
    check_col = "합계출산율_2025" if "합계출산율_2025" in merged.columns else None
    if check_col:
        n_missing = merged[check_col].isna().sum()
        print(f"[정보] '{check_col}' 기준 매칭 실패 행: {n_missing} / {len(merged)}")


if __name__ == "__main__":
    main()