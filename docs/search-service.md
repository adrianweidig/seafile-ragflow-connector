# Search-Service

Der Search-Service stellt eine nutzernahe Webseite für RAGFlow-Suchen über
Seafile-Bibliotheken bereit. Er ist kein Admin-Dashboard und kann unabhängig
vom Dashboard laufen.

```bash
connector search-server
```

Der Container besitzt keinen Seafile-Admin-Token und keinen Seafile-Sync-Token.
Vor jeder RAGFlow-Abfrage ruft er die interne Authz-API des Connector-Cores
auf. Nur erlaubte SearchProfiles werden an RAGFlow weitergegeben.

## Routen

| Route | Zweck |
| --- | --- |
| `GET /health` | Healthcheck für Portainer/Reverse Proxy |
| `GET /search` | Weboberfläche "Wissenssuche" |
| `GET /api/search/profiles` | erlaubte Bibliotheken/Datasets für den Nutzer |
| `POST /api/search/query` | Retrieval-Suche über erlaubte Datasets |
| `POST /api/search/chat` | Antwortmodus mit Quellen aus erlaubten Datasets |
| `GET /api/search/source/preview?token=...` | signierter Evidence-Viewer für eine Trefferpassage |
| `GET /api/search/source/document?token=...` | authz-geprüfter same-origin Dokumentproxy für den nativen Browserviewer |

## Authentifizierung

Der erste Auth-Modus ist `trusted_header`. Der Search-Service erwartet, dass
ein vorgeschalteter Reverse Proxy oder Identity-Aware Proxy die Nutzeridentität
setzt:

```env
SEARCH_AUTH_MODE=trusted_header
SEARCH_TRUSTED_USERNAME_HEADER=X-Forwarded-User
SEARCH_TRUSTED_EMAIL_HEADER=X-Forwarded-Email
SEARCH_TRUSTED_DISPLAY_NAME_HEADER=X-Forwarded-Name
```

Die E-Mail ist der primäre ACL-Match-Key. Header dürfen nur aus einer
vertrauenswürdigen Komponente kommen; öffentliche direkte Erreichbarkeit ohne
Proxy ist für produktive Nutzung nicht geeignet.

## Autorisierung

Der Search-Service fragt den Core:

```env
SEARCH_AUTHZ_BASE_URL=http://connector-controller:8080
SEARCH_AUTHZ_SHARED_SECRET=change-me-authz-secret
```

`/api/search/profiles` ruft `GET /api/authz/profiles` auf und zeigt nur
erlaubte SearchProfiles an. `/api/search/query` und `/api/search/chat` senden
die angeforderte Auswahl an `/api/authz/filter-profiles`; verbotene Profile
werden entfernt, bevor RAGFlow angesprochen wird. Wenn kein Profil erlaubt ist,
antwortet der Search-Service mit `403`.

## RAGFlow

```env
SEARCH_RAGFLOW_BASE_URL=http://ragflow:9380
SEARCH_RAGFLOW_API_KEY=change-me
SEARCH_RAGFLOW_VERIFY_SSL=true
SEARCH_RAGFLOW_CA_BUNDLE=
RAGFLOW_SEARCH_TEMPLATE_NAME=search_template
SEARCH_RAGFLOW_TEMPLATE_SOURCE_ORDER=search_app,chat,builtin
SEARCH_ANSWER_GENERATION_MODE=ragflow_chat
RAGFLOW_SEARCH_ANSWER_CHAT_NAME=connector_search_answer
RAGFLOW_SEARCH_ANSWER_CHAT_AUTO_CREATE=true
```

RAGFlow wird pro erlaubtem Dataset abgefragt. Ergebnisse werden
zusammengeführt, dedupliziert und nutzerfreundlich ausgegeben. RAGFlow bekommt
keine Information über verbotene Datasets, weil diese vor dem Aufruf entfernt
werden.

Die Retrieval-Qualität kommt aus einem zentralen `search_template`:

1. RAGFlow Search App mit Name `search_template`.
2. RAGFlow Chat Assistant mit Name `search_template`.
3. Built-in Standard, falls kein Template gefunden wird.

