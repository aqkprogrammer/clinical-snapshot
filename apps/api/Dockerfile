FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY apps/api/pyproject.toml /app/apps/api/
COPY apps/api/src /app/apps/api/src
RUN pip install --no-cache-dir /app/apps/api

COPY data /app/data

ENV CLINICAL_SNAPSHOT_BUNDLE_PATH=/app/data/scenario1_fhir_bundle.json

EXPOSE 8000
CMD ["uvicorn", "clinical_snapshot.main:app", "--host", "0.0.0.0", "--port", "8000"]
