import os
import json
import time
from pathlib import Path
import requests
from dotenv import load_dotenv

# Carga las mismas variables de entorno que la app principal
load_dotenv()

CREDS_FILE = Path("qwen_credentials.json")
QWEN_TOKEN_REFRESH_URL = "https://qwen.ai/oauth/token"
QWEN_CLIENT_ID = os.getenv("QWEN_CLIENT_ID", "dummy_client_id")
QWEN_CLIENT_SECRET = os.getenv("QWEN_CLIENT_SECRET", "dummy_client_secret")
REFRESH_INTERVAL_SECONDS = 3600 # Refrescar cada hora

def load_credentials_from_file():
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            return None
    return None

def save_credentials_to_file(creds):
    CREDS_FILE.write_text(json.dumps(creds, indent=4))

def initialize_credentials():
    """Crea el archivo de credenciales desde el entorno si no existe."""
    if not CREDS_FILE.exists():
        access_token = os.getenv("QWEN_ACCESS_TOKEN")
        refresh_token = os.getenv("QWEN_REFRESH_TOKEN")
        if not access_token or not refresh_token:
            print("ERROR: Credenciales iniciales no encontradas en las variables de entorno.")
            return False
        creds = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expiry_date": 0,
        }
        save_credentials_to_file(creds)
        print("Archivo de credenciales inicializado desde el entorno.")
    return True

def refresh_token():
    """Función principal del worker: carga, refresca y guarda el token."""
    print("Worker: Iniciando ciclo de refresco...")
    creds = load_credentials_from_file()
    if not creds:
        print("Worker: No se encontraron credenciales para refrescar.")
        return

    print("Worker: Refrescando token...")
    try:
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": creds["refresh_token"],
        }
        response = requests.post(QWEN_TOKEN_REFRESH_URL, data=refresh_data, timeout=30)
        response.raise_for_status()
        
        new_token_data = response.json()
        new_expiry = int(time.time()) + new_token_data.get("expires_in", 3600)
        
        new_creds = {
            "access_token": new_token_data["access_token"],
            "refresh_token": new_token_data.get("refresh_token", creds["refresh_token"]),
            "expiry_date": new_expiry,
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai"
        }
        save_credentials_to_file(new_creds)
        print(f"Worker: Token refrescado exitosamente. Nueva expiración en {time.ctime(new_expiry)}")
    except Exception as e:
        print(f"Worker ERROR: No se pudo refrescar el token de Qwen. Error: {e}")

if __name__ == "__main__":
    if not initialize_credentials():
        exit(1)
        
    # Bucle infinito para refrescar periódicamente
    while True:
        refresh_token()
        print(f"Worker: Durmiendo durante {REFRESH_INTERVAL_SECONDS / 60} minutos...")
        time.sleep(REFRESH_INTERVAL_SECONDS)