"""Mini-PKI for localhost HTTPS — required by Claude Desktop 3P.

Claude Desktop rejects self-signed certificates.  We need a proper
Certificate Authority (CA) trusted by the OS so Electron accepts the
TLS connection.  This module generates a private CA, installs it in
the system trust store, and issues a localhost certificate signed by
that CA.
"""

from __future__ import annotations

import os
import platform
import ssl
import subprocess
import sys
from pathlib import Path


_CERT_DIR  = Path.home() / ".llm-relay" / "tls"
_CA_KEY    = _CERT_DIR / "ca-key.pem"
_CA_CERT   = _CERT_DIR / "ca-cert.pem"
_SRV_KEY   = _CERT_DIR / "key.pem"
_SRV_CERT  = _CERT_DIR / "cert.pem"
_CSR       = _CERT_DIR / "server.csr"
_SRL       = _CERT_DIR / "ca-cert.srl"

_CA_NAME   = "/CN=llm-relay CA"


# ── Public API ────────────────────────────────────────────────────────────────


def ensure_certificate() -> tuple[str, str]:
    """Return ``(cert_path, key_path)`` for the localhost server certificate.

    On first call:
      1.  Creates a private CA if one does not already exist.
      2.  Issues a localhost certificate signed by the CA.
      3.  Installs the CA in the system trust store (may prompt for password).

    Subsequent calls are instantaneous (files already exist).
    """
    _CERT_DIR.mkdir(parents=True, exist_ok=True)

    missing = any(
        not p.exists() for p in (_CA_KEY, _CA_CERT, _SRV_KEY, _SRV_CERT)
    )

    if missing:
        _generate_ca()
        _generate_server_cert()
        _install_ca()

    return str(_SRV_CERT), str(_SRV_KEY)


def install_ca_trust() -> None:
    """Re-install the CA certificate in the system trust store.

    Useful as a standalone command (``llm-relay trust-ca``) or when the
    user prompted for a password but dismissed it on first run.
    """
    _CERT_DIR.mkdir(parents=True, exist_ok=True)
    if not _CA_CERT.exists():
        _generate_ca()
    _install_ca()


def create_ssl_context() -> ssl.SSLContext:
    """Return an SSLContext configured with the localhost certificate."""
    cert_path, key_path = ensure_certificate()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


# ── Certificate generation ────────────────────────────────────────────────────


def _generate_ca() -> None:
    """Create a private Certificate Authority (key + self-signed cert)."""
    _run_openssl(
        "genrsa", "-out", str(_CA_KEY), "2048",
    )
    _run_openssl(
        "req", "-x509", "-new", "-nodes",
        "-key", str(_CA_KEY),
        "-sha256", "-days", "3650",
        "-subj", _CA_NAME,
        "-out", str(_CA_CERT),
    )


def _generate_server_cert() -> None:
    """Issue a localhost certificate signed by the private CA."""
    # Server key
    _run_openssl("genrsa", "-out", str(_SRV_KEY), "2048")

    # CSR
    _run_openssl(
        "req", "-new",
        "-key", str(_SRV_KEY),
        "-subj", "/CN=localhost",
        "-out", str(_CSR),
    )

    # Sign with CA (SAN extension for 127.0.0.1 and localhost)
    _run_openssl(
        "x509", "-req",
        "-in", str(_CSR),
        "-CA", str(_CA_CERT),
        "-CAkey", str(_CA_KEY),
        "-CAcreateserial",
        "-out", str(_SRV_CERT),
        "-days", "365",
        "-sha256",
        "-extfile", _san_ext_file(),
    )

    # Cleanup
    _CSR.unlink(missing_ok=True)


def _san_ext_file() -> str:
    """Write a temporary OpenSSL extension file with SAN + serverAuth."""
    path = _CERT_DIR / "san.ext"
    path.write_text(
        "subjectAltName=IP:127.0.0.1,DNS:localhost\n"
        "extendedKeyUsage=serverAuth\n"
    )
    return str(path)


