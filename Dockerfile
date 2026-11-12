FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/app.db \
    FILES_DIR=/data/files

WORKDIR /app

# Runtime libraries required by OpenCV's headless wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --system --uid 10001 --create-home appuser \
    && mkdir -p /data/files \
    && chown -R appuser:appuser /app /data

COPY --chown=10001:10001 . .

USER 10001:10001

EXPOSE 8787
VOLUME ["/data"]

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers"]
