FROM python:3.11-slim
WORKDIR /app

# Instalar supervisor y las dependencias de Python
COPY requirements.txt .
RUN apt-get update && apt-get install -y supervisor && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar el código de la aplicación y la configuración de supervisor
COPY . .

EXPOSE 8000

# El comando para iniciar supervisor
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]