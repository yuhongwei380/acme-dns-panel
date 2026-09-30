import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

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
