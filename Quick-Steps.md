## 1、背景：
由于certbot自动申请ssl证书依赖443端口，受国内备案政策影响，无法通过http auth方式申请证书。

随着内网中的服务逐渐增多，以前ssl证书部署在内网的NAS上，随着运行发现：当NAS需要进行系统更新or维护时，nfs服务会中断，通过nfs挂载的vm或者服务器会出现 一些命令hang住，比如经典的df -h 长时间无响应。

 
## 2、内网SSL证书使用方法
### 2.1我们准备了内网的ssl证书自动更新脚本：
```
cd ~
mkdir -p ssl/domain.com/
cd ssl/
```
### 2.2在 `ssl/` 目录下导入脚本：
```
wget http://192.168.8.24:8081/domain.com/ssl-renew.sh
chmod a+x ssl-renew.sh
```
### 2.3首次本地执行，会自动检测是否已存在证书并且下载
```
bash ssl-renew.sh
```

### 2.4创建cron

crontab -e 
```
0 3 * * * /bin/bash /home/vesoft/ssl/ssl-renew.sh
```
