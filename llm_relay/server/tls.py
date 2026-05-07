"""Self-signed TLS certificate generation for localhost.

Used when Claude Desktop 3P requires an ``https://`` gateway URL
but the proxy only listens on localhost.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from pathlib import Path


_CERT_DIR = Path.home() / ".llm-relay" / "tls"
_CERT_FILE = _CERT_DIR / "cert.pem"
_KEY_FILE  = _CERT_DIR / "key.pem"


def ensure_certificate() -> tuple[str, str]:
    """Return ``(cert_path, key_path)``, generating a self-signed pair if needed.

    The certificate is valid for **127.0.0.1** and **localhost** so both
    the IP and the hostname are accepted by Claude Desktop.
    """
    _CERT_DIR.mkdir(parents=True, exist_ok=True)

    if _CERT_FILE.exists() and _KEY_FILE.exists():
        return str(_CERT_FILE), str(_KEY_FILE)

    # Generate via openssl (available on macOS / most Linux distros).
    # Fall back to a pure-Python approach if openssl is not found.
    try:
        _generate_with_openssl()
    except Exception:
        _generate_with_cryptography()

    return str(_CERT_FILE), str(_KEY_FILE)


def create_ssl_context() -> ssl.SSLContext:
    """Return an SSLContext configured with the self-signed certificate."""
    cert_path, key_path = ensure_certificate()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


# ── OpenSSL path ──────────────────────────────────────────────────────────────


def _generate_with_openssl() -> None:
    import subprocess

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(_KEY_FILE),
            "-out", str(_CERT_FILE),
            "-days", "365", "-nodes",
            "-subj", "/CN=localhost",
            "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )


# ── Pure-Python fallback ─────────────────────────────────────────────────────


def _generate_with_cryptography() -> None:
    """Generate a self-signed cert using the ``cryptography`` library if available."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        _generate_minimal_cert()
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(x509.datetime.utcnow())
        .not_valid_after(x509.datetime.utcnow() + x509.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress("127.0.0.1"),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    _KEY_FILE.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    _CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _generate_minimal_cert() -> None:
    """Absolute fallback — writes a placeholder that clearly won't work, but at least the server starts."""
    _KEY_FILE.write_text("PLACEHOLDER — install openssl or cryptography")
    _CERT_FILE.write_text("PLACEHOLDER — install openssl or cryptography")
