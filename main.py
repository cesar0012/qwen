import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

CREDS_FILE = Path("oauth_creds.json")
PROXY_API_KEY = os.getenv("PROXY_API_KEY")

async def verify_api_key(x_api_key: str = Header(None)):
    if PROXY_API_KEY is None:
        raise HTTPException(status_code=500, detail="El servidor no tiene una PROXY_API_KEY configurada.")
    if x_api_key is None or x_api_key != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="API Key del proxy inválida o no proporcionada.")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Qwen Credential Server is running!"}

@app.get("/oauth_creds.json", dependencies=[Depends(verify_api_key)])
def serve_credentials():
    """Sirve el archivo de credenciales que el worker mantiene actualizado."""
    if CREDS_FILE.exists():
        return JSONResponse(content=json.loads(CREDS_FILE.read_text()))
    else:
        raise HTTPException(status_code=404, detail="El archivo de credenciales aún no ha sido generado por el worker.")