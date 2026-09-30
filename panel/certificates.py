from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat


def domain_conf(root, domain):
    suffix = "_ecc" if domain["key_type"] == "ec-256" else ""
    return root / "accounts" / domain["account_id"] / "certs" / domain["id"] / (domain["name"] + suffix) / (domain["name"] + ".conf")


def domain_issued(root, domain):
    conf = domain_conf(root, domain)
    return conf.is_file() and (conf.parent / (domain["name"] + ".cer")).is_file()


def managed_certificate(root, domain):
    # Retained files must not become a newly added configuration's certificate.
    if not domain_issued(root, domain):
        return {"available": False, "expires": None, "days_left": None, "sans": [], "issuer": None, "status": "pending"}
    info = certificate_info(root, domain["name"])
    if info["available"]:
        try:
            issued = x509.load_pem_x509_certificate((domain_conf(root, domain).parent / (domain["name"] + ".cer")).read_bytes())
            installed = x509.load_pem_x509_certificate((root / "ssl-renew" / domain["name"] / "fullchain.pem").read_bytes())
            if issued.fingerprint(hashes.SHA256()) != installed.fingerprint(hashes.SHA256()):
                return {**info, "available": False, "status": "invalid"}
        except (ValueError, OSError):
            return {**info, "available": False, "status": "invalid"}
    expected = {domain["name"]} | ({"*." + domain["name"]} if domain["wildcard"] else set())
    if info["available"] and not expected.issubset(set(info["sans"])):
        return {**info, "available": False, "status": "invalid"}
    return info


def certificate_info(root, domain):
    directory = root / "ssl-renew" / domain
    base = {"available": False, "expires": None, "days_left": None, "sans": [], "issuer": None, "status": "pending"}
    if directory.is_symlink():
        return {**base, "status": "invalid"}
    cert_path, key_path = directory / "fullchain.pem", directory / "privkey.pem"
    if not cert_path.exists() or not key_path.exists():
        return base
    if cert_path.is_symlink() or key_path.is_symlink():
        return {**base, "status": "invalid"}
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        key = load_pem_private_key(key_path.read_bytes(), password=None)
        public_bytes = lambda k: k.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if public_bytes(cert.public_key()) != public_bytes(key.public_key()):
            return {**base, "status": "invalid"}
        days = (cert.not_valid_after_utc - datetime.now(timezone.utc)).days
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        return {"available": True, "expires": cert.not_valid_after_utc.isoformat(), "days_left": days,
                "sans": sans, "issuer": cert.issuer.rfc4514_string(),
                "status": "expired" if days < 0 else "expiring" if days < 30 else "valid"}
    except (ValueError, TypeError, OSError, x509.ExtensionNotFound):
        return {**base, "status": "invalid"}

