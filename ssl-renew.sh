#!/bin/bash
# ============================================================
# SSL 证书自动续期脚本（兼容 RSA / ECC）
# 功能：每天检查证书到期时间
#   - 剩余天数 < 0：已过期，立即执行替换
#   - 0 <= 剩余天数 <= RENEW_BEFORE_DAYS：即将到期，执行替换
#   - 否则跳过
# 备份：每次替换前备份旧证书，最多保留最近 2 个
# 用法：配置好下方变量后，加入 crontab 每天执行一次
# ============================================================

# ---------------------- 需要你填写的配置 ----------------------
# 域名（替换成你自己的真实域名，示例为 vesoft-inc.com）
DOMAIN="vesoft-inc.com"

# 证书所在目录（privkey.pem 和 fullchain.pem 所在的目录）
CERT_DIR="/home/vesoft/ssl/${DOMAIN}"

# 提前多少天续期（N-1 天替换。举例：希望提前 5 天，则填 5）
RENEW_BEFORE_DAYS=5

# 证书下载地址
FULLCHAIN_URL="http://192.168.8.24:8081/${DOMAIN}/fullchain.pem"
PRIVKEY_URL="http://192.168.8.24:8081/${DOMAIN}/privkey.pem"

# nginx reload 命令（写全路径更稳妥，避免 cron PATH 不全）
# 若用 root 跑，建议去掉 sudo：NGINX_RELOAD_CMD="/usr/sbin/nginx -s reload"
NGINX_RELOAD_CMD="sudo /usr/sbin/nginx -s reload"

# 日志目录（用户可写路径，避免 /var/log 权限问题）
LOG_DIR="/home/vesoft/ssl/logs"
LOG_FILE="${LOG_DIR}/ssl-renew-${DOMAIN}.log"

# 备份保留数量（最多保留最近 N 个）
BACKUP_KEEP=2
# --------------------------------------------------------------

CERT_FILE="${CERT_DIR}/fullchain.pem"
KEY_FILE="${CERT_DIR}/privkey.pem"

# 确保日志目录存在
mkdir -p "$LOG_DIR" 2>/dev/null

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ---------- 检查证书文件 ----------
if [ ! -f "$CERT_FILE" ]; then
    log "ERROR: 证书文件不存在: $CERT_FILE"
    exit 1
fi

expire_date=$(openssl x509 -in "$CERT_FILE" -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -z "$expire_date" ]; then
    log "ERROR: 无法读取证书到期时间，文件可能损坏: $CERT_FILE"
    exit 1
fi

expire_ts=$(date -d "$expire_date" +%s)
now_ts=$(date +%s)
days_left=$(( (expire_ts - now_ts) / 86400 ))

log "证书 ${DOMAIN} 剩余 ${days_left} 天到期（到期时间: ${expire_date}）"

# ---------- 判断是否需要替换 ----------
if [ "$days_left" -lt 0 ]; then
    log "警告：证书已过期 ${days_left#-} 天，立即执行替换！"
elif [ "$days_left" -le "$RENEW_BEFORE_DAYS" ]; then
    log "证书剩余 ${days_left} 天，达到续期阈值（${RENEW_BEFORE_DAYS} 天），执行替换。"
else
    log "证书剩余 ${days_left} 天，未到达续期阈值（${RENEW_BEFORE_DAYS} 天），跳过。"
    exit 0
fi

# ---------- 下载新证书（先下到临时文件） ----------
log "开始下载新证书..."
tmp_fullchain="$(mktemp)"
tmp_privkey="$(mktemp)"

if ! wget -q -O "$tmp_fullchain" "$FULLCHAIN_URL"; then
    log "ERROR: 下载 fullchain.pem 失败: $FULLCHAIN_URL"
    rm -f "$tmp_fullchain" "$tmp_privkey"
    exit 1
fi

if ! wget -q -O "$tmp_privkey" "$PRIVKEY_URL"; then
    log "ERROR: 下载 privkey.pem 失败: $PRIVKEY_URL"
    rm -f "$tmp_fullchain" "$tmp_privkey"
    exit 1
fi

# ---------- 校验证书合法性 ----------
if ! openssl x509 -in "$tmp_fullchain" -noout >/dev/null 2>&1; then
    log "ERROR: 下载的 fullchain.pem 不是有效证书，放弃替换。"
    rm -f "$tmp_fullchain" "$tmp_privkey"
    exit 1
fi

# ---------- 校验证书与私钥是否匹配（兼容 RSA / ECC） ----------
cert_pub=$(openssl x509 -in "$tmp_fullchain" -noout -pubkey 2>/dev/null | openssl md5)
key_pub=$(openssl pkey -in "$tmp_privkey" -pubout 2>/dev/null | openssl md5)

if [ -z "$cert_pub" ] || [ -z "$key_pub" ]; then
    log "ERROR: 无法提取证书或私钥公钥，文件可能无效，放弃替换。"
    rm -f "$tmp_fullchain" "$tmp_privkey"
    exit 1
fi

if [ "$cert_pub" != "$key_pub" ]; then
    log "ERROR: 证书与私钥不匹配，放弃替换。"
    rm -f "$tmp_fullchain" "$tmp_privkey"
    exit 1
fi

key_algo=$(openssl x509 -in "$tmp_fullchain" -noout -text 2>/dev/null | grep -m1 'Public Key Algorithm' | awk -F: '{print $2}' | xargs)
log "证书与私钥校验通过（密钥类型: ${key_algo:-unknown}）。"

# ---------- 备份旧证书 ----------
backup_dir="${CERT_DIR}/backup_$(date +%Y%m%d%H%M%S)"
mkdir -p "$backup_dir"
cp -a "$CERT_FILE" "$backup_dir/" 2>/dev/null
cp -a "$KEY_FILE"  "$backup_dir/" 2>/dev/null
log "旧证书已备份到: $backup_dir"

# 只保留最近 N 个备份，删除更早的
ls -1dt "${CERT_DIR}"/backup_* 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -rf
log "已清理旧备份，仅保留最近 ${BACKUP_KEEP} 个。"

# ---------- 替换证书 ----------
mv "$tmp_fullchain" "$CERT_FILE"
mv "$tmp_privkey"   "$KEY_FILE"
chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"
log "证书已替换: $CERT_FILE / $KEY_FILE"

# ---------- reload nginx ----------
if eval "$NGINX_RELOAD_CMD" >>"$LOG_FILE" 2>&1; then
    log "nginx reload 成功。"
else
    log "ERROR: nginx reload 失败，请检查配置！"
    exit 1
fi

log "证书续期流程完成。"
exit 0
