import os
import json
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Configuración ---
# Carga las variables de entorno desde un archivo .env (útil para desarrollo local)
load_dotenv()

# Define la clase para las credenciales de Qwen
class QwenCredentials(BaseModel):
    access_token: str
    refresh_token: str
    expiry_date: int

# --- Variables Globales y Funciones de Ayuda ---
app = FastAPI()
CREDS_FILE = Path("qwen_credentials.json") # Archivo para persistir tokens refrescados

QWEN_API_BASE_URL = "https://portal.qwen.ai"
QWEN_TOKEN_REFRESH_URL = "https://qwen.ai/oauth/token"
QWEN_CLIENT_ID = os.getenv("QWEN_CLIENT_ID", "dummy_client_id")
QWEN_CLIENT_SECRET = os.getenv("QWEN_CLIENT_SECRET", "dummy_client_secret")

# --- <--- CAMBIO IMPORTANTE: Clave secreta para nuestro proxy ---
# Esta clave la definirás en las variables de entorno de Coolify
PROXY_API_KEY_SECRET = os.getenv("PROXY_API_KEY", "MI_CLAVE_SUPER_SECRETA_123")

def load_credentials() -> Optional[QwenCredentials]:
    """Carga las credenciales desde el archivo o las variables de entorno."""
    # Prioridad 1: Cargar desde el archivo si existe (para tokens refrescados)
    if CREDS_FILE.exists():
        try:
            creds_data = json.loads(CREDS_FILE.read_text())
            return QwenCredentials(**creds_data)
        except (json.JSONDecodeError, TypeError):
            pass # Si falla, intentamos cargar desde el entorno
            
    # Prioridad 2: Cargar desde variables de entorno (configuración inicial)
    access_token = os.getenv("QWEN_ACCESS_TOKEN")
    refresh_token = os.getenv("QWEN_REFRESH_TOKEN")
    
    if access_token and refresh_token:
        # Creamos credenciales con una fecha de expiración pasada para forzar el refresco la primera vez
        initial_creds = QwenCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            expiry_date=0 
        )
        save_credentials(initial_creds)
        return initial_creds
        
    return None

def save_credentials(creds: QwenCredentials):
    """Guarda las credenciales en el archivo JSON."""
    CREDS_FILE.write_text(creds.model_dump_json())

async def refresh_access_token_if_needed() -> QwenCredentials:
    """Verifica si el token ha expirado y lo refresca si es necesario."""
    creds = load_credentials()
    if not creds:
        raise HTTPException(status_code=500, detail="Credenciales de Qwen no configuradas en el servidor. Asegúrate de definir QWEN_ACCESS_TOKEN y QWEN_REFRESH_TOKEN.")

    if time.time() > (creds.expiry_date - 60):
        print("Token expirado o inicial. Refrescando...")
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
            "client_id": QWEN_CLIENT_ID,
            "client_secret": QWEN_CLIENT_SECRET,
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(QWEN_TOKEN_REFRESH_URL, data=refresh_data)
                response.raise_for_status()
                new_token_data = response.json()
                new_expiry = int(time.time()) + new_token_data.get("expires_in", 3600)
                new_creds = QwenCredentials(
                    access_token=new_token_data["access_token"],
                    refresh_token=new_token_data.get("refresh_token", creds.refresh_token),
                    expiry_date=new_expiry
                )
                save_credentials(new_creds)
                print("Token refrescado exitosamente.")
                return new_creds
            except httpx.HTTPStatusError as e:
                print(f"Error al refrescar el token: {e.response.text}")
                raise HTTPException(status_code=500, detail=f"No se pudo refrescar el token de Qwen: {e.response.text}")
            except Exception as e:
                print(f"Error inesperado al refrescar el token: {e}")
                raise HTTPException(status_code=500, detail="Error inesperado durante el refresco del token.")
    return creds

# --- <--- CAMBIO IMPORTANTE: Función de seguridad ---
async def verify_api_key(x_api_key: str = Header(None)):
    """Verifica que la solicitud incluya la clave secreta correcta."""
    if x_api_key is None or x_api_key != PROXY_API_KEY_SECRET:
        raise HTTPException(status_code=401, detail="API Key del proxy inválida o no proporcionada en la cabecera X-API-Key")
    return x_api_key

# --- Endpoint Principal del Proxy (AHORA SEGURO) ---
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_qwen(request: Request, path: str, api_key: str = Depends(verify_api_key)): # <--- CAMBIO: Añadida la dependencia de seguridad
    """
    Este endpoint captura CUALQUIER solicitud, la valida con nuestra API Key,
    y luego la reenvía a la API de Qwen gestionando la autenticación.
    """
    creds = await refresh_access_token_if_needed()
    qwen_url = f"{QWEN_API_BASE_URL}/{path}"
    headers = {key: value for key, value in request.headers.items() if key.lower() not in ['host', 'authorization', 'x-api-key']}
    headers["Authorization"] = f"Bearer {creds.access_token}"
    body = await request.body()
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method,
                url=qwen_url,
                headers=headers,
                content=body,
                timeout=300.0
            )
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return JSONResponse(content=response.json(), status_code=response.status_code)
            else:
                print(f"Respuesta no-JSON de Qwen (Status: {response.status_code}): {response.text}")
                return Response(content=response.content, status_code=response.status_code, media_type=content_type)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Error al conectar con la API de Qwen: {e}")