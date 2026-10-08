import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from panel.acme import AcmeRunner, JobManager, redact
from panel.certificates import certificate_info, domain_conf
from panel.config import Config
from panel.store import Store, check_password, now
from panel.web import create_apps, normalize_domain


def make_certificate(root, name="example.com"):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name), x509.DNSName("*." + name)]), False)
            .sign(key, hashes.SHA256()))
    directory = root / "ssl-renew" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "privkey.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def mark_issued(store, root, name="example.com"):
    domain = store.one("SELECT * FROM domains WHERE name=?", (name,))
    conf = domain_conf(root, domain)
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("Le_Domain='" + name + "'\n", encoding="utf-8")
    installed = root / "ssl-renew" / name / "fullchain.pem"
    (conf.parent / (name + ".cer")).write_bytes(installed.read_bytes() if installed.exists() else b"issued fixture")


@pytest.fixture
def apps(tmp_path):
    admin, public = create_apps(Config(tmp_path))
    return TestClient(admin), TestClient(public), admin.state.store, tmp_path


def authenticate(client, password="admin"):
    response = client.post("/api/login", json={"password": password}, headers={"X-Panel-Request": "1"})
    assert response.status_code == 200
    client.headers.update({"X-Panel-Request": "1", "X-CSRF-Token": response.json()["csrf"]})


def account_and_domain(client, wildcard=True):
    assert client.put("/api/settings", json={"email": "user@example.com"}).status_code == 200
    account = client.post("/api/accounts", json={"name": "Cloudflare Production", "provider": "cf", "credentials": {"CF_Token": "super-private-token"}})
    assert account.status_code == 200, account.text
    domain = client.post("/api/domains", json={"name": "Example.COM", "account_id": account.json()["id"], "wildcard": wildcard})
    assert domain.status_code == 200, domain.text
    return account.json()["id"], domain.json()["id"]


