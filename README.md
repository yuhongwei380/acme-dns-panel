# ACME DNS Panel

当前面板版本：`0.1.1`。

轻量的 acme.sh 网页管理工具：DNS 账户、普通/通配证书、每日续期检查，以及局域网免认证证书下载页面。

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

Ubuntu 20.04 默认的 Python 3.8、Ubuntu 22.04 默认的 Python 3.10 均已满足要求，可直接使用上面的默认安装命令。如果希望使用已安装的 Python 3.12，可安装对应的 venv 包并显式选择该解释器：

```bash
sudo apt-get install python3.12-venv
ACME_PANEL_PYTHON=/usr/bin/python3.12 bash scripts/install.sh
# 如果已经位于 scripts 目录：
ACME_PANEL_PYTHON=/usr/bin/python3.12 bash install.sh
```

脚本优先检查 `python3`，版本不足时自动尝试 `python3.14`、`python3.13`、`python3.12`、`python3.11`、`python3.10`、`python3.9`、`python3.8`。设置 `ACME_PANEL_PYTHON` 时只使用指定解释器，失败会明确报错；选中的解释器用于创建虚拟环境，后续服务使用虚拟环境中的 Python。不需要修改系统默认 `python3`。

安装脚本创建 Python 虚拟环境，安装并校验固定版本 acme.sh 3.1.1，初始化数据库，再通过 sudo 注册并启动 systemd 服务。不会修改原有 `~/.acme.sh`、shell 配置或 cron。首次部署需要联网；普通安装不会升级已安装的 acme.sh。重复执行保留配置、账户、密码与证书。

默认管理员用户名固定为 **admin**，无需填写。默认密码为 **admin**，登录时必须输入；密码框有显示/隐藏图标。可在服务设置中更改密码，修改后所有会话失效。

管理页面默认监听 `0.0.0.0:8080`，可通过 `http://服务器实际局域网IP:8080` 访问；只读页面为 `http://服务器实际局域网IP:8001`。如希望仅本机访问，可将 `admin_host` 改为 `127.0.0.1`，远程访问使用 SSH 转发：

```bash
SERVER_IP='替换为服务器实际局域网IP'
ssh -L 8080:127.0.0.1:8080 "用户名@${SERVER_IP}"
```

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
├── logs/                # 预留；运行日志默认进入 systemd journal
└── config.toml           # 监听地址、端口和任务超时
```

数据目录自动设置 700 权限，密钥和数据库设置 600 权限；Linux 服务使用 umask 0077。DNS 账户密钥以明文受限文件保存，acme.sh 也会在其账户/域名配置中保存密钥，因此备份需按敏感数据处理。Web API 不返回这些值。

## 使用流程

1. 使用服务器实际局域网 IP 打开管理页面，登录后在「服务设置」填写 ACME 联系邮箱。下载地址自动使用当前访问主机与下载端口，无需填写 IP。下载端口默认 8001，可修改后点击「重载下载服务」立即生效。
2. 在「DNS 账户」选择服务商并填写凭据，支持同一服务商多个账户。
3. 添加主域名，例如 `example.com`，添加前必须先保存 ACME 联系邮箱；未填写时提示前往「服务设置」，并阻止添加。仅选择已有的 DNS 账户，不在此流程中创建或配置账户。未检测到 DNS 账户，或者选定账户的凭据缺失时，禁止添加并报错。默认同时申请 `example.com` 与 `*.example.com`，使用 Let's Encrypt 和 ECC P-256。添加域名仅保存配置，不会自动申请证书。
4. 点击「申请证书」，在任务日志中查看进度。DNS 等待时间 0 为自动检查，也可设为 120 秒。
5. 签发后在只读页面查看证书有效期、复制下载链接或 wget 命令。

```bash
SERVER_IP='替换为服务器实际局域网IP'
wget "http://${SERVER_IP}:8001/example.com/fullchain.pem"
wget "http://${SERVER_IP}:8001/example.com/privkey.pem"
```

普通局域网 HTTP 可能禁止剪贴板 API，此时页面弹出并选中地址，可按 Ctrl+C 或长按复制。HTTPS 环境通常支持一键复制。

代码没有固定服务器 IP：管理页面的下载链接使用当前访问主机与正在运行的下载端口，只读页面使用自身访问地址。请通过服务器实际局域网 IP 或局域网可解析的主机名访问。旧版保存的对外下载地址不再使用。

下载服务支持单独重载：在「服务设置」修改下载端口，点击「重载下载服务」后自动保存到 config.toml，重启后仍使用新端口。新端口监听成功才替换旧服务；端口被占用或无法保存配置时保留原服务并提示错误。管理端口、登录会话和证书任务不受影响。新端口需允许局域网客户端访问。重载记录可通过 `journalctl -u acme-dns-panel` 查看。

### 客户端脚本下载

管理页「客户端脚本」编辑一份共享模板，只读页每张可下载证书的卡片提供自己的 `ssl-renew.sh`。地址为 `http://服务器实际局域网IP:下载端口/<主域名>/ssl-renew.sh`，免登录下载。下载时会自动填入该域名，以及请求所用的下载服务地址和端口，避免多张证书共用写死的配置。

