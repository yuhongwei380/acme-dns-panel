from pathlib import Path

from fastapi.testclient import TestClient

from panel.acme import AcmeRunner
from panel.certificates import domain_conf
from panel.config import Config
from panel.web import SettingsInput, create_apps
import pytest


@pytest.mark.parametrize("url", ["http://host'evil:8001", "http://bad host:8001", "http://host:99999", "http://user:pass@host:8001", "http://host/path", "http://host/?x=1"])
def test_download_base_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        SettingsInput(email="user@example.com", public_url=url)


def test_rotation_clears_sourced_cloudflare_credentials(tmp_path):
    config = Config(tmp_path)
    admin, _ = create_apps(config)
    store = admin.state.store
    domain = {"id":"domain-id", "account_id":"account-id", "name":"example.com", "key_type":"ec-256", "dns_sleep":120}
    account_conf = tmp_path / "accounts/account-id/account.conf"
    account_conf.parent.mkdir()
    account_conf.write_text("SAVED_CF_Token='old-token'\nSAVED_CF_Zone_ID='old-zone'\nACCOUNT_EMAIL='user@example.com'\n")
    cert_conf = domain_conf(tmp_path, domain)
    cert_conf.parent.mkdir(parents=True)
    cert_conf.write_text("CF_Token='old-token'\nCF_Zone_ID='old-zone'\nLe_Domain='example.com'\n")
    from panel.providers import BY_ID
    AcmeRunner(config, store).clear_cached_credentials(domain, BY_ID["cf"])
    assert account_conf.read_text() == "ACCOUNT_EMAIL='user@example.com'\n"
    assert "Le_Domain='example.com'" in cert_conf.read_text()
    assert "Le_DNSSleep='120'" in cert_conf.read_text()
    assert "old-token" not in cert_conf.read_text() and "old-zone" not in cert_conf.read_text()


def test_credentials_cannot_break_acme_shell_configuration(tmp_path):
    admin, _ = create_apps(Config(tmp_path))
    client = TestClient(admin)
    login = client.post("/api/login", json={"password":"admin"}, headers={"X-Panel-Request":"1"})
    headers = {"X-Panel-Request":"1", "X-CSRF-Token":login.json()["csrf"]}
    response = client.post("/api/accounts", headers=headers, json={"name":"test", "provider":"cf", "credentials":{"CF_Token":"broken'quote"}})
    assert response.status_code == 400
