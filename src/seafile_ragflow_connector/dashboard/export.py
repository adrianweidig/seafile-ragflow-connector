from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

MAX_CELL_CHARS = 32767
SHEET_NAME_LIMIT = 31

SheetRows = tuple[str, Sequence[str], Sequence[Sequence[Any]]]


def audit_export_filename(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d-%H%M%SZ")
    return f"connector-audit-{timestamp}.xlsx"


def build_audit_workbook(snapshot: Mapping[str, Any]) -> bytes:
    sheets = [
        _overview_sheet(snapshot),
        _sync_runs_sheet(_as_list(snapshot.get("sync_runs"))),
        _changes_sheet(_as_list(snapshot.get("changes"))),
        _logs_sheet(_as_list(snapshot.get("logs"))),
        _sources_sheet(snapshot),
        _targets_sheet(snapshot),
        _openwebui_sheet(snapshot),
        _diagnostics_sheet(snapshot),
    ]
    return _build_workbook(sheets)


def _overview_sheet(snapshot: Mapping[str, Any]) -> SheetRows:
    status = _as_mapping(snapshot.get("status"))
    metrics = _as_mapping(snapshot.get("metrics"))
    export_limits = _as_mapping(snapshot.get("export_limits"))
    rows: list[list[Any]] = [
        ["Export erzeugt", snapshot.get("generated_at")],
        ["Connector-Zustand", status.get("state")],
        ["Prozess gestartet", status.get("started_at")],
        ["Laufzeit Sekunden", status.get("uptime_seconds")],
        ["Laufende Jobs", status.get("running_jobs")],
        ["Queue/Retry Jobs", status.get("queued_or_retrying_jobs")],
        ["Fehlgeschlagene Jobs", status.get("failed_jobs")],
        ["Letzter erfolgreicher Sync", _to_json(status.get("last_successful_sync"))],
        ["Letzter fehlgeschlagener Sync", _to_json(status.get("last_failed_sync"))],
        ["Verarbeitete Objekte", status.get("objects_processed")],
        ["Erkannte Änderungen", status.get("changes_detected")],
        ["Fehler", status.get("errors_count")],
        ["Warnungen", status.get("warnings_count")],
        ["Libraries", metrics.get("libraries")],
        ["Dateien", metrics.get("files")],
        ["Sync-Läufe gespeichert", metrics.get("sync_runs")],
        ["Änderungen gespeichert", metrics.get("changes")],
        ["Logs gespeichert", metrics.get("logs")],
        ["Jobs nach Status", _to_json(metrics.get("jobs_by_status"))],
        ["Dateien nach Status", _to_json(metrics.get("files_by_status"))],
        ["Exportlimit Sync-Läufe", export_limits.get("max_sync_runs")],
        ["Exportlimit Änderungen", export_limits.get("max_event_entries")],
        ["Exportlimit Logs", export_limits.get("max_log_entries")],
    ]
    return ("Overview", ["Feld", "Wert"], rows)


def _sync_runs_sheet(runs: Sequence[Mapping[str, Any]]) -> SheetRows:
    headers = [
        "Sync-ID",
        "Status",
        "Quelle",
        "Ziel",
        "Start",
        "Ende",
        "Dauer ms",
        "Geprüft",
        "Neu",
        "Aktualisiert",
        "Gelöscht",
        "Übersprungen",
        "Fehler",
        "Warnungen",
        "Zusammenfassung",
        "Details",
    ]
    rows = [
        [
            run.get("sync_id"),
            run.get("status"),
            run.get("source"),
            run.get("target"),
            run.get("started_at"),
            run.get("ended_at"),
            run.get("duration_ms"),
            run.get("objects_checked"),
            run.get("objects_created"),
            run.get("objects_updated"),
            run.get("objects_deleted"),
            run.get("objects_skipped"),
            run.get("errors_count"),
            run.get("warnings_count"),
            run.get("summary"),
            _to_json(run.get("details")),
        ]
        for run in runs
    ]
    return ("Sync Runs", headers, rows)


def _changes_sheet(changes: Sequence[Mapping[str, Any]]) -> SheetRows:
    headers = [
        "Zeitpunkt",
        "Sync-ID",
        "Aktion",
        "Änderungstyp",
        "Status",
        "Objektname",
        "Quellpfad",
        "Zielpfad",
        "Vorheriger Name",
        "Neuer Name",
        "Quelle",
        "Ziel",
        "Fehler",
        "Details",
    ]
    rows = [
        [
            change.get("occurred_at"),
            change.get("sync_id"),
            change.get("action"),
            change.get("change_type"),
            change.get("status"),
            change.get("object_name"),
            change.get("source_path"),
            change.get("target_path"),
            change.get("previous_name"),
            change.get("new_name"),
            change.get("source_system"),
            change.get("target_system"),
            change.get("error_message"),
            _to_json(change.get("details")),
        ]
        for change in changes
    ]
    return ("Changes", headers, rows)


def _logs_sheet(logs: Sequence[Mapping[str, Any]]) -> SheetRows:
    headers = ["Zeitpunkt", "Level", "Komponente", "Sync-ID", "Nachricht", "Details"]
    rows = [
        [
            entry.get("occurred_at"),
            entry.get("level"),
            entry.get("component"),
            entry.get("sync_id"),
            entry.get("message"),
            _to_json(entry.get("details")),
        ]
        for entry in logs
    ]
    return ("Logs", headers, rows)


def _sources_sheet(snapshot: Mapping[str, Any]) -> SheetRows:
    source = _as_mapping(_as_mapping(snapshot.get("systems")).get("source"))
    libraries = _as_list(source.get("libraries"))
    headers = ["Repo-ID", "Name", "Status", "Head Commit", "Letzter Sync Commit", "Fehler"]
    rows = [
        [
            item.get("repo_id"),
            item.get("name"),
            item.get("status"),
            item.get("head_commit_id"),
            item.get("last_synced_commit_id"),
            item.get("last_error"),
        ]
        for item in libraries
    ]
    return ("Sources", headers, rows)


def _targets_sheet(snapshot: Mapping[str, Any]) -> SheetRows:
    target = _as_mapping(_as_mapping(snapshot.get("systems")).get("target"))
    datasets = _as_list(target.get("datasets"))
    headers = ["Repo-ID", "Dataset-ID", "Dataset-Name", "Template Hash"]
    rows = [
        [
            item.get("repo_id"),
            item.get("dataset_id"),
            item.get("dataset_name"),
            item.get("template_hash"),
        ]
        for item in datasets
    ]
    return ("Targets", headers, rows)


def _openwebui_sheet(snapshot: Mapping[str, Any]) -> SheetRows:
    openwebui = _as_mapping(snapshot.get("openwebui"))
    status = _as_mapping(openwebui.get("status"))
    mappings = _as_list(openwebui.get("mappings"))
    headers = [
        "Repo-ID",
        "Dataset-ID",
        "Dataset-Name",
        "Chat-ID",
        "Tool-ID",
        "Pipe-ID",
        "Modellname",
        "Status",
        "Letzter Erfolg",
        "Fehler",
    ]
    rows: list[list[Any]] = [
        [
            "Status",
            "",
            status.get("status"),
            "",
            "",
            "",
            status.get("mode"),
            "",
            "",
            status.get("last_error"),
        ]
    ]
    rows.extend(
        [
            item.get("repo_id"),
            item.get("ragflow_dataset_id"),
            item.get("ragflow_dataset_name"),
            item.get("ragflow_chat_id"),
            item.get("openwebui_tool_id"),
            item.get("openwebui_pipe_id"),
            item.get("openwebui_model_name"),
            item.get("sync_status"),
            item.get("last_successful_sync_at"),
            item.get("last_error"),
        ]
        for item in mappings
    )
    return ("OpenWebUI", headers, rows)


def _diagnostics_sheet(snapshot: Mapping[str, Any]) -> SheetRows:
    diagnostics = _as_mapping(snapshot.get("diagnostics"))
    rows = [[key, _to_json(value)] for key, value in diagnostics.items()]
    return ("Diagnostics", ["Bereich", "Wert"], rows)


def _build_workbook(sheets: Sequence[SheetRows]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _root_relationships())
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_relationships(len(sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _worksheet_xml(sheet))
    return output.getvalue()


def _worksheet_xml(sheet: SheetRows) -> str:
    _name, headers, data_rows = sheet
    rows: list[Sequence[Any]] = [headers, *data_rows]
    body = "\n".join(_row_xml(index, row, header=index == 1) for index, row in enumerate(rows, 1))
    last_col = _column_name(max(len(headers), 1))
    last_row = max(len(rows), 1)
    widths = "\n".join(
        f'<col min="{index}" max="{index}" width="{_column_width(header)}" customWidth="1"/>'
        for index, header in enumerate(headers, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"<cols>{widths}</cols>"
        f"<sheetData>{body}</sheetData>"
        f'<autoFilter ref="A1:{last_col}{last_row}"/>'
        "</worksheet>"
    )


def _row_xml(row_index: int, row: Sequence[Any], *, header: bool) -> str:
    cells = "".join(
        _cell_xml(row_index, column_index, value, header=header)
        for column_index, value in enumerate(row, start=1)
    )
    return f'<row r="{row_index}">{cells}</row>'


def _cell_xml(row_index: int, column_index: int, value: Any, *, header: bool) -> str:
    coordinate = f"{_column_name(column_index)}{row_index}"
    style = ' s="1"' if header else ""
    text = escape(_cell_text(value), {'"': "&quot;"})
    return (
        f'<c r="{coordinate}" t="inlineStr"{style}>'
        f'<is><t xml:space="preserve">{text}</t></is></c>'
    )


def _content_types(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _root_relationships() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_relationships(sheet_count: int) -> str:
    relationships = [
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            f'worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        for index in range(1, sheet_count + 1)
    ]
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(relationships)}</Relationships>'
    )


def _workbook_xml(sheets: Sequence[SheetRows]) -> str:
    entries = "".join(
        f'<sheet name="{escape(_sheet_name(sheet[0]))}" sheetId="{index}" r:id="rId{index}"/>'
        for index, sheet in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{entries}</sheets></workbook>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF172033"/>'
        '<bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        "</cellStyleXfs>"
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" '
        'applyFill="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _column_width(header: str) -> int:
    header_width = len(header) + 4
    if any(token in header.lower() for token in ("pfad", "details", "nachricht", "summary")):
        return max(header_width, 42)
    return min(max(header_width, 14), 28)


def _sheet_name(name: str) -> str:
    sanitized = "".join("_" if char in "[]:*?/\\'" else char for char in name)
    return sanitized[:SHEET_NAME_LIMIT] or "Sheet"


def _cell_text(value: Any) -> str:
    if isinstance(value, Mapping | list | tuple):
        text = _to_json(value)
    elif value is None:
        text = ""
    else:
        text = str(value)
    clean = _clean_xml_text(text)
    if len(clean) <= MAX_CELL_CHARS:
        return clean
    return clean[: MAX_CELL_CHARS - 1] + "…"


def _to_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _clean_xml_text(text: str) -> str:
    return "".join(
        char
        for char in text
        if char in "\t\n\r" or ord(char) >= 32
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [item for item in value if isinstance(item, Mapping)]
