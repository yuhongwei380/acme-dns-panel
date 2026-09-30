"""Standalone Linux uninstaller; requires only Python's standard library."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MARKER = ".panel-install.json"
DIRECTORIES = ("app", "venv", "acme")
DATA_DIRECTORIES = ("accounts", "ssl-renew", "data", "logs")


def validate_root(root, home, uid):
    original = root.expanduser().absolute()
    if original.is_symlink():
        raise ValueError("安装目录不能是符号链接")
    root = original.resolve()
    if root == Path(root.anchor) or root == home.resolve():
        raise ValueError("不能卸载根目录或用户家目录本身")
    marker = root / MARKER
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("未找到安装标记，请先使用新版安装脚本部署此目录")
    info = json.loads(marker.read_text(encoding="utf-8"))
    if info.get("application") != "acme-dns-panel" or info.get("root") != str(root) or info.get("uid") != uid:
        raise ValueError("安装标记中的应用、目录或所属用户不匹配")
    if root.stat().st_uid != uid:
        raise ValueError("请使用安装目录所属用户执行卸载")
    # Check every target before stopping services or deleting anything. Never delete the root itself.
    for name in (*DIRECTORIES, *DATA_DIRECTORIES, "config.toml", MARKER):
        target = root / name
        if target.is_symlink() or target.resolve().parent != root:
            raise ValueError(f"卸载目标不能是符号链接或位于目录之外：{target}")
    return root


def remove_runtime(root, purge):
    for name in (*DIRECTORIES, *(DATA_DIRECTORIES if purge else ())):
        path = root / name
        if path.exists():
            if not path.is_dir():
                raise ValueError(f"预期为目录：{path}")
            shutil.rmtree(path)
    if purge:
        (root / "config.toml").unlink(missing_ok=True)
        (root / MARKER).unlink(missing_ok=True)
    else:
        (root / "data" / "acme-dns-panel.service").unlink(missing_ok=True)


def stop_service(root, unit=None):
    unit = unit or Path("/etc/systemd/system/acme-dns-panel.service")
    if not unit.exists():
        return
    if unit.is_symlink():
        raise ValueError("systemd 服务文件为符号链接，无法确认归属")
    contents = unit.read_text(encoding="utf-8").splitlines()
    if f'Environment="ACME_PANEL_ROOT={root}"' not in contents or f'ExecStart="{root}/venv/bin/python" -m panel' not in contents:
        raise ValueError("systemd 服务属于其他安装目录，已停止卸载")
    subprocess.run(["sudo", "systemctl", "disable", "--now", "acme-dns-panel.service"], check=True)
    subprocess.run(["sudo", "rm", "--", str(unit)], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)


def main():
    parser = argparse.ArgumentParser(description="卸载 ACME DNS Panel，默认保留账户、配置和证书")
    parser.add_argument("--purge", action="store_true", help="删除本安装目录中的账户、配置、证书和日志")
    parser.add_argument("--yes", action="store_true", help="配合 --purge，跳过删除数据的交互确认")
    parser.add_argument("--no-service", action="store_true", help="用于 --no-service 安装；不操作 systemd")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("卸载脚本要求 Linux")
    if os.getuid() == 0:
        parser.error("请使用安装时的普通用户执行，仅操作 systemd 时调用 sudo")
    root = validate_root(Path(os.environ.get("ACME_PANEL_ROOT", "~/acme-dns-panel")), Path.home(), os.getuid())
    if args.purge and not args.yes:
        print(f"将删除 {root} 内的 DNS 密钥、CA 账户、证书、配置和日志。此操作不可恢复。")
        if input("请输入完整安装目录以确认：").strip() != str(root):
            raise ValueError("目录确认不匹配，已取消卸载")
    if not args.no_service:
        stop_service(root)
    # A manual instance (including one started without systemd) must stop before deletion.
    import fcntl
    lock_path = root / "data" / "service.lock"
    if lock_path.is_symlink():
        raise ValueError("服务锁不能是符号链接")
    lock = None
    try:
        if lock_path.parent.exists():
            lock = lock_path.open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("仍有手动运行的实例，请先停止进程再卸载")
        remove_runtime(root, args.purge)
    finally:
        if lock:
            lock.close()
    print(f"卸载完成：{root}")
    print("已删除运行程序及安装数据。" if args.purge else "DNS 账户、配置、证书和任务记录已保留；重新安装可恢复使用。")
    print("源码、README 和卸载脚本保留。原有 ~/.acme.sh 不受影响。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, EOFError, subprocess.CalledProcessError) as exc:
        print(f"卸载失败：{exc}", file=sys.stderr)
        sys.exit(1)
