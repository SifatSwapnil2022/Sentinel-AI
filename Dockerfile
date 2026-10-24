# One image runs the API (default), the worker and the admin CLI:
#   docker run sentinel-server                        -> API on :8000
#   docker run sentinel-server sentinel-worker        -> background worker
#   docker run sentinel-server sentinel-admin migrate -> database migrations
# The `demo` target adds the simulator and its dependencies.

ARG PYTHON=3.13

FROM python:${PYTHON}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so source edits don't invalidate the slowest layer.
COPY pyproject.toml uv.lock ./
COPY core/pyproject.toml core/README.md core/
COPY server/pyproject.toml server/
COPY sdk/python/pyproject.toml sdk/python/README.md sdk/python/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-workspace --package sentinel-server
COPY core/src core/src
COPY server/src server/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package sentinel-server

FROM python:${PYTHON}-slim AS server
RUN useradd --system --uid 10001 --no-create-home sentinel
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER sentinel
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
CMD ["sentinel-api"]

FROM build AS demo-build
COPY sdk/python/src sdk/python/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --all-packages

FROM python:${PYTHON}-slim AS demo
RUN useradd --system --uid 10001 --no-create-home sentinel
COPY --from=demo-build /app/.venv /app/.venv
COPY demo /app/demo
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/demo
USER sentinel
ENTRYPOINT ["python", "simulate.py"]
