import asyncio
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from panel.config import Config
from panel.http_service import PublicHTTPService
from panel.web import create_apps


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def request(port):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    assert b"200 OK" in response
    assert b'"ok":true' in response


def test_reload_serves_new_port_and_preserves_old_on_failure(tmp_path, monkeypatch):
    async def scenario():
        config = Config(tmp_path, public_host="127.0.0.1", public_port=free_port())
        app = FastAPI()

        @app.get("/")
        def index():
            return {"ok": True}

        service = PublicHTTPService(config, app)
        await service.start()
        original = config.public_port
        try:
            await request(original)
            with socket.socket() as occupied:
                occupied.bind(("127.0.0.1", 0))
                occupied.listen()
                with pytest.raises(OSError):
                    await service.reload(occupied.getsockname()[1])
            assert config.public_port == original
            await request(original)
            assert not service.failed.is_set()

            replacement = free_port()
            await service.reload(replacement)
            await request(replacement)
            with pytest.raises(OSError):
                await asyncio.open_connection("127.0.0.1", original)
            monkeypatch.setenv("ACME_PANEL_ROOT", str(tmp_path))
            assert Config.load().public_port == replacement

            def cannot_save(port):
                raise OSError("read-only configuration")
            monkeypatch.setattr(config, "save_public_port", cannot_save)
            with pytest.raises(OSError):
                await service.reload(free_port())
            await request(replacement)
            assert config.public_port == replacement
            assert not service.failed.is_set()
        finally:
            await service.close()
    asyncio.run(scenario())


def test_port_persistence_preserves_other_configuration(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('# note\n[service]\nadmin_host="127.0.0.1"\npublic_port=8001 # download\nsecure_cookie=true\n[other]\nvalue="keep"\n')
    config = Config(tmp_path)
    config.save_public_port(9001)
    monkeypatch.setenv("ACME_PANEL_ROOT", str(tmp_path))
    loaded = Config.load()
    assert loaded.public_port == 9001
    assert loaded.admin_host == "127.0.0.1"
    assert loaded.secure_cookie
    assert '# note' in path.read_text() and '# download' in path.read_text()
    assert '[other]\nvalue="keep"' in path.read_text()


def test_reload_endpoint_requires_admin_and_csrf(tmp_path):
    admin, public = create_apps(Config(tmp_path))
    client = TestClient(admin)
    assert client.post('/api/public-service/reload', json={"public_port":9001}, headers={"X-Panel-Request":"1"}).status_code == 401
    login = client.post('/api/login', json={"password":"admin"}, headers={"X-Panel-Request":"1"})
    headers = {"X-Panel-Request":"1", "X-CSRF-Token":login.json()['csrf']}
    assert client.post('/api/public-service/reload', json={"public_port":9001}, headers={"X-Panel-Request":"1"}).status_code == 403
    assert client.post('/api/public-service/reload', json={"public_port":8080}, headers=headers).status_code == 422
    assert client.post('/api/public-service/reload', json={"public_port":9001}, headers=headers).status_code == 503
    assert TestClient(public).post('/api/public-service/reload', json={"public_port":9001}, headers=headers).status_code == 404
    admin.state.store.set_setting("public_url", "http://obsolete.example:9999")
    assert "public_url" not in client.get('/api/settings').json()
    assert "public_url" not in TestClient(public).get('/api/certificates').json()
