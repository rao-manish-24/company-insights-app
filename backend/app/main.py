import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware
from app.models import company  # noqa: F401 — register models

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info(
        "Starting %s | env=%s | llm_model=%s | log_level=%s",
        settings.app_name,
        settings.environment,
        settings.llm_model,
        settings.log_level,
    )
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    log_path = setup_logging(
        level=settings.log_level,
        log_format=settings.log_format,  # type: ignore[arg-type]
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    if log_path:
        logging.getLogger(__name__).info("File logging enabled path=%s", log_path)

    app = FastAPI(
        title=settings.app_name,
        description="Translate company news into partner-ready insights and recommendations.",
        version="1.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Request logging outermost so it wraps CORS + route handling
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(router, prefix="/api")
    return app


app = create_app()
