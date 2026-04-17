FROM python:3.10-slim

WORKDIR /app

# 安裝相依套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 啟動 FastAPI，監聽 8000 埠
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]