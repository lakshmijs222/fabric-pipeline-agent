# Fabric L1 Support Bot — container image (runs both the bot and the dashboard).
# A single image is built once; docker-compose runs it as two services with
# different start commands.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (see .dockerignore for what's excluded)
COPY . .

# Runtime data/logs — persisted via volumes in compose / cloud
RUN mkdir -p data logs

# Default command runs the bot; the dashboard service overrides this in compose.
CMD ["python", "main.py"]
