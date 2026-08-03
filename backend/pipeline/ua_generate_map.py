"""
대구 돌봄공백 미스매치 지도 생성 스크립트
------------------------------------------------
final_mismatch_analysis.py의 결과(daegu_최종_미스매치_결과.csv)를 읽어서,
읍면동별 대표 좌표를 카카오 주소검색 API로 구한 뒤,
Leaflet.js 기반 인터랙티브 웹페이지(HTML) 하나로 만듭니다.

사용법:
  1. KAKAO_API_KEY 입력
  2. INPUT_CSV 파일명 확인
  3. python generate_map.py 실행
  4. daegu_돌봄지도.html 파일이 생성됩니다 -> 더블클릭하면 브라우저에서 바로 열림
"""

import pandas as pd
import requests
import time
import json
import os

# ============================================
# 0. 설정
# ============================================
KAKAO_API_KEY = "860588e2100897c43eb155016f51d129"
INPUT_CSV = "data/ua_data/daegu_최종_통합결과_학원지수반영.csv"
OUTPUT_HTML = "daegu_돌봄지도.html"
CENTROID_CACHE_PATH = "data/ua_data/dong_centroid_cache.json"

# 미스매치 유형별 색상 (지도 마커 + 범례에 사용)
TYPE_COLORS = {
    "완전공백": "#8B0000",      # 진한 빨강 - 가장 심각
    "이중취약": "#FF4500",      # 주황빨강
    "물리적부족": "#FFA500",    # 주황
    "질적미스매치": "#4169E1",  # 파랑
    "양호": "#2E8B57",          # 초록
    "판정불가": "#A9A9A9",      # 회색
}


# ============================================
# 1. 읍면동 대표 좌표 구하기 (카카오 주소검색)
# ============================================
def load_cache(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocode_dong(query, api_key, cache):
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


def add_centroids(df, api_key):
    cache = load_cache(CENTROID_CACHE_PATH)
    lats, lngs = [], []
    total = len(df)

    for i, row in enumerate(df.itertuples(), start=1):
        # "대구광역시 중구 동인동"처럼 검색 -> 대표 좌표 확보
        query = f"대구광역시 {row.시군구명} {row.읍면동명}"
        result = geocode_dong(query, api_key, cache)
        lats.append(result["lat"])
        lngs.append(result["lng"])
        if i % 20 == 0 or i == total:
            print(f"[진행] {i}/{total}")
        time.sleep(0.05)

    save_cache(CENTROID_CACHE_PATH, cache)
    df["중심_위도"] = lats
    df["중심_경도"] = lngs
    return df


# ============================================
# 2. HTML(Leaflet 지도) 생성
# ============================================
def build_html(df):
    markers = []
    for row in df.itertuples():
        if pd.isna(row.중심_위도) or pd.isna(row.중심_경도):
            continue
        mtype = row.미스매치_유형
        color = TYPE_COLORS.get(mtype, "#999999")

        cover = f"{row.전체_커버율:.1%}" if hasattr(row, '전체_커버율') and pd.notna(row.전체_커버율) else "-"
        fill = f"{row.전체_충원율:.1%}" if hasattr(row, '전체_충원율') and pd.notna(row.전체_충원율) else "-"

        # 구 단위 사회지표 (같은 구 안의 모든 동이 값을 공유 -> "구 참고값"이라고 명시)
        birth_rate = f"{row.합계출산율_2025:.2f}" if hasattr(row, '합계출산율_2025') and pd.notna(row.합계출산율_2025) else "-"
        employ_rate = f"{row.고용률:.1f}%" if hasattr(row, '고용률') and pd.notna(row.고용률) else "-"
        unemploy_rate = f"{row.실업률:.1f}%" if hasattr(row, '실업률') and pd.notna(row.실업률) else "-"
        newlywed = f"{int(row.신혼부부수_2024):,}쌍" if hasattr(row, '신혼부부수_2024') and pd.notna(row.신혼부부수_2024) else "-"
        price = f"{row.평균제곱미터당가격_만원:,.0f}만원/㎡" if hasattr(row, '평균제곱미터당가격_만원') and pd.notna(row.평균제곱미터당가격_만원) else "-"

        popup = (
            f"<b>{row.시군구명} {row.읍면동명}</b><br>"
            f"유형: <b>{mtype}</b><br>"
            f"영유아인구(0-6세): {int(row.영유아인구_0_6세):,}명<br>"
            f"유치원 {int(row.유치원수)}곳 · 어린이집 {int(getattr(row, '어린이집수', 0))}곳<br>"
            f"보육시설 정원 합계: {int(row.통합_정원):,}명 · 현원 합계: {int(row.통합_현원):,}명<br>"
            f"전체 커버율(보육+학원 정원/인구): {cover}<br>"
            f"보육 충원율(현원/정원): {fill}<br>"
            f"체육시설(태권도장 등): {int(getattr(row, '체육시설수', 0))}곳"
            + (f" (유아가능 {int(row.유아가능_체육시설수)}곳)" if hasattr(row, '유아가능_체육시설수') else "")
            + f"<br>학원(영유아 대상): {int(getattr(row, '학원수', 0))}곳"
            + f"<br>아파트 평균가: {price}"
            + f"<br><span style='color:#888;font-size:11px'>--- 구 참고값 ---</span><br>"
            f"<span style='color:#888;font-size:11px'>합계출산율(2025): {birth_rate} · "
            f"고용률: {employ_rate} · 실업률: {unemploy_rate} · 신혼부부(2024): {newlywed}</span>"
        )
        # 인구 규모에 비례해 마커 크기 조정 (최소 6, 최대 22)
        radius = max(6, min(22, (row.영유아인구_0_6세 / 80)))

        markers.append({
            "lat": row.중심_위도,
            "lng": row.중심_경도,
            "color": color,
            "radius": radius,
            "popup": popup,
            "type": mtype,
        })

    markers_json = json.dumps(markers, ensure_ascii=False)
    legend_items = "".join(
        f'<div><span style="background:{c};width:12px;height:12px;'
        f'display:inline-block;border-radius:50%;margin-right:6px;"></span>{t}</div>'
        for t, c in TYPE_COLORS.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>대구 영유아 돌봄지도</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" />
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  body {{ margin:0; font-family: "Malgun Gothic", sans-serif; }}
  #map {{ height: 100vh; width: 100%; }}
  #legend {{
    position: absolute; top: 12px; right: 12px; z-index: 1000;
    background: white; padding: 12px 16px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3); font-size: 14px; line-height: 1.6;
  }}
  #title {{
    position: absolute; top: 12px; left: 12px; z-index: 1000;
    background: white; padding: 10px 16px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3); font-size: 16px; font-weight: bold;
  }}
