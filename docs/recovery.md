# Recovery

## Worker-Crash

Jobs sind idempotent. Locks laufen ab und Jobs können erneut ausgeführt werden.

## Redis-Verlust

PostgreSQL bleibt die Recovery-Quelle. Queued oder laufende Jobs können aus dem
dauerhaften Job-State rekonstruiert werden.

## Seafile-Ausfall

Solange Seafile nicht erreichbar ist, werden keine Delete-Entscheidungen
getroffen. Download- und Discovery-Jobs gehen in den Retry.

## RAGFlow-Ausfall

Upload-, Delete-, Parse- und Status-Jobs werden mit Backoff wiederholt.
Discovery kann weiterlaufen, muss aber Backpressure anwenden, um unbegrenzte
Queues zu vermeiden.
