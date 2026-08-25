FROM python:3.11-slim

WORKDIR /app

# 安裝基本相依工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 設定時區為台北
ENV TZ=Asia/Taipei
ENV PYTHONUNBUFFERED=1

# 安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案原始碼
COPY . .

# 建立 data 目錄供 SQLite 掛載
RUN mkdir -p /app/data

CMD ["python", "main.py"]
