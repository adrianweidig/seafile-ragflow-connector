from __future__ import annotations

import json
import logging
from typing import Any

from seafile_ragflow_connector.dashboard.store import DashboardEventStore


class DashboardLogHandler(logging.Handler):
    def __init__(self, store: DashboardEventStore) -> None:
        super().__init__()
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            details: dict[str, Any] = {}
            event_name = message
            sync_id = None
            level = record.levelname.lower()
            try:
                payload = json.loads(message)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                details = dict(payload)
                event_name = str(payload.get("event") or payload.get("message") or message)
                sync_id_value = payload.get("sync_id")
                sync_id = str(sync_id_value) if sync_id_value else None
                level = str(payload.get("level") or level).lower()
            self.store.record_log(
                level=level,
                message=event_name,
                component=record.name,
                sync_id=sync_id,
                details=details,
            )
        except Exception:
            # Dashboard persistence must never destabilize the connector or recurse through logging.
            return
