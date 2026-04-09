FROM python:3.11-slim

# Устанавливаем системные зависимости для Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxss1 \
    libgtk-3-0 \
    libxrandr2 \
    libxcomposite1 \
    libxdamage1 \
    libcups2 \
    libpango-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    fonts-liberation \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем браузер Chromium для Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# Копируем исходный код
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]
