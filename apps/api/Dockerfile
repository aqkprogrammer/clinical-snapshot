FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY apps/api/pyproject.toml /app/apps/api/
COPY apps/api/src /app/apps/api/src
RUN pip install --no-cache-dir /app/apps/api

COPY data /app/data

ENV CLINICAL_SNAPSHOT_BUNDLE_PATH=/app/data/scenario1_fhir_bundle.json

# Run unprivileged. The service only ever reads one file and binds one port.
RUN useradd --system --uid 10001 --no-create-home snapshot \
    && chown -R snapshot:snapshot /app
USER snapshot

EXPOSE 8000
CMD ["uvicorn", "clinical_snapshot.main:app", "--host", "0.0.0.0", "--port", "8000"]
