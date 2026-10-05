from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from seafile_ragflow_connector.dashboard.logging import DashboardLogHandler
from seafile_ragflow_connector.dashboard.store import DashboardEventStore
from seafile_ragflow_connector.utils.redaction import redact_mapping


def _redact_processor(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return redact_mapping(event_dict)


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
    *,
    dashboard_store: DashboardEventStore | None = None,
) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    old_dashboard_handlers = [
        handler for handler in root_logger.handlers if isinstance(handler, DashboardLogHandler)
    ]
    root_logger.handlers = [
        handler for handler in root_logger.handlers if not isinstance(handler, DashboardLogHandler)
    ]
    for handler in old_dashboard_handlers:
        handler.close()
    if dashboard_store is not None:
        root_logger.addHandler(DashboardLogHandler(dashboard_store))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
    ]
    if log_format == "console":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
