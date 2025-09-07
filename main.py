import os
import json
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Configuración ---
# Carga las variables de entorno desde un archivo .env
load_dotenv()

# Define la clase para las credenciales de Qwen
class QwenCredentials(BaseModel):
    access_token: str
    refresh_token: str
    expiry_date: int  # Almacenaremos el tiempo de expiración como timestamp de Unix

# --- Variables Globales y Funciones de Ayuda ---
app = FastAPI()
# Usaremos un archivo para persistir las credenciales, simulando el oauth_creds.json
CREDS_FILE = Path("qwen_credentials.json")

# URL del endpoint de Qwen al que reenviaremos las solicitudes
QWEN_API_BASE_URL = "https://portal.qwen.ai"

# URL del endpoint de token de Qwen para refrescar el access_token
# NOTA: Este es el endpoint estándar para refrescar tokens OAuth2.
# Si Qwen usa uno diferente, habría que cambiarlo aquí.
QWEN_TOKEN_REFRESH_URL = "https://qwen.ai/oauth/token" 

# El client_id y client_secret son necesarios para el refresco de OAuth2.
# Estos valores se obtienen al registrar una "app" en la plataforma del proveedor.
# Aquí usamos valores genéricos, que podrían necesitar ser actualizados.
QWEN_CLIENT_ID = os.getenv("QWEN_CLIENT_ID", "tu_client_id_aqui") # Deberás obtenerlo de Qwen si es necesario
QWEN_CLIENT_SECRET = os.getenv("QWEN_CLIENT_SECRET", "tu_client_secret_aqui") # Deberás obtenerlo de Qwen

def load_credentials() -> Optional[QwenCredentials]:
    """Carga las credenciales desde el archivo JSON."""
    if CREDS_FILE.exists():
        try:
            creds_data = json.loads(CREDS_FILE.read_text())
            return QwenCredentials(**creds_data)
        except (json.JSONDecodeError, TypeError):
            return None
    return None

def save_credentials(creds: QwenCredentials):
    """Guarda las credenciales en el archivo JSON."""
    CREDS_FILE.write_text(creds.model_dump_json())

async def refresh_access_token_if_needed() -> QwenCredentials:
    """
    Verifica si el token ha expirado y lo refresca si es necesario.
    Esta es la función MÁGICA de nuestro proxy.
    """
    creds = load_credentials()
    if not creds:
        raise HTTPException(status_code=500, detail="Credenciales de Qwen no configuradas en el servidor.")

    # Comprueba si el token ha expirado (con un margen de 60 segundos)
    if time.time() > (creds.expiry_date - 60):
        print("Token expirado. Refrescando...")
        
        # Datos para la solicitud de refresco
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
            "client_id": QWEN_CLIENT_ID,
            "client_secret": QWEN_CLIENT_SECRET,
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(QWEN_TOKEN_REFRESH_URL, data=refresh_data)
                response.raise_for_status() # Lanza un error si la respuesta es 4xx o 5xx
                
                new_token_data = response.json()
                
                # Actualiza nuestras credenciales con los nuevos datos
                new_expiry = int(time.time()) + new_token_data.get("expires_in", 3600)
                
                new_creds = QwenCredentials(
                    access_token=new_token_data["access_token"],
                    # A menudo, se devuelve un nuevo refresh_token
                    refresh_token=new_token_data.get("refresh_token", creds.refresh_token),
                    expiry_date=new_expiry
                )
                
                save_credentials(new_creds)
                print("Token refrescado exitosamente.")
                return new_creds

            except httpx.HTTPStatusError as e:
                print(f"Error al refrescar el token: {e.response.text}")
                raise HTTPException(status_code=500, detail="No se pudo refrescar el token de Qwen.")
            except Exception as e:
                print(f"Error inesperado al refrescar el token: {e}")
                raise HTTPException(status_code=500, detail="Error inesperado durante el refresco del token.")

    # Si no ha expirado, simplemente devuelve las credenciales actuales
    return creds

# --- Endpoint de Configuración Inicial (SOLO PARA LA PRIMERA VEZ) ---
class InitialCredentials(BaseModel):
    access_token: str
    refresh_token: str
    # La expiración inicial en segundos (ej: 3600 para 1 hora)
    expires_in: int = 3600 

@app.post("/setup")
async def setup_credentials(initial_creds: InitialCredentials):
    """
    Endpoint para configurar las credenciales por primera vez.
    DEBERÍAS PROTEGER ESTE ENDPOINT O ELIMINARLO EN PRODUCCIÓN.
    """
    if CREDS_FILE.exists():
        raise HTTPException(status_code=400, detail="Las credenciales ya han sido configuradas.")
    
    expiry_timestamp = int(time.time()) + initial_creds.expires_in
    
    creds_to_save = QwenCredentials(
        access_token=initial_creds.access_token,
        refresh_token=initial_creds.refresh_token,
        expiry_date=expiry_timestamp
    )
    save_credentials(creds_to_save)
    
    return {"message": "Credenciales configuradas exitosamente."}

# --- <--- NUEVO ENDPOINT AÑADIDO AQUÍ ---
# --- Endpoint para Sincronizar Credenciales (PARA KILO CODE) ---
@app.get("/credentials")
async def get_credentials():
    """
    Endpoint para que herramientas como Kilo Code puedan descargar el archivo de credenciales.
    """
    creds = load_credentials()
    if not creds:
        raise HTTPException(status_code=404, detail="El archivo de credenciales no existe en el servidor. Ejecuta el setup primero.")
    
    # Kilo Code espera un formato específico, que es el contenido de oauth_creds.json
    # Este formato puede ser diferente del QwenCredentials. Devolvemos el contenido crudo.
    return JSONResponse(content=json.loads(CREDS_FILE.read_text()))

# --- Endpoint Principal del Proxy (DEBE IR AL FINAL) ---
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_qwen(request: Request, path: str):
    """
    Este endpoint captura CUALQUIER solicitud y la reenvía a la API de Qwen,
    gestionando la autenticación automáticamente y manejando errores de forma robusta.
    """
    creds = await refresh_access_token_if_needed()
    
    # Construimos la URL completa. path ya incluirá /v1/chat/completions, etc.
    qwen_url = f"{QWEN_API_BASE_URL}/{path}"
    
    # Copiamos las cabeceras de la solicitud original, excepto 'host'
    headers = {key: value for key, value in request.headers.items() if key.lower() != 'host'}
    # Sobrescribimos la cabecera de Autorización con nuestro token válido
    headers["Authorization"] = f"Bearer {creds.access_token}"

    body = await request.body()
    
    async with httpx.AsyncClient() as client:
        try:
            # Reenviamos la solicitud al servidor de Qwen
            response = await client.request(
                method=request.method,
                url=qwen_url,
                headers=headers,
                content=body,
                timeout=300.0
            )
            
            # Verificamos si la respuesta de Qwen es un JSON antes de procesarla
            content_type = response.headers.get("content-type", "")
            
            if "application/json" in content_type:
                # Si es un JSON, lo devolvemos como JSON
                return JSONResponse(
                    content=response.json(),
                    status_code=response.status_code
                )
            else:
                # Si NO es un JSON (ej. un error HTML), lo devolvemos tal cual para poder depurar
                print(f"Respuesta no-JSON de Qwen (Status: {response.status_code}): {response.text}")
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    media_type=content_type
                )
                
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Error al conectar con la API de Qwen: {e}")