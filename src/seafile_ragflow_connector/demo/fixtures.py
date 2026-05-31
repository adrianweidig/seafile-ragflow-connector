from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path

from seafile_ragflow_connector.domain.naming import slugify

CANONICAL_DEMO_LIBRARIES = (
    "Connector Demo Wissen",
    "Connector Demo Präsentationen",
    "Connector Demo Edge Cases",
)

_CONTENT_TYPES_OPEN = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
)
_RELATIONSHIPS_OPEN = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">'
)
_DEFAULT_RELS_TYPE = (
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
)
_DEFAULT_XML_TYPE = '<Default Extension="xml" ContentType="application/xml"/>'
_OFFICE_DOCUMENT_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" '
)
_SLIDE_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/slide" '
)
_WORKSHEET_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/worksheet" '
)

@dataclass(frozen=True)
class DemoFileSpec:
    library_name: str
    relative_path: str
    mime_type: str
    kind: str


DEMO_FILE_SPECS = (
    DemoFileSpec(
        "Connector Demo Wissen",
        "wissen_mehrseitig.pdf",
        "application/pdf",
        "knowledge_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Wissen",
        "prozesshandbuch.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "knowledge_docx",
    ),
    DemoFileSpec("Connector Demo Wissen", "kurznotiz.txt", "text/plain", "knowledge_txt"),
    DemoFileSpec("Connector Demo Wissen", "integration.md", "text/markdown", "knowledge_md"),
    DemoFileSpec("Connector Demo Wissen", "kennzahlen.csv", "text/csv", "knowledge_csv"),
    DemoFileSpec(
        "Connector Demo Wissen",
        "kennzahlen.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "knowledge_xlsx",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "foliennummern.pdf",
        "application/pdf",
        "presentation_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "quartalsdemo.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "presentation_pptx",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "tabelle_im_pdf.pdf",
        "application/pdf",
        "table_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "ocr_hinweis.pdf",
        "application/pdf",
        "ocr_pdf",
    ),
    DemoFileSpec("Connector Demo Edge Cases", "umlaute_aeoeuess.txt", "text/plain", "umlauts"),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "html_fragmente.md",
        "text/markdown",
        "html_fragments",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "tabellenzellen.csv",
        "text/csv",
        "edge_table",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "aehnlicher_inhalt_a.txt",
        "text/plain",
        "duplicate_a",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "aehnlicher_inhalt_b.txt",
        "text/plain",
        "duplicate_b",
    ),
)

def write_demo_testset(root: Path) -> dict[str, list[str]]:
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, list[str]] = {name: [] for name in CANONICAL_DEMO_LIBRARIES}
    for spec in DEMO_FILE_SPECS:
        library_dir = root / slugify(spec.library_name, fallback="library")
        library_dir.mkdir(parents=True, exist_ok=True)
        target = library_dir / spec.relative_path
        _write_demo_file(target, spec.kind)
        result[spec.library_name].append(str(target))
    return result

