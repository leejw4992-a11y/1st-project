"""
공공데이터 CSV 빠르게 열어보기 / 필터링 스크립트
------------------------------------------------
사용법 (VSCode 터미널에서):
    python ua_csv_viewer.py "파일명.csv"

가장 먼저 실행하면 전체 컬럼 목록과 미리보기(5행)를 보여줍니다.
그걸 보고 아래 CONFIG 부분에서 원하는 컬럼/필터 조건을 채운 뒤 다시 실행하면
필터링된 결과만 화면에 뜨고, filtered_결과.csv(또는 파일별 지정 경로)로 저장됩니다.

※ 2026-07-29 수정: 파일명에 따라 자동으로 다른 폴더(data/ua_data, data/monthly 등)에서
   찾도록 FOLDER_BY_KEYWORD를 추가했습니다. 예: "대구_인구세대_월별통합.csv"는
   data/ua_data가 아니라 data/monthly 폴더에 있으므로 자동으로 그쪽을 봅니다.
"""

import pandas as pd
import sys
import os
import re

# ============================================
# 0. 여기만 프로젝트에 맞게 수정하세요
# ============================================

# 파일명에 특정 키워드가 있으면 기본 폴더(data/ua_data) 대신 이 폴더에서 찾음
FOLDER_BY_KEYWORD = {
    "인구세대_월별통합": "data/monthly",   # 대구_인구세대_월별통합.csv (ua_monthly_population_processor.py 결과)
    "주민등록인구및세대현황_월간": "data/monthly",  # 원본 월별 파일들도 여기서 바로 열어볼 수 있게
}
DEFAULT_FOLDER = "data/ua_data"


def resolve_input_path(filename):
    for keyword, folder in FOLDER_BY_KEYWORD.items():
        if keyword in filename:
            return f"{folder}/{filename}"
    return f"{DEFAULT_FOLDER}/{filename}"


CSV_PATH = resolve_input_path(sys.argv[1]) if len(sys.argv) > 1 else f"{DEFAULT_FOLDER}/data.csv"

# 보고 싶은 컬럼만 리스트로 적으세요. 비워두면(= []) 전체 컬럼 다 봄
COLUMNS_TO_KEEP = ["시도명", "시군구명", "읍면동명", "영아인구_0_2세", "유아인구_3_6세", "영유아인구_0_6세"]

# 특정 컬럼 값으로 행 필터링하고 싶을 때 사용 (없으면 빈 딕셔너리로 둠)
# 예: {"시군구": "대구광역시 동구"} 처럼 '컬럼명': '포함될 문자열'
FILTER_CONTAINS = {"시도명": "대구광역시"}

# 결측치(빈 값) 있는 행 제외할 컬럼 지정 (없으면 빈 리스트)
DROP_NA_SUBSET = []  # 예: ["oper_time"]

# 첫 번째 컬럼처럼 "지역명 (법정동코드)" 형태로 값이 들어있는 경우,
# 법정동코드만 뽑아서 새 컬럼(법정동코드)으로 추가하고 싶으면 그 컬럼명을 적으세요.
# 안 쓰려면 None으로 두세요.
REGION_COLUMN_WITH_CODE = None  # 예: "행정구역(동읍면)별"

# 법정동코드 앞자리로만 걸러내고 싶을 때 (예: 대구 전체 = "27")
BJDONG_CODE_PREFIX = None  # 예: "27"

# 나이별 컬럼(0세남자, 1세여자 등)을 합산해서 연령대 인구를 계산하고 싶으면 켜세요.
# 이 CSV처럼 "N세남자"/"N세여자" 컬럼이 있는 인구 데이터 전용 기능입니다.
COMPUTE_AGE_GROUPS = True

# 계산할 연령대를 정의 (레이블: [포함할 나이 리스트])
# 프로젝트 연령 기준: 만 0~6세 (미취학아동)
AGE_GROUP_DEFINITIONS = {
    "영아인구_0_2세": [0, 1, 2],
    "유아인구_3_6세": [3, 4, 5, 6],
    "영유아인구_0_6세": [0, 1, 2, 3, 4, 5, 6],
}

OUTPUT_PATH = "data/ua_data/filtered_결과.csv"

# 필터 조건이 하나도 없어도(빈 상태여도) 강제로 결과를 저장할지 여부.
# 기본 False: 아무 설정 없으면 "안내 메시지만 출력하고 종료" (기존 동작 유지)
FORCE_OUTPUT = False

