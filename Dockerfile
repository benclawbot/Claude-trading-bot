# Dockerfile for BTC Trading Bot
# Build: docker build -t trading-bot .
# Run:   docker run -d --name trading-bot -v $(pwd)/trading_bot.db:/app/trading_bot.db -v $(pwd)/models:/app/models -v $(pwd)/trading_bot.log:/app/trading_bot.log --env-file .env trading-bot

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create models directory
RUN mkdir -p models

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Expose dashboard port
EXPOSE 8050

# Run the bot
CMD ["python", "main.py"]
