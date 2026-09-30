import asyncio
import base64
import json
import os
import re
import signal
import uuid
from datetime import datetime, timedelta, timezone

from .providers import BY_ID, PROVIDERS
from .store import now
from .certificates import domain_conf, domain_issued, managed_certificate


def redact(text, credentials):
    for value in sorted(credentials.values(), key=len, reverse=True):
        if value:
            for variant in {value, json.dumps(value)[1:-1], base64.b64encode(value.encode()).decode(),
                            value.replace("'", "'\\''")}:
                text = text.replace(variant, "[REDACTED]")
    return re.sub(r"(?i)((?:secret|password|token|authorization|api[_ -]?key)\s*[:=]\s*)[^\s]+", r"\1[REDACTED]", text)


class AcmeRunner:
    def __init__(self, config, store):
        self.config, self.store = config, store

    def command(self, account_id, domain_id):
        script = self.config.root / "acme" / "acme.sh"
        if not script.is_file():
            raise RuntimeError("尚未安装 acme.sh。请先在 Linux 执行 scripts/install.sh。")
        profile = self.config.root / "accounts" / account_id
        return ["sh", str(script), "--home", str(script.parent), "--config-home", str(profile),
                "--cert-home", str(profile / "certs" / domain_id)]

    def clear_cached_credentials(self, domain, provider):
        # domain.conf is sourced by acme.sh and can override a rotated CF token.
        names = {f["name"] for f in provider["fields"]} | {"CF_Key", "CF_Email"}
        pattern = re.compile(r"^(?:export\s+)?(?:SAVED_)?(?:" + "|".join(re.escape(n) for n in names) + r")\s*=")
        for path in (self.config.root / "accounts" / domain["account_id"] / "account.conf", domain_conf(self.config.root, domain)):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                filtered = "".join(line for line in text.splitlines(keepends=True) if not pattern.match(line))
                if path == domain_conf(self.config.root, domain):
                    filtered = "".join(line for line in filtered.splitlines(keepends=True) if not line.startswith("Le_DNSSleep="))
                    filtered += f"\nLe_DNSSleep='{domain['dns_sleep'] or ''}'\n"
                temporary = path.with_suffix(".panel.tmp")
                temporary.write_text(filtered, encoding="utf-8")
                temporary.chmod(0o600)
                temporary.replace(path)

    def environment(self, credentials):
        env = os.environ.copy()
        # Never inherit a different DNS account from the service user's shell.
        for provider in PROVIDERS:
            for field in provider["fields"]:
                env.pop(field["name"], None)
        for name in ("CF_Key", "CF_Email", "LE_WORKING_DIR", "LE_CONFIG_HOME", "CERT_HOME"):
            env.pop(name, None)
        env.update(credentials)
        env["AUTO_UPGRADE"] = "0"
        return env

    def append(self, job_id, message):
        self.store.execute("UPDATE jobs SET log=substr(log || ?, -100000) WHERE id=?", (message, job_id))

    async def process(self, args, credentials, job_id):
        proc = await asyncio.create_subprocess_exec(
            *args, env=self.environment(credentials), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=(os.name == "posix"), limit=1024 * 1024)
        async def read_output():
            # Chunked reads avoid a long output line deadlocking the subprocess.
            pending = b""
            while chunk := await proc.stdout.read(4096):
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self.append(job_id, redact(line.decode("utf-8", "replace") + "\n", credentials))
                if len(pending) > 65536:
                    pending = b""
                    self.append(job_id, "[过长日志行已省略]\n")
            if pending:
                self.append(job_id, redact(pending.decode("utf-8", "replace"), credentials))
            return await proc.wait()

        try:
            return await asyncio.wait_for(read_output(), timeout=self.config.task_timeout)
        finally:
            if proc.returncode is None:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except asyncio.TimeoutError:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    await proc.wait()

    async def run(self, job):
        domain = self.store.one("SELECT * FROM domains WHERE id=?", (job["domain_id"],))
        if not domain:
            raise RuntimeError("域名已删除")
        account = self.store.one("SELECT * FROM accounts WHERE id=?", (domain["account_id"],))
        credentials = self.store.credentials(account["id"])
        command = self.command(account["id"], domain["id"])
        self.clear_cached_credentials(domain, BY_ID[account["provider"]])
        ecc = ["--ecc"] if domain["key_type"] == "ec-256" else []
        email = self.store.setting("email")
        if not email:
            raise RuntimeError("请先在服务设置中填写 ACME 联系邮箱")
        # Each profile has its own ACME registration and CA account.
        register = command + ["--register-account", "--server", domain["server"], "-m", email]
        if await self.process(register, credentials, job["id"]) != 0:
            raise RuntimeError("ACME 账户注册失败，详见日志")
        if job["action"] == "issue":
            args = command + ["--issue", "--dns", BY_ID[account["provider"]]["plugin"], "-d", domain["name"],
                              "--keylength", domain["key_type"], "--server", domain["server"]]
            if domain["wildcard"]:
                args += ["-d", "*." + domain["name"]]
            if domain["dns_sleep"]:
                args += ["--dnssleep", str(domain["dns_sleep"])]
        else:
            if not domain_issued(self.config.root, domain):
                raise RuntimeError("该域名尚未签发，请先申请证书")
            if domain["dns_sleep"]:
                command += ["--dnssleep", str(domain["dns_sleep"])]
            args = command + ["--renew", "-d", domain["name"], "--server", domain["server"]] + ecc
        self.append(job["id"], f"域名：{domain['name']} · 操作：{job['action']}\n")
        code = await self.process(args, credentials, job["id"])
        if code not in (0, 2):  # acme.sh returns 2 when renewal is not due.
            raise RuntimeError(f"acme.sh 返回 {code}，详见日志")
        directory = self.config.root / "ssl-renew" / domain["name"]
        if directory.is_symlink():
            raise RuntimeError("证书输出目录不能是符号链接")
        directory.mkdir(mode=0o700, exist_ok=True)
        for filename in ("privkey.pem", "fullchain.pem"):
            if (directory / filename).is_symlink():
                raise RuntimeError("证书输出文件不能是符号链接")
        install = command + ["--install-cert", "-d", domain["name"]] + ecc + [
            "--key-file", str(directory / "privkey.pem"), "--fullchain-file", str(directory / "fullchain.pem")]
        if await self.process(install, credentials, job["id"]) != 0:
            raise RuntimeError("证书安装失败，详见日志")
        for filename in ("privkey.pem", "fullchain.pem"):
            (directory / filename).chmod(0o600)
        if not managed_certificate(self.config.root, domain)["available"]:
            raise RuntimeError("安装后的证书与私钥未通过校验")
        self.append(job["id"], "\n证书已安装，下载地址保持不变。\n")


