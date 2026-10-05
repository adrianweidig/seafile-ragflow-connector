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
| `GET /livez` | billige Prozess-/Eventloop-Liveness ohne Upstream-Zugriff |
| `GET /readyz` | kurz gecachte Readiness für Datenbank, Core-Authz, RAGFlow und den konfigurierten Identitätsdienst |
| `GET /metrics` | Prometheus-Textformat ohne Nutzer-, Repository- oder Pfadlabels |
| `GET /health` | rückwärtskompatibler Alias für `/livez` |
| `GET /search` | Weboberfläche "Wissenssuche" |
| `GET /auth/login` | Anmeldeseite im Modus `openwebui_ldap` |
| `POST /auth/login` | serverseitige LDAP-Anmeldung über OpenWebUI |
| `POST /auth/logout` | beendet die lokale Search-Sitzung |
| `GET /api/search/profiles` | erlaubte Bibliotheken/Datasets für den Nutzer |
| `POST /api/search/query` | paginierte Retrieval-Suche über erlaubte Datasets |
| `POST /api/search/chat` | paginierter Antwortmodus mit Quellen aus erlaubten Datasets |
| `GET /api/search/source/preview?token=...` | signierter Evidence-Viewer für eine Trefferpassage |
| `GET /api/search/source/document?token=...` | authz-geprüfter same-origin Dokumentproxy für den nativen Browserviewer |

## Authentifizierung

Im Modus `trusted_header` erwartet der Search-Service, dass ein vorgeschalteter
Reverse Proxy oder Identity-Aware Proxy die Nutzeridentität setzt:

```env
SEARCH_AUTH_MODE=trusted_header
SEARCH_TRUSTED_USERNAME_HEADER=X-Forwarded-User
SEARCH_TRUSTED_EMAIL_HEADER=X-Forwarded-Email
SEARCH_TRUSTED_DISPLAY_NAME_HEADER=X-Forwarded-Name
SEARCH_TRUSTED_PROXY_CIDRS=10.20.30.0/28
```

Die E-Mail ist der primäre ACL-Match-Key. Header dürfen nur aus einer
vertrauenswürdigen Komponente kommen. Der Search-Service wertet sie nur aus,
wenn die unmittelbare Peer-IP in `SEARCH_TRUSTED_PROXY_CIDRS` liegt; ein
`X-Forwarded-For`-Wert begründet kein Vertrauen. Bei öffentlicher Bindung und
fehlender Proxy-Allowlist verweigert der Service im Produktionsmodus den Start.

Der Reverse Proxy muss vom Client gelieferte Identitätsheader verwerfen und die
Header ausschließlich aus seiner authentifizierten Session neu setzen. Eine
Nginx-Konfiguration darf deshalb beispielsweise nur verifizierte Variablen
weiterreichen, niemals `$http_x_forwarded_user` oder `$http_x_forwarded_email`:

```nginx
proxy_set_header X-Forwarded-User  $authenticated_user;
proxy_set_header X-Forwarded-Email $authenticated_email;
proxy_set_header X-Forwarded-Name  $authenticated_display_name;
```

Wenn OpenWebUI bereits erfolgreich an LDAP/AD angebunden ist, kann Search
dieselbe Pipeline nutzen:

```env
SEARCH_AUTH_MODE=openwebui_ldap
SEARCH_OPENWEBUI_LDAP_BASE_URL=http://openwebui:8080
SEARCH_OPENWEBUI_LDAP_VERIFY_SSL=true
SEARCH_OPENWEBUI_LDAP_CA_BUNDLE=
SEARCH_OPENWEBUI_LDAP_TIMEOUT_SECONDS=20
SEARCH_SESSION_SECRET=change-me-search-session-secret
SEARCH_SESSION_TTL_SECONDS=28800
SEARCH_SESSION_COOKIE_NAME=connector_search_session
SEARCH_SESSION_COOKIE_SECURE=true
```

