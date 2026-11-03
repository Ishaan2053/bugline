# Expense splitter demo app: seeds the "Goa trip" group on first start, then serves on port 8000.
FROM python:3.14.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BUGLINE_DB=/data/bugline.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY seed.py .

RUN useradd --create-home bugline && mkdir /data && chown bugline /data
USER bugline

EXPOSE 8000
CMD ["sh", "-c", "python seed.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
