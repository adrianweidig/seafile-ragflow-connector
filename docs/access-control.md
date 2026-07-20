# Access-Control und ACL-Snapshot

Das Access-Control-Modul liegt unter
`src/seafile_ragflow_connector/security/access_control.py`. Es kapselt die
gemeinsame Entscheidung für Search-Webseite und OpenWebUI-Pipe.

## Datenmodell

`library_acl_subjects` speichert Rohberechtigungen aus Seafile:

| Feld | Bedeutung |
| --- | --- |
| `repo_id` | Seafile-Bibliothek |
| `subject_type` | `owner`, `user` oder `group` |
| `subject_id` | E-Mail oder Gruppen-ID |
| `subject_name` | optionaler Anzeigename |
| `permission` | `r`, `rw` oder `admin` |
| `source` | `seafile_owner`, `seafile_user_share`, `seafile_group_share` |
| `last_seen_at` | Zeitpunkt des letzten ACL-Snapshots |

`library_acl_effective_users` enthält die zur Query-Zeit relevante,
expandierte Nutzerberechtigung:

| Feld | Bedeutung |
| --- | --- |
| `repo_id` | Seafile-Bibliothek |
| `user_email` | normalisiert mit trim und lowercase |
| `permission` | höchste effektive Berechtigung |
| `sources` | JSON-Liste der Berechtigungsquellen, z. B. `owner`, `user_share`, `group:42` |
| `last_seen_at` | Zeitpunkt des letzten ACL-Snapshots |

`search_profiles` verbindet Seafile-Bibliotheken mit RAGFlow-Datasets. Diese
Profile sind unabhängig von OpenWebUI-Mappings und bleiben nutzbar, wenn
OpenWebUI deaktiviert ist.

## Snapshot-Aufbau

Der Controller führt den ACL-Snapshot periodisch aus, wenn
`SEARCH_ACL_SYNC_ENABLED=true` gesetzt ist. Zusätzlich kann ein manueller Lauf
gestartet werden:

```bash
connector authz-sync-once
```

Ein Snapshot liest alle Bibliotheken, Owner, direkte User-Shares,
Gruppen-Shares und Gruppenmitglieder. Entfernte Shares verschwinden beim
nächsten Refresh aus Roh- und Effective-ACLs. Wenn ein Gruppenmember-Call für
eine Bibliothek fehlschlägt, wird das zugehörige SearchProfile als `failed`
markiert und die Bibliothek bleibt fail-closed.

## Entscheidung

Die zentralen DTOs:

```python
UserIdentity(username: str | None, email: str | None)
AuthzResource(repo_id: str | None, ragflow_dataset_id: str | None)
AuthzDecision(decision, repo_id, ragflow_dataset_id, permission, reason, acl_version)
```

`check_access()` löst zuerst das Repo/Dataset-Mapping über `search_profiles`
auf und prüft anschließend die effektive User-ACL. E-Mail-Adressen werden
case-insensitive verglichen. Ein Username wird als E-Mail-Fallback genutzt,
wenn er selbst wie eine E-Mail-Adresse aussieht, z. B.
`olaf@example.local`. Ein Username ohne Domain, z. B. `olaf`, wird nur dann
akzeptiert, wenn genau eine effektive ACL-Mailadresse der Bibliothek diesen
lokalen Teil besitzt. Gibt es mehrere Treffer wie `olaf@example.local` und
`olaf@other.local`, bleibt die Entscheidung fail-closed mit
`ambiguous_username`.

`filter_profiles_for_user()` ist der gemeinsame Bulk-Pfad für GUI-Auswahl und
Multi-Dataset-Suche. Verbotene Profile werden vor jeder RAGFlow-Abfrage
ausgefiltert.

## API-Verhalten

`POST /api/authz/check` prüft ein einzelnes Repo oder Dataset.

`POST /api/authz/filter-profiles` filtert angefragte Profile und liefert
getrennte `allowed`- und `denied`-Listen.

`GET /api/authz/profiles` liefert alle erlaubten SearchProfiles für den
aktuellen Nutzer. Search-Service und interne Reverse-Proxies übergeben dafür
die Nutzerfelder als Header:

```http
X-Authz-Username: olaf
X-Authz-Email: olaf@example.local
```

Alle drei Routen verlangen das Authz-Bearer-Secret. Ohne korrektes Secret
antwortet der Core mit `401` beziehungsweise `403`.

## Abgrenzung zur nativen RAGFlow-Sichtbarkeit

`RAGFLOW_GENERATED_DATASET_PERMISSION=team` macht neu erzeugte
Bibliotheks-Datasets für alle Mitglieder des RAGFlow-Tenants des Connectors
sichtbar. Das ist eine tenantweite RAGFlow-Berechtigung und keine Seafile-ACL.
Nutzer benötigen weiterhin eine Mitgliedschaft in diesem RAGFlow-Tenant; für
Connector-Suche und OpenWebUI entscheidet zusätzlich unverändert der oben
beschriebene Seafile-ACL-Snapshot. Das interne Template-Dataset (standardmäßig
`connector_template`) bleibt immer privat (`me`).

`team` allein überträgt keine Eigentümerschaft an vorhandenen Chats oder Search
Apps und macht fremd besessene Artefakte nicht automatisch ausführbar. Für
einen kontrollierten Admin-Zieluser kann der Connector deshalb eine separate
interaktive Identität konfigurieren. Diese besitzt ihre automatisch
verwalteten Chat- und Search-App-Spiegel und referenziert die kanonischen
Team-Datasets. Normale Nutzer erhalten dadurch keine native RAGFlow-Freigabe;
sie arbeiten weiterhin über Connector Search oder OpenWebUI mit Seafile-ACL-
Prüfung.