Search sendet Benutzername und Passwort nur serverseitig an
`POST /api/v1/auths/ldap`. OpenWebUI führt den LDAP-Service-Bind, die
Nutzersuche, den Nutzer-Bind und seine konfigurierte Gruppensynchronisierung
aus. Das von OpenWebUI zurückgegebene Token wird weder gespeichert noch an den
Browser weitergereicht. Search erstellt stattdessen eine eigene HMAC-signierte,
zeitlich begrenzte Sitzung mit `HttpOnly`, `SameSite=Lax` und standardmäßig
`Secure`. Das Session-Secret muss im Produktionsmodus explizit gesetzt werden.
Die Abmeldung löscht nur die Search-Sitzung; LDAP- oder OpenWebUI-Sitzungen
bleiben unverändert.

Im Swarm-Standardprofil wird Search über
`SEARCH_SERVICE_PUBLISHED_PORT` im Routing-Mesh veröffentlicht. Produktiv
sollte im Modus `trusted_header` davor ein authentifizierender Proxy stehen;
nur dessen konkretes Netz gehört in die CIDR-Allowlist. Im Modus
`openwebui_ldap` reicht ein normaler TLS-Reverse-Proxy ohne eigene
Nutzeranmeldung. Core-only lässt das Search-Modul vollständig weg.

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
SEARCH_ANSWER_LLM_BASE_URL=
SEARCH_ANSWER_LLM_MODEL=
SEARCH_ANSWER_LLM_API_KEY=
SEARCH_ANSWER_LLM_TIMEOUT_SECONDS=60
SEARCH_ANSWER_LLM_MAX_TOKENS=900
SEARCH_ANSWER_LLM_TEMPERATURE=0.2
```

Ohne getrennte interaktive RAGFlow-Identität verwendet
`SEARCH_RAGFLOW_API_KEY` denselben Key wie `RAGFLOW_API_KEY`. Wenn die
automatisch verwalteten Chats und Search-App-Spiegel einem kontrollierten
Admin-Zieluser über `RAGFLOW_INTERACTIVE_API_KEY` gehören, muss der
Search-Service für native beziehungsweise Connector-Chat-Antworten denselben
interaktiven Key verwenden. Das ändert nicht die Berechtigungsgrenze: Die
Dataset-Auswahl wird weiterhin vor jedem RAGFlow-Aufruf über die Seafile-ACL
gefiltert.

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

Die UI-Einstellung **Treffer pro Seite** steuert die Seitengröße (Standard 20,
Maximum 100). Weitere Ergebnisse werden über einen opaken Cursor nachgeladen,
der an Nutzer, Frage, Profilauswahl, die aktuelle Dataset-/ACL-Auflösung und den
Service-Scope gebunden ist. Die erste Seite legt dafür einen kurzlebigen
Result-Snapshot an; Folgeseiten lesen ausschließlich diesen Snapshot und bleiben
daher auch bei veränderter Upstream-Rangfolge lücken- und duplikatfrei. Der
ältere Request-Parameter `top_k` bleibt kompatibel. RAGFlows internes `top_k`
ist dagegen der Kandidatenpool und bleibt standardmäßig `1024`. Dadurch kann
RAGFlow sauber hybrid suchen, während die Oberfläche kompakte Seiten zeigt.

Pro Request sind höchstens 25 Profile zulässig. Bis zu vier erlaubte Datasets
werden parallel abgefragt; wenn RAGFlow für ein Dataset mehrere Seiten liefert,
holt der Service sie bis zur benötigten Kandidatenmenge nach. Die Antwort
enthält `request_id`, `timing_ms` und:

```json
{
  "pagination": {"next_cursor": "…", "has_more": true},
  "partial_failures": [
    {"profile_id": "…", "reason": "dataset_not_ready"}
  ]
}
```

Ein einzelnes nicht bereites oder fehlerhaftes Dataset verwirft damit nicht die
erfolgreichen Treffer anderer erlaubter Datasets. Der Cursor ist nicht als
dauerhafte ID zu speichern oder manuell zu verändern. Result-Snapshots laufen
nach 180 Sekunden ab und sind sowohl nach Anzahl als auch Speichergröße
begrenzt. Bei `cursor_expired` startet die UI die Suche bewusst neu; ein
ungültiger oder fremder Cursor wird nicht übernommen.

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
Quellenprompt aus `S1` bis `Sn`. Wenn `SEARCH_ANSWER_LLM_BASE_URL` und
`SEARCH_ANSWER_LLM_MODEL` gesetzt sind, ruft der Search-Service zuerst diesen
OpenAI-kompatiblen `/chat/completions`-Endpunkt auf. `SEARCH_ANSWER_LLM_API_KEY`
ist optional; bei leerem Wert wird kein Authorization-Header gesendet.

Ist der OpenAI-kompatible Pfad nicht konfiguriert oder schlägt er fehl, bleibt
`SEARCH_ANSWER_GENERATION_MODE` maßgeblich: Bei `ragflow_chat` wird der
benannte RAGFlow-Answer-Chat genutzt, bei `retrieval_summary` oder `disabled`
entsteht direkt eine lokale quellengestützte Kurzantwort. Alle Pfade dürfen nur
aus den bereitgestellten Quellen argumentieren und sollen Quellenmarker wie
`[S1]` verwenden. Wenn ein Modell eine Antwort ohne Quellenmarker liefert, hängt
der Search-Service die genutzten Quellen in eckigen Klammern an. Quellen und
Diagnostics bleiben auch bei Fallbacks erhalten.

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

Search und OpenWebUI verwenden dafür den versionierten `SourceDTO v1` mit
stabilem Quellenmarker, Status, Locator, `viewer_url` und `original_url`.
Bestehende `EvidenceHit`-Aufrufer bleiben kompatibel. OpenWebUI erhält native
Citation-Events; kompaktes Quellen-Markdown wird nur genutzt, wenn die native
Ausgabe nicht verfügbar oder unvollständig ist.

Der zusätzliche Dokumentviewer verwendet `viewer_url` und ruft das Original über
den Connector-Core ab. Der Search-Service speichert keinen Seafile-Admin- oder
Sync-Token; er prüft Preview-Token und Nutzerheader, fragt die Authz-API und
streamt die Datei nur bei `allow` weiter. Der Core lädt über den bestehenden
Seafile-Sync-Client und liefert PDF, Text und Bilder inline aus. HTML und
Markdown werden nicht als aktives same-origin HTML ausgeliefert, sondern als
Text. Office-Dateien erhalten einen Download-/Fallback-Hinweis.

Damit RAGFlow-Anzeigenamen auf echte Seafile-Pfade in Unterordnern abgebildet
werden können, hat `connector-search` lesenden Zugriff auf den Connector-State
über `DATABASE_URL` oder die `POSTGRES_*`-Werte. Dieser Zugriff ersetzt keine
Seafile-Berechtigungsprüfung und enthält keine Seafile-Admin- oder Sync-Tokens.

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
- mobile Bereichsnavigation zwischen Antwort, Dokument und Quellen
- serverseitig request-spezifisch abbrechen, exakt denselben fehlgeschlagenen
  Request wiederholen und weitere Treffer per stabilem Snapshot-Cursor nachladen
- letztes erfolgreiches Ergebnis bleibt während Loading, Abbruch und Fehler
  sichtbar; nach Cursor-Ablauf startet ein Retry mit einer frischen Rangfolge
- persistierte Bibliotheksauswahl und maximal 25 ausgewählte Profile
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
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/search.compose.yml up -d
```

Für Host-Port-Exposure:

```env
SEARCH_SERVICE_PUBLISHED_PORT=127.0.0.1:18090
```

Für LAN- oder Reverse-Proxy-Betrieb sollte der Search-Service hinter einem
Proxy liegen, der TLS terminiert und die Trusted-Header kontrolliert setzt.
