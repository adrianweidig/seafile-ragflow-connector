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
```

RAGFlow wird pro erlaubtem Dataset abgefragt. Ergebnisse werden
zusammengeführt, dedupliziert und nutzerfreundlich ausgegeben. RAGFlow bekommt
keine Information über verbotene Datasets, weil diese vor dem Aufruf entfernt
werden.

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

## Weboberfläche

Die GUI unter `/search` ist als Arbeitsoberfläche für Endnutzer gebaut:

- Kopfzeile "Wissenssuche"
- großes zentrales Suchfeld
- Bibliotheksauswahl mit Checkboxen
- Umschaltung zwischen "Dokumente finden" und "Antwort mit Quellen"
- Kartenlayout für Ergebnisse
- Dokumentname, Bibliothek, Pfad, Snippet, optional Score und Seite
- Aktionen "Quelle öffnen" und "Vorschau"
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
