"""
3-7 사회지표(맞벌이·출산·경제활동·신혼부부·영유아인구 추이) 정리 스크립트
------------------------------------------------------------------
KOSIS류 CSV는 헤더가 2~3줄에 걸쳐 있는 경우가 많아, 파일마다 실제 헤더 구조에 맞게
개별 파싱한 뒤, 대구 9개 구·군 단위로 하나의 표에 정리한다.

지리적 단위가 파일마다 다르다는 점에 주의:
  - 구·군 단위(9개): 경제활동인구, 출생아수/합계출산율, 신혼부부수, 연령별인구현황
  - 시도 단위(대구 전체 1개 값): 시도별 맞벌이가구
  - 전국 단위(지역 구분 없음): 18세미만자녀 맞벌이가구

출력:
  - data/ua_data/daegu_구군별_사회지표_통합.csv   (구·군 9행: 출생아수/출산율/신혼부부수/경제활동지표)
  - data/ua_data/daegu_구군별_영유아인구_연도별추이.csv (구·군 x 연도, 0~6세 인구 추이)
  - data/ua_data/대구_맞벌이가구_배경자료.csv     (시도/전국 단위 배경 참고용, 구군 구분 없음)

사용법:
  python ua_process_social_indicators.py
"""

import pandas as pd
import re
import os

# ============================================
# 0. 설정
# ============================================
INPUT_DIR = "data/ua_data"

ECON_CSV = f"{INPUT_DIR}/시군구_경제활동인구_총괄_20260728173232.csv"
BIRTH_CSV = f"{INPUT_DIR}/시군구_출생아수__합계출산율_20260728171141.csv"
NEWLYWED_CSV = f"{INPUT_DIR}/시군구별_신혼부부_수_20260728090519.csv"
DUALINCOME_SIDO_CSV = f"{INPUT_DIR}/시도별_맞벌이_가구_20260728085343.csv"
DUALINCOME_U18_CSV = f"{INPUT_DIR}/18세_미만_자녀가_있는_맞벌이_가구_20260728085520_분석(전년_대비_증감,증감률).csv"
AGE_POP_CSVS = {
    2022: f"{INPUT_DIR}/202212_202212_연령별인구현황_연간.csv",
    2023: f"{INPUT_DIR}/202312_202312_연령별인구현황_연간.csv",
    2024: f"{INPUT_DIR}/202412_202412_연령별인구현황_연간.csv",
    2025: f"{INPUT_DIR}/202512_202512_연령별인구현황_연간.csv",
}

OUT_GUGUN = f"{INPUT_DIR}/daegu_구군별_사회지표_통합.csv"
OUT_AGE_TREND = f"{INPUT_DIR}/daegu_구군별_영유아인구_연도별추이.csv"
OUT_BACKGROUND = f"{INPUT_DIR}/대구_맞벌이가구_배경자료.csv"

DAEGU_DISTRICTS = ["수성구", "달서구", "달성군", "군위군", "중구", "동구", "서구", "남구", "북구"]
# ↑ 주의: 반드시 긴 이름을 먼저 확인해야 함. "서구"가 "달서구"의 부분 문자열이라
#   짧은 이름을 먼저 매칭하면 "달서구"를 "서구"로 잘못 인식하는 버그가 생김.


def extract_district(label):
    """'2201 대구 중구', '22010 중구', '대구광역시 중구 (2711000000)' 등에서 구·군명만 추출"""
    if pd.isna(label):
        return None
    label = str(label)
    for d in DAEGU_DISTRICTS:
        if d in label:
            return d
    return None


