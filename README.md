# ACME DNS Panel

当前版本：`26.10.6`。

轻量的 acme.sh 网页管理工具，支持 DNS 账户管理、普通及通配证书签发、自动续期和局域网证书下载。

## 首次部署（Linux）

要求 Python 3.8+、venv、curl、tar、openssl、sha256sum 和 systemd。以证书所属的普通用户运行，不要直接使用 root。

```bash
# Debian / Ubuntu：如缺少依赖
sudo apt-get install python3 python3-venv curl tar openssl

# 在本项目源码目录执行
bash scripts/install.sh

# 或指定统一安装目录
ACME_PANEL_ROOT=/home/vesoft/acme-dns-panel bash scripts/install.sh
```

默认使用 `python3`，版本不足时查找其他受支持版本。也可指定解释器：

```bash
sudo apt-get install python3.12-venv
ACME_PANEL_PYTHON=/usr/bin/python3.12 bash scripts/install.sh
```

安装脚本创建虚拟环境、安装独立的 acme.sh 3.1.1 并启动 systemd 服务。首次安装需要联网；重新执行可更新面板，保留配置、账户、密码和证书，不升级已有 acme.sh，也不影响原有 `~/.acme.sh`。

管理员账户为 `admin`，初始密码为 `admin`，请在「服务设置」中修改。

| 入口 | 默认地址 |
|---|---|
| 管理页面 | `http://服务器局域网IP:8080` |
| 只读下载页 | `http://服务器局域网IP:8001` |

## 统一目录

```text
~/acme-dns-panel/
├── app/                  # 面板程序
├── venv/                 # Python 运行环境
├── acme/                 # 独立的 acme.sh 程序、DNS 插件
├── accounts/<账户ID>/    # credentials.json、account.conf、CA 账户及 certs/
├── ssl-renew/<域名>/     # privkey.pem、fullchain.pem
├── data/panel.db         # 配置、密码哈希、会话和脱敏任务日志
├── data/acme-dns-panel.service
├── scripts/              # 卸载脚本
├── logs/
└── config.toml           # 监听地址、端口和任务超时
```

数据目录权限为 `700`，密钥和数据库为 `600`。DNS 凭据以明文受限文件保存，备份也需妥善保管。运行日志默认写入 systemd journal。

## 使用流程

1. 登录管理页面，在「服务设置」保存 ACME 联系邮箱。
2. 在「DNS 账户」选择服务商并填写凭据，支持同一服务商多个账户。
3. 添加主域名（如 `example.com`）并选择 DNS 账户。默认申请主域名及 `*.example.com`，使用 Let's Encrypt 和 ECC P-256。
4. 点击「申请证书」，在任务日志中查看进度。DNS 等待时间 0 为自动检查，也可设为 120 秒。
5. 签发后在只读页面查看证书有效期、复制下载链接或 wget 命令。

```bash
SERVER_IP='替换为服务器实际局域网IP'
wget "http://${SERVER_IP}:8001/example.com/fullchain.pem"
wget "http://${SERVER_IP}:8001/example.com/privkey.pem"
```

下载地址随访问主机和下载端口自动生成。HTTP 环境不支持剪贴板 API 时，页面会弹出地址供手动复制。

### 客户端脚本下载

在管理页「客户端脚本」保存共享模板，可使用仓库中的 [ssl-renew.sh](ssl-renew.sh)。只读页为每张证书提供适配后的脚本，地址为 `http://服务器局域网IP:下载端口/<主域名>/ssl-renew.sh`。

下载时自动替换单行 `DOMAIN`、`FULLCHAIN_URL`、`PRIVKEY_URL` 配置，也支持 `{{DOMAIN}}`、`{{FULLCHAIN_URL}}`、`{{PRIVKEY_URL}}`、`{{DOWNLOAD_BASE}}` 占位符。以 `example.com` 为示例的域名、目录和日志路径也会替换；自定义路径建议引用 `${DOMAIN}`。

