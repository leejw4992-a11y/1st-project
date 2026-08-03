FROM python:3.14

# 공식 이미지에 uv가 없으므로 바이너리만 복사
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# 대문자 UV가 아니라 소문자 uv 명령 사용
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]