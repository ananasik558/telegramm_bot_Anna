FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY tests ./tests
COPY pytest.ini ./
COPY README.md ./

RUN mkdir -p /app/data

CMD ["python", "-m", "bot"]
