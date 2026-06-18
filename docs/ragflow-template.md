# RAGFlow-Template

Der Connector sucht genau ein Dataset mit dem Namen aus
`RAGFLOW_TEMPLATE_DATASET_NAME`, standardmäßig `connector_template`. Wenn es
fehlt und `RAGFLOW_TEMPLATE_AUTO_CREATE=true` gesetzt ist, legt der Connector
das Template automatisch an.

Das Template wird nur für die Dataset-Erstellung verwendet. Bestehende Datasets
behalten ihre aktuellen RAGFlow-Einstellungen.

## Automatische Defaults

Das automatisch angelegte Dataset-Template nutzt bewusst konservative
RAGFlow-Defaults:

- `chunk_method=naive` mit `layout_recognize=DeepDOC`, damit Seitenpositionen
  und Layoutinformationen für Quellen nutzbar bleiben.
- `chunk_token_num=512`, `task_page_size=12` und vollständige Seitenabdeckung
  über `pages=[[1, 1000000]]`.
- `auto_questions=0` und `auto_keywords=0`, damit Dataset-Parsing nicht durch
  zusätzliche LLM-Aufgaben blockiert wird.
- `raptor.use_raptor=false` und `graphrag.use_graphrag=false`, weil diese
  Modi Parsezeit und Betriebsaufwand deutlich erhöhen.

Bei Dokument-Uploads schreibt der Connector vor dem Parse zusätzliche
RAGFlow-Dokumentmetadaten wie Seafile-Pfad, Repo-ID, Dateityp,
Ingestion-Strategie und Quell-Hash. Diese Metadaten stehen anschließend der
OpenWebUI-Pipe und den RAGFlow-Referenzen zur Verfügung.

## Template-Chat

Wenn OpenWebUI-Sync aktiv ist, legt der Connector zusätzlich einen
Template-Chat mit `RAGFLOW_TEMPLATE_CHAT_NAME`, standardmäßig
`connector_template_chat`, an. Dieser Chat ist nicht an ein Dataset gebunden,
weil RAGFlow Chats nur mit bereits geparsten Datasets verbinden kann.

Die pro Dataset erzeugten Chats übernehmen dieselben RAG-Defaults:

- Zitate und Referenz-Metadaten sind aktiviert.
- Multiturn-Refinement, Keyword-Retrieval und TOC-Enhancement sind aktiviert.
- `top_n=10`, `top_k=1024`, `similarity_threshold=0.1` und
  `vector_similarity_weight=0.35` bevorzugen Recall, ohne offensichtlich
  schwache Treffer ungebremst durchzulassen.

## Search-Template

Für die nutzernahe Search-Webseite und den OpenWebUI-Proxy-Fallback gibt es ein
separates Suchqualitäts-Template mit `RAGFLOW_SEARCH_TEMPLATE_NAME`,
standardmäßig `search_template`.

Die Auflösung ist bewusst ACL-neutral:

1. RAGFlow Search App `search_template` über `/api/v1/searches`.
2. RAGFlow Chat Assistant `search_template` über `/api/v1/chats`.
3. Built-in Standard des Connectors.

Aus dem Template werden nur Retrieval-Qualitätswerte übernommen, zum Beispiel
`similarity_threshold`, `vector_similarity_weight`, `top_n`, `top_k`,
`rerank_id`, `keyword`, `highlight`, `cross_languages`, `use_kg` und
`toc_enhance`. Dataset- oder Dokumentlisten aus dem Template werden ignoriert.
Die tatsächlich abgefragten Datasets kommen immer erst aus der
ACL-gefilterten Bibliotheksauswahl.

Der Built-in Standard folgt RAGFlows dokumentierter Hybrid Search:

- `similarity_threshold=0.2`
- `vector_similarity_weight=0.3`
- `top_n=8`
- `top_k=1024`
- `keyword=true`
- `highlight=true`
- `use_kg=false`
- `toc_enhance=false`

Wichtig: Das Suchfeld "Treffer" in der Connector-UI steuert nur die sichtbare
Ergebnisanzahl. RAGFlows `top_k` bleibt der interne Kandidatenpool und wird
deshalb aus `search_template` oder dem Built-in Standard übernommen. Dadurch
wird nicht mehr versehentlich nur mit acht Kandidaten gesucht.

Wenn `RAGFLOW_SEARCH_TEMPLATE_AUTO_CREATE=true` gesetzt ist, legt der
Controller eine Search App `search_template` mit den Built-in-Defaults an,
sofern die RAGFlow-Version die Search-App-API unterstützt. Der separate
Search-Service liest nur und erstellt keine RAGFlow-Artefakte.

## Create-Payload-Whitelist

- `avatar`
- `description`
- `embedding_model`
- `permission`
- `chunk_method`
- `parser_config`
- `parse_type`
- `pipeline_id`

`name` wird immer vom Connector generiert.

Built-in Chunking (`chunk_method`, `parser_config`) und Ingestion-Pipeline-Modus
(`parse_type`, `pipeline_id`) dürfen nicht gemischt werden.
