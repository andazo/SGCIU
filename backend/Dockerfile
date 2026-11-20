FROM python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd

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
