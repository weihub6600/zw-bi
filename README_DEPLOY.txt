Baijiarui BI fnOS/BaoTa production package
Version: 15.7.7

First install:
  chmod +x install.sh
  BJR_INSTALL_PRODUCTION=1 bash install.sh /www/wwwroot/baijiarui-bi

Upgrade:
  chmod +x deploy/baota/update.sh
  bash deploy/baota/update.sh /www/wwwroot/baijiarui-bi

Production requirements:
  - shared/.env must set APP_ENVIRONMENT=production.
  - Use HTTPS with SESSION_COOKIE_SECURE=true.
  - Set a non-default APP_SECRET (at least 32 characters), SETUP_INIT_TOKEN (at least 16 characters),
    explicit HTTPS CORS_ORIGINS, and TRUSTED_PROXY_IPS.
  - The upgrade script creates a database backup before migration. If migration fails it only rolls back
    the application symlink; database restoration is a manual, reviewed operation.
  - To restore a reviewed backup manually: python scripts/release_tool.py restore-db <backup.sql>.

BaoTa Nginx example: deploy/baota/nginx.conf.example
