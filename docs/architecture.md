# Architektur

Der Connector ist eine Sync-Control-Plane. Er patcht RAGFlow nicht und nutzt
WebDAV nicht als Kernmechanismus.
Seafile ist die einzige Quelle der Wahrheit: Zielsystem-Löschungen in RAGFlow
oder OpenWebUI lösen niemals Änderungen in Seafile aus, sondern werden durch
den nächsten Sync aus Seafile repariert.

```text
Seafile API -> controller -> PostgreSQL state -> Redis jobs -> workers -> RAGFlow API
                         \-> reconciler ------------------------/
                         \-> OpenWebUI sync -> OpenWebUI API
                         \-> HTTP proxy ----> RAGFlow API
Admin browser -> controller dashboard -> PostgreSQL controls -> scheduler/job queue
```

## Komponenten

| Komponente | Verantwortung |
| --- | --- |
| controller | Discovery-Loop, Dataset-Provisioning, commit-gepinnte Delta-Planung und interaktive Dashboard-Administration |
| worker | Download, Klassifikation, Artefakt-Erzeugung, Upload, Delete, Parse |
| reconciler | Eigenständiger Zustandsvergleich zwischen Seafile-Snapshot, DB und RAGFlow; Reparaturen werden als deduplizierte Jobs ausgeführt |
| PostgreSQL | dauerhafter Sync-Zustand und Job-Historie |
| Redis | Queue, Retry-Verzögerung, Worker-Fan-out |
| Controller-Dashboard | Status/Logs sowie authentifizierte globale, bibliotheksspezifische und laufbezogene Steuerung |
| Standalone-Dashboard | absichtlich lesende Statusansicht ohne Orchestrator, Queue oder Adminaktionen |
| OpenWebUI sync | optionale idempotente Erzeugung von RAGFlow-Chats, OpenWebUI-Tools und Pipes |
| HTTP proxy | geschützte OpenWebUI-Function-Aufrufe ohne RAGFlow-Secrets im Function-Code |

Der globale Steuerzustand wird vor Scheduler und Worker-Claims einmalig aus
`CONNECTOR_AUTOMATION_INITIAL_STATE` angelegt. Danach ist PostgreSQL die
Wahrheitsquelle; Neustarts und spätere Env-Änderungen überschreiben keine
Operatorentscheidung.

## Admin-Control-Plane

Die schreibende Administrationsoberfläche ist Teil des Controllers, weil nur
dieser Prozess Orchestrator, persistenten JobStore und Redis-Signalweg gemeinsam
verdrahtet. Der eigenständige Prozess `connector dashboard` erhält diese
Abhängigkeiten absichtlich nicht und bleibt lesend. So kann ein Diagnose-
Dashboard niemals versehentlich zu einer zweiten Scheduling-Instanz werden.

Der Steuerfluss lautet:

```text
Browser
  -> Dashboard Basic Auth + Request-Schutz
  -> Controller-Dashboard-API
  -> persistente globale/Bibliotheks-/Laufsteuerung in PostgreSQL
  -> Scheduler und Reconciler prüfen Richtlinien vor dem Einplanen
  -> JobStore hält oder aktiviert persistente Jobs
  -> Redis signalisiert verfügbare Arbeit
  -> Worker prüft Pause/Stop an sicheren Checkpoints
```

PostgreSQL ist die Wahrheit für Operatorzustände und Läufe; Browserzustand und
Redis sind es nicht. Redis dient weiterhin nur als Wake-up-Signal. Deshalb
überleben Aktiv-/Pausiert-/Deaktiviert-Entscheidungen, Laufstatus und
Fortschritt einen Browser- oder Controller-Neustart. Deduplizierung,
Repository-Leases und Fence-Tokens bleiben auch bei Pause und Fortsetzen
wirksam.

Die globale Queue-Steuerung hat Vorrang vor bibliotheksspezifischen Richtlinien.
`start` aktiviert Automatik, gibt die Queue frei und stößt Discovery an;
`deactivate` schaltet nur neue Automatik aus. `pause` hält neue Claims,
`resume` gibt die Queue frei und `stop` kombiniert deaktivierte Automatik,
pausierte Queue und kooperativen Cancel aller aktiven Jobs. Die sichtbaren
globalen Statuswerte sind `running`, `deactivated`, `paused` und `stopped`.

Bibliotheken verwenden getrennt von ihrem technischen `Library.status` die
Operatorzustände `active`, `disabled` und `paused`. Eine deaktivierte oder
pausierte Bibliothek bleibt vorhanden, wird nicht als gelöscht markiert und
löst keine Zielbereinigung aus; automatische und manuelle Sync-/OpenWebUI-
Arbeit für sie wird gefiltert. Laufpause setzt einen persistenten Hold:
wartende Jobs sind nicht claimbar, laufende Jobs kehren am nächsten sicheren
Checkpoint nach `queued` zurück. Stop oder Cancel gewinnt gegenüber Pause.

Ein Worker unterbricht keine externe HTTP-Operation mitten im Request. Die
Anforderung wird am nächsten sicheren Datei-, Änderungs- oder Job-Checkpoint
übernommen, ohne einen bestätigten Cursor oder eine bereits erfolgreiche
Dokumentversion zurückzusetzen.

Dashboard-Aktionen verwalten niemals Docker-, Swarm- oder Portainer-Prozesse.
Damit bleibt der Controller samt Dashboard für Diagnose und Fortsetzen
erreichbar, wenn die fachliche Connector-Arbeit angehalten wurde. Die
Steuer-API ist gegenüber der lesenden API zusätzlich fail closed abgesichert;
interne Authz-/Proxy-Routen und Monitoring-Proben behalten ihre getrennten
Authentifizierungsgrenzen.

