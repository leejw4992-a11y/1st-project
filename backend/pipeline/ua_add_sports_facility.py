"""
유치원(3-3) + 체육시설(3-4) 동 단위 통합 스크립트
------------------------------------------------------------
※ 왜 이렇게 만들었는가:
  1) 기존 daegu_동별_체육시설_통합요약(.csv/_v2)은 폐기된 API 파이프라인(정원 없는
     clcnt/ppcnt 버전)에서 만들어져 유치원수가 파일마다 다르게 나오는 문제가 있었음
     -> 검증된 최종본(daegu_최종_미스매치_결과.csv)을 그대로 사용해서 해결.
  2) 대구_체육시설_정제데이터.csv의 '동이름'은 법정동(예: 침산동)인데, 미스매치
     결과의 '읍면동명'은 행정동(예: 침산1동/2동/3동)이라 텍스트로 매칭이 안 됨
     -> 정제데이터의 좌표(TM, EPSG:5174)를 WGS84로 변환한 뒤 카카오 좌표->행정구역
     API로 행정동을 다시 역조회해서 해결 (유치원 파이프라인과 동일한 방식).

입력:
  - data/ua_data/daegu_최종_미스매치_결과.csv   (유치원+인구, 152개 동, 이미 완성)
  - data/ua_data/대구_체육시설_정제데이터.csv   (체육도장업 819곳, TM 좌표 포함)

출력:
  - data/ua_data/daegu_최종_통합결과_체육시설포함.csv

사용법:
  1. KAKAO_API_KEY 입력
  2. pip install pyproj requests pandas --break-system-packages (pyproj 없으면)
  3. python ua_add_sports_facility.py 실행
"""

import pandas as pd
import requests
import time
import json
import os
import re
from pyproj import Transformer

# ============================================
# 0. 설정
# ============================================
KAKAO_API_KEY = "860588e2100897c43eb155016f51d129"

MISMATCH_CSV = "data/ua_data/daegu_최종_미스매치_결과.csv"
SPORTS_CSV = "data/data_sports/대구_체육시설_정제데이터.csv"
OUTPUT_CSV = "data/ua_data/daegu_최종_통합결과_체육시설포함.csv"
REGION_CACHE_PATH = "data/ua_data/region_cache.json"  # 기존 유치원 파이프라인과 캐시 공유

SOURCE_EPSG = "EPSG:5174"  # 중부원점 TM (서울 열린데이터광장 안내 기준)


# ============================================
# 1. TM 좌표 -> WGS84 위경도 변환
# ============================================
def convert_tm_to_wgs84(df, x_col="좌표정보(X)", y_col="좌표정보(Y)"):
    transformer = Transformer.from_crs(SOURCE_EPSG, "EPSG:4326", always_xy=True)
    lats, lngs = [], []
    for x, y in zip(df[x_col], df[y_col]):
        if pd.isna(x) or pd.isna(y):
            lats.append(None)
            lngs.append(None)
            continue
        lon, lat = transformer.transform(x, y)
        lats.append(lat)
        lngs.append(lon)
    df["위도"] = lats
    df["경도"] = lngs
    return df


# ============================================
# 2. 좌표 -> 행정동 역조회 (기존 파이프라인과 캐시 공유)
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


# ============================================
# 3. 이름 정규화 (기존 파이프라인과 동일한 규칙)
# ============================================
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
# 4. 메인
# ============================================
def main():
    if KAKAO_API_KEY == "여기에_카카오_REST_API_키_입력":
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(MISMATCH_CSV):
        print(f"[오류] 파일 없음: {MISMATCH_CSV}")
        return
    if not os.path.exists(SPORTS_CSV):
        print(f"[오류] 파일 없음: {SPORTS_CSV}")
        return

    mismatch = load_csv_auto(MISMATCH_CSV)
    sports = load_csv_auto(SPORTS_CSV)

    print(f"[정보] 미스매치 결과 {len(mismatch)}행, 체육시설 원본 {len(sports)}행 로드")

    if "영업상태명" in sports.columns:
        before = len(sports)
        sports = sports[sports["영업상태명"] == "영업/정상"].copy()
        if len(sports) != before:
            print(f"[정보] 영업/정상만 필터링: {before}행 -> {len(sports)}행")

    # 1) TM -> WGS84 변환
    print("\n[1단계] TM 좌표 -> WGS84 변환...")
    sports = convert_tm_to_wgs84(sports)
    n_coord_fail = sports["위도"].isna().sum()
    print(f"[1단계 완료] 좌표 변환 실패: {n_coord_fail} / {len(sports)}")

    # 2) 좌표 -> 행정동 역조회
    print("\n[2단계] 좌표 -> 행정동 역조회 (카카오 API)...")
    sports = add_dong_column(sports, KAKAO_API_KEY)
    n_dong_fail = sports["읍면동_행정"].isna().sum()
    print(f"[2단계 완료] 행정동 매칭 실패: {n_dong_fail} / {len(sports)}")

    # 3) 구군+행정동 단위 집계
    sports["_구군_norm"] = sports["구군_행정"].apply(normalize_name)
    sports["_읍면동_norm"] = sports["읍면동_행정"].apply(normalize_name)

    agg_dict = {"체육시설수": ("사업장명", "count")}
    sports_agg = sports.groupby(["_구군_norm", "_읍면동_norm"]).agg(**agg_dict)
    if "유아특화_여부" in sports.columns:
        sports_agg["유아특화_체육시설수"] = sports.groupby(["_구군_norm", "_읍면동_norm"])["유아특화_여부"].sum()
    if "유아가능_여부" in sports.columns:
        sports_agg["유아가능_체육시설수"] = sports.groupby(["_구군_norm", "_읍면동_norm"])["유아가능_여부"].sum()
    sports_agg = sports_agg.reset_index()

    # 4) 미스매치 결과와 병합
    mismatch["_구군_norm"] = mismatch["시군구명"].apply(normalize_name)
    mismatch["_읍면동_norm"] = mismatch["읍면동명"].apply(normalize_name)

    merged = mismatch.merge(sports_agg, on=["_구군_norm", "_읍면동_norm"], how="left")

    for col in ["체육시설수", "유아특화_체육시설수", "유아가능_체육시설수"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype(int)

    merged = merged.drop(columns=["_구군_norm", "_읍면동_norm"])
    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[완료] '{OUTPUT_CSV}'에 저장했습니다. ({len(merged)}행)")
    print(f"\n[정보] 체육시설이 1곳 이상 있는 동: {(merged['체육시설수'] > 0).sum()} / {len(merged)}")
    print(f"[정보] 대구 전체 체육시설 총합(동 단위 합계): {merged['체육시설수'].sum()}")
    print(f"[참고] 원본(영업/정상) 총합: {len(sports)} — 위 합계와 최대한 가까워야 매칭이 온전한 것")


if __name__ == "__main__":
    main()