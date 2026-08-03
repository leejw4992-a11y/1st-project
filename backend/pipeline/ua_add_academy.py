"""
학원교습소 통합 스크립트 (3-5, 보조지표)
------------------------------------------------------------
※ 팀 결정: 체육학원/사교육 연계는 핵심 돌봄공백 지수에서 제외하기로 확정됨(v6).
   이 스크립트는 3-4(체육시설)와 동일하게 "핵심 지수엔 미포함, 보조 참고 컬럼"으로만
   최종 결과에 추가한다. 미스매치_유형 재분류에는 영향을 주지 않는다.

처리 순서:
  1) 연도별 중복 제거 (같은 학원+주소는 최신 연도만 남김, 유치원 일반현황과 동일 처리)
  2) 도로명주소 지오코딩 (좌표 없음, 유치원 kinder_enrich.py와 동일 방식)
  3) 좌표 -> 행정동 역조회
  4) 행정동 단위 집계 (학원수, 정원합계) 후 최종 결과에 보조 컬럼으로 병합

입력:
  - data/ua_data/daegu_최종_통합결과_부동산포함.csv
  - data/ua_data/5번_2023년_2026년_대구광역시_영유아_학원교습소_정보.csv

출력:
  - data/ua_data/daegu_최종_통합결과_학원포함.csv

사용법:
  1. KAKAO_API_KEY 입력
  2. python ua_add_academy.py 실행
"""

import pandas as pd
import requests
import time
import json
import os
import re

# ============================================
# 0. 설정
# ============================================
KAKAO_API_KEY = "860588e2100897c43eb155016f51d129"

INPUT_DIR = "data/ua_data"
MISMATCH_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_부동산포함.csv"
ACADEMY_CSV = f"{INPUT_DIR}/5번 2023년~2026년 대구광역시 영유아 학원교습소 정보.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_학원포함.csv"

GEOCODE_CACHE_PATH = f"{INPUT_DIR}/geocode_cache.json"   # 유치원 파이프라인과 캐시 공유
REGION_CACHE_PATH = f"{INPUT_DIR}/region_cache.json"     # 좌표->행정동 캐시 공유


# ============================================
# 1. 유틸
# ============================================
def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc, thousands=",")
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


