import os
import shutil
import subprocess
import logging
from pathlib import Path

import pytest

from panel.deployment import (DEFAULT_NGINX_TEMPLATE, commands, covers_domain,
                              deployment_script, validate_template, public_path)
from test_panel import apps, authenticate, account_and_domain, make_certificate, mark_issued


@pytest.mark.parametrize("service,expected", [
    ("example.com", True), ("app.example.com", True),
    ("a.b.example.com", False), ("otherexample.com", False),
])
def test_actual_san_coverage(service, expected):
    assert covers_domain(["example.com", "*.example.com"], service) is expected


def test_template_validation():
    assert validate_template(DEFAULT_NGINX_TEMPLATE.replace("\n", "\r\n")) == DEFAULT_NGINX_TEMPLATE
    for content in ("server {}", DEFAULT_NGINX_TEMPLATE + "{{UNKNOWN}}", DEFAULT_NGINX_TEMPLATE + "\x00"):
        with pytest.raises(ValueError):
            validate_template(content)


def test_deployment_download_is_scoped(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_and_domain(admin)
    make_certificate(root)
    mark_issued(store, root)
    original = Path("ssl-renew.sh").read_text(encoding="utf-8")
    store.set_setting("client_script", original)
    plain = public.get("/example.com/ssl-renew.sh").text
    quick = public.get("/example.com/ssl-renew.sh?deployment=1").text
    assert '/home/vesoft/ssl/logs' in plain
    assert 'LOG_DIR="${HOME}/ssl/logs"' in quick
    assert 'CERT_DIR="${HOME}/ssl/${DOMAIN}"' in quick
    assert 'ACME_SKIP_NGINX_RELOAD' in quick
    assert 'sudo -n /usr/sbin/nginx -t' in quick
    assert store.setting("client_script") == original


def test_template_auth_and_generation_validation(apps):
    admin, public, store, root = apps
    assert admin.get("/api/nginx-template").status_code == 401
    authenticate(admin)
    account_and_domain(admin)
    make_certificate(root)
    mark_issued(store, root)
    store.set_setting("client_script", Path("ssl-renew.sh").read_text(encoding="utf-8"))
    assert admin.get("/api/nginx-template").json()["content"] == DEFAULT_NGINX_TEMPLATE
    assert admin.put("/api/nginx-template", json={"content": "server {}"}).status_code == 422
    template = DEFAULT_NGINX_TEMPLATE + "# imported template\n"
    assert admin.put("/api/nginx-template", json={"content": template}).status_code == 200
    public.headers.update({"X-Panel-Request": "1"})
    payload = {"certificate_domain": "example.com", "service_domain": "App.Example.Com", "proxy_port": 8088}
    response = public.post("/api/quick-deploy", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert 'http://testserver/example.com/ssl-renew.sh?deployment=1' in data["certificate_command"]
    assert '/etc/nginx/conf.d/app.example.com.conf' in data["nginx_command"]
    assert 'proxy_pass http://127.0.0.1:8088;' in data["nginx_command"]
    assert '# imported template' in data["nginx_command"]
    assert '$host$request_uri' in data["nginx_command"]
    for value in ('a.b.example.com', 'example.com; touch /tmp/pwn', 'other.org'):
        assert public.post("/api/quick-deploy", json={**payload, "service_domain": value}).status_code == 422
    for port in (0, 65536, True, "8000"):
        assert public.post("/api/quick-deploy", json={**payload, "proxy_port": port}).status_code == 422
    assert public.post("/api/quick-deploy", json={**payload, "certificate_domain": "missing.org"}).status_code == 404
    store.set_setting("client_script", 'DOMAIN="example.com"\nFULLCHAIN_URL="x"\nPRIVKEY_URL="y"')
    assert public.post("/api/quick-deploy", json=payload).status_code == 409


def bash_executable():
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    executable = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is not installed")
    return executable


def shell_path(path):
    path = path.resolve().as_posix()
    if os.name == "nt":
        return subprocess.check_output([bash_executable(), "-c", '/usr/bin/cygpath -u "$1"', "bash", path],
                                       text=True, encoding="utf-8").strip()
    return path


def run_commands(command, tmp_path, mocks):
    # Only mocked tools run: no network, system cron, sudo, or system nginx writes.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, content in mocks.items():
        target = bin_dir / name
        with target.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write("#!/bin/bash\n" + content)
        target.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    prelude = "export PATH=/usr/bin:/bin\nexport HOME='" + shell_path(home) + "'\n"
    # The real generated command sets a deterministic system PATH. Inject mocks after it.
    command = command.replace("export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                              "export PATH='" + shell_path(bin_dir) + "':/usr/bin:/bin")
    return subprocess.run([bash_executable()], input=prelude + command, text=True, encoding="utf-8",
                          capture_output=True, timeout=30)


def test_certificate_command_preserves_cron_and_deduplicates(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "cron").write_text("12 4 * * * existing-job\n0 3 * * * old-path # acme-dns-panel:example.com\n0 3 * * * other-cert # acme-dns-panel:other.org\n")
    mocks = {
        "wget": '''cat >"$2" <<'RENEW'
#!/bin/bash
mkdir -p "$HOME/ssl/example.com"
printf cert >"$HOME/ssl/example.com/fullchain.pem"
printf key >"$HOME/ssl/example.com/privkey.pem"
test "$ACME_SKIP_NGINX_RELOAD" = 1
RENEW
''',
        "crontab": 'if [ "$1" = -l ]; then cat "$HOME/cron"; else cp "$1" "$HOME/cron"; fi\n',
        "flock": 'exit 0\n',
    }
    command = commands("example.com", "app.example.com", 8000, "http://certs:8001", DEFAULT_NGINX_TEMPLATE)["certificate_command"]
    for _ in range(2):
        result = run_commands(command, tmp_path, mocks)
        assert result.returncode == 0, result.stderr
    cron = (home / "cron").read_text()
    assert "existing-job" in cron and "other-cert" in cron
    assert cron.count("# acme-dns-panel:example.com") == 1
    assert "old-path" not in cron
    assert shell_path(home) + '/ssl/example.com/ssl-renew.sh' in cron


@pytest.mark.parametrize("failure", ["none", "test", "reload"])
def test_nginx_command_preserves_variables_and_rolls_back(tmp_path, failure):
    home = tmp_path / "home"
    certs = home / "ssl/example.com"
    certs.mkdir(parents=True)
    (certs / "fullchain.pem").write_text("cert")
    (certs / "privkey.pem").write_text("key")
    nginx_root = tmp_path / "nginx"
    conf_dir = nginx_root / "conf.d"
    conf_dir.mkdir(parents=True)
    conf_file = conf_dir / "app.example.com.conf"
    conf_file.write_text("# original configuration\n")
    root_path = shell_path(nginx_root)
    command = commands("example.com", "app.example.com", 8080, "http://certs:8001", DEFAULT_NGINX_TEMPLATE)["nginx_command"]
    command = command.replace("/etc/nginx", root_path)
    # grep pattern has escaped dots in conf.d and a fixed include path; root has no regex metacharacters in fixtures.
    mocks = {
        "sudo": '"$@"\n',
        "nginx": '''case "$1" in
-T) printf '    include %s/conf.d/*.conf;\\n' 'ROOT' ;;
-t) if [ 'FAILURE' = test ] && grep -q 'proxy_pass' 'ROOT/conf.d/app.example.com.conf'; then exit 1; fi ;;
-s) if [ 'FAILURE' = reload ] && grep -q 'proxy_pass' 'ROOT/conf.d/app.example.com.conf'; then exit 1; fi
    echo reload >>"$HOME/reloads" ;;
esac
'''.replace("ROOT", root_path).replace("FAILURE", failure),
    }
    result = run_commands(command, tmp_path, mocks)
    assert result.returncode == (0 if failure == "none" else 1), result.stderr
    rendered = conf_file.read_text()
    if failure == "none":
        assert shell_path(certs) + "/fullchain.pem" in rendered
        assert "{{CERT_DIR}}" not in rendered
        assert '$host$request_uri' in rendered and '$proxy_add_x_forwarded_for' in rendered
        assert "proxy_pass http://127.0.0.1:8080;" in rendered
    else:
        assert rendered == "# original configuration\n"
    assert len(list(conf_dir.glob("*.bak.*"))) == 1
    assert (home / "reloads").exists() is (failure != "test")


def test_shipped_renewal_script_and_generated_commands_parse(tmp_path):
    template = Path("ssl-renew.sh").read_text(encoding="utf-8")
    script = deployment_script(template, "example.com", "https://certs.example.org:8001")
    generated = commands("example.com", "app.example.com", 8000, "https://certs.example.org:8001", DEFAULT_NGINX_TEMPLATE)
    for content in (script, *generated.values()):
        result = subprocess.run([bash_executable(), "-n"], input=content, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("prefix", ["https://other.org/", "//other.org/", "/../", "/download/../", "/download/$x/", "/download/%2f/"])
def test_public_prefix_rejects_unsafe_paths(prefix):
    with pytest.raises(ValueError):
        public_path(prefix)


def test_prefix_survives_reverse_proxy_stripping(apps):
    admin, public, store, root = apps
    authenticate(admin)
    account_and_domain(admin)
    make_certificate(root)
    mark_issued(store, root)
    store.set_setting("client_script", Path("ssl-renew.sh").read_text(encoding="utf-8"))
    payload = {"certificate_domain": "example.com", "service_domain": "app.example.com",
               "proxy_port": 8000, "public_path": "/download/"}
    result = public.post("/api/quick-deploy", json=payload, headers={"X-Panel-Request": "1"})
    assert result.status_code == 200, result.text
    assert "http://testserver/download/example.com/ssl-renew.sh?deployment=1&public_path=%2Fdownload%2F" in result.json()["certificate_command"]
    script = public.get("/example.com/ssl-renew.sh?deployment=1&public_path=%2Fdownload%2F")
    assert script.status_code == 200
    assert 'FULLCHAIN_URL="http://testserver/download/example.com/fullchain.pem"' in script.text
    assert 'PRIVKEY_URL="http://testserver/download/example.com/privkey.pem"' in script.text
    for prefix in ("//evil.org/", "/download/../"):
        assert public.post("/api/quick-deploy", json={**payload, "public_path": prefix}, headers={"X-Panel-Request": "1"}).status_code == 422
        assert public.get("/example.com/ssl-renew.sh", params={"public_path": prefix}).status_code == 400


def test_error_requests_are_logged_without_credentials(apps, caplog):
    admin, public, store, root = apps
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        response = admin.post("/api/quick-deploy", json={"password": "never-log-this"},
                              headers={"X-Panel-Request": "1"})
    assert response.status_code == 404
    request_id = response.headers["X-Request-ID"]
    assert request_id in caplog.text
    assert "ACME DNS Panel HTTP POST '/api/quick-deploy' status=404" in caplog.text
    assert "never-log-this" not in caplog.text


def test_prefixed_public_mount_routes_generation(apps):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    admin, public, store, root = apps
    authenticate(admin)
    account_and_domain(admin)
    make_certificate(root)
    mark_issued(store, root)
    store.set_setting("client_script", Path("ssl-renew.sh").read_text(encoding="utf-8"))
    outer = FastAPI()
    outer.mount("/download", public.app)
    outer.mount("/", admin.app)
    client = TestClient(outer)
    headers = {"X-Panel-Request": "1"}
    payload = {"certificate_domain": "example.com", "service_domain": "app.example.com", "proxy_port": 8000}
    assert client.post("/api/quick-deploy", json=payload, headers=headers).status_code == 404
    result = client.post("/download/api/quick-deploy", json=payload, headers=headers)
    assert result.status_code == 200
    assert "/download/example.com/ssl-renew.sh" in result.json()["certificate_command"]
    assert client.get("/download/assets/public.js").status_code == 200
    assert client.get("/download/api/certificates").status_code == 200
