import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from backend.config import get_settings
from backend.database import engine, Base
from backend.middleware.compose_body_limit import ComposeSendBodyLimitMiddleware
from backend.middleware.sensitive_terminal_path import SensitiveTerminalPathMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.routers import (
    accounts,
    admin,
    ai,
    auth,
    calendar,
    chat,
    compose,
    emails,
    events,
    public_api,
    snippets,
    snoozes,
    terminal,
    terminal_admin,
    terminal_enrollment,
    terminal_firmware,
    terminal_ota,
    todos,
)
from backend.services.attachment_cache_maintenance import attachment_cache_maintenance_loop

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
    attachment_maintenance_stop = asyncio.Event()
    attachment_maintenance_task = asyncio.create_task(
        attachment_cache_maintenance_loop(attachment_maintenance_stop),
        name="attachment-cache-maintenance",
    )
    try:
        yield
    finally:
        attachment_maintenance_stop.set()
        try:
            await asyncio.wait_for(attachment_maintenance_task, timeout=5)
        except TimeoutError:
            attachment_maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await attachment_maintenance_task
        except Exception:
            logger.exception("Attachment cache maintenance task stopped unexpectedly")
        finally:
            await engine.dispose()


app = FastAPI(
    title="Mail Client API",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(ComposeSendBodyLimitMiddleware)
app.add_middleware(SensitiveTerminalPathMiddleware)

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
app.include_router(public_api.router)
app.include_router(snoozes.router)
app.include_router(snippets.router)
app.include_router(terminal_admin.router)
app.include_router(terminal_enrollment.router)
app.include_router(terminal_firmware.router)
app.include_router(terminal_ota.router)
app.include_router(terminal.router)


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
