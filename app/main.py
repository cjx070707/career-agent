from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.auth import router as auth_router
from app.api.applications import router as applications_router
from app.api.candidates import router as candidates_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.interviews import router as interviews_router
from app.api.jobs import router as jobs_router
from app.api.matches import router as matches_router
from app.api.resumes import router as resumes_router
from app.api.vision import router as vision_router
from app.db.session import init_db
from app.env import settings
from app.middleware.error_handler import unhandled_exception_handler, value_error_handler
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import limiter
from app.middleware.request_id import RequestIDMiddleware


init_db()

app = FastAPI(title=settings.app_name, version=settings.app_version)

# ── Rate limiter state ────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# In production, replace "*" with the actual frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings, "cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request ID + structured logging ──────────────────────────────────────────
# Order matters: RequestID must run before Logging so request_id is available.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# ── Global exception handlers ─────────────────────────────────────────────────
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(applications_router)
app.include_router(interviews_router)
app.include_router(candidates_router)
app.include_router(jobs_router)
app.include_router(resumes_router)
app.include_router(matches_router)
app.include_router(vision_router)

# ── Static demo files ─────────────────────────────────────────────────────────
demo_directory = Path(__file__).resolve().parents[1] / "demo"
if demo_directory.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/demo", StaticFiles(directory=demo_directory, html=True), name="demo")
