FROM python:3.11-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files and static resources
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Default environment configuration
ENV PORT=8080
ENV HOST=0.0.0.0
ENV YTDLP_COOLDOWN=600
ENV COOKIES_FILE=cookies.txt
ENV MAX_STREAM_TIMEOUT=60.0

# Expose port
EXPOSE 8080

# Run application through python main block to apply environment variables
CMD ["python", "app.py"]
