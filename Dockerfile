FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY knowledge ./knowledge
COPY scripts ./scripts
# Build the embedding index at start-up if a key is present (cheap: ~100 chunks), then serve.
CMD sh -c "python -m scripts.build_index || true; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