模板上限为 256 KiB，下载使用 UTF-8 和 Linux 换行符。清空并保存可关闭脚本下载。

### 快速部署

在管理页「快速部署」导入或编辑 nginx 模板，点击保存后生效。支持 `.conf` / `.txt` 文件，上限为 256 KiB；模板必须包含且只支持 `{{SERVICE_DOMAIN}}`、`{{CERT_DIR}}`、`{{PROXY_PORT}}` 三种占位符。证书路径建议加双引号，`$host`、`$scheme` 等 nginx 变量会保留。

客户端脚本须先配置，除 `DOMAIN`、证书下载地址外，还需包含 `CERT_DIR`、`LOG_DIR`、`LOG_FILE`、`NGINX_RELOAD_CMD` 单行配置。

在只读页选择未过期的证书，填写服务域名和反向代理端口，生成两组命令，依次在目标 Linux 服务器执行：

1. **部署证书**：需要 Bash、wget、OpenSSL、crontab、flock 及可访问的下载地址。证书和脚本保存到 `~/ssl/<证书主域名>/`，日志保存到 `~/ssl/logs/`；保留已有 cron，并添加每天 03:00（目标机时区）的更新任务，重复执行会去重。
2. **配置 nginx**：需已安装并启动 nginx，且 `http` 块加载 `/etc/nginx/conf.d/*.conf`。命令备份并写入 `/etc/nginx/conf.d/<服务域名>.conf`，通过 `nginx -t` 后重载，失败则恢复原配置。

两组命令应以同一部署用户执行，路径取该用户的 `$HOME`；家目录仅支持 ASCII 字母、数字及 `_./-`。服务域名必须匹配证书，通配符只匹配一级子域名。

nginx 配置需要 sudo 权限，并须能访问家目录中的证书。后续自动更新使用 `/usr/sbin/nginx -t` 和 `/usr/sbin/nginx -s reload`，普通用户需配置对应的无密码 sudo 权限。

面板负责签发和续期，目标机定时下载更新后的证书。面板只生成部署命令，执行结果和更新日志在目标机查看。

#### 反向代理路径与排错

只读页可以放在 `/download/` 等子路径下。页面的静态资源、证书列表、快速部署 API 和下载链接均使用该前缀；nginx 应将整个前缀转发到下载服务，并删除前缀。例如下载端口为 8081：

