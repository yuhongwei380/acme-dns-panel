from panel.config import Config


def test_load_toml_settings_on_supported_python_versions(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text(
        '[service]\nadmin_host="0.0.0.0"\nadmin_port=8088\npublic_port=8008\nsecure_cookie=true\ntask_timeout=600\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ACME_PANEL_ROOT", str(tmp_path))
    config = Config.load()
    assert config.root == tmp_path.resolve()
    assert config.admin_host == "0.0.0.0"
    assert config.admin_port == 8088
    assert config.public_port == 8008
    assert config.secure_cookie is True
    assert config.task_timeout == 600
