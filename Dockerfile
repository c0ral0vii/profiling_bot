# ❌ БЫЛО: FROM alpine:3.21
# ✅ СТАЛО: Debian с glibc
FROM python:3.10-slim-bookworm

ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /app

# Устанавливаем системные зависимости для Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    ffmpeg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN uv python install 3.10

COPY . .
RUN chmod +x ./scripts/*.sh

RUN uv run playwright install-deps
RUN uv run playwright install firefox

ENTRYPOINT ["sh"]