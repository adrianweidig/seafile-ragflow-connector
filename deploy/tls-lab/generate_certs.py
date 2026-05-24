from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(Path(__file__).with_name("certs")))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    root_key = _new_key()
    root_cert = _root_ca(root_key)
    _write_cert(out_dir / "top-secret-root-ca.pem", root_cert)
    _write_key(out_dir / "top-secret-root-ca.key.pem", root_key)

    for name in ("rag.top.secret", "seafile.top.secret", "connector.top.secret"):
        key = _new_key()
        cert = _server_cert(name, key, issuer_cert=root_cert, issuer_key=root_key)
        _write_pair(out_dir, name, cert, key)

    wrong_key = _new_key()
    wrong_cert = _server_cert(
        "other.top.secret",
        wrong_key,
        issuer_cert=root_cert,
        issuer_key=root_key,
    )
    _write_pair(out_dir, "wronghost.top.secret", wrong_cert, wrong_key)

    expired_key = _new_key()
    expired_cert = _server_cert(
        "expired-rag.top.secret",
        expired_key,
        issuer_cert=root_cert,
        issuer_key=root_key,
        not_before=datetime.now(UTC) - timedelta(days=10),
        not_after=datetime.now(UTC) - timedelta(days=1),
    )
    _write_pair(out_dir, "expired-rag.top.secret", expired_cert, expired_key)

    selfsigned_key = _new_key()
    selfsigned_cert = _server_cert(
        "selfsigned-rag.top.secret",
        selfsigned_key,
        issuer_cert=None,
        issuer_key=selfsigned_key,
    )
    _write_pair(out_dir, "selfsigned-rag.top.secret", selfsigned_cert, selfsigned_key)
    print(f"TLS lab certificates written to {out_dir}")


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _root_ca(key: rsa.RSAPrivateKey) -> x509.Certificate:
    now = datetime.now(UTC)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Top Secret Local Test Root CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Seafile RAGFlow Connector TLS Lab"),
        ]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )


def _server_cert(
    dns_name: str,
    key: rsa.RSAPrivateKey,
    *,
    issuer_cert: x509.Certificate | None,
    issuer_key: rsa.RSAPrivateKey,
    not_before: datetime | None = None,
    not_after: datetime | None = None,
) -> x509.Certificate:
    now = datetime.now(UTC)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, dns_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Seafile RAGFlow Connector TLS Lab"),
        ]
    )
    issuer = issuer_cert.subject if issuer_cert is not None else subject
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(issuer_key, hashes.SHA256())
    )


def _write_pair(
    out_dir: Path,
    name: str,
    cert: x509.Certificate,
    key: rsa.RSAPrivateKey,
) -> None:
    _write_cert(out_dir / f"{name}.cert.pem", cert)
    _write_key(out_dir / f"{name}.key.pem", key)


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


if __name__ == "__main__":
    main()
