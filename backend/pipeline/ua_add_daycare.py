"""
어린이집 데이터 통합 스크립트 (3-2)
------------------------------------------------------------
어린이집은 이미 위도/경도가 있어 지오코딩 불필요. 좌표 -> 행정동 역조회만 하면 됨.
기존 daegu_최종_통합결과_전체.csv(유치원+체육시설+사회지표)에 어린이집 정원/현원을
더해서, "통합 보육시설"(유치원+어린이집) 기준 진짜 공급/충원 지표를 만든다.

왜 중요한가:
  유치원은 구조상 0~2세(영아)를 받지 못한다. 그동안 커버율(정원/영유아인구_0_6세)은
  유치원이 애초에 못 받는 영아 인구까지 분모에 포함해 실제보다 낮게 나오는 구조적
  왜곡이 있었다. 어린이집(0~5세 전체 대응)을 더하면 이 왜곡이 크게 줄어든다.

입력:
  - data/ua_data/daegu_최종_통합결과_전체.csv
  - data/ua_data/2번_대구_어린이집총원현원.csv

출력:
  - data/ua_data/daegu_최종_통합결과_어린이집포함.csv

사용법:
  1. KAKAO_API_KEY 입력
  2. python ua_add_daycare.py 실행
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
MISMATCH_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_전체.csv"
DAYCARE_CSV = f"{INPUT_DIR}/2번_대구_어린이집총원현원.csv"
OUTPUT_CSV = f"{INPUT_DIR}/daegu_최종_통합결과_어린이집포함.csv"
REGION_CACHE_PATH = f"{INPUT_DIR}/region_cache.json"  # 기존 파이프라인과 캐시 공유


# ============================================
# 1. 좌표 -> 행정동 역조회 (기존 파이프라인과 동일 로직)
# ============================================
def load_cache(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


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


def add_dong_column(df, api_key):
    cache = load_cache(REGION_CACHE_PATH)
    gu_list, dong_list = [], []
    total = len(df)

    for i, row in enumerate(df.itertuples(), start=1):
        lat, lng = getattr(row, "위도", None), getattr(row, "경도", None)
        if pd.isna(lat) or pd.isna(lng):
            gu_list.append(None)
            dong_list.append(None)
            continue
        result = coord_to_dong(lat, lng, api_key, cache)
        gu_list.append(result["구군"])
        dong_list.append(result["읍면동"])
        if i % 50 == 0 or i == total:
            print(f"[역지오코딩 진행] {i}/{total}")
        time.sleep(0.05)

    save_cache(REGION_CACHE_PATH, cache)
    df["구군_행정"] = gu_list
    df["읍면동_행정"] = dong_list
    return df


def normalize_name(name):
    if pd.isna(name):
        return None
    name = str(name).replace("·", ".").replace(" ", "")
    return re.sub(r"[().]", "", name)


def load_csv_auto(path):
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise RuntimeError(f"인코딩 인식 실패: {path}")


# ============================================
# 2. 메인
# ============================================
def main():
    if KAKAO_API_KEY == "여기에_카카오_REST_API_키_입력":
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(MISMATCH_CSV) or not os.path.exists(DAYCARE_CSV):
        print("[오류] 입력 파일을 확인하세요.")
        return

    mismatch = load_csv_auto(MISMATCH_CSV)
    daycare = load_csv_auto(DAYCARE_CSV)
    print(f"[정보] 동 단위 결과 {len(mismatch)}행, 어린이집 원본 {len(daycare)}행 로드")

    # 운영중인 어린이집만 (미 운영 89곳 제외)
    before = len(daycare)
    daycare = daycare[daycare["운영여부"] == "운영"].copy()
    print(f"[정보] 운영중만 필터링: {before}행 -> {len(daycare)}행")

    # 1) 좌표 -> 행정동 역조회
    print("\n[1단계] 좌표 -> 행정동 역조회...")
    daycare = add_dong_column(daycare, KAKAO_API_KEY)
    n_failed = daycare["읍면동_행정"].isna().sum()
    print(f"[1단계 완료] 행정동 매칭 실패: {n_failed} / {len(daycare)}")

    # 2) 구군+행정동 단위 집계
    daycare["_구군_norm"] = daycare["구군_행정"].apply(normalize_name)
    daycare["_읍면동_norm"] = daycare["읍면동_행정"].apply(normalize_name)

    agg = daycare.groupby(["_구군_norm", "_읍면동_norm"]).agg(
        어린이집수=("기관명", "count"),
        어린이집정원=("정원", "sum"),
        어린이집현원=("현원", "sum"),
    ).reset_index()

    # 3) 기존 결과와 병합
    mismatch["_구군_norm"] = mismatch["시군구명"].apply(normalize_name)
    mismatch["_읍면동_norm"] = mismatch["읍면동명"].apply(normalize_name)

    merged = mismatch.merge(agg, on=["_구군_norm", "_읍면동_norm"], how="left")
    for col in ["어린이집수", "어린이집정원", "어린이집현원"]:
        merged[col] = merged[col].fillna(0).astype(int)

    # 4) 통합(유치원+어린이집) 공급/실현/커버율/충원율 재계산
    merged["통합_정원"] = merged["정원_합계"] + merged["어린이집정원"]
    merged["통합_현원"] = merged["원아수_합계"] + merged["어린이집현원"]
    merged["통합_커버율"] = merged.apply(
        lambda r: (r["통합_정원"] / r["영유아인구_0_6세"]) if r["영유아인구_0_6세"] > 0 else None, axis=1
    )
    merged["통합_충원율"] = merged.apply(
        lambda r: (r["통합_현원"] / r["통합_정원"]) if r["통합_정원"] > 0 else None, axis=1
    )

    merged = merged.drop(columns=["_구군_norm", "_읍면동_norm"])
    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행)")
    print(f"[정보] 대구 전체 어린이집 정원 합계: {merged['어린이집정원'].sum():,} "
          f"(원본 운영중 정원 합계: {daycare['정원'].sum():,})")
    print(f"[정보] 유치원만 있을 때 커버율 0곳: {(merged['커버율']==0).sum()}개 동 "
          f"-> 통합 후 커버율 0곳: {(merged['통합_커버율']==0).sum()}개 동")


if __name__ == "__main__":
    main()