Aus dem Template werden nur Suchparameter übernommen. Datasets, `kb_ids` oder
Dokumentlisten aus RAGFlow werden ignoriert, damit die Seafile-ACL-Auswahl
immer die einzige Berechtigungsgrenze bleibt.

Die UI-Einstellung "Treffer" steuert die sichtbare Ergebnisanzahl. RAGFlows
`top_k` ist dagegen der interne Kandidatenpool und bleibt standardmäßig `1024`.
Dadurch kann RAGFlow sauber hybrid suchen, während die Oberfläche trotzdem nur
eine kompakte Ergebnisliste zeigt.

Optionale Overrides:

```env
SEARCH_RAGFLOW_CANDIDATE_TOP_K=
SEARCH_RAGFLOW_TOP_N=
SEARCH_RAGFLOW_SIMILARITY_THRESHOLD=
SEARCH_RAGFLOW_VECTOR_SIMILARITY_WEIGHT=
SEARCH_RAGFLOW_RERANK_ID=
SEARCH_RAGFLOW_KEYWORD=
SEARCH_RAGFLOW_HIGHLIGHT=
SEARCH_RAGFLOW_CROSS_LANGUAGES=
SEARCH_RAGFLOW_USE_KG=
SEARCH_RAGFLOW_TOC_ENHANCE=
```

Leere Werte bedeuten: Wert aus `search_template` oder Built-in Standard nutzen.
Reranker, Knowledge Graph und TOC Enhance können gute Ergebnisse verbessern,
erhöhen aber Latenz und Betriebsanforderungen. Deshalb sind sie im Built-in
Standard deaktiviert und sollten bewusst im Template aktiviert werden.

Der Antwortmodus (`/api/search/chat`) nutzt Retrieval weiterhin als erste
Berechtigungs- und Quellenstufe. Danach baut der Search-Service einen kompakten
Quellenprompt aus `S1` bis `Sn` und ruft den benannten RAGFlow-Answer-Chat über
OpenAI-kompatible Chat Completions auf. Der Prompt erlaubt nur Aussagen aus den
bereitgestellten Quellen und erwartet Quellenmarker wie `[S1]`. Wenn der Chat
fehlt, leer antwortet oder RAGFlow nicht erreichbar ist, fällt die API auf eine
gekennzeichnete quellengestützte Kurzantwort zurück; Quellen und Diagnostics
bleiben erhalten.

## Quellenlinks

Für den Button "Quelle öffnen" braucht der Search-Service nur eine öffentliche
Seafile-Basis-URL oder ein Link-Template. Er bekommt dafür keinen Seafile-Token:

```env
SEARCH_SEAFILE_PUBLIC_BASE_URL=https://sea.top.secret
SEARCH_SEAFILE_FILE_URL_TEMPLATE=
```

Ohne Template erzeugt der Search-Service Links nach
`{base}/lib/{repo_id}/file{path_quoted}{page_fragment}`. Bei abweichenden
Seafile-Routen kann `SEARCH_SEAFILE_FILE_URL_TEMPLATE` gesetzt werden. Verfügbare
Platzhalter sind `base`, `repo_id`, `repo_id_quoted`, `path`, `path_quoted`,
`path_query`, `path_no_leading_slash`, `path_no_leading_slash_quoted`, `page`
und `page_fragment`.

Zusätzlich erzeugt der Search-Service pro Treffer einen signierten Preview-Link
zum internen Evidence-Viewer. Dieser Viewer ist der verlässliche Pfad zur
angezeigten Passage: Er zeigt Dokumentname, Bibliothek, Pfad, Fundstelle,
Snippet, Score und den bestmöglichen Originallink. Dafür werden nur die bereits
autorisierten RAGFlow-Treffer- und Metadaten in einem signierten Token genutzt;
der Search-Service wird dadurch nicht zu einem generischen Seafile-Daten-Tunnel.

