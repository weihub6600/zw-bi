# 百嘉瑞 BI 灾难恢复步骤

适用站点：/www/wwwroot/bjr-bi
数据库：baijiarui_bi
数据库用户：baijiarui
当前版本：以 /www/wwwroot/bjr-bi/current/VERSION 为准

## 重要原则

1. 先确认备份文件，再恢复数据库。
2. 不要先执行 install.sh、init-schema、migrate 或 CREATE DATABASE。
3. 不要删除 shared、shared/backups、.env 或当前版本目录。
4. 数据库恢复前，先把当前状态再备份一份。

如果只是数据库丢失，但站点文件还在，通常只需要恢复数据库并重新启动后端。

## 1. 进入正确环境

进入运行宝塔的容器后，提示符应类似：

    root@xxxx:/www/wwwroot/bjr-bi#

如果 /www/wwwroot/bjr-bi 不存在，说明当前在 FNOS 宿主机或错误容器，不要重新安装。

    cd /www/wwwroot/bjr-bi
    APP=/www/wwwroot/bjr-bi

## 2. 确认站点和备份

    ls -lah "$APP"
    readlink -f "$APP/current"
    cat "$APP/current/VERSION"
    ls -lah "$APP/shared/backups/database/mysql/crontab_backup/baijiarui_bi"

数据库定时备份目录：

    /www/wwwroot/bjr-bi/shared/backups/database/mysql/crontab_backup/baijiarui_bi

选择修改时间最新、大小不为 0B 的 .sql 或 .sql.gz 文件。

## 3. 创建数据库

如果宝塔数据库列表没有 baijiarui_bi：

- 数据库名：baijiarui_bi
- 用户名：baijiarui
- 字符集：utf8mb4
- 排序规则：utf8mb4_general_ci
- 设置强密码并记录

如果用户已存在，不要删除用户，直接重置密码即可。

编辑：

    /www/wwwroot/bjr-bi/shared/.env

确认这些配置对应当前数据库密码：

    MYSQL_HOST=127.0.0.1
    MYSQL_PORT=3306
    MYSQL_DATABASE=baijiarui_bi
    MYSQL_USER=baijiarui
    MYSQL_PASSWORD=当前数据库密码

不要把 .env 内容发到聊天或上传到公开网盘。

## 4. 导入数据库

先确认客户端存在：

    ls -l /www/server/mysql/bin/mysql

.sql 文件导入：

    /www/server/mysql/bin/mysql -h127.0.0.1 -P3306 -ubaijiarui -p --protocol=TCP --default-character-set=utf8mb4 baijiarui_bi < /路径/备份文件.sql

.sql.gz 文件导入：

    gzip -dc /路径/备份文件.sql.gz | /www/server/mysql/bin/mysql -h127.0.0.1 -P3306 -ubaijiarui -p --protocol=TCP --default-character-set=utf8mb4 baijiarui_bi

出现 Enter password: 时输入 baijiarui 用户密码。密码不会回显，这是正常的。

出现任何 ERROR 时停止，不要重复导入，先保存错误信息。

## 5. 验证数据库

    /www/server/mysql/bin/mysql -h127.0.0.1 -P3306 -ubaijiarui -p --protocol=TCP baijiarui_bi -e "SHOW TABLES;"

至少应看到：

    users
    products
    sales_daily
    shops
    warehouses
    filter_presets
    product_categories
    product_category_relations
    schema_migrations

## 6. 启动后端

优先使用项目自带服务脚本：

    APP=/www/wwwroot/bjr-bi
    APP_ROOT="$APP" bash "$APP/current/deploy/baota/service.sh" start
    APP_ROOT="$APP" bash "$APP/current/deploy/baota/service.sh" status
    curl -sS http://127.0.0.1:8000/api/health; echo

如果环境安装了 Supervisor，则使用：

    supervisorctl restart baijiarui-bi
    supervisorctl status baijiarui-bi

如果当前环境没有 supervisorctl，使用 service.sh 即可。

健康接口应包含 ok=true、app=百嘉瑞BI 和当前版本号。

启动失败时查看：

    tail -n 100 /www/wwwroot/bjr-bi/shared/logs/backend.log
    tail -n 100 /www/wwwroot/bjr-bi/backend-error.log

## 7. 宝塔网站记录丢失时

如果文件管理器能看到站点，但宝塔“网站”列表没有记录：

1. 宝塔 → 网站 → 添加站点。
2. 网站目录填写：/www/wwwroot/bjr-bi/current/frontend-dist。
3. 不创建数据库，不清空目录，PHP 选择纯静态。
4. 配置中保留 API 代理和 Vue 路由。

换局域网 IP 后自动适应时，站点配置应包含：

    listen 80 default_server;
    server_name _;
    root /www/wwwroot/bjr-bi/current/frontend-dist;

API 代理必须包含：

    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        proxy_request_buffering off;
        proxy_buffering off;
    }

Vue 路由必须包含：

    location / {
        try_files $uri $uri/ /index.html;
    }

检查并重载 Nginx：

    /www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload

## 8. 最终验证

    curl -iS -H 'Host: 10.20.30.40' http://127.0.0.1/api/health

返回 HTTP/1.1 200 OK 且包含 ok=true，说明未知局域网 IP 已能进入百嘉瑞。

浏览器访问当前 NAS 的局域网 IP，检查登录、商品分析、库存、销售、分类、个人筛选预设和历史导入批次。

## 9. 重新设置定时备份

宝塔计划任务建议：

1. 每天 02:00 备份数据库 baijiarui_bi。
2. 备份目录：
   /www/wwwroot/bjr-bi/shared/backups/database/mysql/crontab_backup/baijiarui_bi
3. 每天 02:30 将整个 /www/wwwroot/bjr-bi 同步到网盘。
4. 网盘至少保留最近 30 个版本。
5. 每月实际测试一次恢复。

备份包含 .env 和业务数据，网盘必须设置为私密存储。

## 常见错误

### 登录 502

    curl -sS http://127.0.0.1:8000/api/health; echo
    APP_ROOT=/www/wwwroot/bjr-bi bash /www/wwwroot/bjr-bi/current/deploy/baota/service.sh status

通常是后端未启动，或 .env 中数据库密码不正确。

### 数据库报 1045

重置宝塔数据库用户 baijiarui 的密码，并同步修改 shared/.env。

### Nginx 返回 404

确认配置包含 listen 80 default_server、server_name _ 和 location ^~ /api/，然后执行 Nginx 测试和重载命令。

### 宝塔网站列表为空

这通常是宝塔面板的 sites 记录丢失，不代表站点文件丢失。重新登记网站即可，不要覆盖整个面板数据库。