# ============================================
# 0-1. 파일 종류별 자동 프로필
# ------------------------------------------------
# 파일명에 아래 키워드가 포함되어 있으면, 위에서 손으로 채운 CONFIG 대신
# 이 프로필 값이 자동으로 적용됩니다. (모르는 파일이면 위 수동 CONFIG 그대로 사용)
# 새 파일 종류를 추가하고 싶으면 이 딕셔너리에 항목을 추가하면 됩니다.
#
# output_path : 이 프로필 전용 저장 경로 (지정 안 하면 위 OUTPUT_PATH 사용)
#               -> 다른 파이프라인이 쓰는 data/ua_data/filtered_결과.csv를
#                  실수로 덮어쓰지 않도록, 파일마다 저장 위치를 분리합니다.
# force_output : True면 필터 조건이 비어 있어도 항상 저장 (조회 후 그대로 CSV로 남기고 싶을 때)
# ============================================
FILE_PROFILES = {
    "성별_연령별": {
        "filter_contains": {"시도명": "대구광역시"},
        "compute_age_groups": True,
        "columns_to_keep": ["시도명", "시군구명", "읍면동명",
                             "영아인구_0_2세", "유아인구_3_6세", "영유아인구_0_6세"],
        "output_path": "data/ua_data/filtered_결과.csv",
        "force_output": False,
    },
    "방과후": {
        # 파일명 자체에 '대구광역시'가 들어있어 이미 대구 전용 파일 -> 필터 불필요, 전체 컬럼 확인용
        "filter_contains": {},
        "compute_age_groups": False,
        "columns_to_keep": [],
        "output_path": "data/ua_data/filtered_결과.csv",
        "force_output": False,
    },
    "통학차량": {
        # 아직 실제 컬럼 구조 미확인 -> 일단 전체 컬럼만 보여줌 (프로필은 자리만 잡아둠)
        "filter_contains": {},
        "compute_age_groups": False,
        "columns_to_keep": [],
        "output_path": "data/ua_data/filtered_결과.csv",
        "force_output": False,
    },
    "인구세대_월별통합": {
        # 대구_인구세대_월별통합.csv (ua_monthly_population_processor.py 결과)
        # 이미 대구 10개 지역(전체+9개 구군)만 있고 36개월치라, 필터 없이도 바로 저장해서 보는 게 유용함.
        # 특정 구·군만 보고 싶으면 아래 filter_contains를 실행 전에 직접 고쳐서 쓰세요.
        # 예: {"행정구역": "군위군"}  또는  {"기준월": "202606"}
        "filter_contains": {},
        "compute_age_groups": False,
        "columns_to_keep": [],
        "output_path": "data/monthly/필터결과.csv",
        "force_output": True,
    },
}


