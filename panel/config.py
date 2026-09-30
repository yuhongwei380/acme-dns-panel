from dataclasses import dataclass
from pathlib import Path
import os
import re
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.8–3.10
    import tomli as tomllib


@dataclass
class Config:
    root: Path
    admin_host: str = "0.0.0.0"
    admin_port: int = 8080
    public_host: str = "0.0.0.0"
    public_port: int = 8001
    secure_cookie: bool = False
    task_timeout: int = 3600

    @classmethod
    def load(cls):
        root = Path(os.environ.get("ACME_PANEL_ROOT", "~/acme-dns-panel")).expanduser().resolve()
        values = {}
        if (root / "config.toml").exists():
            with (root / "config.toml").open("rb") as f:
                values = tomllib.load(f).get("service", {})
        allowed = {"admin_host", "admin_port", "public_host", "public_port", "secure_cookie", "task_timeout"}
        config = cls(root, **{k: v for k, v in values.items() if k in allowed})
        if not (1 <= config.admin_port <= 65535 and 1 <= config.public_port <= 65535):
            raise ValueError("端口必须在 1–65535 之间")
        if config.admin_port == config.public_port:
            raise ValueError("管理端口与下载端口不能相同")
        if config.task_timeout < 60:
            raise ValueError("task_timeout 不能小于 60 秒")
        return config

    def prepare(self):
        if any(c in str(self.root) for c in ("'", "\n", "\r", "\x00")):
            raise ValueError("acme.sh 数据目录不支持单引号、换行或空字符")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        for name in ("acme", "accounts", "ssl-renew", "data", "logs"):
            path = self.root / name
            if path.is_symlink():
                raise ValueError(f"数据目录不能是符号链接：{path}")
            path.mkdir(exist_ok=True, mode=0o700)
            path.chmod(0o700)

    def save_public_port(self, port):
        """Atomically update the port while retaining unrelated settings and comments."""
        path = self.root / "config.toml"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        table = re.search(r"(?m)^\s*\[service\][^\n]*\n?", text)
        if table:
            start = table.end()
            following = re.search(r"(?m)^\s*\[", text[start:])
            end = start + following.start() if following else len(text)
            body = text[start:end]
            key = re.compile(r'''(?m)^([ \t]*(?:public_port|"public_port"|'public_port')[ \t]*=[ \t]*)[^#\n]*''')
            if key.search(body):
                body = key.sub(lambda match: match.group(1) + str(port) + " ", body, count=1)
            else:
                body = f"public_port = {port}\n" + body
            text = text[:start].rstrip("\n") + "\n" + body + text[end:]
        else:
            text = text.rstrip() + f"\n[service]\npublic_port = {port}\n"
        if tomllib.loads(text)["service"]["public_port"] != port:
            raise ValueError("无法更新 config.toml 中的下载端口")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as file:
                temporary = Path(file.name)
                file.write(text)
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

