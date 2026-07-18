FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r /tmp/requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home \
        --home-dir /home/app --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local
COPY --chown=app:app backend/ ./

# Bundle the FAISS index files so Cloud Run instances don't need to download them.
# ensure_faiss_artifacts() skips the download if these files are already present.
# Total size ~7MB — acceptable to bake into the image.
COPY --chown=app:app data/faiss/ /data/faiss/
COPY --chown=app:app data/graph/ /data/graph/
COPY --chown=app:app data/graph_schema/ /data/graph_schema/

USER app

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
