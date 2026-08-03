"""
학원 포함 최종 재분류 스크립트
------------------------------------------------------------
※ 중요한 한계: 학원 데이터엔 '현원'(실제 등록 아동수) 정보가 없고 '정원'만 있음.
   따라서 커버율(공급 지표)에는 학원 정원을 더할 수 있지만,
   충원율(실제 이용 지표)에는 반영할 수 없다 (기존 유치원+어린이집 현원만 사용).
   -> 공급 쪽만 더 완전해지고, 이용률 쪽은 기존과 동일하다는 점을 발표 시 명시할 것.

계산:
  전체_정원 = 통합_정원(유치원+어린이집) + 학원정원합계
  전체_커버율 = 전체_정원 / 영유아인구_0_6세
  전체_충원율 = 통합_충원율 그대로 사용 (학원 현원 데이터 없어 변경 불가)

입력: data/ua_data/daegu_최종_통합결과_학원포함.csv
출력: data/ua_data/daegu_최종_통합결과_학원지수반영.csv

사용법: python ua_reclassify_with_academy.py
"""

import pandas as pd
import os

INPUT_DIR = "data/ua_data"
INPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_학원포함.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_학원지수반영.csv"


def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def classify(row, cover_median, fill_median):
    # 완전공백 기준: 유치원+어린이집+학원 전부 0곳인 경우로 확장
    if row["유치원수"] == 0 and row["어린이집수"] == 0 and row["학원수"] == 0:
        return "완전공백"
    if pd.isna(row["전체_커버율"]) or pd.isna(row["전체_충원율"]):
        return "판정불가"
    cover_high = row["전체_커버율"] >= cover_median
    fill_high = row["전체_충원율"] >= fill_median
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

    # 전체 정원/커버율 계산 (학원 정원 포함)
    df["전체_정원"] = df["통합_정원"] + df["학원정원합계"]
    df["전체_커버율"] = df.apply(
        lambda r: (r["전체_정원"] / r["영유아인구_0_6세"]) if r["영유아인구_0_6세"] > 0 else None, axis=1
    )
    # 충원율은 학원 현원 데이터가 없어 기존 통합_충원율을 그대로 사용
    df["전체_충원율"] = df["통합_충원율"]

    has_supply = (df["유치원수"] > 0) | (df["어린이집수"] > 0) | (df["학원수"] > 0)
    cover_median = df.loc[has_supply, "전체_커버율"].median()
    fill_median = df.loc[has_supply, "전체_충원율"].median()
    print(f"[정보] 전체_커버율 중앙값: {cover_median:.3f}")
    print(f"[정보] 전체_충원율 중앙값: {fill_median:.3f}")

    df["미스매치_유형"] = df.apply(lambda r: classify(r, cover_median, fill_median), axis=1)

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(df)}행)")
    print("\n=== 미스매치 유형 분포 (학원 포함 재분류 후) ===")
    print(df["미스매치_유형"].value_counts())
    print("\n[참고] 충원율은 학원 현원 데이터가 없어 유치원+어린이집 기준 그대로입니다.")


if __name__ == "__main__":
    main()