# ============================================
# 1. 경제활동인구 (구·군, 최신 반기 = 2025년 하반기)
# ============================================
def parse_econ():
    df = pd.read_csv(ECON_CSV, encoding="cp949", header=[0, 1], thousands=",")
    df.columns = [f"{a}||{b}" for a, b in df.columns]
    region_col = df.columns[0]

    latest_block = "H202502 2025.2/2"
    keep_metrics = {
        "T2 경제활동인구 (천명)": "경제활동인구_천명",
        "T3 취업자 (천명)": "취업자_천명",
        "T6 경제활동참가율 (％)": "경제활동참가율",
        "T7 고용률 (%)": "고용률",
        "T8 실업률 (％)": "실업률",
    }

    out = pd.DataFrame()
    out["구군"] = df[region_col].apply(extract_district)
    for metric, new_name in keep_metrics.items():
        col = f"{latest_block}||{metric}"
        if col in df.columns:
            out[new_name] = df[col]
        else:
            print(f"[경고] 경제활동인구: '{col}' 컬럼 없음")
    out = out.dropna(subset=["구군"])
    return out


# ============================================
# 2. 출생아수 / 합계출산율 (구·군, 2023~2025)
# ============================================
def parse_birth():
    df = pd.read_csv(BIRTH_CSV, encoding="cp949", header=[0, 1], thousands=",")
    df.columns = [f"{a}||{b}" for a, b in df.columns]
    region_col = df.columns[0]

    out = pd.DataFrame()
    out["구군"] = df[region_col].apply(extract_district)

    year_blocks = {
        2023: "Y2023 2023",
        2024: "Y2024 2024",
        2025: "Y2025 Y2025 2025 p)",
    }
    for year, block in year_blocks.items():
        birth_col = f"{block}||T1 출생아수"
        rate_col = f"{block}||T2 합계출산율"
        if birth_col in df.columns:
            out[f"출생아수_{year}"] = df[birth_col]
        if rate_col in df.columns:
            out[f"합계출산율_{year}"] = df[rate_col]

    # 대구광역시 전체 합계 행(구군 추출 안 되는 행)은 제외, 구군만 남김
    out = out.dropna(subset=["구군"])
    return out


# ============================================
# 3. 신혼부부 수 (전국 표에서 대구만 필터)
# ============================================
def parse_newlywed():
    df = pd.read_csv(NEWLYWED_CSV, encoding="cp949", thousands=",")
    daegu = df[df["행정구역별(1)"] == "대구광역시"].copy()
    daegu = daegu[daegu["행정구역별(2)"] != "소계"]  # 대구 전체 소계 행 제외, 구군만
    out = pd.DataFrame()
    out["구군"] = daegu["행정구역별(2)"].apply(extract_district)
    out["신혼부부수_2023"] = daegu["2023"].values
    out["신혼부부수_2024"] = daegu["2024"].values
    out = out.dropna(subset=["구군"])
    return out


# ============================================
# 4. 연령별인구현황 -> 0~5세 인구, 연도별 (구·군)
# ⚠ 주의: 이 파일들은 5세 컬럼까지만 있고 6세 컬럼이 없음(다운로드 범위 제한으로 추정).
#   본 분석(daegu_최종_통합결과_체육시설포함.csv)은 0~6세 기준이라 이 추이표는
#   기준이 다르다는 점에 유의할 것. 6세 포함 데이터가 필요하면 재다운로드 필요.
# ============================================
def parse_age_population():
    all_years = []
    for year, path in AGE_POP_CSVS.items():
        df = pd.read_csv(path, encoding="cp949", thousands=",")
        age_cols = [f"{year}년_계_{age}세" for age in range(0, 6)]  # 0~5세까지만 존재
        missing = [c for c in age_cols if c not in df.columns]
        if missing:
            print(f"[경고] {year}년 파일에 없는 컬럼: {missing}")
        existing_cols = [c for c in age_cols if c in df.columns]

        out = pd.DataFrame()
        out["구군"] = df["행정구역"].apply(extract_district)
        out["연도"] = year
        out["영유아인구_0_5세"] = df[existing_cols].sum(axis=1)
        out = out.dropna(subset=["구군"])
        all_years.append(out)

    combined = pd.concat(all_years, ignore_index=True)
    return combined