Der zusätzliche Dokumentviewer verwendet `viewer_url` und ruft das Original über
den Connector-Core ab. Der Search-Service speichert keinen Seafile-Admin- oder
Sync-Token; er prüft Preview-Token und Nutzerheader, fragt die Authz-API und
streamt die Datei nur bei `allow` weiter. Der Core lädt über den bestehenden
Seafile-Sync-Client und liefert PDF, Text und Bilder inline aus. HTML und
Markdown werden nicht als aktives same-origin HTML ausgeliefert, sondern als
Text. Office-Dateien erhalten einen Download-/Fallback-Hinweis.

```env
SEARCH_SOURCE_PREVIEW_ENABLED=true
SEARCH_SOURCE_HOVER_ENABLED=true
SEARCH_TEXT_FRAGMENT_LINKS_ENABLED=true
SEARCH_DOCUMENT_VIEWER_ENABLED=true
SEARCH_DOCUMENT_VIEWER_MAX_MB=100
SEARCH_RESULT_SNIPPET_CONTEXT_CHARS=420
SEARCH_ANSWER_MAX_SOURCES=8
SEARCH_SOURCE_PREVIEW_SECRET=
```

Wenn `SEARCH_SOURCE_PREVIEW_SECRET` leer bleibt, wird intern das
`SEARCH_AUTHZ_SHARED_SECRET` für die Signatur genutzt. Ein explizites separates
Secret ist für größere Setups empfehlenswert.

Originalsprünge sind bestmöglich, aber nicht garantiert exakt:

- PDF-Treffer bekommen bei bekannter Seite einen `#page=`-Anker.
- Text-/HTML-Treffer ohne Seitenanker können zusätzlich einen Browser
  Text-Fragment-Link (`#:~:text=`) erhalten.
- Exaktes gelbes In-PDF-Highlighting ist mit dem nativen Browserviewer nicht
  zuverlässig steuerbar. Die UI zeigt deshalb die Trefferpassage gelb neben
  dem Viewer und bietet "Passage suchen" zum Kopieren des stabilen Suchtexts
  für `Strg+F`.
- Wenn Browser, Seafile-Viewer oder Login-Redirect das Fragment nicht
  unterstützen, bleibt der Evidence-Viewer die verlässliche Fundstelle.

## Weboberfläche

Die GUI unter `/search` ist als Arbeitsoberfläche für Endnutzer gebaut:

- Kopfzeile "Wissenssuche"
- mittiger Dokumentviewer über Antwort und Chatfeld
- sticky Chatfeld am unteren Rand der Arbeitsfläche
- Bibliotheksauswahl mit Checkboxen
- Filterfeld für Bibliotheken
- Umschaltung zwischen "Dokumente finden" und "Antwort mit Quellen"
- dreispaltiges Desktop-Layout mit Quellenpanel
- Kartenlayout für Ergebnisse mit `S1`-/`S2`-Quellenlabels
- Quellenchips wählen dieselbe Quelle im Viewer aus
- Dokumentname, Bibliothek, Pfad, Snippet, Score und Locator-Chip
- Aktionen "Vorschau", "Quelle öffnen", "Seite öffnen" oder "Passage suchen"
- Hover-/Fokus-Vorschau für Quellenchips und Trefferkarten
- verständliche leere Zustände, Ladezustand und Berechtigungsfehler
- responsive Layout ohne externe CDN-Assets

Technische IDs werden nur als Fallback genutzt. Primäre Texte kommen aus
`display_name`, Dataset-/Dokumentnamen, Pfaden und Snippets.

## Portainer und Compose

In Portainer ist `connector-search` bereits in
`deploy/portainer/docker-compose.yml` enthalten. Für direkte Compose-Varianten
kann das Overlay ergänzt werden:

```bash
docker compose --env-file connector.env \
  -f deploy/compose/shared-network.compose.yml \
  -f deploy/compose/search.compose.yml up -d
```

Für Host-Port-Exposure:

```env
SEARCH_SERVICE_PUBLISHED_PORT=127.0.0.1:18090
```

Für LAN- oder Reverse-Proxy-Betrieb sollte der Search-Service hinter einem
Proxy liegen, der TLS terminiert und die Trusted-Header kontrolliert setzt.
