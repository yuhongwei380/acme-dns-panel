"""Generate commands for execution on the client, never on the panel host."""

import hashlib
import re
import shlex

from .client_scripts import assignment_pattern, render_script


DEFAULT_NGINX_TEMPLATE = """# HTTP 强制跳转 HTTPS
server {
    listen 80;
    server_name {{SERVICE_DOMAIN}};
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name {{SERVICE_DOMAIN}};
    ssl_certificate "{{CERT_DIR}}/fullchain.pem";
    ssl_certificate_key "{{CERT_DIR}}/privkey.pem";
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    location / {
        proxy_pass http://127.0.0.1:{{PROXY_PORT}};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
"""

PLACEHOLDERS = {"SERVICE_DOMAIN", "CERT_DIR", "PROXY_PORT"}


def validate_template(content):
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in content or len(content.encode("utf-8")) > 262144:
        raise ValueError("模板不能包含空字符，且大小不能超过 256 KiB")
    found = set(re.findall(r"\{\{([^{}]+)\}\}", content))
    if found != PLACEHOLDERS or "{{" in re.sub(r"\{\{([^{}]+)\}\}", "", content):
        raise ValueError("模板必须包含且只支持 {{SERVICE_DOMAIN}}、{{CERT_DIR}}、{{PROXY_PORT}} 占位符")
    return content


def covers_domain(sans, service):
    return any(service == san.lower() or (
        san.startswith("*.") and service.partition(".")[2] == san[2:].lower()
    ) for san in sans)


def deployment_script(content, domain, base):
    if not assignment_pattern("DOMAIN").search(content):
        raise ValueError("快速部署要求客户端脚本包含单行 DOMAIN 配置，请管理员补充")
    content = render_script(content, domain, base)
    overrides = {
        "CERT_DIR": '"${HOME}/ssl/${DOMAIN}"',
        "LOG_DIR": '"${HOME}/ssl/logs"',
        "LOG_FILE": '"${LOG_DIR}/ssl-renew-${DOMAIN}.log"',
        "NGINX_RELOAD_CMD": "'if [ \"${ACME_SKIP_NGINX_RELOAD:-0}\" != 1 ]; then if [ \"$(id -u)\" = 0 ]; then /usr/sbin/nginx -t && /usr/sbin/nginx -s reload; else sudo -n /usr/sbin/nginx -t && sudo -n /usr/sbin/nginx -s reload; fi; fi'",
    }
    for name, value in overrides.items():
        if not assignment_pattern(name).search(content):
            raise ValueError("快速部署要求客户端脚本包含单行 " + name + " 配置，请管理员补充")
        content = assignment_pattern(name).sub(lambda match: match.group(1) + value, content)
    return content


def bash_command(body):
    delimiter = "ACME_DEPLOY_" + hashlib.sha256(body.encode()).hexdigest()[:16]
    return "bash <<'" + delimiter + "'\n" + body.rstrip() + "\n" + delimiter


