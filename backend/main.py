import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from backend.config import get_settings
from backend.database import engine, Base
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.routers import auth, admin, emails, compose, accounts, ai, todos, chat, calendar, events

# Import all models so they register with Base
import backend.models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="Mail Client API",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
origins = [o.strip() for o in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(emails.router)
app.include_router(compose.router)
app.include_router(accounts.router)
app.include_router(ai.router)
app.include_router(todos.router)
app.include_router(chat.router)
app.include_router(calendar.router)
app.include_router(events.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


BUILD_VERSION_FILE = "/opt/mail/.build_version"


@app.get("/api/build-version")
async def build_version():
    try:
        with open(BUILD_VERSION_FILE, "r") as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = "unknown"
    return {"version": version}


# Serve frontend
import os

FRONTEND_DIR = "/opt/mail/frontend/dist"

if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