def test_auth_password_and_csrf(apps):
    admin, public, store, root = apps
    assert admin.get("/api/accounts").status_code == 401
    assert admin.post("/api/login", json={"password": "admin"}).status_code == 403
    assert admin.post("/api/login", json={"password": "wrong"}, headers={"X-Panel-Request": "1"}).status_code == 401
    authenticate(admin)
    assert admin.get("/api/session").json()["username"] == "admin"
    assert "admin" not in store.setting("password")
    assert check_password("admin", store.setting("password"))
    assert admin.put("/api/settings", json={"email": "user@example.com"}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert admin.post("/api/password", json={"current_password": "wrong", "new_password": "updated"}).status_code == 400
    assert admin.post("/api/password", json={"current_password": "admin", "new_password": "updated"}).status_code == 200
    assert admin.get("/api/session").status_code == 401
    authenticate(admin, "updated")
    assert admin.post("/api/logout").status_code == 200
    assert admin.get("/api/session").status_code == 401


def test_login_rate_limit(apps):
    client = apps[0]
    for _ in range(10):
        assert client.post("/api/login", json={"password": "bad"}, headers={"X-Panel-Request": "1"}).status_code == 401
    assert client.post("/api/login", json={"password": "admin"}, headers={"X-Panel-Request": "1"}).status_code == 429


@pytest.mark.parametrize("resource", ["domains", "accounts"])
def test_removal_requires_password_and_preserves_data_on_failure(apps, resource):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    if resource == "accounts":
        response = admin.post("/api/accounts", json={"name": "Unused", "provider": "cf", "credentials": {"CF_Token": "unused-token"}})
        target_id = response.json()["id"]
        credential_file = root / "accounts" / target_id / "credentials.json"
    else:
        target_id = domain_id
        make_certificate(root)
        mark_issued(store, root)
    endpoint = "/api/" + resource + "/" + target_id
    assert admin.delete(endpoint).status_code == 422
    assert admin.request("DELETE", endpoint, json={"password": ""}).status_code == 422
    response = admin.request("DELETE", endpoint, json={"password": "wrong-password"})
    assert response.status_code == 403 and "wrong-password" not in response.text
    assert admin.get("/api/session").status_code == 200
    assert store.one("SELECT id FROM " + resource + " WHERE id=?", (target_id,))
    if resource == "accounts":
        assert credential_file.exists()
    else:
        assert public.get("/example.com/fullchain.pem").status_code == 200
    assert admin.request("DELETE", endpoint, json={"password": "admin"}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert admin.request("DELETE", endpoint, json={"password": "admin"}).status_code == 200
    assert not store.one("SELECT id FROM " + resource + " WHERE id=?", (target_id,))
    if resource == "accounts":
        assert not credential_file.exists()
    else:
        assert public.get("/example.com/fullchain.pem").status_code == 404
        assert (root / "ssl-renew/example.com/fullchain.pem").exists()


def test_removal_password_attempts_are_limited_across_resources(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    for attempt in range(10):
        endpoint = "/api/domains/" + domain_id if attempt % 2 else "/api/accounts/" + account_id
        assert admin.request("DELETE", endpoint, json={"password": "wrong"}).status_code == 403
    assert admin.request("DELETE", "/api/domains/" + domain_id, json={"password": "admin"}).status_code == 429
    assert store.one("SELECT id FROM domains WHERE id=?", (domain_id,))


def test_removal_checks_current_password_after_password_change(apps):
    admin, public, store, root = apps
    authenticate(admin)
    _, domain_id = account_and_domain(admin)
    assert admin.post("/api/password", json={"current_password": "admin", "new_password": "new-password"}).status_code == 200
    authenticate(admin, "new-password")
    endpoint = "/api/domains/" + domain_id
    assert admin.request("DELETE", endpoint, json={"password": "admin"}).status_code == 403
    assert admin.request("DELETE", endpoint, json={"password": "new-password"}).status_code == 200


def test_credentials_isolation_update_and_in_use(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    second = admin.post("/api/accounts", json={"name": "Second", "provider": "cf", "credentials": {"CF_Token": "another-token"}}).json()["id"]
    assert store.credentials(second)["CF_Token"] == "another-token"
    listing = admin.get("/api/accounts")
    assert "super-private-token" not in listing.text and "another-token" not in listing.text
    assert admin.put("/api/accounts/" + account_id, json={"name": "Changed", "provider": "cf", "credentials": {}}).status_code == 200
    assert store.credentials(account_id)["CF_Token"] == "super-private-token"
    assert admin.put("/api/accounts/" + account_id, json={"name": "Changed", "provider": "cf", "credentials": {"CF_Token": "replacement"}}).status_code == 200
    assert store.credentials(account_id)["CF_Token"] == "replacement"
    assert admin.request("DELETE", "/api/accounts/" + account_id, json={"password": "admin"}).status_code == 409
    assert admin.post("/api/accounts", json={"name": "bad", "provider": "ali", "credentials": {"PATH": "/evil"}}).status_code == 400
    assert admin.post("/api/accounts", json={"name": "bad", "provider": "ali", "credentials": {"Ali_Key": "missing-secret"}}).status_code == 400


@pytest.mark.parametrize("value", ["../etc", "*.example.com", "--help", "https://example.com", "127.0.0.1", "example.com:80", "a..com", "-bad.com"])
def test_reject_unsafe_domains(value):
    with pytest.raises(ValueError):
        normalize_domain(value)


def test_domain_settings_and_validation(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    assert admin.get("/api/domains").json()[0]["name"] == "example.com"
    assert normalize_domain("例子.中国") == "xn--fsqu00a.xn--fiqs8s"
    assert admin.post("/api/domains", json={"name": "example.com", "account_id": account_id}).status_code == 409
    assert admin.put("/api/domains/" + domain_id, json={"name": "example.com", "account_id": account_id, "dns_sleep": 120, "auto_renew": False}).status_code == 200
    assert admin.put("/api/domains/" + domain_id, json={"name": "example.com", "account_id": account_id, "wildcard": False}).status_code == 400
    assert admin.put("/api/settings", json={"email": "bad"}).status_code == 422
    assert admin.put("/api/settings", json={"email": "user@example.com"}).status_code == 200
    assert admin.post("/api/domains/" + domain_id + "/jobs", json={"action": "issue"}).status_code == 400


@pytest.mark.parametrize("email", [None, "", "   "])
def test_add_domain_requires_saved_acme_email(apps, email):
    admin, public, store, root = apps
    authenticate(admin)
    account = admin.post("/api/accounts", json={"name": "Cloudflare", "provider": "cf", "credentials": {"CF_Token": "test-token"}})
    assert account.status_code == 200
    if email is not None:
        store.set_setting("email", email)
    payload = {"name": "example.com", "account_id": account.json()["id"]}
    response = admin.post("/api/domains", json=payload)
    assert response.status_code == 400
    assert "ACME 联系邮箱" in response.json()["detail"]
    assert "服务设置" in response.json()["detail"]
    assert not store.rows("SELECT * FROM domains")
    assert not store.rows("SELECT * FROM jobs")
    assert admin.put("/api/settings", json={"email": "user@example.com"}).status_code == 200
    assert admin.post("/api/domains", json=payload).status_code == 200
    assert not store.rows("SELECT * FROM jobs")


def test_domain_requires_existing_complete_dns_account(apps):
    admin, public, store, root = apps
    authenticate(admin)
    assert admin.put("/api/settings", json={"email": "user@example.com"}).status_code == 200
    response = admin.post("/api/domains", json={"name":"example.com", "account_id":"missing-account"})
    assert response.status_code == 400
    assert "未检测到" in response.json()["detail"]
    assert store.rows("SELECT * FROM domains") == []
    assert store.rows("SELECT * FROM accounts") == []
    account = admin.post("/api/accounts", json={"name":"test", "provider":"cf", "credentials":{"CF_Token":"test-token"}}).json()["id"]
    credentials_file = root / "accounts" / account / "credentials.json"
    credentials_file.unlink()
    response = admin.post("/api/domains", json={"name":"example.com", "account_id":account})
    assert response.status_code == 400
    assert "凭据缺失" in response.json()["detail"]
    store.save_credentials(account,{"CF_Token":""})
    assert admin.post("/api/domains", json={"name":"example.com", "account_id":account}).status_code == 400
    assert store.rows("SELECT * FROM domains") == []
    store.save_credentials(account,{"CF_Token":"test-token"})
    assert admin.post("/api/domains", json={"name":"example.com", "account_id":account}).status_code == 200
    assert store.rows("SELECT * FROM jobs") == []


def test_public_only_exposes_certificates_and_revokes_deleted_domain(apps):
    admin, public, store, root = apps
    authenticate(admin)
    _, domain_id = account_and_domain(admin)
    assert public.get("/api/certificates").status_code == 200
    assert public.get("/example.com/privkey.pem").status_code == 404
    make_certificate(root)
    mark_issued(store, root)
    listing = public.get("/api/certificates")
    assert "super-private-token" not in listing.text
    assert "account_id" not in listing.text
    assert listing.json()["domains"][0]["certificate"]["available"]
    for file in ("fullchain.pem", "privkey.pem"):
        response = public.get("/example.com/" + file)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    assert public.get("/api/settings").status_code == 404
    assert public.get("/example.com/account.conf").status_code == 404
    assert public.get("/accounts/credentials.json").status_code == 404
    assert public.get("/%2e%2e/data/panel.db").status_code == 404
    assert public.get("/assets/public.js").status_code == 200
    assert admin.request("DELETE", "/api/domains/" + domain_id, json={"password": "admin"}).status_code == 200
    assert public.get("/example.com/privkey.pem").status_code == 404
    assert (root / "ssl-renew/example.com/privkey.pem").exists()
    # Re-adding the same name does not expose old files or reuse the removed order.
    account_id = store.one("SELECT id FROM accounts")["id"]
    assert admin.post("/api/domains", json={"name":"example.com", "account_id":account_id}).status_code == 200
    assert public.get("/example.com/privkey.pem").status_code == 404
    assert admin.get("/api/domains").json()[0]["issued"] is False


def test_certificate_rejects_mismatched_private_key(apps):
    root = apps[3]
    make_certificate(root)
    assert certificate_info(root, "example.com")["status"] == "valid"
    wrong = ec.generate_private_key(ec.SECP256R1())
    (root / "ssl-renew/example.com/privkey.pem").write_bytes(wrong.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    assert certificate_info(root, "example.com")["status"] == "invalid"


def test_jobs_queue_and_daily_scheduling(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    manager = JobManager(Config(root), store)
    domain = store.one("SELECT * FROM domains WHERE id=?", (domain_id,))
    job_id = manager.enqueue(domain, "issue")
    with pytest.raises(ValueError):
        manager.enqueue(domain, "renew")
    assert admin.request("DELETE", "/api/domains/" + domain_id, json={"password": "admin"}).status_code == 409
    assert admin.put("/api/accounts/" + account_id, json={"name": "Changed", "provider": "cf", "credentials": {}}).status_code == 409
    store.execute("UPDATE jobs SET status='success' WHERE id=?", (job_id,))
    manager.schedule_due()
    assert len(store.rows("SELECT * FROM jobs")) == 1  # Never auto issue an unissued domain.
    unfinished = domain_conf(root, domain)
    unfinished.parent.mkdir(parents=True)
    unfinished.write_text("Le_Domain='example.com'\n")
    manager.schedule_due()
    assert len(store.rows("SELECT * FROM jobs")) == 1  # A failed first order's config is not an issued cert.
    mark_issued(store, root)
    manager.schedule_due()
    manager.schedule_due()
    assert len(store.rows("SELECT * FROM jobs")) == 2
    assert store.one("SELECT * FROM domains WHERE id=?", (domain_id,))["last_checked"]
    store.execute("UPDATE jobs SET status='running' WHERE status='queued'")
    restarted = Store(root)
    assert restarted.one("SELECT * FROM jobs WHERE action='renew'")["status"] == "interrupted"


@pytest.mark.parametrize("server", ["letsencrypt", "zerossl", "buypass", "https://ca.example.com/acme/directory"])
def test_acme_issue_install_and_renew_arguments(apps, server):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    store.execute("UPDATE domains SET server=? WHERE id=?", (server, domain_id))
    store.set_setting("email", "user@example.com")
    (root / "acme/acme.sh").write_text("mock")
    calls = []

    class RecordingRunner(AcmeRunner):
        async def process(self, args, credentials, job_id):
            calls.append((args, credentials))
            if "--issue" in args:
                make_certificate(root)
                mark_issued(store, root)
            if "--install-cert" in args:
                assert (root / "ssl-renew/example.com/fullchain.pem").exists()
            return 2 if "--renew" in args else 0

    runner = RecordingRunner(Config(root), store)
    manager = JobManager(Config(root), store, runner)
    domain = store.one("SELECT * FROM domains WHERE id=?", (domain_id,))
    job_id = manager.enqueue(domain, "issue")
    asyncio.run(runner.run(store.one("SELECT * FROM jobs WHERE id=?", (job_id,))))
    issue = next(args for args, _ in calls if "--issue" in args)
    assert "*.example.com" in issue and "--force" not in issue
    assert issue[issue.index("--dns") + 1] == "dns_cf"
    assert issue[issue.index("--server") + 1] == server
    register = calls[0][0]
    assert register[register.index("--server") + 1] == server
    assert str(root / "accounts" / account_id) in issue
    assert str(root / "accounts" / account_id / "certs" / domain_id) in issue
    install = next(args for args, _ in calls if "--install-cert" in args)
    assert "--ecc" in install and str(root / "ssl-renew/example.com/privkey.pem") in install
    assert calls[0][1] == {"CF_Token": "super-private-token"}
    store.execute("UPDATE jobs SET action='renew' WHERE id=?", (job_id,))
    asyncio.run(runner.run(store.one("SELECT * FROM jobs WHERE id=?", (job_id,))))
    renew = next(args for args, _ in calls if "--renew" in args)
    assert "--ecc" in renew and "--force" not in renew
    assert renew[renew.index("--server") + 1] == server


@pytest.mark.parametrize("server", ["letsencrypt", "zerossl", "buypass", "https://ca.example.com/acme/directory"])
def test_authority_is_saved_and_preserved_on_settings_edit(apps, server):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, _ = account_and_domain(admin)
    payload = {"name": "second.example.com", "account_id": account_id, "server": server}
    response = admin.post("/api/domains", json=payload)
    assert response.status_code == 200, response.text
    domain_id = response.json()["id"]
    assert store.one("SELECT server FROM domains WHERE id=?", (domain_id,))["server"] == server
    assert admin.put("/api/domains/" + domain_id, json={**payload, "dns_sleep": 120}).status_code == 200


@pytest.mark.parametrize("server", ["other", "--help", "http://ca.example.com/directory",
    "https://ca.example.com", "https://user:pass@ca.example.com/directory",
    "https://ca.example.com/directory#fragment", "https://ca.example.com:bad/directory",
    "https://ca.example.com/dir'ectory", "https://ca.example.com/dir\nectory"])
def test_invalid_custom_authority_rejected(server):
    from panel.web import DomainInput
    with pytest.raises(ValueError):
        DomainInput(name="example.com", account_id="a", server=server)


def test_legacy_staging_is_preserved_but_not_offered_for_new_domains(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    payload = {"name": "example.com", "account_id": account_id, "server": "letsencrypt_test"}
    assert admin.post("/api/domains", json={**payload, "name": "second.example.com"}).status_code == 400
    store.execute("UPDATE domains SET server='letsencrypt_test' WHERE id=?", (domain_id,))
    assert admin.put("/api/domains/" + domain_id, json={**payload, "dns_sleep": 120}).status_code == 200
    assert public.get("/api/certificates").json()["domains"][0]["staging"] is True
    staging_url = "https://acme-staging-v02.api.letsencrypt.org/directory"
    assert admin.post("/api/domains", json={**payload, "name": "second.example.com", "server": staging_url}).status_code == 200
    assert all(d["staging"] for d in public.get("/api/certificates").json()["domains"])


def test_subprocess_redacts_and_times_out(apps):
    store, root = apps[2:]
    job_id = "process-test"
    store.execute("INSERT INTO jobs(id,domain_id,domain_name,action,status,created) VALUES (?,?,?,?,?,?)", (job_id,"d","example.com","issue","running",now()))
    runner = AcmeRunner(Config(root, task_timeout=1), store)
    code = asyncio.run(runner.process([sys.executable,"-c","import os; print(os.environ['CF_Token'])"], {"CF_Token":"redact-this-token"}, job_id))
    assert code == 0
    assert "redact-this-token" not in store.one("SELECT log FROM jobs WHERE id=?", (job_id,))["log"]
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(runner.process([sys.executable,"-c","import time; time.sleep(15)"], {}, job_id))
    assert "secret-value" not in redact("token=secret-value", {"CF_Token":"secret-value"})


def test_pages_and_cookie_security(apps):
    admin, public, store, root = apps
    assert "login-password" in admin.get("/").text
    assert "data-eye" in admin.get("/").text
    assert "只读" in public.get("/").text
    assert public.get("/assets/style.css").status_code == 200
    response = admin.post("/api/login", json={"password":"admin"}, headers={"X-Panel-Request":"1"})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_client_script_admin_edit_and_public_download(apps):
    admin, public, store, root = apps
    assert admin.get("/api/client-script").status_code == 401
    assert admin.put("/api/client-script", json={"content": "#!/bin/bash"}, headers={"X-Panel-Request": "1"}).status_code == 401
    assert public.get("/ssl-renew.sh").status_code == 400
    assert public.get("/api/certificates").json()["script"]["available"] is False
    authenticate(admin)
    account_and_domain(admin)
    make_certificate(root)
    mark_issued(store, root)
    assert admin.get("/api/client-script").json() == {"filename": "ssl-renew.sh", "content": "", "adaptable": False}
    content = '#!/bin/bash\r\n# 证书替换\r\nDOMAIN="{{DOMAIN}}"\r\nFULLCHAIN_URL="{{FULLCHAIN_URL}}"\r\nPRIVKEY_URL="{{PRIVKEY_URL}}"\r\n'
    payload = {"content": content}
    assert admin.put("/api/client-script", json=payload, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert admin.put("/api/client-script", json=payload).status_code == 200
    expected = content.replace("\r\n", "\n")
    assert admin.get("/api/client-script").json()["content"] == expected
    response = public.get("/example.com/ssl-renew.sh")
    assert response.status_code == 200
    rendered = '#!/bin/bash\n# 证书替换\nDOMAIN="example.com"\nFULLCHAIN_URL="http://testserver/example.com/fullchain.pem"\nPRIVKEY_URL="http://testserver/example.com/privkey.pem"\n'
    assert response.content == rendered.encode("utf-8")
    assert public.get("/ssl-renew.sh?domain=example.com").content == response.content
    assert response.headers["content-disposition"] == 'attachment; filename="ssl-renew.sh"'
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert public.get("/api/certificates").json()["script"] == {"filename": "ssl-renew.sh", "available": True, "adaptable": True}
    assert expected not in public.get("/api/certificates").text
    _, restarted_public = create_apps(Config(root))
    assert restarted_public.state.store.setting("client_script") == expected
    assert TestClient(restarted_public).get("/example.com/ssl-renew.sh").content == response.content
    assert public.put("/api/client-script", json=payload, headers={"X-Panel-Request": "1"}).status_code == 405
    assert public.get("/ssl-renew.py").status_code == 404
    assert admin.put("/api/client-script", json={"content": ""}).status_code == 200
    assert public.get("/example.com/ssl-renew.sh").status_code == 404
    assert public.get("/api/certificates").json()["script"]["available"] is False


@pytest.mark.parametrize("content", ["echo hi\x00", "x" * 262145, "中" * 90000],
                         ids=["nul", "ascii_too_large", "utf8_too_large"])
def test_client_script_rejects_invalid_content_without_overwriting(apps, content):
    admin, public, store, root = apps
    authenticate(admin)
    assert admin.put("/api/client-script", json={"content": "#!/bin/bash\necho ok\n"}).status_code == 200
    assert admin.put("/api/client-script", json={"content": content}).status_code == 422
    assert store.setting("client_script") == "#!/bin/bash\necho ok\n"


def test_client_script_matches_each_certificate_and_download_origin(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_id, domain_id = account_and_domain(admin)
    second = admin.post("/api/domains", json={"name": "second.example.org", "account_id": account_id})
    assert second.status_code == 200
    for name in ("example.com", "second.example.org"):
        make_certificate(root, name)
        mark_issued(store, root, name)
    template = 'DOMAIN="example.com"\nFULLCHAIN_URL="old"\nPRIVKEY_URL="old"\nCERT_DIR="/ssl/example.com"\n'
    assert admin.put("/api/client-script", json={"content": template}).status_code == 200
    for name in ("example.com", "second.example.org"):
        response = public.get("/" + name + "/ssl-renew.sh", headers={"Host": "192.168.8.24:8081"})
        assert response.status_code == 200
        assert 'DOMAIN="' + name + '"' in response.text
        assert 'http://192.168.8.24:8081/' + name + '/fullchain.pem' in response.text
        assert 'CERT_DIR="/ssl/' + name + '"' in response.text
        changed_port = public.get("/" + name + "/ssl-renew.sh", headers={"Host": "certs.local:9001"})
        assert 'http://certs.local:9001/' + name + '/privkey.pem' in changed_port.text
    assert store.setting("client_script") == template
    assert public.get("/missing.example.org/ssl-renew.sh").status_code == 404
    assert public.get("/example.com/ssl-renew.sh", headers={"Host": "bad'host:8001"}).status_code == 400
    assert admin.put("/api/client-script", json={"content": "echo hello"}).status_code == 200
    assert public.get("/example.com/ssl-renew.sh").status_code == 409


def test_worker_enforces_total_job_deadline(apps):
    admin, public, store, root = apps
    authenticate(admin)
    _, domain_id = account_and_domain(admin)
    config = Config(root, task_timeout=0.05)

    class SlowRunner(AcmeRunner):
        async def run(self, job):
            await asyncio.sleep(10)

    manager = JobManager(config, store, SlowRunner(config, store))
    domain = store.one("SELECT * FROM domains WHERE id=?", (domain_id,))
    job_id = manager.enqueue(domain, "issue")

    async def check():
        manager.start()
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                job = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
                if job["status"] == "failed":
                    assert "任务超时" in job["log"]
                    return
            pytest.fail("Worker did not finish timed-out job")
        finally:
            await manager.stop()

    asyncio.run(check())