建议通用脚本使用 `example.com` 作为示例域名，证书下载地址使用 `http://示例主机:端口/example.com/fullchain.pem` 和 `privkey.pem`。下载时自动替换这些地址，以及脚本目录和日志路径中的 `example.com`。兼容脚本中的单行 `DOMAIN=...`、`FULLCHAIN_URL=...`、`PRIVKEY_URL=...` 配置，下载时自动替换其值；也支持 `{{DOMAIN}}`、`{{FULLCHAIN_URL}}`、`{{PRIVKEY_URL}}`、`{{DOWNLOAD_BASE}}` 占位符。客户端证书目录和日志路径应引用 `${DOMAIN}` 区分不同证书。脚本缺少域名或下载地址配置时，不提供适配后的下载；旧的 `/ssl-renew.sh` 地址必须显式携带 `?domain=<主域名>`。

无需配置脚本变量表单；脚本不会在证书服务器上执行。内容保存在面板数据库中，限制为 256 KiB，下载使用 UTF-8 编码和 Linux 换行符。清空内容并保存可停止提供下载。

### DNS 服务商

| 服务商 | acme.sh 插件 | 凭据环境变量 |
|---|---|---|
| 阿里云 | dns_ali | Ali_Key、Ali_Secret |
| 腾讯云 | dns_tencent | Tencent_SecretId、Tencent_SecretKey |
| DNSPod 传统 Token | dns_dp | DP_Id、DP_Key |
| Cloudflare | dns_cf | CF_Token；CF_Account_ID、CF_Zone_ID 可选 |
| 华为云 | dns_huaweicloud | HUAWEICLOUD_Username、HUAWEICLOUD_Password、HUAWEICLOUD_DomainName |

字段对应 acme.sh 3.1.1 插件要求。华为云的 DomainName 是华为云账户名，不是申请证书的域名。账户应具有对应区域 DNS 记录读取、添加和删除权限；Cloudflare Token 通常需要 Zone / DNS / Edit、Zone / Zone / Read。

编辑账户时，留空保留原值；可选字段填 `-` 可清空。密钥变更会通过环境变量用于后续签发与续期，并清除 acme.sh 缓存的旧 DNS 字段。此固定版本 acme.sh 以 shell 单引号存储凭据，因此面板拒绝包含单引号、换行或空字符的凭据。

## 自动续期与任务

面板每分钟检查调度状态，对已首次签发且启用自动续期的域名，每 24 小时执行一次 `acme.sh --renew`。acme.sh 判断是否到期，未到续期时间不会重新申请；不使用 `--force`。`--install-cert` 固定安装到统一目录，续期后下载地址不变。无需另设 cron；本服务暂停时不会检查续期。

任务在一个进程内串行执行，Linux 使用目录锁避免重复启动。任务超时默认一小时，超时或服务关闭会终止子进程。等待任务持久化，重启后继续；运行任务标记为中断。日志脱敏并限长，保留最多 200 条已结束任务（页面显示最近 100 条）。

可更改域名的等待时间和自动续期开关。第一版不允许直接修改已添加域名的主域名、DNS 账户、SAN、CA 或密钥类型，以避免隐式覆盖申请。移除域名证书和 DNS 账户均需再次输入当前管理员密码，后端校验通过才执行。移除域名会停止续期并撤下公开下载，磁盘证书及 acme.sh 状态保留；重新添加域名使用独立的签发状态目录，需重新申请后才开放下载。暂不提供现有 `~/.acme.sh` 证书自动导入。

