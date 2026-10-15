FROM python:3.12-alpine
WORKDIR /app
RUN mkdir -p /data && chown 1000:1000 /data
COPY app/server.py app/server.py
COPY web web
COPY openapi.json openapi.json
ENV BIND=0.0.0.0 PORT=8799 DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
EXPOSE 8799
CMD ["python", "app/server.py"]
