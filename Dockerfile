FROM python:3.11-slim-bookworm

# Install Chromium and dumb-init
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-common \
    fonts-liberation \
    dumb-init \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_PATH=/usr/bin/chromium \
    PYTHONUNBUFFERED=1 \
    FAST_BROWSER_HOST=127.0.0.1 \
    FAST_BROWSER_PORT=9222 \
    FAST_BROWSER_AUTO_LAUNCH=1

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt .

COPY fast_browser/ ./fast_browser/

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["python3", "-m", "fast_browser.server"]
