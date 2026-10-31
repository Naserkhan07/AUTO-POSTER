FROM python:3.12-slim

# Install system dependencies: ffmpeg, git, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest and install package
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application code and assets
COPY shorts_bot/ ./shorts_bot/
COPY channels.toml main.py links.txt ./
COPY assets/ ./assets/

# Define persistent storage directories
VOLUME ["/app/work", "/app/credentials"]

# Default entrypoint runs the 24/7 autopilot scheduler and uploader
CMD ["python", "main.py"]
