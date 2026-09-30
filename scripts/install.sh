#!/usr/bin/env bash
set -euo pipefail
umask 077

# Run as the user who will own the certificates, never as root.
if [[ "$(id -u)" == 0 ]]; then
  echo '请使用证书所属的普通用户运行安装脚本；注册 systemd 时才会调用 sudo。' >&2
  exit 1
fi
if [[ "$(uname -s)" != Linux ]]; then
  echo '自动安装与 acme.sh 签发要求 Linux。Windows 可运行面板用于开发。' >&2
  exit 1
fi
INSTALL_SERVICE=1
if [[ "${1:-}" == --no-service ]]; then INSTALL_SERVICE=0; shift; fi
if [[ $# != 0 ]]; then echo '用法：ACME_PANEL_ROOT=/path bash scripts/install.sh [--no-service]' >&2; exit 1; fi
for dependency in python3 curl tar openssl sha256sum; do
  command -v "$dependency" >/dev/null || { echo "缺少依赖：$dependency" >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PANEL_ROOT="${ACME_PANEL_ROOT:-$HOME/acme-dns-panel}"
mkdir -p -- "$PANEL_ROOT"
PANEL_ROOT="$(cd -- "$PANEL_ROOT" && pwd)"
if [[ "$PANEL_ROOT" == / || "$PANEL_ROOT" == "$HOME" ]]; then
  echo '请指定独立的数据目录，不使用 / 或家目录本身。' >&2; exit 1
fi
if [[ "$PANEL_ROOT" == *$'\n'* || "$PANEL_ROOT" == *$'\r'* || "$PANEL_ROOT" == *"'"* || "$PANEL_ROOT" == *'"'* || "$PANEL_ROOT" == *'%'* || "$PANEL_ROOT" == *'\'* ]]; then
  echo '安装路径不支持换行、引号、百分号或反斜杠。' >&2; exit 1
fi
for directory in app acme accounts ssl-renew data logs; do
  [[ ! -L "$PANEL_ROOT/$directory" ]] || { echo '安装目录不能是符号链接。' >&2; exit 1; }
  mkdir -p -- "$PANEL_ROOT/$directory"
  chmod 700 "$PANEL_ROOT/$directory"
done
chmod 700 "$PANEL_ROOT"
[[ ! -L "$PANEL_ROOT/scripts" && ! -L "$PANEL_ROOT/.panel-install.json" ]] || { echo '脚本目录和安装标记不能是符号链接。' >&2; exit 1; }
mkdir -p -- "$PANEL_ROOT/scripts"
if [[ "$SOURCE_DIR" != "$PANEL_ROOT" ]]; then
  cp -- "$SOURCE_DIR/scripts/uninstall.sh" "$SOURCE_DIR/scripts/uninstall.py" "$PANEL_ROOT/scripts/"
fi
cp -R -- "$SOURCE_DIR/panel" "$PANEL_ROOT/app/"
cp -- "$SOURCE_DIR/requirements.txt" "$PANEL_ROOT/app/requirements.txt"
if [[ "$SOURCE_DIR" != "$PANEL_ROOT" ]]; then
  cp -- "$SOURCE_DIR/README.md" "$PANEL_ROOT/README.md"
fi
if [[ ! -f "$PANEL_ROOT/config.toml" ]]; then
  cp -- "$SOURCE_DIR/config.example.toml" "$PANEL_ROOT/config.toml"
fi
python3 -m venv "$PANEL_ROOT/venv"
"$PANEL_ROOT/venv/bin/python" -m pip install -r "$PANEL_ROOT/app/requirements.txt"

# Pin and checksum the upstream release; never pipe remote content directly to sh.
ACME_VERSION=3.1.1
ACME_SHA256=c5d623ac0af400e83cd676aefaf045228f60e9fc597fea5db4c3a5bd7f6bfcf4
if [[ ! -f "$PANEL_ROOT/acme/acme.sh" ]]; then
  BUILD_DIR="$(mktemp -d)"
  trap 'rm -rf -- "$BUILD_DIR"' EXIT
  curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://codeload.github.com/acmesh-official/acme.sh/tar.gz/refs/tags/$ACME_VERSION" -o "$BUILD_DIR/acme.tar.gz"
  printf '%s  %s\n' "$ACME_SHA256" "$BUILD_DIR/acme.tar.gz" | sha256sum -c -
  tar -xzf "$BUILD_DIR/acme.tar.gz" -C "$BUILD_DIR"
  (cd "$BUILD_DIR/acme.sh-$ACME_VERSION" && sh ./acme.sh --install --no-cron --no-profile \
    --home "$PANEL_ROOT/acme" --config-home "$PANEL_ROOT/acme")
  printf '%s\n' "$ACME_VERSION" > "$PANEL_ROOT/acme/panel-version"
fi

# Initialize the database without launching listeners or making any CA requests.
(cd "$PANEL_ROOT/app" && ACME_PANEL_ROOT="$PANEL_ROOT" "$PANEL_ROOT/venv/bin/python" -c \
  'from panel.web import create_apps; create_apps()')
ACME_PANEL_ROOT="$PANEL_ROOT" "$PANEL_ROOT/venv/bin/python" - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ['ACME_PANEL_ROOT']).resolve()
(root / '.panel-install.json').write_text(json.dumps({
    'application': 'acme-dns-panel', 'root': str(root), 'uid': os.getuid()
}), encoding='utf-8')
PY

if [[ "$INSTALL_SERVICE" == 1 ]]; then
  command -v systemctl >/dev/null || { echo '无 systemd，请使用 --no-service 并手动启动。' >&2; exit 1; }
  SERVICE_USER="$(id -un)"
  SERVICE_GROUP="$(id -gn)"
  # The unit lives in the unified directory; only its systemd registration is outside it.
  cat > "$PANEL_ROOT/data/acme-dns-panel.service" <<EOF
[Unit]
Description=ACME DNS Panel and LAN Certificate Library
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory="$PANEL_ROOT/app"
Environment="ACME_PANEL_ROOT=$PANEL_ROOT"
ExecStart="$PANEL_ROOT/venv/bin/python" -m panel
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths="$PANEL_ROOT"
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 644 "$PANEL_ROOT/data/acme-dns-panel.service" /etc/systemd/system/acme-dns-panel.service
  sudo systemctl daemon-reload
  sudo systemctl enable acme-dns-panel
  sudo systemctl restart acme-dns-panel
fi
printf '\n安装完成：%s\n管理员：admin / 初始密码：admin\n管理：http://127.0.0.1:8080\n只读：http://服务器局域网IP:8001\n' "$PANEL_ROOT"

