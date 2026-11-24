# Stage 1: Build
FROM python:3.12-slim-bookworm as builder

# Install build dependencies (gcc, Python headers, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy only the requirements file to take advantage of Docker's caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim-bookworm

# Set the working directory
WORKDIR /app

# Copy installed Python packages and binaries from the builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application code
COPY . .

# Expose HTTP health check port
EXPOSE 8080

# Docker container health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, sys, urllib.request; sys.exit(0) if os.getenv('HEALTH_ENABLE', 'true').strip().lower() in ('false', '0', 'no') else urllib.request.urlopen('http://127.0.0.1:' + os.getenv('HEALTH_PORT', '8080') + '/health', timeout=4)" || exit 1

# Run the application
CMD ["python", "-u", "main.py"]