Die Schreibgrenze verlangt gemeinsam
`CONNECTOR_DASHBOARD_CONTROL_ENABLED=true`, aktiviertes Dashboard, vollständige
Basic-Auth-Konfiguration, `Content-Type: application/json` und
`X-Connector-Admin-Action: 1`. Globaler Stop sowie Stop/Cancel eines Laufs
benötigen zusätzlich die exakte JSON-Bestätigung `{"confirm":"STOP"}`.
Bestehende Service-POSTs für Authz und
OpenWebUI-Proxy behalten ihre eigenen Secrets und laufen nicht durch diese
Browsergrenze. Angenommene Adminaktionen werden mit Akteur, Aktion, Ziel,
Vorher-/Nachher-Zustand und Ergebnis persistent geloggt, ohne Passwörter,
Tokens oder andere Secrets zu übernehmen.

## Fortschrittsmodell

Workflow-, Bibliotheks- und Sync-Läufe referenzieren dieselben persistenten
Jobs und Sync-Zustände. Sichtbare Fortschrittsdaten werden daraus aggregiert,
nicht als unabhängiger Browserzähler geführt. Pro Bibliothek werden aktuelle
Phase, bekannte Datei-Gesamtzahl, verarbeitete Dateien und Parsing-Zustände
ausgewiesen. Parsing liefert `tracked`, `done`, `pending`, `failed` und
`percent`; der Lauf ergänzt `completed`, `total`, `percent`, `phases` und
`libraries`. Jobs machen Phase, Prozentwert sowie Pause-/Cancel-Anforderung
sichtbar. Prozentwerte entstehen nur bei bekanntem Nenner. RAGFlow-Statuswerte
werden defensiv normalisiert, damit fehlende oder ungültige Werte keinen
bestätigten Fortschritt zurücksetzen.

## Delete- und Repair-Fluss

Wenn eine Library in Seafile verschwindet, markiert der Connector die Library
lokal als `deleted`, entfernt das zugehörige RAGFlow-Dataset und lässt den
OpenWebUI-Sync die dazugehörigen RAGFlow-Chats, Tools und Pipes löschen. Wenn
ein Dataset oder Dokument in RAGFlow ohne Seafile-Löschung verschwindet, erzeugt
der Connector Dataset und Dokumente beim nächsten Sync aus Seafile neu. Wenn
OpenWebUI-Tools oder -Pipes fehlen, werden eigene Artefakte idempotent erneut
angelegt.

## Konsistenzmodell

Ein Vollsync erfasst nach Möglichkeit einen vollständigen Snapshot für einen
festen Seafile-Commit. Erst nach erfolgreicher Verarbeitung wird der Cursor per
Compare-and-swap auf diesen Snapshot vorgeschoben. Ein Delta-Lauf vergleicht
den letzten bestätigten Snapshot mit dem neuen Commit-Snapshot und verarbeitet
Create, Update, Rename und Delete. Fehlt eine vollständige Basis, bleibt der
Cursor unverändert und der Lauf fällt auf Vollsync zurück.

Mutierende Jobs benötigen pro Bibliothek eine zeitlich begrenzte Lease mit
monotonem Fence-Token. Dadurch kann ein alter Worker nach Lease-Verlust keinen
neueren Lauf als erfolgreich abschließen. Neue Dokumentversionen werden erst
nach erfolgreichem Parse zum aktuellen Dokument befördert; die vorherige
Version bleibt bis dahin referenzierbar. Verzögerte Löschungen laufen über eine
persistente Cleanup-Outbox.

## Dataset-Einstellungen

`connector_template` wird nur beim Erzeugen eines RAGFlow-Datasets verwendet.
Fehlt das Template, kann der Connector es automatisch mit konservativen
DeepDOC-, Seiten- und Metadaten-Defaults anlegen. Danach sind die aktuellen
RAGFlow-Einstellungen des Ziel-Datasets maßgeblich. Dadurch kann ein Admin
Chunking, Parser-Einstellungen oder Ingestion Pipeline direkt in RAGFlow ändern,
ohne den Connector neu zu konfigurieren.

## OpenWebUI

Die OpenWebUI-Integration ist additiv. Für jede aktive Library mit
RAGFlow-Dataset speichert der Connector ein Mapping aus Dataset, RAGFlow-Chat,
OpenWebUI-Tool, OpenWebUI-Pipe und sichtbarem Modellnamen. Die Pipe erscheint in
OpenWebUI als eigenes Custom-Model. Tool und Pipe sind deterministisch benannt,
enthalten keine Admin-Secrets und nutzen ausschließlich den Connector-Proxy.

Quellen werden aus RAGFlow-Referenzen normalisiert und als OpenWebUI-Source- bzw.
Citation-Metadaten zurückgegeben. Wenn kein stabiler RAGFlow-Deep-Link
konfiguriert ist, kann der Connector signierte Preview-Links erzeugen, die nur
Metadaten und Auszüge anzeigen. Optional kann die Preview über ein lokales
Seafile-URL-Template zusätzlich auf das Originaldokument und bei PDFs auf eine
Seitenposition verweisen. Die Preview ist offline-fähig und lädt keine externen
Assets.

## Datei-Ingestion

Der Connector behandelt Dateiendungen als Hinweise, nicht als vollständige
Policy. Unbekannte Dateien können akzeptiert werden, wenn sie als Text erkannt
werden. Code und textbasierte Spezialformate wie Ada-Dateien werden bei Bedarf
vor dem Upload in stabile Text-Artefakte überführt.