</style>
</head>
<body>
<div id="title">대구시 영유아 돌봄지도<br><span style="font-weight:normal;font-size:12px;">동네마다 다른 온도와 정책 우선지역</span></div>
<div id="legend"><b>미스매치 유형</b>{legend_items}</div>
<div id="map"></div>
<script>
  const markers = {markers_json};

  // 대구광역시 경계 (실제 마커 분포 범위 기준으로 타이트하게 설정)
  const daeguBounds = L.latLngBounds([35.60, 128.35], [36.30, 128.85]);

  const map = L.map('map', {{
    maxBounds: daeguBounds.pad(0.05),  // 약간의 여유만 두고 그 밖은 못 나가게
    maxBoundsViscosity: 1.0,
    minZoom: 11,                       // 너무 줌아웃해서 경북 전체가 보이지 않도록 상향
  }}).fitBounds(daeguBounds);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  markers.forEach(m => {{
    L.circleMarker([m.lat, m.lng], {{
      radius: m.radius,
      fillColor: m.color,
      color: '#333',
      weight: 1,
      fillOpacity: 0.75
    }}).addTo(map).bindPopup(m.popup);
  }});
</script>
</body>
</html>
"""
    return html


# ============================================
# 3. 메인
# ============================================
def main():
    if KAKAO_API_KEY == "여기에_카카오_REST_API_키_입력":
        print("[오류] KAKAO_API_KEY를 입력해주세요.")
        return
    if not os.path.exists(INPUT_CSV):
        print(f"[오류] 파일 없음: {INPUT_CSV}")
        return

    df = None
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            df = pd.read_csv(INPUT_CSV, encoding=enc)
            break
        except Exception:
            continue
    if df is None:
        print("[오류] CSV 인코딩 인식 실패")
        return

    print(f"[정보] {len(df)}개 읍면동 로드")
    print("\n[1단계] 읍면동 대표 좌표 구하는 중...")
    df = add_centroids(df, KAKAO_API_KEY)
    n_failed = df["중심_위도"].isna().sum()
    print(f"[1단계 완료] 좌표 실패: {n_failed} / {len(df)}")

    print("\n[2단계] 지도 HTML 생성 중...")
    html = build_html(df)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[완료] '{OUTPUT_HTML}' 생성 완료. 더블클릭해서 브라우저로 열어보세요.")


if __name__ == "__main__":
    main()