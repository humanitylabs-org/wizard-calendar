FROM python:3.12-slim-bookworm
WORKDIR /app
# zoneinfo needs IANA data; slim does not guarantee that it is installed.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data && chown 1000:1000 /data
COPY app/server.py app/prepare_data.py app/
COPY web web
COPY openapi.json openapi.json
ENV BIND=0.0.0.0 PORT=8799 DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 8799
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8799/healthz',timeout=2); assert r.status == 200"]
CMD ["python", "app/server.py"]
