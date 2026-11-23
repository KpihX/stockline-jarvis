# Python service image (backend or ai): `docker build --build-arg APP=backend -f docker/python.Dockerfile .`
# Dependencies come from the app's uv.lock (cached layer); the code is bind-mounted in dev for --reload.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG APP
# Optional extras, empty by default (the stock image is unchanged). Used by the `ai` service for the NVIDIA STT provider:
#   AI_UV_SYNC_ARGS="--extra nvidia"   AI_APT_PACKAGES="ffmpeg"   in .env, then `make rebuild` (see README, "NVIDIA STT")
ARG UV_SYNC_ARGS=""
ARG APT_PACKAGES=""
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app/apps/${APP}

RUN if [ -n "$APT_PACKAGES" ]; then apt-get update && apt-get install -y --no-install-recommends $APT_PACKAGES && rm -rf /var/lib/apt/lists/*; fi
COPY apps/${APP}/pyproject.toml apps/${APP}/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project $UV_SYNC_ARGS

COPY apps/${APP}/ ./
EXPOSE 4000 4100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
