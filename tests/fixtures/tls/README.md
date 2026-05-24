# TLS test fixtures

This directory documents the TLS certificate fixture shape used by local HTTPS
verification tests. The tests generate their certificates in a temporary
directory at runtime, so private keys are not committed to the repository.

To inspect the same fixture set manually, generate it with:

```bash
uv run python deploy/tls-lab/generate_certs.py --out-dir deploy/tls-lab/certs
```

The generated fixture set contains:

- `top-secret-root-ca.pem`: local test Root CA for CA-signed server
  certificates.
- `rag.top.secret.*`, `seafile.top.secret.*`, `connector.top.secret.*`:
  valid CA-signed HTTPS server certificates for local `.top.secret` domains.
- `wronghost.top.secret.*`: certificate file whose SAN is deliberately
  `other.top.secret`.
- `expired-rag.top.secret.*`: expired CA-signed server certificate.
- `selfsigned-rag.top.secret.*`: self-signed server certificate for the
  diagnostic case where a single self-signed leaf certificate is used as a
  trust anchor.