证书颁发机构默认使用正式版 Let's Encrypt，选项包括 Let's Encrypt、ZeroSSL、Buypass 和「其他」，不再预置测试环境。「其他」允许填写完整 HTTPS ACME Directory 地址。ZeroSSL 由 acme.sh 使用服务设置中的联系邮箱自动获取 EAB 并注册；需要额外 EAB 的自定义 CA 应先在对应 acme.sh 账户中完成注册。Buypass 已停止 TLS/SSL 签发与续期，选项保留并明确提示停用（[官方公告](https://www.buypass.com/products/tls-ssl-certificates/discontinues-issuance-of-tls-ssl-certificates)）。旧版测试 CA 域名保留原配置和非受信任标识，不会自动切换；改用正式 CA 需移除后重新添加。

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

管理页需要密码，免认证下载服务仅开放数据库中仍管理的域名的 `fullchain.pem`、`privkey.pem`；不开放目录浏览、DNS 密钥或管理 API。下载包括私钥，8001 端口应限制在可信局域网，不能直接暴露到公网。

管理页默认允许局域网访问。已有 config.toml 会保留原配置；升级时如仍为 `127.0.0.1`，请改为 `0.0.0.0` 后重启服务。通过 HTTPS 反向代理管理页时，设置 `secure_cookie=true`；代理时保留根路径 `/`。默认密码按需求设为 admin，建议部署后自行修改。会话有效期 12 小时，使用 HttpOnly / SameSite Cookie、CSRF Token 和登录失败限速。

```bash
sudo systemctl status acme-dns-panel
sudo systemctl restart acme-dns-panel
journalctl -u acme-dns-panel -f
```

### 不使用 systemd

```bash
bash scripts/install.sh --no-service
cd ~/acme-dns-panel/app
ACME_PANEL_ROOT=~/acme-dns-panel ../venv/bin/python -m panel
```

### systemd 服务文件校验

安装脚本在注册服务前使用 `systemd-analyze verify` 校验生成的 unit（系统提供此命令时）。`WorkingDirectory` 使用不带引号的绝对路径；`Environment` 和 `ExecStart` 按各自的 systemd 语法处理引号。

如果旧版安装报 `bad unit file setting`，可先修复两个服务文件的 WorkingDirectory，再重新加载和启动：

```bash
# 默认安装目录；自定义部署时改为实际目录
PANEL_ROOT="$HOME/acme-dns-panel"
sed -i 's/^WorkingDirectory="\(.*\)"$/WorkingDirectory=\1/' "$PANEL_ROOT/data/acme-dns-panel.service"
sudo sed -i 's/^WorkingDirectory="\(.*\)"$/WorkingDirectory=\1/' /etc/systemd/system/acme-dns-panel.service
sudo systemd-analyze verify /etc/systemd/system/acme-dns-panel.service
sudo systemctl daemon-reload
sudo systemctl restart acme-dns-panel
sudo systemctl status acme-dns-panel --no-pager
```

### 备份和迁移

停止服务后备份整个统一目录。迁移后重新运行部署脚本建立本机虚拟环境、重新注册 systemd 服务。acme.sh 安装记录中包含绝对路径，第一版迁移要求保持相同的根目录路径，尚不支持自动重写迁移路径；不把原主机 venv 作为跨机器可用环境。

## 卸载（Linux）

使用安装时的普通用户执行。默认停止并取消 systemd 开机启动，移除面板程序、虚拟环境和本面板安装的 acme.sh，保留 DNS 账户、CA 账户、证书、数据库、配置和日志。重新安装可恢复使用；卸载期间停止自动续期和 HTTP 下载。

```bash
# 从源码目录执行
bash scripts/uninstall.sh

# 自定义安装目录
ACME_PANEL_ROOT=/home/vesoft/acme-dns-panel bash scripts/uninstall.sh

# 或直接使用安装目录内附带的卸载脚本
bash ~/acme-dns-panel/scripts/uninstall.sh

# 完全删除安装数据：要求输入完整安装目录确认
bash scripts/uninstall.sh --purge

# 自动化清理时，显式跳过数据删除确认
bash scripts/uninstall.sh --purge --yes

# 对应 --no-service 安装，先停止手动运行的进程
bash scripts/uninstall.sh --no-service
```

`--purge` 只删除已知运行目录及数据文件，不删除整个根目录，源码、README 和卸载脚本保留。脚本校验安装标记、目录所属用户、符号链接、服务归属和运行锁，不操作原有 `~/.acme.sh` 或其他安装。新版安装脚本会生成卸载标记；旧版安装目录需先重新执行安装脚本。无需卸载系统 Python、curl、openssl 等共享依赖，也不清除系统 journal 中的历史运行日志。

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