def _write_demo_file(path: Path, kind: str) -> None:
    if kind == "knowledge_pdf":
        _write_pdf(
            path,
            [
                "Connector Demo Wissen - Seite 1\nÜberblick: Seafile ist die Quelle der Wahrheit.",
                "Connector Demo Wissen - Seite 2\nRAGFlow erhält Datasets aus connector_template.",
                "Connector Demo Wissen - Seite 3\nOpenWebUI zeigt kompakte Quellen mit Auszug.",
                "Connector Demo Wissen - Seite 4\nTOP_K steuert die Anzahl relevanter Treffer.",
                "Connector Demo Wissen - Seite 5\n"
                "Originaldokumente können per Link geöffnet werden.",
                "Connector Demo Wissen - Seite 6\nPreview läuft lokal und ohne CDN.",
                "Connector Demo Wissen - Seite 7\nPDF-Seitenanker sollen #page=7 erzeugen.",
            ],
        )
    elif kind == "knowledge_docx":
        _write_docx(
            path,
            [
                "Abschnitt Betrieb: Der Connector synchronisiert nur von Seafile zu RAGFlow.",
                "Tabelle: System | Zweck | Status",
                "Aufzählung: Discovery, Upload, Parse, OpenWebUI-Sync.",
            ],
        )
    elif kind == "knowledge_txt":
        path.write_text(
            "Kurzer Fließtext für die normale Wissensabfrage. "
            "Die Demo prüft Quellen, Preview und Original-Link.\n",
            encoding="utf-8",
        )
    elif kind == "knowledge_md":
        path.write_text(
            "# Integration\n\n- Seafile bleibt Quelle der Wahrheit.\n"
            "- RAGFlow speichert Datasets und Chunks.\n\n"
            "```text\nTOP_K=8\n```\n",
            encoding="utf-8",
        )
    elif kind == "knowledge_csv":
        _write_csv(path, [["Metrik", "Wert"], ["TOP_K", "8"], ["Preview", "lokal"]])
    elif kind == "knowledge_xlsx":
        _write_xlsx(path, [["Metrik", "Wert"], ["TOP_K", "8"], ["Preview", "lokal"]])
    elif kind == "presentation_pdf":
        _write_pdf(
            path,
            [
                f"Connector Demo Präsentationen - Folie {index}\n"
                f"Foliennummer {index}: Quellenangabe und Preview prüfen."
                for index in range(1, 8)
            ],
        )
    elif kind == "presentation_pptx":
        _write_pptx(
            path,
            [
                "Folie 1: Connector Demo Präsentationen",
                "Folie 2: Quellen, Preview und Seitenanker",
            ],
        )
    elif kind == "table_pdf":
        _write_pdf(
            path,
            [
                "PDF mit eingebetteter Tabelle\nSpalte A | Spalte B\nAlpha | 10\nBeta | 20",
                "Tabellenhinweis\nZellen sollen als lesbarer Text erscheinen.",
            ],
        )
    elif kind == "ocr_pdf":
        _write_pdf(
            path,
            [
                "OCR-Hinweis\nDiese Seite simuliert OCR-relevanten Inhalt und macht "
                "Parsingqualität sichtbar.",
            ],
        )
    elif kind == "umlauts":
        path.write_text(
            "Umlaute-Test: ä, ö, ü, Ä, Ö, Ü und ß müssen lesbar bleiben.\n",
            encoding="utf-8",
        )
    elif kind == "html_fragments":
        path.write_text(
            "# HTML-Fragmente\n\n"
            "Dieser Text enthält <table><tr><td>Alpha</td><td>Beta</td></tr></table> "
            "und &uuml;bernommene Entities. Tags dürfen nicht roh erscheinen.\n",
            encoding="utf-8",
        )
    elif kind == "edge_table":
        _write_csv(path, [["Schlüssel", "Wert"], ["HTML", "<td>Alpha</td>"], ["Entity", "&uuml;"]])
    elif kind == "duplicate_a":
        path.write_text(
            "Ähnlicher Inhalt: Der Connector nutzt Quellenranking und Deduplizierung.",
            encoding="utf-8",
        )
    elif kind == "duplicate_b":
        path.write_text(
            "Ähnlicher Inhalt: Der Connector nutzt Quellenranking und Deduplizierung "
            "mit zweiter Datei.",
            encoding="utf-8",
        )
    else:
        msg = f"unknown demo file kind: {kind}"
        raise ValueError(msg)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _write_pdf(path: Path, pages: list[str]) -> None:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    for index, text in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        stream = _pdf_stream(text)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
                f"/BaseFont /Helvetica >> >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
    _write_pdf_objects(path, objects)


def _pdf_stream(text: str) -> bytes:
    lines = text.splitlines() or [text]
    commands = ["BT", "/F1 14 Tf", "72 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -24 Td")
        commands.append(f"({_pdf_escape(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", "replace")


def _pdf_escape(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace(
        "(", "\\("
    ).replace(")", "\\)")


def _write_pdf_objects(path: Path, objects: list[bytes]) -> None:
    offsets = [0]
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(body))


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    _write_zip(
        path,
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_CONTENT_TYPES_OPEN}"
                f"{_DEFAULT_RELS_TYPE}"
                f"{_DEFAULT_XML_TYPE}"
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_OFFICE_DOCUMENT_REL}"
                'Target="word/document.xml"/>'
                "</Relationships>"
            ),
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}<w:sectPr/></w:body></w:document>"
            ),
        },
    )


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{chr(64 + col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    _write_zip(
        path,
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_CONTENT_TYPES_OPEN}"
                f"{_DEFAULT_RELS_TYPE}"
                f"{_DEFAULT_XML_TYPE}"
                '<Override PartName="/xl/workbook.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_OFFICE_DOCUMENT_REL}"
                'Target="xl/workbook.xml"/>'
                "</Relationships>"
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Demo" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_WORKSHEET_REL}"
                'Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
            ),
        },
    )


def _write_pptx(path: Path, slides: list[str]) -> None:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for index in range(1, len(slides) + 1)
    )
    slide_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{index}"/>'
        for index in range(1, len(slides) + 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{index}" '
        f"{_SLIDE_REL}"
        f'Target="slides/slide{index}.xml"/>'
        for index in range(1, len(slides) + 1)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_CONTENT_TYPES_OPEN}"
            f"{_DEFAULT_RELS_TYPE}"
            f"{_DEFAULT_XML_TYPE}"
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.presentation.main+xml"/>'
            f"{slide_overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_RELATIONSHIPS_OPEN}"
            '<Relationship Id="rId1" '
            f"{_OFFICE_DOCUMENT_REL}"
            'Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{slide_ids}</p:sldIdLst></p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_RELATIONSHIPS_OPEN}{rels}</Relationships>"
        ),
    }
    for index, title in enumerate(slides, start=1):
        files[f"ppt/slides/slide{index}.xml"] = _slide_xml(title)
    _write_zip(path, files)


def _slide_xml(title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/>"
        "<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>"
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Titel"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="914400" y="914400"/>'
        '<a:ext cx="8229600" cy="1371600"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>'
        f"{escape(title)}"
        "</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))


def _mime_for_path(path: Path) -> str:
    for spec in DEMO_FILE_SPECS:
        if spec.relative_path == path.name:
            return spec.mime_type
    return "application/octet-stream"
