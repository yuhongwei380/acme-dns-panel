import asyncio
import hashlib
import hmac
import ipaddress
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .acme import JobManager
from .certificates import managed_certificate, domain_issued
from .config import Config
from .compat import run_blocking
from .providers import PROVIDERS, BY_ID
from .store import Store, hash_password, check_password, now

STATIC = Path(__file__).parent / "static"


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class RemovalInput(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str
    credentials: Dict[str, str]


def normalize_domain(value):
    try:
        name = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("域名格式不正确")
    if len(name) > 253 or "." not in name or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in name.split(".")
    ):
        raise ValueError("请输入完整域名，不含协议、端口或 *. 前缀")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    raise ValueError("请输入域名，不是 IP 地址")


class DomainInput(BaseModel):
    name: str
    account_id: str
    wildcard: bool = True
    key_type: str = "ec-256"
    server: str = "letsencrypt"
    dns_sleep: int = Field(default=0, ge=0, le=1800)
    auto_renew: bool = True

    @field_validator("name")
    @classmethod
    def domain_name(cls, value):
        return normalize_domain(value)

    @field_validator("key_type")
    @classmethod
    def valid_key(cls, value):
        if value not in {"ec-256", "2048", "4096"}:
            raise ValueError("不支持的密钥类型")
        return value

    @field_validator("server")
    @classmethod
    def valid_server(cls, value):
        if value in {"letsencrypt", "zerossl", "buypass", "letsencrypt_test"}:
            return value
        if len(value) > 2048 or any(c.isspace() or ord(c) < 32 or c in "'\"\\`$" for c in value):
            raise ValueError("请填写有效的 HTTPS ACME Directory 地址")
        try:
            url = urlsplit(value)
            valid = (url.scheme == "https" and url.hostname and url.path not in {"", "/"}
                     and not url.username and not url.password and not url.fragment)
            url.port  # Reject malformed ports before passing the URL to acme.sh.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("请填写有效的 HTTPS ACME Directory 地址")
        return value


class JobInput(BaseModel):
    action: str


class SettingsInput(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r"[^'\s@]+@[^'\s@]+\.[^'\s@]+", value):
            raise ValueError("请填写有效的联系邮箱")
        return value


class PublicPortInput(BaseModel):
    public_port: int = Field(ge=1, le=65535, strict=True)


