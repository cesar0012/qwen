FROM python:3.11-slim
WORKDIR /app

# Instalar supervisor y las dependencias de Python
COPY requirements.txt .
# Ya no necesitamos supervisor, solo gunicorn
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código, incluyendo oauth_creds.json
COPY . .

EXPOSE 8000

# Usamos Gunicorn para ejecutar Flask/FastAPI
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "main:app", "--worker-class", "uvicorn.workers.UvicornWorker"]