FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ironkeep ./ironkeep

RUN useradd --create-home --uid 1000 ironkeep
USER ironkeep

EXPOSE 8000
CMD ["uvicorn", "ironkeep.main:app", "--host", "0.0.0.0", "--port", "8000"]
