from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import get_settings
from backend.app.db import create_all
from backend.app.routers import admin, auth, payments, tournaments

settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.frontend_url), str(settings.app_url)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
ASSETS_DIR = BASE_DIR / "assets"


@app.on_event("startup")
def startup() -> None:
    create_all()


app.include_router(auth.router, prefix="/api")
app.include_router(tournaments.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{path:path}")
def spa(path: str) -> FileResponse:
    index = FRONTEND_DIR / "index.html"
    return FileResponse(index)
