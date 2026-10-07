FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CORS_ORIGINS=http://localhost:8080

WORKDIR /app

# Serving dependencies only (no training/test extras), so the image stays small and the runtime
# cannot accidentally start a model-selection run.
COPY backend/requirements-runtime.txt /app/backend/requirements-runtime.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /app/backend/requirements-runtime.txt

COPY backend/app /app/backend/app
COPY ml /app/ml
# Which families exist is decided by the registry, not by this file: every registered family that is
# eligible for serving gets its own service, so a family with missing data or artifacts degrades alone
# instead of turning into a 404 for the whole deployment.
COPY data/registry /app/data/registry
# Bengaluru and Chennai serve from data/processed; families registered through
# scripts/register_demand_dataset.py serve from the compressed inference copies published under
# data/inference. No raw multi-hundred-MB source CSV is copied into the image and nothing parses one
# at startup.
COPY data/processed /app/data/processed
COPY data/inference /app/data/inference
# Committed model bundles for the families this project ships (Bengaluru, Chennai). Bundles fitted in
# a development sandbox for the Mumbai demonstration families are deliberately not committed or copied;
# they are rebuilt with scripts/run_mumbai_registration.sh on the machine that will run them.
COPY backend/models /app/backend/models

# Chennai: its normalized extract is copyright CMRL, so it is not in the repository - only its provenance
# sidecar is, and the registry entry carries data_preparation_command. To serve Chennai from this image, run
# `python3 scripts/prepare_chennai_data.py` during the build (or copy your own CSV in); without it the
# container still serves Bengaluru and both Mumbai demonstration families and answers Chennai with a 503 that
# names the missing file rather than pretending the family does not exist.
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