# ============================================
# 5. 배경자료 (시도/전국 단위 - 구군 구분 없음)
# ============================================
def parse_background():
    rows = []

    # 5-1. 시도별 맞벌이가구 (대구광역시 1개 행)
    df1 = pd.read_csv(DUALINCOME_SIDO_CSV, encoding="cp949", header=[0, 1], thousands=",")
    df1.columns = [f"{a}||{b}" for a, b in df1.columns]
    region_col = df1.columns[0]
    daegu_row = df1[df1[region_col] == "대구광역시"]
    for year in [2023, 2024, 2025]:
        col = f"{year}||- 맞벌이가구비율 (%)"
        if col in df1.columns and not daegu_row.empty:
            rows.append({"구분": "대구광역시_맞벌이가구비율", "연도": year, "값": daegu_row[col].values[0]})

    # 5-2. 전국 18세미만자녀 맞벌이가구 비율 (전국 '계' 1개 행, 원데이터만)
    df2 = pd.read_csv(DUALINCOME_U18_CSV, encoding="cp949", header=[0, 1, 2], thousands=",")
    df2.columns = [f"{a}||{b}||{c}" for a, b, c in df2.columns]
    region_col2 = df2.columns[0]
    total_row = df2[df2[region_col2] == "계"]
    for year in [2023, 2024, 2025]:
        col = f"{year}||- 맞벌이 가구 비율 (%)||원데이터"
        if col in df2.columns and not total_row.empty:
            rows.append({"구분": "전국_18세미만자녀_맞벌이가구비율", "연도": year, "값": total_row[col].values[0]})

    return pd.DataFrame(rows)


# ============================================
# 6. 메인
# ============================================
def main():
    print("[1/5] 경제활동인구 파싱...")
    econ = parse_econ()
    print(f"  -> {len(econ)}개 구군")

    print("[2/5] 출생아수/합계출산율 파싱...")
    birth = parse_birth()
    print(f"  -> {len(birth)}개 구군")

    print("[3/5] 신혼부부수 파싱...")
    newlywed = parse_newlywed()
    print(f"  -> {len(newlywed)}개 구군")

    print("[4/5] 연령별인구현황(0-6세 추이) 파싱...")
    age_trend = parse_age_population()
    print(f"  -> {len(age_trend)}행 (구군 x 연도)")

    print("[5/5] 배경자료(시도/전국 단위) 파싱...")
    background = parse_background()

    # 구·군 단위 통합 (경제활동 + 출생아수/출산율 + 신혼부부수)
    gugun = econ.merge(birth, on="구군", how="outer").merge(newlywed, on="구군", how="outer")
    gugun.to_csv(OUT_GUGUN, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUT_GUGUN}' 저장 ({len(gugun)}행)")

    age_trend_wide = age_trend.pivot(index="구군", columns="연도", values="영유아인구_0_5세")
    age_trend_wide.columns = [f"영유아인구_0_5세_{c}" for c in age_trend_wide.columns]
    age_trend_wide = age_trend_wide.reset_index()
    age_trend_wide.to_csv(OUT_AGE_TREND, index=False, encoding="utf-8-sig")
    print(f"[완료] '{OUT_AGE_TREND}' 저장 ({len(age_trend_wide)}행)")

    background.to_csv(OUT_BACKGROUND, index=False, encoding="utf-8-sig")
    print(f"[완료] '{OUT_BACKGROUND}' 저장 ({len(background)}행) - 구군 구분 없는 배경 참고용")

    print("\n=== 구·군별 통합 지표 미리보기 ===")
    print(gugun.to_string())
    print("\n=== 영유아인구 0-6세 연도별 추이 ===")
    print(age_trend_wide.to_string())
    print("\n=== 배경자료 ===")
    print(background.to_string())


if __name__ == "__main__":
    main()