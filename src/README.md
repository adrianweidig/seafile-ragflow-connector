# Anwendungscode

Der Python-Anwendungscode liegt unter `seafile_ragflow_connector/`.

Das Projekt nutzt das `src`-Layout, damit Tests und lokale Ausführung denselben
Importpfad wie das installierte Paket verwenden. Für lokale Checks sollte daher
`PYTHONPATH=src` gesetzt werden, wenn nicht über `uv run` oder das installierte
Paket gearbeitet wird.
