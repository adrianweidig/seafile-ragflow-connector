# RAGFlow-Template

Der Connector sucht genau ein Dataset mit dem Namen aus
`RAGFLOW_TEMPLATE_DATASET_NAME`, standardmäßig `connector_template`. Wenn es
fehlt und `RAGFLOW_TEMPLATE_AUTO_CREATE=true` gesetzt ist, legt der Connector
das Template automatisch an.

Das Template wird nur für die Dataset-Erstellung verwendet. Bestehende Datasets
behalten ihre aktuellen RAGFlow-Einstellungen; allein die verwaltete
`permission` wird auf den konfigurierten Zielwert abgeglichen.

## Sichtbarkeit erzeugter Bibliotheks-Datasets

`RAGFLOW_GENERATED_DATASET_PERMISSION` steuert ausschließlich die
RAGFlow-Berechtigung vom Connector erzeugter Bibliotheks-Datasets:

- `me` ist der sichere Default und lässt das Dataset nur für den
  RAGFlow-API-Key-Besitzer sichtbar.
- `team` macht das Dataset für alle Mitglieder des RAGFlow-Tenants des
  Connectors sichtbar. Diese Nutzer müssen dem Tenant bereits angehören.

`team` ist keine Abbildung der Seafile-ACL. Connector-Suche und OpenWebUI-Pipe
prüfen weiterhin die aus Seafile synchronisierten Berechtigungen. Das interne
Template-Dataset (standardmäßig `connector_template`) bleibt unabhängig von
dieser Einstellung immer privat (`me`). Der Connector gleicht auch ein bereits
vorhandenes, exakt erwartetes Bibliotheks-Dataset idempotent auf `me` oder
`team` ab. Dabei wird ausschließlich `permission` aktualisiert; Template-,
Parser- und sonstige Dataset-Einstellungen bleiben erhalten.

`team` bedeutet nur tenantweite Dataset-Sichtbarkeit. Es ändert nicht den
Besitzer bereits vorhandener Chats oder Search Apps und garantiert deshalb
nicht, dass ein anderer Tenant-User solche fremd besessenen Artefakte nativ
ausführen kann.

## Getrennte interaktive Admin-Identität

Der `RAGFLOW_API_KEY` bleibt die kanonische Sync-Identität: Er besitzt das
interne Dataset-Template sowie alle aus Seafile erzeugten Datasets und hält
deren Dokumente synchron. Optional kann genau ein kontrollierter RAGFlow-
Admin-Zieluser die interaktiven Artefakte besitzen:

```env
RAGFLOW_INTERACTIVE_API_KEY=
RAGFLOW_INTERACTIVE_OWNER_ID=
RAGFLOW_INTERACTIVE_CHAT_MODEL_ID=
RAGFLOW_GENERATED_DATASET_PERMISSION=team
```

Sobald der interaktive Key gesetzt ist, sind die zugehörige RAGFlow-User-ID,
eine für diesen User verfügbare Chat-Modell-ID und `team` Pflicht. Der User
muss Mitglied desselben RAGFlow-Tenants sein. Der Connector erzeugt und pflegt
die automatisch verwalteten Chats und den ausführbaren `search_template`-
Spiegel unter dieser Identität. Der Search-App-Spiegel erhält die `kb_ids` der
aktiven connector-eigenen Bibliotheks-Datasets; sein RAGFlow-Feld `chat_id`
wird mit `RAGFLOW_INTERACTIVE_CHAT_MODEL_ID` belegt.

Ohne interaktiven Key bleibt das bisherige Verhalten erhalten: Die Sync-
Identität besitzt Datasets, Chats und Search App. Für Connector Search muss
`SEARCH_RAGFLOW_API_KEY` auf dieselbe Identität zeigen, unter der native oder
Connector-Chat-Antworten ausgeführt werden. Im getrennten Modus ist das der
interaktive Key.

Die Trennung ist bewusst nur für einen kontrollierten Admin-Zieluser gedacht.
`team` ersetzt keine Seafile-ACL und gibt normalen Tenant-Mitgliedern keinen
ACL-geprüften Zugriff auf native RAGFlow-Artefakte. Normale Nutzer verwenden
Connector Search oder OpenWebUI; dort bleibt Seafile die Quelle der
Berechtigungsentscheidung.

Bei einer Migration werden zunächst die neuen interaktiven Spiegel erzeugt und
als Zieluser geprüft. Erst danach dürfen alte, von der Sync-Identität besessene
Chat- oder Search-App-Kopien kontrolliert über deren Besitzer beziehungsweise
die Connector-Bereinigung entfernt werden. Kanonische Datasets und das interne
Template gehören nicht zu dieser Bereinigung.

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

Bei konfigurierter interaktiver Identität werden die automatisch verwalteten
interaktiven Chats unter deren Owner-ID erzeugt. Das bloße Setzen eines
Datasets auf `team` verschiebt keine vorhandenen Chats.

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
Search-Service liest nur und erstellt keine RAGFlow-Artefakte. Im getrennten
Modus gehört die automatisch verwaltete App der interaktiven Identität und
referenziert deren Modell sowie die aktiven kanonischen Bibliotheks-Datasets.

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
