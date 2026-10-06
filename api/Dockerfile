ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG LLAMA_CPP_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cpu

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
RUN uv venv --python 3.12 /opt/venv

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install torch --index-url ${TORCH_INDEX}

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install llama-cpp-python --extra-index-url ${LLAMA_CPP_INDEX} --only-binary llama-cpp-python

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r /tmp/requirements.txt

WORKDIR /srv
COPY app ./app

EXPOSE 8000
VOLUME /models

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
