from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db.session import init_db
from app.api.applications import router as applications_router
from app.api.candidates import router as candidates_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.matches import router as matches_router
from app.api.resumes import router as resumes_router
from app.env import settings


init_db()
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(applications_router)
app.include_router(candidates_router)
app.include_router(jobs_router)
app.include_router(resumes_router)
app.include_router(matches_router)

demo_directory = Path(__file__).resolve().parents[1] / "demo"
if demo_directory.exists():
    app.mount("/demo", StaticFiles(directory=demo_directory, html=True), name="demo")
