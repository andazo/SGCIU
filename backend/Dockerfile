FROM python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apk upgrade --no-cache && addgroup -S sgciu && adduser -S -G sgciu sgciu

COPY requirements.txt ./
RUN pip install -r requirements.txt && pip uninstall --yes pip

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY corpus ./corpus
COPY evaluation ./evaluation

USER sgciu
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
