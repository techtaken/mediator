# FastAPI backend. Build from the backend/ folder:
#   docker build -t mediator-api backend
#   docker run -p 8000:8000 --env-file backend/.env mediator-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 mediator
USER mediator

EXPOSE 8000
# One process: rate limits and live-update streams are in-process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
