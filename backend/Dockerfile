FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TRANSITCROWD_MODEL=/app/backend/models/bengaluru-namma-metro/transitcrowd.joblib \
    TRANSITCROWD_DATA=/app/data/processed/namma_metro_station_hourly.csv \
    TRANSITCROWD_SOURCE_METADATA=/app/data/processed/namma_metro_station_hourly.metadata.json \
    CORS_ORIGINS=http://localhost:8080

WORKDIR /app
COPY backend/requirements-runtime.txt /app/backend/requirements-runtime.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /app/backend/requirements-runtime.txt

COPY backend/app /app/backend/app
COPY backend/models/bengaluru-namma-metro /app/backend/models/bengaluru-namma-metro
COPY data/processed/namma_metro_station_hourly.csv /app/data/processed/namma_metro_station_hourly.csv
COPY data/processed/namma_metro_station_hourly.metadata.json /app/data/processed/namma_metro_station_hourly.metadata.json
COPY ml /app/ml

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