# ── System trust store ────────────────────────────────────────────────────────


def _install_ca() -> None:
    """Add the CA certificate to the OS trust store."""
    system = platform.system()
    if system == "Darwin":
        _install_ca_macos()
    elif system == "Linux":
        _install_ca_linux()
    elif system == "Windows":
        _install_ca_windows()
    else:
        _warn_manual_install()


def _install_ca_macos() -> None:
    """Add the CA to the system trust store on macOS."""
    ca_path = str(_CA_CERT)

    subprocess.run(
        ["security", "delete-certificate", "-c", "llm-relay CA"],
        capture_output=True,
    )

    # Electron on macOS uses the System keychain, not login.
    # We request admin privileges via a native macOS dialog.
    print("  Adding CA to System keychain (a macOS dialog will appear)...")
    script = (
        f'do shell script "security add-trusted-cert -d -r trustRoot'
        f' -p ssl -k /Library/Keychains/System.keychain {ca_path}'  # noqa
        f' && echo OK"'
        f' with administrator privileges'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        # Do NOT capture output — the admin dialog needs GUI access.
        timeout=60,
    )
    if result.returncode == 0:
        _ok("CA certificate installed in System keychain")
        return

    # Fallback: try login keychain with GUI prompt
    result = subprocess.run(
        [
            "security", "add-trusted-cert",
            "-d", "-r", "trustRoot", "-p", "ssl",
            "-k", str(Path.home() / "Library" / "Keychains" / "login.keychain-db"),
            ca_path,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        _ok("CA certificate installed in login keychain")
        return

    _print_macos_manual_install(ca_path)


def _install_ca_linux() -> None:
    ca_path = str(_CA_CERT)
    dest = Path("/usr/local/share/ca-certificates/llm-relay-ca.crt")
    try:
        dest.write_bytes(_CA_CERT.read_bytes())
        subprocess.run(["update-ca-certificates"], check=True)
        _ok("CA certificate installed (system trust store)")
    except Exception:
        print(
            f"\n  \033[33m⚠\033[0m  Manual CA install required:\n"
            f"    sudo cp {ca_path} /usr/local/share/ca-certificates/llm-relay-ca.crt\n"
            f"    sudo update-ca-certificates\n",
            file=sys.stderr,
        )


def _install_ca_windows() -> None:
    ca_path = str(_CA_CERT)
    try:
        subprocess.run(
            ["certutil", "-addstore", "Root", ca_path],
            check=True,
            capture_output=True,
        )
        _ok("CA certificate installed (Windows trust store)")
    except Exception:
        print(
            f"\n  \033[33m⚠\033[0m  Run this in an Administrator terminal:\n"
            f"    certutil -addstore Root {ca_path}\n",
            file=sys.stderr,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_openssl(*args: str) -> None:
    """Run an openssl command, raising a clear error on failure."""
    try:
        subprocess.run(
            ["openssl", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"openssl failed: {exc.stderr.strip()}\n"
            f"  Command: openssl {' '.join(args)}"
        ) from exc
    except FileNotFoundError:
        raise RuntimeError(
            "openssl is not installed. Install it with:\n"
            "  brew install openssl    (macOS)\n"
            "  apt install openssl     (Linux)"
        )


def _warn_manual_install() -> None:
    ca_path = str(_CA_CERT)
    _print_macos_manual_install(ca_path)


def _print_macos_manual_install(ca_path: str) -> None:
    print(
        f"\n  \033[31m✗\033[0m  CA cert could not be auto-installed.\n"
        f"\n  Run this command once (it will ask for your macOS password):\n"
        f"\n    \033[1msudo security add-trusted-cert"
        f" -d -r trustRoot -p ssl"
        f" -k /Library/Keychains/System.keychain"
        f" \\\n        {ca_path}\033[0m\n"
        f"\n  Then restart Claude Desktop.\n",
        file=sys.stderr,
    )


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")
