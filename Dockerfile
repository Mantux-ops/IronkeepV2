FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY bot/requirements.txt bot-requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r bot-requirements.txt

COPY . .

RUN chmod +x scripts/run_app.sh scripts/run_scheduler.sh

EXPOSE 8000

CMD ["./scripts/run_app.sh"]