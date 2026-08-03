"""
주민등록인구및세대현황(월간) 여러 파일 통합 스크립트 (v2 - 실제 구조 반영)
------------------------------------------------------------
실제 파일 구조 확인 결과:
  - 파일 하나에 이미 대구 10개 행(대구 전체 + 9개 구/군)만 들어있음 (별도 필터링 불필요)
  - 파일명은 기간 범위(예: 202307_202312)이고, 그 안에 여러 '달'이 컬럼으로 나란히 있음
    예) "2026년01월_거주자 인구수", "2026년01월_세대수", ..., "2026년06월_남여 비율"
  - 즉 "가로형"(월별 컬럼) 구조 -> "세로형"(월별 행) 시계열로 변환해야 분석하기 좋음

사용법:
  1. data/monthly 폴더에 기간별 CSV들(202307_202312, 202401_202412 등)을 모아두세요.
  2. python ua_monthly_population_processor.py 실행
  3. data/monthly/대구_인구세대_월별통합.csv 로 저장됩니다 (세로형, 기준월별로 정리됨)
"""

import pandas as pd
import glob
import os
import re

# ============================================
# 0. 설정
# ============================================
INPUT_DIR = "data/monthly"
INPUT_PATTERN = os.path.join(INPUT_DIR, "*.csv")
OUTPUT_CSV = os.path.join(INPUT_DIR, "대구_인구세대_월별통합.csv")

REGION_COL = "행정구역"  # 지역명이 들어있는 컬럼명 (실제 확인된 값)

# 컬럼명 안의 "년MM월_지표명" 패턴을 잡는 정규식
MONTH_COL_PATTERN = re.compile(r"(\d{4})년(\d{2})월_(.+)")


# ============================================
# 1. 유틸 함수
# ============================================
def load_csv_auto(path):
    for enc in ["cp949", "euc-kr", "utf-8-sig", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc, thousands=",")
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def extract_bjdong_code(text):
    """'대구광역시 중구 (2711000000)' 형태에서 괄호 안 법정동코드만 추출"""
    if pd.isna(text):
        return None
    m = re.search(r"\((\d+)\)", str(text))
    return m.group(1) if m else None


def wide_to_long(df):
    """가로형(월별 컬럼) -> 세로형(월별 행)으로 변환"""
    if REGION_COL not in df.columns:
        print(f"[경고] '{REGION_COL}' 컬럼이 없습니다. 실제 컬럼: {list(df.columns)[:5]}...")
        return pd.DataFrame()

    df["법정동코드"] = df[REGION_COL].apply(extract_bjdong_code)

    records = []
    for col in df.columns:
        m = MONTH_COL_PATTERN.match(col)
        if not m:
            continue
        year, month, metric = m.groups()
        yyyymm = f"{year}{month}"
        for _, row in df.iterrows():
            records.append({
                "행정구역": row[REGION_COL],
                "법정동코드": row["법정동코드"],
                "기준월": yyyymm,
                "지표": metric,
                "값": row[col],
            })

    if not records:
        return pd.DataFrame()

    long_df = pd.DataFrame(records)
    # 지표(거주자 인구수, 세대수 등)를 다시 컬럼으로 펼침 -> 한 행 = 한 지역의 한 달 데이터
    wide_again = long_df.pivot_table(
        index=["행정구역", "법정동코드", "기준월"], columns="지표", values="값", aggfunc="first"
    ).reset_index()
    wide_again.columns.name = None
    return wide_again


# ============================================
# 2. 메인
# ============================================
def main():
    files = sorted(glob.glob(INPUT_PATTERN))
    if not files:
        print(f"[오류] '{INPUT_PATTERN}' 패턴에 맞는 파일이 없습니다.")
        print(f"       '{INPUT_DIR}' 폴더에 파일들이 들어있는지 확인하세요.")
        return

    print(f"[정보] {len(files)}개 파일 발견")

    all_dfs = []
    for path in files:
        df = load_csv_auto(path)
        long_df = wide_to_long(df)
        if long_df.empty:
            print(f"[경고] {os.path.basename(path)} -> 변환된 데이터 없음 (건너뜀)")
            continue
        all_dfs.append(long_df)
        months = sorted(long_df["기준월"].unique())
        print(f"  {os.path.basename(path)} -> {len(long_df)}행, 기준월 {months[0]}~{months[-1]}")

    if not all_dfs:
        print("[오류] 처리된 데이터가 없습니다.")
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["법정동코드", "기준월"], keep="last")
    combined = combined.sort_values(["법정동코드", "기준월"])

    combined.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] 총 {len(combined)}행을 '{OUTPUT_CSV}'에 저장했습니다.")
    print(f"[정보] 포함된 기준월 범위: {sorted(combined['기준월'].unique())}")
    print(f"[정보] 컬럼: {list(combined.columns)}")


if __name__ == "__main__":
    main()