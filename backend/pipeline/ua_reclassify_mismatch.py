"""
미스매치 유형 재분류 스크립트
------------------------------------------------------------
daegu_최종_통합결과_보정.csv(150개 동, 출장소 병합 완료)를 대상으로
'통합_커버율'/'통합_충원율'(유치원+어린이집 합산 기준) 중앙값을 기준으로
미스매치 4분면 + 완전공백을 다시 분류한다.

기존에는 유치원만 반영한 '커버율'/'충원율_동단위'로 분류했으나, 어린이집을
더한 지금은 '통합_커버율'/'통합_충원율'이 훨씬 정확한 공급 지표이므로 교체한다.

입력: data/ua_data/daegu_최종_통합결과_보정.csv
출력: data/ua_data/daegu_최종_통합결과_최종.csv

사용법: python ua_reclassify_mismatch.py
"""

import pandas as pd
import os

INPUT_DIR = "data/ua_data"
INPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_보정.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_최종.csv"


def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def classify(row, cover_median, fill_median):
    if row["유치원수"] == 0 and row["어린이집수"] == 0:
        return "완전공백"
    if pd.isna(row["통합_커버율"]) or pd.isna(row["통합_충원율"]):
        return "판정불가"
    cover_high = row["통합_커버율"] >= cover_median
    fill_high = row["통합_충원율"] >= fill_median
    if cover_high and fill_high:
        return "양호"
    elif cover_high and not fill_high:
        return "질적미스매치"
    elif not cover_high and fill_high:
        return "물리적부족"
    else:
        return "이중취약"


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"[오류] 파일 없음: {INPUT_CSV}")
        return

    df = load_csv_auto(INPUT_CSV)
    print(f"[정보] {len(df)}행 로드")

    has_supply = (df["유치원수"] > 0) | (df["어린이집수"] > 0)
    cover_median = df.loc[has_supply, "통합_커버율"].median()
    fill_median = df.loc[has_supply, "통합_충원율"].median()
    print(f"[정보] 통합_커버율 중앙값(공급 있는 동 기준): {cover_median:.3f}")
    print(f"[정보] 통합_충원율 중앙값: {fill_median:.3f}")

    df["미스매치_유형"] = df.apply(lambda r: classify(r, cover_median, fill_median), axis=1)

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(df)}행)")
    print("\n=== 미스매치 유형 분포 (재분류 후) ===")
    print(df["미스매치_유형"].value_counts())


if __name__ == "__main__":
    main()