# Synapse node: FastAPI HTTP API (port 8000) + P2P socket server (port 7000).

FROM docker.io/library/python:3.14-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM docker.io/library/python:3.14-slim
LABEL org.opencontainers.image.title="synapse-backend" \
      org.opencontainers.image.description="Synapse node: search API, P2P shard, analytics"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    SYNAPSE_DATA_DIR=/data \
    SYNAPSE_SAMPLES_DIR=/app/datasets
RUN useradd --system --uid 10001 --create-home --home-dir /app synapse \
    && mkdir -p /data && chown synapse:synapse /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=synapse:synapse synapse ./synapse
COPY --chown=synapse:synapse datasets ./datasets
USER synapse
EXPOSE 8000 7000
VOLUME ["/data"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "synapse", "serve"]
