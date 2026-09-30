import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

BASH = shutil.which("bash") if os.name != "nt" else r"C:\Program Files\Git\bin\bash.exe"
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).exists(), reason="Bash is required")
HELPER = Path(__file__).resolve().parents[1] / "scripts/python-runtime.sh"


def select(tmp_path, versions, explicit=None):
    for name, compatible in versions.items():
        path = tmp_path / name
        path.write_bytes(f"#!/bin/bash\nexit {0 if compatible else 1}\n".encode("utf-8"))
        path.chmod(0o755)
    prefix = shlex.quote(tmp_path.as_posix())
    override = "unset ACME_PANEL_PYTHON;" if explicit is None else f"export ACME_PANEL_PYTHON={shlex.quote(explicit)};"
    # Isolate command lookup from Python versions installed on the test host.
    code = f"source {shlex.quote(HELPER.as_posix())}; PATH=\"$(cd -- {prefix} && pwd)\"; {override} select_panel_python && printf '%s' \"$PYTHON_BIN\""
    return subprocess.run([BASH, "-c", code], text=True, capture_output=True, encoding="utf-8")


def test_older_default_falls_back_to_installed_312(tmp_path):
    result = select(tmp_path, {"python3":False,"python3.12":True})
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("/python3.12")


def test_compatible_38_default_is_used(tmp_path):
    result = select(tmp_path, {"python3":True,"python3.12":True})
    assert result.returncode == 0
    assert result.stdout.endswith("/python3")


def test_explicit_python_is_honored(tmp_path):
    result = select(tmp_path, {"python3":True,"python3.12":True}, (tmp_path / "python3.12").as_posix())
    assert result.returncode == 0
    assert result.stdout.endswith("/python3.12")


def test_bad_explicit_version_does_not_silently_fall_back(tmp_path):
    result = select(tmp_path, {"python3":True,"python3.12":False}, "python3.12")
    assert result.returncode != 0
    assert "3.8" in result.stderr


def test_no_compatible_python_has_clear_error(tmp_path):
    result = select(tmp_path, {"python3":False})
    assert result.returncode != 0
    assert "ACME_PANEL_PYTHON" in result.stderr
