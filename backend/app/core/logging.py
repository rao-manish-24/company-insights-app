import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

LogFormat = Literal["text", "json"]

TEXT_FMT = "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter for cloud log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """Inject request_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        from app.core.request_context import get_request_id

        record.request_id = get_request_id() or "-"
        return True


def _build_formatter(log_format: LogFormat) -> logging.Formatter:
    if log_format == "json":
        return JsonFormatter()
    return logging.Formatter(fmt=TEXT_FMT, datefmt=DATE_FMT)


def setup_logging(
    level: str = "INFO",
    log_format: LogFormat = "text",
    log_file: str = "logs/companypulse.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> Path | None:
    """Configure stdout + rotating file logging. Returns the log file path if enabled."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    request_filter = RequestIdFilter()
    formatter = _build_formatter(log_format)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.addFilter(request_filter)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    log_path: Path | None = None
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            # Resolve relative to backend working directory (/app in Docker)
            log_path = Path.cwd() / log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.addFilter(request_filter)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # Volume mounts may not be writable by non-root — keep stdout logging
            logging.getLogger(__name__).warning(
                "File logging disabled path=%s reason=%s", log_path, exc
            )
            log_path = None

    # Keep noisy libraries quieter unless debugging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return log_path
