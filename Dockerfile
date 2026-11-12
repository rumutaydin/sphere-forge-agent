# Based on the organisers' template Dockerfile. Entry point and arguments must stay:
#   python scripts/main.py --input_dir <inputs> --output_dir <outputs>
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

# The CAD kernel (OpenCASCADE via CadQuery) needs these at import time
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies (cached layer, only rebuilt when the lockfile changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app

ENV PATH="/app/.venv/bin:$PATH"
# The container runs as a non-root user: nothing may be written outside /tmp and the output dir
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp

# Agent settings, frozen with the commit. After code freeze the handed-over <team>.env replaces them.
# ENV OPENAI_BASE_URL=http://<your Brev instance>:8000/v1 \
#     OPENAI_API_KEY=<your vLLM --api-key> \
#     OPENAI_MODEL=<model>
ENV FORGE_DEPTH=off FORGE_FACES=off FORGE_THINKING=on FORGE_REASONING_EFFORT=medium FORGE_MAX_TOKENS=16000 FORGE_LLM_TIMEOUT_S=700 FORGE_CANDIDATES=2 FORGE_CARVE=1 FORGE_WORKERS=9 FORGE_BUDGET_S=3000

CMD ["python", "scripts/main.py"]
