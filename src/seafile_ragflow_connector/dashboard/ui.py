from __future__ import annotations

from importlib import resources

DASHBOARD_HTML = (
    resources.files("seafile_ragflow_connector.dashboard")
    .joinpath("assets/dashboard.html")
    .read_text(encoding="utf-8")
)