def commands(domain, service, port, base, template):
    validate_template(template)
    # Ordinary absolute home paths only: safe for nginx strings and cron's parser.
    preamble = '''set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
case "$HOME" in
    /*) ;;
    *) echo "无法识别用户家目录" >&2; exit 1 ;;
esac
case "$HOME" in
    *[!a-zA-Z0-9_./-]*) echo "家目录包含不支持的字符，请手动部署" >&2; exit 1 ;;
esac
'''
    preamble += 'CERT_DIR="$HOME/ssl/' + domain + '"\n'
    url = base + "/" + domain + "/ssl-renew.sh?deployment=1"
    certificate = preamble + '''for tool in wget openssl crontab flock; do
    command -v "$tool" >/dev/null || { echo "缺少依赖: $tool" >&2; exit 1; }
done
umask 077
mkdir -p "$CERT_DIR"
exec 9>"$HOME/ssl/.deploy.lock"
flock 9
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
'''
    certificate += "wget -O \"$WORK_DIR/ssl-renew.sh\" " + shlex.quote(url) + "\n"
    certificate += '''bash -n "$WORK_DIR/ssl-renew.sh"
install -m 700 "$WORK_DIR/ssl-renew.sh" "$CERT_DIR/ssl-renew.sh"
ACME_SKIP_NGINX_RELOAD=1 /bin/bash "$CERT_DIR/ssl-renew.sh"
if ! LC_ALL=C crontab -l >"$WORK_DIR/current.cron" 2>"$WORK_DIR/cron.err"; then
    if ! grep -q 'no crontab for' "$WORK_DIR/cron.err"; then
        cat "$WORK_DIR/cron.err" >&2; exit 1
    fi
    : >"$WORK_DIR/current.cron"
fi
'''
    marker = "# acme-dns-panel:" + domain
    certificate += "awk -v marker=" + shlex.quote(marker) + " 'substr($0, length($0)-length(marker)+1) != marker' \"$WORK_DIR/current.cron\" >\"$WORK_DIR/next.cron\"\n"
    certificate += "printf '0 3 * * * /bin/bash \"%s/ssl-renew.sh\" " + marker + "\\n' \"$CERT_DIR\" >>\"$WORK_DIR/next.cron\"\n"
    certificate += '''crontab "$WORK_DIR/next.cron"
echo "证书部署完成，已添加每日 03:00 更新任务（目标服务器时区）。"
'''

    values = {"SERVICE_DOMAIN": service, "PROXY_PORT": str(port), "CERT_DIR": "{{CERT_DIR}}"}
    rendered = re.sub(r"\{\{(SERVICE_DOMAIN|PROXY_PORT|CERT_DIR)\}\}", lambda m: values[m[1]], template)
    delimiter = "NGINX_" + hashlib.sha256(rendered.encode()).hexdigest()[:16]
    nginx = preamble + '''as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi
}
command -v nginx >/dev/null || { echo "请先安装 nginx" >&2; exit 1; }
test -s "$CERT_DIR/fullchain.pem" && test -s "$CERT_DIR/privkey.pem" || {
    echo "请先以同一用户执行证书部署命令" >&2; exit 1;
}
as_root nginx -t
ACTIVE_CONFIG=$(as_root nginx -T 2>&1)
if ! printf '%s\\n' "$ACTIVE_CONFIG" | grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/conf[.]d/[*][.]conf[[:space:]]*;'; then
    echo "nginx 主配置需要在 http 块内加载 /etc/nginx/conf.d/*.conf，请先确认配置" >&2; exit 1
fi
umask 077
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
'''
    nginx += "CONFIG_FILE='/etc/nginx/conf.d/" + service + ".conf'\n"
    nginx += "cat >\"$WORK_DIR/template.conf\" <<'" + delimiter + "'\n" + rendered.rstrip() + "\n" + delimiter + "\n"
    nginx += '''CONFIG=$(cat "$WORK_DIR/template.conf")
CONFIG=${CONFIG//\\{\\{CERT_DIR\\}\\}/$CERT_DIR}
printf '%s\\n' "$CONFIG" >"$WORK_DIR/new.conf"
as_root mkdir -p /etc/nginx/conf.d
HAD_CONFIG=0
if as_root test -e "$CONFIG_FILE"; then
    HAD_CONFIG=1
    as_root cp -p "$CONFIG_FILE" "$WORK_DIR/previous.conf"
    BACKUP_FILE="$CONFIG_FILE.bak.$(date +%Y%m%d%H%M%S).$$"
    as_root cp -p "$CONFIG_FILE" "$BACKUP_FILE"
    echo "原配置已备份: $BACKUP_FILE"
fi
rollback() {
    if [ "$HAD_CONFIG" = 1 ]; then
        as_root cp -p "$WORK_DIR/previous.conf" "$CONFIG_FILE"
    else
        as_root rm -f "$CONFIG_FILE"
    fi
}
if ! as_root tee "$CONFIG_FILE" <"$WORK_DIR/new.conf" >/dev/null; then
    rollback; echo "写入失败，已恢复配置" >&2; exit 1
fi
if ! as_root nginx -t; then
    rollback; echo "检查失败，已恢复配置，未重载 nginx" >&2; exit 1
fi
if ! as_root nginx -s reload; then
    rollback
    as_root nginx -t && as_root nginx -s reload
    echo "重载失败，已恢复配置" >&2; exit 1
fi
echo "nginx 配置完成。请确保部署用户的证书目录允许 nginx 主进程访问。"
'''
    return {"certificate_command": bash_command(certificate), "nginx_command": bash_command(nginx)}