class JobManager:
    def __init__(self, config, store, runner=None):
        self.store, self.config = store, config
        self.runner = runner or AcmeRunner(config, store)
        self.tasks = []

    def enqueue(self, domain, action):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT id FROM jobs WHERE domain_id=? AND status IN ('queued','running')", (domain["id"],)).fetchone()
            if active:
                raise ValueError("该域名已有等待或运行中的任务")
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,domain_id,domain_name,action,status,created) VALUES (?,?,?,?,'queued',?)",
                       (job_id, domain["id"], domain["name"], action, now()))
            db.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM jobs WHERE status NOT IN ('queued','running') ORDER BY created DESC LIMIT -1 OFFSET 200)")
        return job_id

    async def worker(self):
        while True:
            job = self.store.one("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1")
            if not job:
                await asyncio.sleep(1)
                continue
            self.store.execute("UPDATE jobs SET status='running', started=? WHERE id=?", (now(), job["id"]))
            try:
                await asyncio.wait_for(self.runner.run(job), timeout=self.config.task_timeout)
                status = "success"
                self.store.execute("UPDATE domains SET last_checked=? WHERE id=?", (now(), job["domain_id"]))
            except asyncio.CancelledError:
                self.store.execute("UPDATE jobs SET status='interrupted', finished=? WHERE id=?", (now(), job["id"]))
                raise
            except asyncio.TimeoutError:
                status = "failed"
                self.runner.append(job["id"], "\n任务超时，子进程已终止。请检查网络和 DNS 配置后重试。\n")
            except Exception as exc:
                status = "failed"
                # Only internal, sanitized errors are exposed; subprocess logs are redacted separately.
                self.runner.append(job["id"], f"\n任务失败：{exc}\n")
            self.store.execute("UPDATE jobs SET status=?, finished=? WHERE id=?", (status, now(), job["id"]))

    def schedule_due(self):
        threshold = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for domain in self.store.rows("SELECT * FROM domains WHERE auto_renew=1 AND (last_checked IS NULL OR last_checked<?)", (threshold,)):
            # New domains require an explicit first issue, never silently submit orders.
            if not domain_issued(self.config.root, domain):
                continue
            try:
                self.enqueue(domain, "renew")
                self.store.execute("UPDATE domains SET last_checked=? WHERE id=?", (now(), domain["id"]))
            except ValueError:
                pass

    async def scheduler(self):
        while True:
            self.schedule_due()
            await asyncio.sleep(60)

    def start(self):
        self.tasks = [asyncio.create_task(self.worker()), asyncio.create_task(self.scheduler())]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
