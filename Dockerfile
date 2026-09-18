FROM python:3.12-slim

WORKDIR /app

# System deps (none required beyond slim for this app)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY config ./config
COPY data ./data
COPY src ./src

RUN pip install --no-cache-dir .

# Ensure writable dirs for cache + tip sheets + web state
RUN mkdir -p /app/output/pages /app/data/cache \
    && chmod -R a+rwX /app/output /app/data

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "hkjc_predictor.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
