"""Generate a device-local certificate for LAN phone connections."""
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import socket


def ensure_certificate(base_dir, local_ip):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    folder = Path(base_dir) / 'config' / 'certs'
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / 'jarvis.crt', folder / 'jarvis.key'
    if cert_path.exists() and key_path.exists():
        try:
            existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
            existing_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            matches = existing.public_key().public_numbers() == existing_key.public_key().public_numbers()
            names = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            if matches and existing.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=1) and ipaddress.ip_address(local_ip) in names.get_values_for_type(x509.IPAddress):
                return
        except (ValueError, OSError, x509.ExtensionNotFound):
            import logging
            logging.getLogger(__name__).warning("Regenerating invalid local dashboard certificate")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'JARVIS Local Dashboard')])
    now = datetime.now(timezone.utc)
    names = [x509.DNSName('localhost'), x509.DNSName(socket.gethostname()),
             x509.IPAddress(ipaddress.ip_address(local_ip))]
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
