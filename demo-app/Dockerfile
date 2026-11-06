# Expense splitter demo app: seeds the "Goa trip" group on first start, then serves on port 8000.
FROM python:3.15.0-slim

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
# The slim image has no curl, so the check uses Python's own HTTP client.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["sh", "-c", "python seed.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
