import os
import json
import time
from pathlib import Path
from typing import Optional

import requests # Usamos requests sincrónico, más simple para esta tarea
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

# Clave secreta para proteger el endpoint de credenciales
# Asegúrate de que la variable de entorno en Coolify se llame 'CREDENTIALS_API_KEY'
CREDENTIALS_API_KEY = os.getenv("CREDENTIALS_API_KEY", "MI_CLAVE_SECRETA_POR_DEFECTO")

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
            print("ERROR: Credenciales iniciales no encontradas en las variables de entorno.")
            return
        creds = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expiry_date": 0, # Forzar refresco la primera vez
        }
        save_credentials_to_file(creds)
    
    # Comprueba si el token ha expirado (con un margen de 60 segundos)
    if time.time() > (creds.get("expiry_date", 0) - 60):
        print("Token expirado o inicial. Refrescando...")
        try:
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": QWEN_CLIENT_ID,
                "client_secret": QWEN_CLIENT_SECRET,
            }
            response = requests.post(QWEN_TOKEN_REFRESH_URL, data=refresh_data, timeout=30)
            response.raise_for_status()
            
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
            print(f"ALERTA: No se pudo refrescar el token de Qwen: {e}")
            # No lanzamos un error, simplemente serviremos el token antiguo.
            # La próxima solicitud lo intentará de nuevo.

# --- <--- CAMBIO IMPORTANTE: FUNCIÓN DE SEGURIDAD CON LOGGING DE DEPURACIÓN ---
async def verify_api_key(x_api_key: str = Header(None)):
    """Verifica que la solicitud incluya la clave secreta correcta."""
    
    # Imprimimos en los logs para ver qué está pasando
    print("--- INICIO DE VERIFICACIÓN DE API KEY ---")
    print(f"DEBUG: Clave secreta esperada en el servidor: '{CREDENTIALS_API_KEY}'")
    print(f"DEBUG: Clave recibida en la cabecera X-API-Key: '{x_api_key}'")

    if x_api_key is None or x_api_key != CREDENTIALS_API_KEY:
        print("DEBUG: ¡La verificación de la clave falló!")
        print("--- FIN DE VERIFICACIÓN DE API KEY ---")
        raise HTTPException(status_code=401, detail="API Key inválida o no proporcionada en la cabecera X-API-Key")
    
    print("DEBUG: ¡La verificación de la clave fue exitosa!")
    print("--- FIN DE VERIFICACIÓN DE API KEY ---")
    return x_api_key

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
        raise HTTPException(status_code=404, detail="Credenciales no disponibles en el servidor.")