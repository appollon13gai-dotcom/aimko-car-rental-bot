FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Run the bot
CMD ["python", "bot.py"]
