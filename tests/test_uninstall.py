import json
from pathlib import Path

import pytest

from scripts.uninstall import MARKER, validate_root, remove_runtime, stop_service


def installation(tmp_path):
    root = tmp_path / "installed-panel"
    root.mkdir()
    for name in ("app", "venv", "acme", "accounts", "ssl-renew", "data", "logs"):
        directory = root / name
        directory.mkdir()
        (directory / "retained-file").write_text(name)
    (root / "config.toml").write_text("configuration")
    (root / "source.py").write_text("source must survive purge")
    (root / MARKER).write_text(json.dumps({"application":"acme-dns-panel", "root":str(root.resolve()), "uid":root.stat().st_uid}))
    return root


def test_default_uninstall_retains_keys_certificates_and_database(tmp_path):
    root = installation(tmp_path)
    validated = validate_root(root, tmp_path / "home", root.stat().st_uid)
    remove_runtime(validated, False)
    for name in ("accounts", "ssl-renew", "data", "logs"):
        assert (root / name / "retained-file").exists()
    for name in ("app", "venv", "acme"):
        assert not (root / name).exists()
    assert (root / "config.toml").exists()
    assert (root / MARKER).exists()
    remove_runtime(validate_root(root, tmp_path / "home", root.stat().st_uid), False)


def test_purge_does_not_delete_source_or_unrelated_files(tmp_path):
    root = installation(tmp_path)
    remove_runtime(validate_root(root, tmp_path / "home", root.stat().st_uid), True)
    assert (root / "source.py").read_text() == "source must survive purge"
    assert sorted(p.name for p in root.iterdir()) == ["source.py"]


def test_reject_wrong_root_owner_and_missing_marker(tmp_path):
    root = installation(tmp_path)
    uid = root.stat().st_uid
    with pytest.raises(ValueError):
        validate_root(root, root, uid)
    with pytest.raises(ValueError):
        validate_root(root, tmp_path / "home", uid + 1)
    (root / MARKER).write_text(json.dumps({"application":"acme-dns-panel", "root":str(tmp_path / "wrong"), "uid":uid}))
    with pytest.raises(ValueError):
        validate_root(root, tmp_path / "home", uid)
    (root / MARKER).unlink()
    with pytest.raises(ValueError):
        validate_root(root, tmp_path / "home", uid)
    assert (root / "accounts/retained-file").exists()


def test_service_for_other_installation_is_not_stopped(tmp_path, monkeypatch):
    root = installation(tmp_path)
    unit = tmp_path / "acme-dns-panel.service"
    unit.write_text('Environment="ACME_PANEL_ROOT=/other/panel"\nExecStart="/other/panel/venv/bin/python" -m panel\n')
    calls = []
    monkeypatch.setattr("scripts.uninstall.subprocess.run", lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError):
        stop_service(root, unit)
    assert not calls
    assert unit.exists()


def test_owned_service_disabled_removed_and_reloaded(tmp_path, monkeypatch):
    root = installation(tmp_path)
    unit = tmp_path / "acme-dns-panel.service"
    unit.write_text(f'Environment="ACME_PANEL_ROOT={root}"\nExecStart="{root}/venv/bin/python" -m panel\n')
    calls = []
    monkeypatch.setattr("scripts.uninstall.subprocess.run", lambda args, **kw: calls.append(args))
    stop_service(root, unit)
    assert calls == [
        ["sudo", "systemctl", "disable", "--now", "acme-dns-panel.service"],
        ["sudo", "rm", "--", str(unit)],
        ["sudo", "systemctl", "daemon-reload"],
    ]
