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

load_dotenv()
app = FastAPI()

CREDS_FILE = Path("qwen_credentials.json")
QWEN_TOKEN_REFRESH_URL = "https://qwen.ai/oauth/token"
QWEN_CLIENT_ID = os.getenv("QWEN_CLIENT_ID", "dummy_client_id")
QWEN_CLIENT_SECRET = os.getenv("QWEN_CLIENT_SECRET", "dummy_client_secret")

# Clave secreta que coincide con el nombre de la variable en Coolify
PROXY_API_KEY = os.getenv("PROXY_API_KEY")

def load_credentials_from_file():
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text())
        except (json.JSONDecodeError, TypeError):
            return None
    return None

def save_credentials_to_file(creds):
    CREDS_FILE.write_text(json.dumps(creds, indent=4))

def refresh_token_if_needed():
    creds = load_credentials_from_file()
    if not creds:
        access_token = os.getenv("QWEN_ACCESS_TOKEN")
        refresh_token = os.getenv("QWEN_REFRESH_TOKEN")
        if not access_token or not refresh_token:
            print("ERROR: Credenciales iniciales de Qwen no encontradas.")
            return
        creds = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expiry_date": 0,
        }
        save_credentials_to_file(creds)
    
    if time.time() > (creds.get("expiry_date", 0) - 60):
        print("Token expirado. Refrescando...")
        try:
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"]
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
            print("Token refrescado exitosamente.")
        except Exception as e:
            print(f"ALERTA: No se pudo refrescar el token de Qwen: {e}")

async def verify_api_key(x_api_key: str = Header(None)):
    if PROXY_API_KEY is None:
        raise HTTPException(status_code=500, detail="El servidor no tiene una PROXY_API_KEY configurada.")
        
    if x_api_key is None or x_api_key != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="API Key del proxy inválida o no proporcionada en la cabecera X-API-Key")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Qwen Credential Server is running!"}

@app.get("/credentials.json", dependencies=[Depends(verify_api_key)])
def serve_credentials():
    refresh_token_if_needed()
    creds = load_credentials_from_file()
    if creds:
        return JSONResponse(content=creds)
    else:
        raise HTTPException(status_code=404, detail="Credenciales no disponibles en el servidor.")