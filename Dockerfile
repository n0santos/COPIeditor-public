FROM python:3.14-slim

ARG BUILD_SHA=dev
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.revision="${BUILD_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"
ENV BUILD_SHA=${BUILD_SHA} BUILD_DATE=${BUILD_DATE}

WORKDIR /app

# System deps for pdfplumber / lxml + Java for HermiT OWL reasoner
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ensure raw dir exists (enrichment.db is mounted as PVC at runtime)
RUN mkdir -p data/raw

EXPOSE 8765

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
