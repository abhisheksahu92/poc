FROM python:3.11-slim

# Install poppler (needed for pdf2image)
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY tests/ ./tests/

# Create folders for mounted volumes
RUN mkdir -p ./data/source_pdfs ./data/source_pdfs

CMD ["python", "app/main.py"]