def load_cache(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def normalize_name(name):
    if pd.isna(name):
        return None
    name = str(name).replace("·", ".").replace(" ", "")
    return re.sub(r"[().]", "", name)


def get_stem(name):
    """'신암1동'->'신암', '다사읍(전체)'->'다사' 처럼 뿌리 이름 추출 (부동산 스크립트와 동일 규칙)"""
    if pd.isna(name):
        return None
    name = str(name).replace("(전체)", "").replace(" ", "")
    m = re.match(r"^(.*?)[\d.]*가?(동|읍|면)$", name)
    return m.group(1) if m else name


# ============================================
# 2. 주소 지오코딩 (유치원과 동일 방식)
# ============================================
def geocode_address(addr, api_key, cache):
    if addr in cache:
        return cache[addr]

    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": addr}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()
        documents = data.get("documents", [])
        if documents:
            result = {"lat": float(documents[0]["y"]), "lng": float(documents[0]["x"])}
        else:
            result = {"lat": None, "lng": None}
    except Exception as e:
        print(f"[경고] '{addr}' 지오코딩 실패: {e}")
        result = {"lat": None, "lng": None}

    cache[addr] = result
    return result


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


# ============================================
# 3. 메인
# ============================================
def main():
    if not KAKAO_API_KEY or len(KAKAO_API_KEY.strip()) < 20:
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(MISMATCH_CSV) or not os.path.exists(ACADEMY_CSV):
        print("[오류] 입력 파일을 확인하세요.")
        return

    mismatch = load_csv_auto(MISMATCH_CSV)
    academy = load_csv_auto(ACADEMY_CSV)
    print(f"[정보] 최종 결과 {len(mismatch)}행, 학원 원본 {len(academy)}행 로드")

    # 1) 연도별 중복 제거 -> 학원+주소 기준 최신 연도만
    academy["_연도숫자"] = academy["기준년도"].astype(str).str.extract(r"(\d{4})").astype(int)
    academy = academy.sort_values("_연도숫자")
    before = len(academy)
    academy = academy.drop_duplicates(subset=["학원명", "도로명주소"], keep="last").copy()
    print(f"[정보] 연도별 중복 제거: {before}행 -> {len(academy)}행 (최신 연도만 유지)")

    # 2) 주소 지오코딩
    print("\n[1단계] 주소 지오코딩...")
    geo_cache = load_cache(GEOCODE_CACHE_PATH)
    lats, lngs = [], []
    total = len(academy)
    for i, addr in enumerate(academy["도로명주소"], start=1):
        result = geocode_address(addr, KAKAO_API_KEY, geo_cache)
        lats.append(result["lat"])
        lngs.append(result["lng"])
        if i % 50 == 0 or i == total:
            print(f"[진행] {i}/{total}")
        time.sleep(0.05)
    save_cache(GEOCODE_CACHE_PATH, geo_cache)
    academy["위도"] = lats
    academy["경도"] = lngs
    n_geo_fail = academy["위도"].isna().sum()
    print(f"[1단계 완료] 지오코딩 실패: {n_geo_fail} / {total}")

    # 3) 좌표 -> 행정동
    print("\n[2단계] 좌표 -> 행정동 역조회...")
    region_cache = load_cache(REGION_CACHE_PATH)
    gu_list, dong_list = [], []
    for i, row in enumerate(academy.itertuples(), start=1):
        lat, lng = getattr(row, "위도", None), getattr(row, "경도", None)
        if pd.isna(lat) or pd.isna(lng):
            gu_list.append(None)
            dong_list.append(None)
            continue
        result = coord_to_dong(lat, lng, KAKAO_API_KEY, region_cache)
        gu_list.append(result["구군"])
        dong_list.append(result["읍면동"])
        time.sleep(0.05)
    save_cache(REGION_CACHE_PATH, region_cache)
    academy["구군_행정"] = gu_list
    academy["읍면동_행정"] = dong_list
    n_dong_fail = academy["읍면동_행정"].isna().sum()
    print(f"[2단계 완료] 행정동 매칭 실패: {n_dong_fail} / {len(academy)}")

    # 디버그용 저장
    debug_path = f"{INPUT_DIR}/학원_행정동_매핑_확인용.csv"
    academy[["학원명", "도로명주소", "정원합계", "분야명", "구군_행정", "읍면동_행정"]].to_csv(
        debug_path, index=False, encoding="utf-8-sig"
    )
    print(f"[정보] 디버그 파일 저장: '{debug_path}'")

    # 4) '뿌리 이름' 기준으로 집계 및 병합 (부동산 스크립트와 동일 원리 - 법정동 주소 특성상 필요)
    print("\n[3단계] 뿌리 이름 기준 집계 및 최종 결과 병합...")
    academy["_구군_norm"] = academy["구군_행정"].apply(normalize_name)
    academy["_stem"] = academy["읍면동_행정"].apply(get_stem)

    agg = academy.groupby(["_구군_norm", "_stem"]).agg(
        학원수=("학원명", "count"),
        학원정원합계=("정원합계", "sum"),
    ).reset_index()

    mismatch["_구군_norm"] = mismatch["시군구명"].apply(normalize_name)
    mismatch["_stem"] = mismatch["읍면동명"].apply(get_stem)

    merged = mismatch.merge(agg, on=["_구군_norm", "_stem"], how="left")
    merged["학원수"] = merged["학원수"].fillna(0).astype(int)
    merged["학원정원합계"] = merged["학원정원합계"].fillna(0).astype(int)
    merged = merged.drop(columns=["_구군_norm", "_stem"])

    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행)")
    print(f"[정보] 학원수 총합(병합후): {merged['학원수'].sum()} (원본 지오코딩 성공 학원 수: {len(academy) - n_dong_fail})")
    print("[참고] 학원 데이터는 핵심 미스매치 지수 계산에는 반영되지 않았습니다 (팀 결정에 따라 보조 컬럼으로만 추가).")


if __name__ == "__main__":
    main()