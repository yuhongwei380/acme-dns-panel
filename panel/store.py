import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def check_password(password, encoded):
    _, salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return hmac.compare_digest(actual, expected)


class Store:
    def __init__(self, root):
        self.root = root
        self.path = root / "data" / "panel.db"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS domains (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL REFERENCES accounts(id),
                    wildcard INTEGER NOT NULL, key_type TEXT NOT NULL, server TEXT NOT NULL,
                    dns_sleep INTEGER NOT NULL, auto_renew INTEGER NOT NULL, created TEXT NOT NULL,
                    last_checked TEXT);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, domain_id TEXT NOT NULL, domain_name TEXT NOT NULL,
                    action TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
                    started TEXT, finished TEXT, log TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
            """)
            if not db.execute("SELECT 1 FROM settings WHERE key='password'").fetchone():
                db.execute("INSERT INTO settings VALUES ('password', ?)", (hash_password("admin"),))
            db.execute("UPDATE jobs SET status='interrupted', finished=?, log=log || ? WHERE status='running'",
                       (now(), "\n服务重启，任务中断。可重新申请或检查续期。"))
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def setting(self, key, default=""):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def credentials(self, account_id):
        return json.loads((self.root / "accounts" / account_id / "credentials.json").read_text(encoding="utf-8"))

    def save_credentials(self, account_id, credentials):
        directory = self.root / "accounts" / account_id
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        path = directory / "credentials.json"
        temporary = directory / "credentials.tmp"
        with temporary.open("w", encoding="utf-8") as f:
            temporary.chmod(0o600)
            json.dump(credentials, f, ensure_ascii=False)
        temporary.replace(path)
        path.chmod(0o600)

