import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest

BASH = shutil.which("bash") if os.name != "nt" else r"C:\Program Files\Git\bin\bash.exe"
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).exists(), reason="Bash is required")


@pytest.mark.parametrize("root", ["/home/test/acme-dns-panel", "/home/test/certificate panel"])
def test_generated_unit_uses_absolute_working_directory_without_quotes(root):
    installer = (Path(__file__).resolve().parents[1] / "scripts/install.sh").read_text(encoding="utf-8")
    template = re.search(r'cat > "\$PANEL_ROOT/data/acme-dns-panel.service" <<EOF\n(.*?)\nEOF', installer, re.S).group(1)
    command = f"PATH=/usr/bin:/bin:$PATH; PANEL_ROOT={shlex.quote(root)}; SERVICE_USER=test; SERVICE_GROUP=test; cat <<EOF\n{template}\nEOF\n"
    result = subprocess.run([BASH,"-c",command], capture_output=True, text=True, encoding="utf-8", check=True)
    settings = dict(line.split("=",1) for line in result.stdout.splitlines() if "=" in line)
    assert settings["WorkingDirectory"] == root + "/app"
    assert settings["WorkingDirectory"].startswith("/")
    assert shlex.split(settings["ExecStart"]) == [root + "/venv/bin/python", "-m", "panel"]
    assert shlex.split(settings["Environment"]) == ["ACME_PANEL_ROOT=" + root]
    assert shlex.split(settings["ReadWritePaths"]) == [root]


@pytest.mark.parametrize("settings,admin_port,public_port", [
    ('[service]\nadmin_port=9080\npublic_port=9001\n', 9080, 9001),
    ('[service]\npublic_port=9443 # custom download port\n', 8080, 9443),
    ('[service]\n', 8080, 8001),
])
def test_install_completion_addresses_use_service_configuration(tmp_path, settings, admin_port, public_port):
    repo = Path(__file__).resolve().parents[1]
    installer = (repo / "scripts/install.sh").read_text(encoding="utf-8")
    summary = installer.split("# Use the same installed configuration loader as the running service.\n", 1)[1]
    code = summary.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    (tmp_path / "config.toml").write_text(settings, encoding="utf-8")
    result = subprocess.run([sys.executable, "-c", code], cwd=repo,
                            env={**os.environ, "ACME_PANEL_ROOT": str(tmp_path), "PYTHONIOENCODING": "utf-8"},
                            capture_output=True, text=True, encoding="utf-8", check=True)
    assert f"管理：http://服务器局域网IP:{admin_port}" in result.stdout
    assert f"只读：http://服务器局域网IP:{public_port}" in result.stdout
