"""Environment variables verified against acme.sh 3.1.1 DNS plugins."""

PROVIDERS = [
    {"id": "ali", "name": "阿里云", "plugin": "dns_ali", "hint": "RAM 用户需要 DNS 记录读取、添加和删除权限。",
     "fields": [{"name": "Ali_Key", "label": "AccessKey ID", "required": True},
                {"name": "Ali_Secret", "label": "AccessKey Secret", "required": True}]},
    {"id": "tencent", "name": "腾讯云", "plugin": "dns_tencent", "hint": "使用腾讯云 API 密钥，需要 DNSPod 记录读取、添加和删除权限。",
     "fields": [{"name": "Tencent_SecretId", "label": "SecretId", "required": True},
                {"name": "Tencent_SecretKey", "label": "SecretKey", "required": True}]},
    {"id": "dp", "name": "DNSPod（传统 Token）", "plugin": "dns_dp", "hint": "DNSPod 传统 API Token，与腾讯云 SecretId / SecretKey 不同。",
     "fields": [{"name": "DP_Id", "label": "Token ID", "required": True},
                {"name": "DP_Key", "label": "Token Key", "required": True}]},
    {"id": "cf", "name": "Cloudflare", "plugin": "dns_cf", "hint": "推荐 API Token：Zone / DNS / Edit 与 Zone / Zone / Read。Account ID 和 Zone ID 可选。",
     "fields": [{"name": "CF_Token", "label": "API Token", "required": True},
                {"name": "CF_Account_ID", "label": "Account ID", "required": False},
                {"name": "CF_Zone_ID", "label": "Zone ID", "required": False}]},
    {"id": "huaweicloud", "name": "华为云", "plugin": "dns_huaweicloud", "hint": "此 acme.sh 插件使用 IAM 用户名、密码和账户名（不是 DNS 域名），需要 DNS 操作权限。",
     "fields": [{"name": "HUAWEICLOUD_Username", "label": "IAM 用户名", "required": True},
                {"name": "HUAWEICLOUD_Password", "label": "IAM 密码", "required": True},
                {"name": "HUAWEICLOUD_DomainName", "label": "华为云账户名", "required": True}]},
]
BY_ID = {p["id"]: p for p in PROVIDERS}

