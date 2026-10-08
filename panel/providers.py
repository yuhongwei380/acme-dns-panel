"""Environment variables verified against acme.sh 3.1.1 DNS plugins."""

PROVIDERS = [
    {"id": "ali", "name": "阿里云", "plugin": "dns_ali", "hint": "所需凭据：RAM 用户的 AccessKey ID、AccessKey Secret。\n所需权限：读取、添加和删除目标域名的 DNS 记录。",
     "fields": [{"name": "Ali_Key", "label": "AccessKey ID", "required": True},
                {"name": "Ali_Secret", "label": "AccessKey Secret", "required": True}]},
    {"id": "tencent", "name": "腾讯云", "plugin": "dns_tencent", "hint": "所需凭据：腾讯云 API 密钥 SecretId、SecretKey。\n所需权限：读取、添加和删除 DNSPod 中目标域名的 DNS 记录。",
     "fields": [{"name": "Tencent_SecretId", "label": "SecretId", "required": True},
                {"name": "Tencent_SecretKey", "label": "SecretKey", "required": True}]},
    {"id": "dp", "name": "DNSPod（传统 Token）", "plugin": "dns_dp", "hint": "所需凭据：DNSPod 传统 API Token 的 ID、Key。\n所需权限：读取、添加和删除目标域名的 DNS 记录。\n如果凭据是 SecretId / SecretKey，请选择「腾讯云」。",
     "fields": [{"name": "DP_Id", "label": "Token ID", "required": True},
                {"name": "DP_Key", "label": "Token Key", "required": True}]},
    {"id": "cf", "name": "Cloudflare", "plugin": "dns_cf", "hint": "所需凭据：Cloudflare API Token。\n所需权限：Zone → DNS → Edit（编辑 DNS 记录）；Zone → Zone → Read（读取域名区域信息）。\n授权范围：Token 必须包含要申请证书的主域名。",
     "fields": [{"name": "CF_Token", "label": "API Token", "required": True,
                 "help": "必填。填写 API Token，不是登录密码或 Global API Key。"},
                {"name": "CF_Account_ID", "label": "账户 ID（Account ID）", "required": False,
                 "help": "通常留空，自动查找。需限定 Cloudflare 账户时填写账户 ID。"},
                {"name": "CF_Zone_ID", "label": "区域 ID（Zone ID）", "required": False,
                 "help": "通常留空，自动查找。单个主域名可填写区域 ID；多个主域名请留空。填写 ID，不是域名。"}]},
    {"id": "huaweicloud", "name": "华为云", "plugin": "dns_huaweicloud", "hint": "所需凭据：IAM 用户名、IAM 用户密码、所属华为云账户名。\n所需权限：读取、添加和删除目标域名的 DNS 记录。\n华为云账户名是云账户名称，不是要申请证书的域名。",
     "fields": [{"name": "HUAWEICLOUD_Username", "label": "IAM 用户名", "required": True},
                {"name": "HUAWEICLOUD_Password", "label": "IAM 密码", "required": True},
                {"name": "HUAWEICLOUD_DomainName", "label": "华为云账户名", "required": True}]},
]
BY_ID = {p["id"]: p for p in PROVIDERS}
