"""
부동산 실거래가 통합 스크립트 (3-6)
------------------------------------------------------------
85,760건의 개별 거래를 전부 지오코딩하는 대신, 법정동/리(시군구 문자열) 단위로
먼저 집계(297개 그룹)한 뒤, 그 법정동들만 좌표를 구하고 행정동으로 역조회한다.

처리 순서:
  1) 모든 주거형태(아파트/단독다가구/연립다세대/오피스텔) 필터링 (해제된 거래 제외)
  2) ㎡당 가격 계산 후 법정동(시군구 문자열) 단위 집계 (연도별 + 전체기간)
  3) 법정동 대표 좌표 확보 (카카오 주소검색, 297개만)
  4) 좌표 -> 행정동 역조회 (카카오 좌표->행정구역)
  5) 행정동 단위로 재집계 후 최종 미스매치 결과와 병합

입력:
  - data/ua_data/daegu_최종_통합결과_최종.csv
  - data/ua_data/6번_2023년_2026년_대구광역시_부동산_실거래가_데이터.csv

출력:
  - data/ua_data/daegu_최종_통합결과_부동산포함.csv

사용법:
  1. KAKAO_API_KEY 입력
  2. python ua_add_realestate.py 실행
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
MISMATCH_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_최종.csv"
REALESTATE_CSV = f"{INPUT_DIR}/6번 2023년~2026년 대구광역시 부동산 실거래가 데이터.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_부동산포함.csv"

BJDONG_CACHE_PATH = f"{INPUT_DIR}/bjdong_centroid_cache.json"   # 법정동 -> 좌표 캐시
REGION_CACHE_PATH = f"{INPUT_DIR}/region_cache.json"            # 좌표 -> 행정동 캐시 (기존과 공유)


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


# ============================================
# 2. 법정동 대표 좌표 (주소 검색)
# ============================================
def geocode_address(query, api_key, cache):
    if query in cache:
        return cache[query]

    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": query}

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
        print(f"[경고] '{query}' 지오코딩 실패: {e}")
        result = {"lat": None, "lng": None}

    cache[query] = result
    return result


# ============================================
# 3. 좌표 -> 행정동 역조회 (기존 파이프라인과 동일)
# ============================================
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
# 4. 메인
# ============================================
def main():
    if not KAKAO_API_KEY or len(KAKAO_API_KEY.strip()) < 20:
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(MISMATCH_CSV) or not os.path.exists(REALESTATE_CSV):
        print("[오류] 입력 파일을 확인하세요.")
        return

    mismatch = load_csv_auto(MISMATCH_CSV)
    re_df = load_csv_auto(REALESTATE_CSV)
    print(f"[정보] 최종 결과 {len(mismatch)}행, 부동산 원본 {len(re_df)}행 로드")

    # 1) 모든 주거형태(아파트/단독다가구/연립다세대/오피스텔) 포함, 해제된 거래만 제외
    before = len(re_df)
    re_df = re_df.copy()
    if "해제사유발생일" in re_df.columns:
        re_df = re_df[re_df["해제사유발생일"] == "-"]
    print(f"[정보] 정상거래만 필터링: {before}행 -> {len(re_df)}행")
    print(f"[정보] 주택유형 구성: {re_df['주택유형'].value_counts().to_dict()}")

    # 2) ㎡당 가격 계산 + 법정동(시군구) 단위 집계
    re_df["거래금액(만원)"] = pd.to_numeric(re_df["거래금액(만원)"], errors="coerce")
    re_df["전용면적(㎡)"] = pd.to_numeric(re_df["전용면적(㎡)"], errors="coerce")
    re_df["제곱미터당가격_만원"] = re_df["거래금액(만원)"] / re_df["전용면적(㎡)"]
    re_df["계약년도"] = re_df["계약년월"].astype(str).str[:4]

    print("\n[1단계] 법정동 단위 집계 (전체기간 + 최근 1년)...")
    bjdong_agg = re_df.groupby("시군구").agg(
        거래건수=("제곱미터당가격_만원", "count"),
        평균제곱미터당가격_만원=("제곱미터당가격_만원", "mean"),
    ).reset_index()

    recent = re_df[re_df["계약년도"].isin(["2025", "2026"])]
    recent_agg = recent.groupby("시군구").agg(
        최근거래건수=("제곱미터당가격_만원", "count"),
        최근평균제곱미터당가격_만원=("제곱미터당가격_만원", "mean"),
    ).reset_index()
    bjdong_agg = bjdong_agg.merge(recent_agg, on="시군구", how="left")
    print(f"[정보] 법정동 단위 그룹 수: {len(bjdong_agg)}")

    # 3) 법정동 대표 좌표
    print("\n[2단계] 법정동 대표 좌표 확보...")
    addr_cache = load_cache(BJDONG_CACHE_PATH)
    lats, lngs = [], []
    total = len(bjdong_agg)
    for i, addr in enumerate(bjdong_agg["시군구"], start=1):
        result = geocode_address(addr, KAKAO_API_KEY, addr_cache)
        lats.append(result["lat"])
        lngs.append(result["lng"])
        if i % 50 == 0 or i == total:
            print(f"[진행] {i}/{total}")
        time.sleep(0.05)
    save_cache(BJDONG_CACHE_PATH, addr_cache)
    bjdong_agg["위도"] = lats
    bjdong_agg["경도"] = lngs
    n_geo_fail = bjdong_agg["위도"].isna().sum()
    print(f"[2단계 완료] 좌표 실패: {n_geo_fail} / {total}")

    # 4) 좌표 -> 행정동
    print("\n[3단계] 좌표 -> 행정동 역조회...")
    region_cache = load_cache(REGION_CACHE_PATH)
    gu_list, dong_list = [], []
    for i, row in enumerate(bjdong_agg.itertuples(), start=1):
        if pd.isna(row.위도) or pd.isna(row.경도):
            gu_list.append(None)
            dong_list.append(None)
            continue
        result = coord_to_dong(row.위도, row.경도, KAKAO_API_KEY, region_cache)
        gu_list.append(result["구군"])
        dong_list.append(result["읍면동"])
        time.sleep(0.05)
    save_cache(REGION_CACHE_PATH, region_cache)
    bjdong_agg["구군_행정"] = gu_list
    bjdong_agg["읍면동_행정"] = dong_list
    n_dong_fail = bjdong_agg["읍면동_행정"].isna().sum()
    print(f"[3단계 완료] 행정동 매칭 실패: {n_dong_fail} / {total}")

    # 디버그용: 법정동별로 어떤 행정동에 매칭됐는지 저장 (매칭 원인 진단용)
    debug_path = f"{INPUT_DIR}/부동산_법정동_매핑_확인용.csv"
    bjdong_agg[["시군구", "거래건수", "위도", "경도", "구군_행정", "읍면동_행정"]].to_csv(
        debug_path, index=False, encoding="utf-8-sig"
    )
    print(f"[정보] 법정동별 행정동 매핑 결과를 '{debug_path}'에 저장했습니다 (매칭 오류 진단용)")

    # 5) 행정동 단위 재집계 (거래건수로 가중평균)
    print("\n[4단계] '뿌리 이름' 기준으로 병합 (법정동 하나가 여러 행정동으로 쪼개지는 문제 해결)...")
    # 부동산 데이터는 법정동 단위(신암동)인데 분석은 행정동 단위(신암1동~5동)라 이름이 안 맞음.
    # "신암1동"->"신암", "두류1.2동"->"두류", "다사읍(전체)"->"다사" 처럼 뒷자리를 떼서 공통 뿌리로 매칭.
    def get_stem(name):
        if pd.isna(name):
            return None
        name = str(name).replace("(전체)", "").replace(" ", "")
        m = re.match(r"^(.*?)[\d.]*가?(동|읍|면)$", name)
        return m.group(1) if m else name

    bjdong_agg["_구군_norm"] = bjdong_agg["구군_행정"].apply(normalize_name)
    bjdong_agg["_stem"] = bjdong_agg["읍면동_행정"].apply(get_stem)

    bjdong_agg["_가중가격"] = bjdong_agg["평균제곱미터당가격_만원"] * bjdong_agg["거래건수"]
    bjdong_agg["_최근가중가격"] = bjdong_agg["최근평균제곱미터당가격_만원"] * bjdong_agg["최근거래건수"].fillna(0)

    dong_agg = bjdong_agg.groupby(["_구군_norm", "_stem"]).agg(
        실거래건수=("거래건수", "sum"),
        _가중가격합=("_가중가격", "sum"),
        최근실거래건수=("최근거래건수", "sum"),
        _최근가중가격합=("_최근가중가격", "sum"),
    ).reset_index()
    dong_agg["평균제곱미터당가격_만원"] = dong_agg["_가중가격합"] / dong_agg["실거래건수"]
    dong_agg["최근평균제곱미터당가격_만원"] = dong_agg.apply(
        lambda r: (r["_최근가중가격합"] / r["최근실거래건수"]) if r["최근실거래건수"] > 0 else None, axis=1
    )
    dong_agg = dong_agg.drop(columns=["_가중가격합", "_최근가중가격합"])

    # 6) 최종 결과와 병합 (동일한 뿌리 이름을 가진 모든 행정동이 같은 값을 공유)
    mismatch["_구군_norm"] = mismatch["시군구명"].apply(normalize_name)
    mismatch["_stem"] = mismatch["읍면동명"].apply(get_stem)

    merged = mismatch.merge(dong_agg, on=["_구군_norm", "_stem"], how="left")
    merged = merged.drop(columns=["_구군_norm", "_stem"])

    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행)")
    n_no_price = merged["실거래건수"].isna().sum()
    print(f"[정보] 부동산 거래 데이터 매칭 안 된 동(해당 동에 실거래 자체가 없는 경우일 수 있음): {n_no_price}")


if __name__ == "__main__":
    main()