# ============================================
# 1. CSV 로드 (인코딩 자동 시도: 공공데이터는 cp949/euc-kr가 흔함)
# ============================================
def load_csv(path):
    if not os.path.exists(path):
        print(f"[오류] 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    # 행정안전부/공공데이터 CSV는 cp949(euc-kr)인 경우가 많아 먼저 시도
    encodings_to_try = ["cp949", "euc-kr", "utf-8-sig", "utf-8"]
    last_err = None
    for enc in encodings_to_try:
        try:
            # thousands="," : "2,366,654" 같은 숫자를 문자열이 아닌 숫자로 인식
            df = pd.read_csv(path, encoding=enc, thousands=",")
            print(f"[정보] 인코딩 '{enc}'로 로드 성공 ({len(df)}행, {len(df.columns)}열)")
            return df
        except Exception as e:
            last_err = e
            continue
    print(f"[오류] 모든 인코딩 시도 실패: {last_err}")
    sys.exit(1)


def extract_bjdong_code(text):
    """'대구광역시 (2700000000)' 같은 문자열에서 괄호 안 법정동코드만 추출"""
    if pd.isna(text):
        return None
    m = re.search(r"\((\d+)\)", str(text))
    return m.group(1) if m else None


def compute_age_groups(df, definitions):
    """'0세남자', '0세여자' 같은 컬럼들을 정의된 연령대별로 합산해 새 컬럼 추가"""
    for label, ages in definitions.items():
        cols = []
        for age in ages:
            cols.append(f"{age}세남자")
            cols.append(f"{age}세여자")
        existing_cols = [c for c in cols if c in df.columns]
        missing_cols = [c for c in cols if c not in df.columns]
        if missing_cols:
            print(f"[경고] '{label}' 계산 중 없는 컬럼 무시: {missing_cols}")
        if existing_cols:
            df[label] = df[existing_cols].sum(axis=1)
        else:
            print(f"[경고] '{label}'을 계산할 컬럼이 하나도 없어 건너뜁니다.")
    return df


# ============================================
# 2. 메인 로직
# ============================================
def main():
    df = load_csv(CSV_PATH)

    # 컬럼 목록 & 미리보기는 항상 먼저 출력 (컬럼명 오타 방지용)
    print("\n=== 전체 컬럼 목록 ===")
    print(list(df.columns))

    print("\n=== 상위 5행 미리보기 ===")
    print(df.head().to_string())

    # 파일명에 등록된 키워드가 있으면 해당 프로필 값을 자동 적용
    filename = os.path.basename(CSV_PATH)
    active_filter_contains = FILTER_CONTAINS
    active_compute_age_groups = COMPUTE_AGE_GROUPS
    active_columns_to_keep = COLUMNS_TO_KEEP
    active_output_path = OUTPUT_PATH
    active_force_output = FORCE_OUTPUT

    for keyword, profile in FILE_PROFILES.items():
        if keyword in filename:
            print(f"\n[정보] 파일명에서 '{keyword}' 감지 → 해당 프로필 자동 적용 (수동 CONFIG 무시)")
            active_filter_contains = profile["filter_contains"]
            active_compute_age_groups = profile["compute_age_groups"]
            active_columns_to_keep = profile["columns_to_keep"]
            active_output_path = profile.get("output_path", OUTPUT_PATH)
            active_force_output = profile.get("force_output", False)
            break

    # 아무 필터/컬럼 설정도 안 했고 force_output도 아니면 여기서 종료 (미리보기까지만 보여주는 모드)
    if (not active_columns_to_keep and not active_filter_contains and not DROP_NA_SUBSET
            and not REGION_COLUMN_WITH_CODE and not BJDONG_CODE_PREFIX
            and not active_compute_age_groups and not active_force_output):
        print("\n[안내] 위 컬럼 목록을 보고 CONFIG 부분(COLUMNS_TO_KEEP, FILTER_CONTAINS 등)을 채운 뒤 다시 실행하세요.")
        return

    result = df.copy()

    # 연령대별 인구 합산
    if active_compute_age_groups:
        result = compute_age_groups(result, AGE_GROUP_DEFINITIONS)

    # 법정동코드 컬럼 새로 만들기
    if REGION_COLUMN_WITH_CODE:
        if REGION_COLUMN_WITH_CODE not in result.columns:
            print(f"[경고] REGION_COLUMN_WITH_CODE '{REGION_COLUMN_WITH_CODE}'가 컬럼에 없습니다.")
        else:
            result["법정동코드"] = result[REGION_COLUMN_WITH_CODE].apply(extract_bjdong_code)

    # 법정동코드 앞자리로 필터 (법정동코드 컬럼이 있어야 동작)
    if BJDONG_CODE_PREFIX:
        if "법정동코드" not in result.columns:
            print("[경고] BJDONG_CODE_PREFIX를 쓰려면 REGION_COLUMN_WITH_CODE를 먼저 지정하세요.")
        else:
            result = result[result["법정동코드"].astype(str).str.startswith(BJDONG_CODE_PREFIX)]

    # 컬럼 선택
    if active_columns_to_keep:
        missing = [c for c in active_columns_to_keep if c not in result.columns]
        if missing:
            print(f"[경고] 존재하지 않는 컬럼: {missing} — 무시하고 진행합니다.")
        keep = [c for c in active_columns_to_keep if c in result.columns]
        result = result[keep]

    # 문자열 포함 필터
    for col, keyword in active_filter_contains.items():
        if col not in result.columns:
            print(f"[경고] 필터 대상 컬럼 '{col}'이 없어 건너뜁니다.")
            continue
        result = result[result[col].astype(str).str.contains(keyword, na=False)]

    # 결측치 제거
    if DROP_NA_SUBSET:
        valid_subset = [c for c in DROP_NA_SUBSET if c in result.columns]
        result = result.dropna(subset=valid_subset)

    print(f"\n=== 필터링 결과 ({len(result)}행) ===")
    print(result.to_string())

    # 저장 경로의 폴더가 없으면 자동 생성
    out_dir = os.path.dirname(active_output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    result.to_csv(active_output_path, index=False, encoding="utf-8-sig")
    print(f"\n[완료] 결과를 '{active_output_path}'로 저장했습니다.")


if __name__ == "__main__":
    main()