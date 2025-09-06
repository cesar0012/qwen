# Dockerfile

# Usa una imagen base de Python oficial
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requisitos e instálalos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de tu aplicación
COPY . .

# Expone el puerto 8000 (el puerto por defecto de Uvicorn)
EXPOSE 8000

# El comando para iniciar la aplicación cuando el contenedor arranque
# Uvicorn se iniciará escuchando en todas las interfaces dentro del contenedor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]