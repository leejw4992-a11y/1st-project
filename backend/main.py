"""
대구 영유아 돌봄 인프라 분석 — FastAPI 웹 서버
------------------------------------------------------------------
정적 HTML(Leaflet 지도)이 하드코딩된 JSON을 그대로 담고 있던 기존 방식에서 벗어나,
FastAPI가 pandas로 만든 최종 데이터를 API로 제공하고, 프런트엔드(static/index.html)는
fetch()로 그 데이터를 받아 지도·대시보드를 그리는 구조로 바꿨다.

실행:
  uv run uvicorn main:app --reload --port 8000
  브라우저에서 http://127.0.0.1:8000 접속
"""

import math
import os

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from analysis_lib import (
    load_base_df, load_with_centroids, compute_entropy_composite,
    compute_regression_models, get_migration_insights,
)

# main.py가 이제 프로젝트 루트에 있으므로, 자기 자신의 위치가 곧 BASE_DIR
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="대구 영유아 돌봄 인프라 분석 API",
    description="수요(인구)-공급(정원)-실현(현원) 3대 지표 기반 미스매치 진단, "
                "엔트로피 가중치 종합지수, 회귀분석 결과를 제공합니다.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# 서버 기동 시 한 번만 무거운 계산(엔트로피 지수, 좌표 병합)을 해두고 메모리에 캐싱한다.
# 요청마다 다시 계산하지 않도록 함 (150행이라 사실 부담은 적지만, 구조적으로 맞는 방식).
# ------------------------------------------------------------------
_CACHE: dict = {}


def get_dong_df() -> pd.DataFrame:
    if "dong_df" not in _CACHE:
        _CACHE["dong_df"] = load_with_centroids()
    return _CACHE["dong_df"]


def get_regression_results() -> dict:
    if "regression" not in _CACHE:
        _CACHE["regression"] = compute_regression_models(load_base_df())
    return _CACHE["regression"]


def clean_json(records: list) -> list:
    """NaN -> None 변환 (JSON은 NaN을 표현할 수 없음)"""
    for r in records:
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
    return records


# ============================================
# API 엔드포인트
# ============================================
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dong")
def get_dong(
    gu: str | None = Query(default=None, description="시군구명으로 필터 (예: 수성구)"),
    mismatch_type: str | None = Query(default=None, alias="type", description="미스매치_유형으로 필터"),
):
    """읍면동 단위 전체 지표 (지도/테이블용)"""
    df = get_dong_df()
    if gu:
        df = df[df["시군구명"] == gu]
    if mismatch_type:
        df = df[df["미스매치_유형"] == mismatch_type]

    cols = [
        "시군구명", "읍면동명", "lat", "lng",
        "영유아인구_0_6세", "영아인구_0_2세", "유아인구_3_6세",
        "유치원수", "어린이집수", "체육시설수", "학원수",
        "전체_정원", "통합_현원", "전체_커버율", "전체_충원율",
        "인프라지수_엔트로피", "사분면", "미스매치_유형",
        "평균제곱미터당가격_만원", "합계출산율_2025", "고용률",
    ]
    cols = [c for c in cols if c in df.columns]
    records = df[cols].to_dict(orient="records")
    return clean_json(records)


@app.get("/api/summary")
def get_summary():
    """미스매치 유형별 분포 + 구별 요약 통계"""
    df = get_dong_df()

    type_counts = df["미스매치_유형"].value_counts().to_dict()

    gu_summary = (
        df[df["시군구명"] != "군위군"]
        .groupby("시군구명")
        .agg(
            읍면동수=("읍면동명", "count"),
            영유아인구_합계=("영유아인구_0_6세", "sum"),
            평균_전체커버율=("전체_커버율", "mean"),
            평균_전체충원율=("전체_충원율", "mean"),
            평균_체육시설수=("체육시설수", "mean"),
            평균_아파트가격=("평균제곱미터당가격_만원", "mean"),
        )
        .round(3)
        .reset_index()
    )

    return {
        "total_dong": int(len(df)),
        "mismatch_type_counts": type_counts,
        "district_summary": clean_json(gu_summary.to_dict(orient="records")),
    }


@app.get("/api/entropy")
def get_entropy():
    """6장: 엔트로피 가중치 산출 결과 및 민감도 분석"""
    df = load_base_df()
    result = compute_entropy_composite(df)
    return {
        "weights": result["weights"],
        "diagnostics": result["diagnostics"],
        "indicators": ["전체_커버율(공급충분도)", "체육밀도(유아1천명당 체육시설수)"],
    }


@app.get("/api/regression")
def get_regression():
    """7장: 회귀분석 결과 (모델 A - 충원율, 모델 B - 집값)"""
    return get_regression_results()


@app.get("/api/insights")
def get_insights():
    """인구이동(MDIS) 데이터 기반 추가 인사이트 (별도 팀원 산출물 반영)"""
    return get_migration_insights()


# ============================================
# 프런트엔드 (정적 파일)
# ============================================
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")