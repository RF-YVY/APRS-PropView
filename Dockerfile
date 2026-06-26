FROM python:3.12-slim

LABEL org.opencontainers.image.title="APRS PropView" \
      org.opencontainers.image.description="VHF APRS propagation monitor, map, digipeater, and IGate web application" \
      org.opencontainers.image.source="https://github.com/rf-yvy/aprs-propview" \
      org.opencontainers.image.url="https://github.com/rf-yvy/aprs-propview" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROPVIEW_DATA_DIR=/data \
    PROPVIEW_HOST=0.0.0.0 \
    PROPVIEW_PORT=14501 \
    PROPVIEW_LAUNCH_BROWSER=

WORKDIR /app

RUN addgroup --system propview \
    && adduser --system --ingroup propview --home /app propview \
    && mkdir -p /data \
    && chown -R propview:propview /app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=propview:propview main.py LICENSE NOTICE TRADEMARKS.md ./
COPY --chown=propview:propview server ./server
COPY --chown=propview:propview static ./static
COPY --chown=propview:propview ico ./ico
COPY --chown=propview:propview config.toml.example ./config.toml.example

USER propview

VOLUME ["/data"]
EXPOSE 14501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json, os, urllib.request; port=os.environ.get('PROPVIEW_PORT','14501'); data=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)"

CMD ["python", "main.py"]
