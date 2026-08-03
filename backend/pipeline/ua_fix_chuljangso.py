"""
출장소 분할 보정 스크립트
------------------------------------------------------------
'다사읍'/'다사읍서재출장소', '논공읍'/'논공읍공단출장소' 문제 해결.

원인: 인구 통계는 '출장소' 단위로 더 세밀하게 나뉘어 있지만, 카카오 좌표->행정구역
API는 이 세부 단위를 반환하지 않고 항상 상위 '읍' 이름만 준다. 그 결과 시설이
전부 '읍' 행으로만 집계되고 '출장소' 행은 구조적으로 항상 공급 0이 됨.

해결: 세밀한 구분을 포기하고, 읍 전체 단위로 인구/시설을 합쳐 하나의 행으로
재계산한다. (좌표 기반으로는 출장소 단위 분해가 원천적으로 불가능하기 때문)

입력:
  - data/ua_data/daegu_최종_통합결과_어린이집포함.csv

출력:
  - data/ua_data/daegu_최종_통합결과_보정.csv

사용법:
  python ua_fix_chuljangso.py
"""

import pandas as pd
import os

INPUT_DIR = "data/ua_data"
INPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_어린이집포함.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_보정.csv"

MERGE_GROUPS = {
    "다사읍(전체)": ["다사읍", "다사읍서재출장소"],
    "논공읍(전체)": ["논공읍", "논공읍공단출장소"],
}

SUM_COLS = [
    "영아인구_0_2세", "유아인구_3_6세", "영유아인구_0_6세",
    "유치원수", "정원_합계", "원아수_합계",
    "체육시설수", "유아특화_체육시설수", "유아가능_체육시설수",
    "어린이집수", "어린이집정원", "어린이집현원",
    "통합_정원", "통합_현원",
]

RATIO_COLS = [
    ("충원율_동단위", "원아수_합계", "정원_합계"),
    ("커버율", "정원_합계", "영유아인구_0_6세"),
    ("통합_커버율", "통합_정원", "영유아인구_0_6세"),
    ("통합_충원율", "통합_현원", "통합_정원"),
]

CARRY_FIRST_COLS = [
    "시도명", "시군구명",
    "경제활동인구_천명", "취업자_천명", "경제활동참가율", "고용률", "실업률",
    "출생아수_2023", "합계출산율_2023", "출생아수_2024", "합계출산율_2024",
    "출생아수_2025", "합계출산율_2025", "신혼부부수_2023", "신혼부부수_2024",
    "영유아인구_0_5세_2022", "영유아인구_0_5세_2023", "영유아인구_0_5세_2024", "영유아인구_0_5세_2025",
]


def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def merge_group(df, new_name, old_names):
    rows = df[df["읍면동명"].isin(old_names)]
    if rows.empty:
        print(f"[경고] '{old_names}' 행을 찾을 수 없습니다.")
        return None

    merged = {"읍면동명": new_name}

    for col in CARRY_FIRST_COLS:
        if col in rows.columns:
            merged[col] = rows[col].iloc[0]

    for col in SUM_COLS:
        if col in rows.columns:
            merged[col] = rows[col].sum()

    for out_col, num_col, denom_col in RATIO_COLS:
        denom = merged.get(denom_col, 0)
        merged[out_col] = (merged[num_col] / denom) if denom and denom > 0 else None

    return merged


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"[오류] 파일 없음: {INPUT_CSV}")
        return

    df = load_csv_auto(INPUT_CSV)
    print(f"[정보] 원본 {len(df)}행 로드")

    all_old_names = [name for names in MERGE_GROUPS.values() for name in names]
    remaining = df[~df["읍면동명"].isin(all_old_names)].copy()

    new_rows = []
    for new_name, old_names in MERGE_GROUPS.items():
        merged_row = merge_group(df, new_name, old_names)
        if merged_row is not None:
            new_rows.append(merged_row)
            old_data = df[df["읍면동명"].isin(old_names)]
            cover_str = f"{merged_row['통합_커버율']:.1%}" if merged_row["통합_커버율"] is not None else "-"
            print(f"\n[{new_name}] = {' + '.join(old_names)}")
            print(f"  영유아인구: {old_data['영유아인구_0_6세'].sum()}, "
                  f"유치원수: {old_data['유치원수'].sum()}, "
                  f"어린이집수: {old_data['어린이집수'].sum()}, "
                  f"통합_커버율: {cover_str}")

    new_df = pd.DataFrame(new_rows)
    result = pd.concat([remaining, new_df], ignore_index=True, sort=False)

    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(result)}행, 원본 {len(df)}행에서 "
          f"{len(df) - len(result)}행 감소)")
    print("[참고] '미스매치_유형' 컬럼은 병합된 두 행에 대해 재분류가 필요합니다 "
          "(전체 데이터 중앙값 기준으로 다시 계산해야 함).")


if __name__ == "__main__":
    main()