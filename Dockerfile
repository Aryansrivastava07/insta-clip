FROM python:3.12-slim

# Install system dependencies (ffmpeg for video processing, nodejs for Prisma CLI engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Generate Prisma Client
RUN prisma generate

# Expose port
EXPOSE 8000

ENV PORT=8000
ENV HOST=0.0.0.0

CMD ["python", "run.py"]