```nginx
location = /download {
    return 301 /download/$is_args$args;
}
location ^~ /download/ {
    proxy_pass http://127.0.0.1:8081/;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

快速部署 API 由下载服务提供，需与该前缀一起代理，不能转发到管理端口。

请求失败时可展开「查看错误详情」，按请求编号查找服务日志：

```bash
sudo journalctl -u acme-dns-panel -n 100 --no-pager
```

代理错误查看 nginx 日志；目标机证书更新日志位于 `~/ssl/logs/ssl-renew-<证书主域名>.log`。

### DNS 服务商

| 服务商 | acme.sh 插件 | 凭据环境变量 |
|---|---|---|
| 阿里云 | dns_ali | Ali_Key、Ali_Secret |
| 腾讯云 | dns_tencent | Tencent_SecretId、Tencent_SecretKey |
| DNSPod 传统 Token | dns_dp | DP_Id、DP_Key |
| Cloudflare | dns_cf | CF_Token；CF_Account_ID、CF_Zone_ID 可选 |
| 华为云 | dns_huaweicloud | HUAWEICLOUD_Username、HUAWEICLOUD_Password、HUAWEICLOUD_DomainName |

凭据需具有目标域名 DNS 记录的读取、添加和删除权限。Cloudflare Token 需包含 Zone / DNS / Edit、Zone / Zone / Read；华为云的 DomainName 是华为云账户名。

编辑账户时留空保留原值，可选字段填 `-` 可清空。凭据不支持单引号、换行或空字符。

## 自动续期与任务

已签发且开启自动续期的域名，每 24 小时执行一次 `acme.sh --renew`，由 acme.sh 判断是否需要续期。下载地址保持不变，无需为面板另设 cron。

任务串行执行，默认超时一小时。重启后等待中的任务继续，运行中的任务标记为中断；页面显示最近 100 条任务，最多保留 200 条已结束记录。

域名可修改 DNS 等待时间和自动续期开关。更换主域名、DNS 账户、SAN、CA 或密钥类型需移除后重新添加。移除需验证管理员密码，随后停止续期和下载，磁盘证书及 acme.sh 状态保留；重新添加后需重新申请。不支持自动导入现有 `~/.acme.sh` 证书。

默认 CA 为 Let's Encrypt，也可选择 ZeroSSL 或自定义 HTTPS ACME Directory。ZeroSSL 使用联系邮箱获取 EAB 并注册；自定义 CA 如需 EAB，须先在对应 acme.sh 账户中注册。Buypass 选项已标记停用；旧测试 CA 配置继续保留，切换正式 CA 需重新添加域名。

## 服务配置

编辑统一目录内的 `config.toml`，重启服务使其生效：

```toml
[service]
admin_host = "0.0.0.0"
admin_port = 8080
public_host = "0.0.0.0"
public_port = 8001
secure_cookie = false
task_timeout = 3600
```

下载端口也可在「服务设置」中修改并重载，成功后自动保存，失败则保留原服务。

下载页免认证且提供私钥，下载端口仅应向可信局域网开放。管理页通过 HTTPS 反向代理访问时设置 `secure_cookie=true`，代理保留根路径 `/`，可参考 [nginx-ssl.conf](nginx-ssl.conf)。

如只需本机访问，将 `admin_host` 设为 `127.0.0.1`，远程使用 SSH 转发：

```bash
ssh -L 8080:127.0.0.1:8080 用户名@服务器IP
```

常用维护命令：

```bash
sudo systemctl status acme-dns-panel
sudo systemctl restart acme-dns-panel
sudo journalctl -u acme-dns-panel -f
```

### 不使用 systemd

```bash
bash scripts/install.sh --no-service
cd ~/acme-dns-panel/app
ACME_PANEL_ROOT=~/acme-dns-panel ../venv/bin/python -m panel
```

### 备份和迁移

停止服务后备份整个安装目录。迁移时保持相同的绝对路径，重新运行安装脚本创建本机虚拟环境并注册服务。

## 卸载（Linux）

使用安装时的普通用户执行。默认停止服务并移除程序、虚拟环境和本面板安装的 acme.sh，保留账户、证书、数据库、配置和日志，重新安装可恢复。

```bash
# 从源码目录执行
bash scripts/uninstall.sh

# 自定义安装目录
ACME_PANEL_ROOT=/home/vesoft/acme-dns-panel bash scripts/uninstall.sh

# 或直接使用安装目录内附带的卸载脚本
bash ~/acme-dns-panel/scripts/uninstall.sh

# 完全删除安装数据：要求输入完整安装目录确认
bash scripts/uninstall.sh --purge

# 对应 --no-service 安装，先停止手动运行的进程
bash scripts/uninstall.sh --no-service
```

`--purge` 删除已知运行目录及数据文件，保留源码和卸载脚本；自动化执行可追加 `--yes` 跳过确认。旧版安装如缺少卸载标记，需先重新运行安装脚本。

## 本地开发与测试

Windows 可预览网页、配置账户与运行测试，真实签发和安装脚本需要 Linux。

```powershell
python -m pip install -r requirements-dev.txt
$env:ACME_PANEL_ROOT = "$PWD/.runtime"
python -m panel
# 管理：http://127.0.0.1:8080  只读：http://127.0.0.1:8001
```

```bash
python -m pytest -q
```

测试使用临时目录、模拟 acme.sh 子进程和临时自签证书，不向真实 DNS 服务商或 CA 发请求。
