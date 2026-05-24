# TLS-Zertifikate für Compose-Beispiele

Lege hier für lokale Tests ein PEM-Bundle ab, zum Beispiel:

```text
deploy/certs/internal-ca.pem
```

Dieses Bundle enthält die Root-CA und, falls vorhanden, die Intermediate-CAs
der internen PKI. Es enthält nicht das Leaf-Zertifikat von Seafile, RAGFlow
oder dem Connector-Proxy und keine privaten Schlüssel.

Prüfung:

```bash
openssl x509 -in deploy/certs/internal-ca.pem -noout -subject -issuer -dates
```

In produktiven Umgebungen sollte der Host-Pfad über
`CONNECTOR_TLS_CA_HOST_FILE` oder `CONNECTOR_CERTS_HOST_DIR` auf ein
administriertes Zertifikatsverzeichnis zeigen. mTLS-Key-Dateien sind sensibel
und sollten nicht in dieses Repository gelegt werden; nutze dafür Docker
Secrets oder einen geschützten Host-Pfad mit read-only Mount.