def create_apps(config=None, runner=None):
    config = config or Config.load()
    config.prepare()
    store = Store(config.root)
    manager = JobManager(config, store, runner)

    @asynccontextmanager
    async def lifecycle(app):
        manager.start()
        yield
        await manager.stop()

    admin = FastAPI(title="ACME DNS Panel", lifespan=lifecycle, docs_url=None, redoc_url=None, openapi_url=None)
    public = FastAPI(title="Certificate Library", docs_url=None, redoc_url=None, openapi_url=None)
    admin.state.store = public.state.store = store
    admin.state.manager = manager
    failures = {}
    removal_failures = {}

    def security_headers(app):
        @app.middleware("http")
        async def headers(request, call_next):
            # Browser form submissions cannot supply this header; CORS is intentionally disabled.
            if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-Panel-Request") != "1":
                return JSONResponse({"detail": "请求来源校验失败"}, status_code=403)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            return response

    security_headers(admin)
    security_headers(public)
    for app in (admin, public):
        app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    def session(request: Request):
        token = hashlib.sha256(request.cookies.get("panel_session", "").encode()).hexdigest()
        current = store.one("SELECT * FROM sessions WHERE token=? AND expires>?", (token, time.time()))
        if not current:
            raise HTTPException(401, "请先登录")
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), current["csrf"]):
            raise HTTPException(403, "会话校验失败，请刷新页面")
        return current

    @admin.post("/api/login")
    async def login(payload: Login, request: Request):
        ip = request.client.host if request.client else "unknown"
        recent = [t for t in failures.get(ip, []) if t > time.monotonic() - 300]
        if len(recent) >= 10:
            raise HTTPException(429, "尝试次数过多，请 5 分钟后重试")
        # Count in-flight requests too, preventing parallel requests bypassing the limit.
        recent.append(time.monotonic())
        failures[ip] = recent
        # Password hashing is intentionally outside the event loop.
        valid = await run_blocking(check_password, payload.password, store.setting("password"))
        if not valid:
            if len(failures) > 1000:
                failures.clear()
            raise HTTPException(401, "密码不正确")
        failures.pop(ip, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        store.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        store.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 43200))
        response = JSONResponse({"username": "admin", "csrf": csrf})
        response.set_cookie("panel_session", token, httponly=True, samesite="strict", secure=config.secure_cookie, max_age=43200)
        return response

    @admin.get("/api/session")
    def get_session(current=Depends(session)):
        return {"username": "admin", "csrf": current["csrf"]}

    @admin.post("/api/logout")
    def logout(current=Depends(session)):
        store.execute("DELETE FROM sessions WHERE token=?", (current["token"],))
        response = JSONResponse({"ok": True})
        response.delete_cookie("panel_session")
        return response

    @admin.post("/api/password")
    async def password(payload: PasswordChange, current=Depends(session)):
        if not await run_blocking(check_password, payload.current_password, store.setting("password")):
            raise HTTPException(400, "当前密码不正确")
        encoded = await run_blocking(hash_password, payload.new_password)
        with store.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='password'", (encoded,))
            db.execute("DELETE FROM sessions")
        return {"ok": True}

    @admin.get("/api/providers", dependencies=[Depends(session)])
    def providers():
        return PROVIDERS

    def get_account(account_id):
        account = store.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        if not account:
            raise HTTPException(404, "DNS 账户不存在")
        return account

    def get_domain(domain_id):
        domain = store.one("SELECT * FROM domains WHERE id=?", (domain_id,))
        if not domain:
            raise HTTPException(404, "域名不存在")
        return domain

    def busy(domain_id=None, account_id=None):
        sql = "SELECT 1 FROM jobs j JOIN domains d ON d.id=j.domain_id WHERE j.status IN ('queued','running')"
        args = ()
        if domain_id:
            sql += " AND d.id=?"
            args = (domain_id,)
        if account_id:
            sql += " AND d.account_id=?"
            args = (account_id,)
        if store.one(sql, args):
            raise HTTPException(409, "相关域名有运行或等待中的任务，请完成后再操作")

    @admin.get("/api/accounts", dependencies=[Depends(session)])
    def accounts():
        result = store.rows("SELECT * FROM accounts ORDER BY created")
        for account in result:
            account["configured_fields"] = [k for k, v in store.credentials(account["id"]).items() if v]
        return result

    def save_account(payload, account_id=None):
        provider = BY_ID.get(payload.provider)
        if not provider:
            raise HTTPException(400, "不支持的 DNS 服务商")
        existing = {}
        if account_id:
            account = get_account(account_id)
            busy(account_id=account_id)
            if account["provider"] != payload.provider:
                raise HTTPException(400, "已建立的账户不能更改服务商，请添加新账户")
            existing = store.credentials(account_id)
        allowed = {f["name"] for f in provider["fields"]}
        if set(payload.credentials) - allowed:
            raise HTTPException(400, "包含不支持的密钥字段")
        # Missing values preserve credentials; explicit empty optional values clear them.
        credentials = {**existing, **payload.credentials}
        for field in provider["fields"]:
            if field["required"] and not credentials.get(field["name"]):
                raise HTTPException(400, f"请填写 {field['label']}")
        if not payload.name.strip():
            raise HTTPException(400, "账户名称不能为空")
        if any(len(v) > 4096 or any(c in v for c in ("\x00", "\n", "\r", "'")) for v in credentials.values()):
            raise HTTPException(400, "此 acme.sh 版本的凭据不能包含单引号、换行或超过 4096 个字符")
        account_id = account_id or uuid.uuid4().hex
        store.save_credentials(account_id, credentials)
        store.execute("INSERT INTO accounts VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                      (account_id, payload.name.strip(), payload.provider, now()))
        return {"id": account_id}

    @admin.post("/api/accounts", dependencies=[Depends(session)])
    def add_account(payload: AccountInput):
        return save_account(payload)

    @admin.put("/api/accounts/{account_id}", dependencies=[Depends(session)])
    def edit_account(account_id: str, payload: AccountInput):
        return save_account(payload, account_id)

    async def confirm_removal(payload: RemovalInput, request: Request, current=Depends(session)):
        ip = request.client.host if request.client else "unknown"
        recent = [t for t in removal_failures.get(ip, []) if t > time.monotonic() - 300]
        if len(recent) >= 10:
            raise HTTPException(429, "密码确认尝试次数过多，请 5 分钟后重试")
        recent.append(time.monotonic())
        removal_failures[ip] = recent
        if not await run_blocking(check_password, payload.password, store.setting("password")):
            raise HTTPException(403, "管理员密码不正确，未执行移除")
        removal_failures.pop(ip, None)

    @admin.delete("/api/accounts/{account_id}", dependencies=[Depends(confirm_removal)])
    def delete_account(account_id: str):
        get_account(account_id)
        if store.one("SELECT 1 FROM domains WHERE account_id=?", (account_id,)):
            raise HTTPException(409, "该账户仍被域名使用，请先移除相关域名")
        store.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        # Explicit API deletion removes credential material, while issued state stays for recovery.
        (config.root / "accounts" / account_id / "credentials.json").unlink(missing_ok=True)
        return {"ok": True}

    def domain_rows():
        result = store.rows("SELECT d.*, a.name AS account_name, a.provider FROM domains d JOIN accounts a ON a.id=d.account_id ORDER BY d.created DESC")
        for domain in result:
            domain["certificate"] = managed_certificate(config.root, domain)
            domain["issued"] = domain_issued(config.root, domain)
            domain["job"] = store.one("SELECT id,status,action,finished FROM jobs WHERE domain_id=? ORDER BY created DESC LIMIT 1", (domain["id"],))
        return result

    @admin.get("/api/domains", dependencies=[Depends(session)])
    def domains():
        return domain_rows()

    @admin.post("/api/domains", dependencies=[Depends(session)])
    def add_domain(payload: DomainInput):
        if not store.setting("email").strip():
            raise HTTPException(400, "未填写 ACME 联系邮箱，无法添加证书。请先在「服务设置」中填写并保存")
        if payload.server == "letsencrypt_test":
            raise HTTPException(400, "新域名请使用正式 CA；测试地址可通过「其他」自行填写")
        account = store.one("SELECT * FROM accounts WHERE id=?", (payload.account_id,))
        if not account:
            raise HTTPException(400, "未检测到所选 DNS 账户，无法添加域名。请先在「DNS 账户」中完成配置")
        provider = BY_ID.get(account["provider"])
        try:
            credentials = store.credentials(account["id"])
        except (OSError, ValueError):
            credentials = {}
        if not provider or not isinstance(credentials, dict) or any(
            not isinstance(credentials.get(field["name"]), str) or not credentials[field["name"]].strip()
            for field in provider["fields"] if field["required"]
        ):
            raise HTTPException(400, "所选 DNS 账户凭据缺失或配置不完整，无法添加域名。请先在「DNS 账户」中修复配置")
        if store.one("SELECT 1 FROM domains WHERE name=?", (payload.name,)):
            raise HTTPException(409, "该域名已存在")
        domain_id = uuid.uuid4().hex
        store.execute("INSERT INTO domains(id,name,account_id,wildcard,key_type,server,dns_sleep,auto_renew,created) VALUES (?,?,?,?,?,?,?,?,?)",
                      (domain_id, payload.name, payload.account_id, payload.wildcard, payload.key_type, payload.server, payload.dns_sleep, payload.auto_renew, now()))
        return {"id": domain_id}

    @admin.put("/api/domains/{domain_id}", dependencies=[Depends(session)])
    def edit_domain(domain_id: str, payload: DomainInput):
        old = get_domain(domain_id)
        busy(domain_id=domain_id)
        get_account(payload.account_id)
        # Changes to SANs/CA/key need a deliberate replacement order; first version avoids hidden force issuance.
        immutable = ("name", "account_id", "wildcard", "key_type", "server")
        if any(getattr(payload, key) != old[key] for key in immutable):
            raise HTTPException(400, "域名、账户、覆盖范围、CA 和密钥类型不可直接变更；请移除后重新添加")
        store.execute("UPDATE domains SET dns_sleep=?, auto_renew=? WHERE id=?", (payload.dns_sleep, payload.auto_renew, domain_id))
        return {"ok": True}

    @admin.delete("/api/domains/{domain_id}", dependencies=[Depends(confirm_removal)])
    def delete_domain(domain_id: str):
        get_domain(domain_id)
        busy(domain_id=domain_id)
        store.execute("DELETE FROM domains WHERE id=?", (domain_id,))
        # Retain on-disk certificates for recovery. Download routes require an active DB record.
        return {"ok": True}

    @admin.post("/api/domains/{domain_id}/jobs", dependencies=[Depends(session)])
    def enqueue(domain_id: str, payload: JobInput):
        domain = get_domain(domain_id)
        if payload.action not in {"issue", "renew"}:
            raise HTTPException(400, "不支持的任务类型")
        if not (config.root / "acme" / "acme.sh").is_file():
            raise HTTPException(400, "acme.sh 尚未安装，请先执行 Linux 部署脚本")
        if not store.setting("email"):
            raise HTTPException(400, "请先在服务设置中填写 ACME 联系邮箱")
        try:
            return {"id": manager.enqueue(domain, payload.action)}
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @admin.get("/api/jobs", dependencies=[Depends(session)])
    def jobs():
        return store.rows("SELECT id,domain_id,domain_name,action,status,created,started,finished FROM jobs ORDER BY created DESC LIMIT 100")

    @admin.get("/api/jobs/{job_id}", dependencies=[Depends(session)])
    def job(job_id: str):
        row = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(404, "任务不存在")
        return row

    @admin.get("/api/settings", dependencies=[Depends(session)])
    def settings():
        return {"email": store.setting("email"),
                "root": str(config.root), "acme_installed": (config.root / "acme" / "acme.sh").is_file(),
                "admin_port": config.admin_port, "public_port": config.public_port}

    @admin.put("/api/settings", dependencies=[Depends(session)])
    def save_settings(payload: SettingsInput):
        store.set_setting("email", payload.email)
        return {"ok": True}

    @admin.post("/api/public-service/reload", dependencies=[Depends(session)])
    async def reload_public_service(payload: PublicPortInput):
        if payload.public_port == config.admin_port:
            raise HTTPException(422, "下载端口不能与管理端口相同")
        service = getattr(admin.state, "public_service", None)
        if service is None:
            raise HTTPException(503, "当前运行方式不支持重载，请使用 python -m panel 启动服务")
        try:
            await service.reload(payload.public_port)
        except OSError:
            raise HTTPException(409, "重载失败：端口被占用、无权监听或配置无法写入，原下载服务保持运行")
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error))
        return {"ok": True, "public_port": config.public_port}

    @public.get("/api/certificates")
    def public_certificates():
        return {"domains": [
            {"name": d["name"], "wildcard": bool(d["wildcard"]), "staging": d["server"] in {
                "letsencrypt_test", "https://acme-staging-v02.api.letsencrypt.org/directory"},
             "certificate": managed_certificate(config.root, d)}
            for d in store.rows("SELECT * FROM domains ORDER BY name")
        ]}

    @public.get("/{domain}/{filename}")
    def download(domain: str, filename: str):
        row = store.one("SELECT * FROM domains WHERE name=?", (domain,))
        if filename not in {"fullchain.pem", "privkey.pem"} or not row:
            raise HTTPException(404, "文件不存在")
        info = managed_certificate(config.root, row)
        if not info["available"]:
            raise HTTPException(404, "证书尚未签发或文件未通过校验")
        path = config.root / "ssl-renew" / domain / filename
        return FileResponse(path, media_type="application/x-pem-file", filename=filename)

    @admin.get("/")
    def admin_page():
        return FileResponse(STATIC / "admin.html")

    @public.get("/")
    def public_page():
        return FileResponse(STATIC / "public.html")

    return admin, public
