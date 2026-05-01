FROM python:3.11-slim

# Install system dependencies (Tesseract FIX)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=10000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]