import os
import json
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Configuración ---
load_dotenv()
app = FastAPI()

# --- Variables Globales y Archivo de Estado ---
CREDS_FILE = Path("qwen_credentials.json") # Archivo para persistir los tokens
QWEN_TOKEN_REFRESH_URL = "https://qwen.ai/oauth/token"
QWEN_CLIENT_ID = os.getenv("QWEN_CLIENT_ID", "dummy_client_id")
QWEN_CLIENT_SECRET = os.getenv("QWEN_CLIENT_SECRET", "dummy_client_secret")

# Clave secreta para proteger el endpoint de credenciales.
# Esta se carga desde la variable de entorno de Coolify.
PROXY_API_KEY = os.getenv("PROXY_API_KEY")

# --- Funciones de Ayuda ---
def load_credentials_from_file():
    """Carga las credenciales únicamente desde el archivo JSON."""
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            return None
    return None

def save_credentials_to_file(creds):
    """Guarda las credenciales en el archivo JSON."""
    CREDS_FILE.write_text(json.dumps(creds, indent=4))

def refresh_token_if_needed():
    """
    Verifica si el token ha expirado y lo refresca si es necesario.
    Esta función ahora se ejecuta de forma síncrona.
    """
    creds = load_credentials_from_file()
    if not creds:
        # Si el archivo no existe, intenta crearlo desde las variables de entorno
        access_token = os.getenv("QWEN_ACCESS_TOKEN")
        refresh_token = os.getenv("QWEN_REFRESH_TOKEN")
        if not access_token or not refresh_token:
            print("ERROR: Credenciales iniciales de Qwen no encontradas en las variables de entorno.")
            return
        creds = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expiry_date": 0, # Forzar refresco la primera vez
        }
        save_credentials_to_file(creds)
    
    # Comprueba si el token ha expirado (con un margen de 60 segundos)
    if time.time() > (creds.get("expiry_date", 0) - 60):
        print("Token expirado o inicial. Intentando refrescar...")
        try:
            # --- <--- CAMBIO IMPORTANTE: Simplificamos el payload de la solicitud ---
            # La CLI de Qwen probablemente solo envía el refresh_token, sin client_id/secret.
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"]
            }
            
            response = requests.post(QWEN_TOKEN_REFRESH_URL, data=refresh_data, timeout=30)
            response.raise_for_status() # Lanza un error si la respuesta es 4xx o 5xx
            
            new_token_data = response.json()
            new_expiry = int(time.time()) + new_token_data.get("expires_in", 3600)
            
            # Formateamos el JSON para que sea compatible con Kilo Code / Qwen CLI
            new_creds = {
                "access_token": new_token_data["access_token"],
                "refresh_token": new_token_data.get("refresh_token", creds["refresh_token"]),
                "expiry_date": new_expiry,
                "token_type": "Bearer",
                "resource_url": "portal.qwen.ai"
            }
            save_credentials_to_file(new_creds)
            print("Token refrescado exitosamente.")
        except Exception as e:
            # Imprime una alerta si el refresco falla, pero no detiene el servidor.
            print(f"ALERTA: No se pudo refrescar el token de Qwen. Error: {e}")

# --- Función de Seguridad ---
async def verify_api_key(x_api_key: str = Header(None)):
    """Verifica que la solicitud incluya la clave secreta correcta."""
    if PROXY_API_KEY is None:
        # Medida de seguridad: si la clave secreta no está configurada en el servidor, no permitir ninguna solicitud.
        raise HTTPException(status_code=500, detail="El servidor no tiene una PROXY_API_KEY configurada.")
        
    if x_api_key is None or x_api_key != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida o no proporcionada en la cabecera X-API-Key")

# --- Endpoints de la API ---
@app.get("/")
def health_check():
    """Endpoint de estado para verificar que el servidor está en línea."""
    return {"status": "ok", "message": "Qwen Credential Server is running!"}

@app.get("/credentials.json", dependencies=[Depends(verify_api_key)])
def serve_credentials():
    """
    Endpoint seguro que primero refresca el token si es necesario,
    y luego sirve el archivo de credenciales.
    """
    refresh_token_if_needed() # Asegurarse de que esté actualizado antes de servirlo
    
    creds = load_credentials_from_file()
    if creds:
        return JSONResponse(content=creds)
    else:
        # Esto solo debería ocurrir si las variables de entorno no están configuradas.
        raise HTTPException(status_code=404, detail="Credenciales no disponibles en el servidor.")