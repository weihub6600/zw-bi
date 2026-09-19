# 百嘉瑞 BI — 库存健康度分析系统

面向批发零售业务的库存与销售数据分析平台。系统每天接收并解析门店提供的库存 / 销售 Excel 与 CSV 文件，
自动对商品进行**库存健康度评估**（缺货、滞销、临期、动销率、效期预警等），并提供部门级 / 店铺级多维分析看板。

当前版本：**v15.7.7**。仓库开发目录直接位于根目录；正式发布包才使用 `releases/<版本号>/` 布局。

## 功能特性

- **数据导入中心**：多门店每日导入库存 / 销售 / 效期数据，支持 xlsx / xls / csv，逐行校验、错误下载、重复批次去重
- **库存健康度分析**：库存周转、安全库存、缺货预测、滞销识别、效期（近效期 / 过期）预警
- **销售趋势分析**：按商品 / 店铺 / 部门多维对比，环比与同比、Top N 排行
- **任务协作**：库存处理任务、审批流（申请删除 / 撤回 / 审批）、任务到期提醒
- **权限体系**：系统管理员 / 部门管理员 / 普通用户三级，基于部门的数据隔离
- **审计日志**：全量操作留痕，支持按部门、用户、操作类型检索
- **系统初始化**：首次部署引导（创建管理员、部门、店铺配置）

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.10+ / FastAPI / SQLAlchemy / PyMySQL |
| 数据库 | MySQL 8.0+（当前迁移使用 JSON_TABLE 等 MySQL 8 能力） |
| 前端 | Vue 3 源码（`frontend/`）与编译产物（`frontend-dist/`） |
| 部署 | 宝塔面板 / systemd，发布链 `releases/<version>/` + 符号链接 `current` |

## 目录结构

```
zw-bi/
├── backend/                  # FastAPI 后端、SQL、测试
├── frontend/                 # Vue 3 前端源码
├── frontend-dist/            # 可选的静态构建产物
├── deploy/                   # 宝塔部署配置与脚本
├── scripts/                  # 发布与数据库工具
├── shared/                   # 本地运行数据（不提交）
└── releases/                 # 正式发布时生成的版本归档
```

## 快速开始

### 本地开发

```bash
# 1. 准备 Python 3.10+ 环境并安装依赖
cd backend
pip install -r requirements.txt

# 2. 复制环境配置并填写数据库连接
cp ../.env.example ../.env    # Windows: copy ..\.env.example ..\.env

# 3. 初始化数据库结构（首次）
py ../scripts/release_tool.py init-schema

# 4. 启动开发服务器
py -m uvicorn app.main:app --reload --port 8000

# 5. 前端开发（另一个终端）
cd ../frontend
npm ci
npm run dev
```

### 生产部署（宝塔面板）

生产环境应使用 HTTPS，并设置 `SESSION_COOKIE_SECURE=true`、明确的 `CORS_ORIGINS`，
以及仅包含实际反向代理地址的 `TRUSTED_PROXY_IPS` 和一次性 `SETUP_INIT_TOKEN`。本地 HTTP 开发保持
`SESSION_COOKIE_SECURE=false`。部署与升级命令见 `deploy/baota/` 和 `scripts/release_tool.py`。

登录失败限流在应用进程内按账号和可信客户端 IP 分别计数。若生产环境启用多个 Uvicorn
worker 或多实例，还应在 Nginx/网关增加共享 `limit_req`；同时将 Uvicorn 的
`forwarded-allow-ips` 与 `TRUSTED_PROXY_IPS` 配成同一组实际代理地址。

## 测试

```bash
python -m unittest discover -s backend/tests -p "test_*.py"

# 前端构建
npm run build --prefix frontend
```

默认测试使用隔离 SQLite 内存库。真实 MySQL 测试必须使用独立 MySQL 8 数据库，
设置 `RUN_MYSQL_INTEGRATION=1` 后单独运行 `backend.tests.test_mysql_integration`。
CI 会启动一次性 MySQL 服务，不读取生产密钥，也不连接生产数据库。

## 版本发布

- 每个正式版本以独立目录 `releases/v<版本号>/` 发布，附带 `manifest.json` 文件哈希清单。
- `scripts/release_tool.py` 提供 `verify` / `init-schema` / `migrate` / `backup-db` / `restore-db` 等运维能力。
- 服务器升级通过符号链接 `current` 切换到新版本目录。迁移前必须备份数据库；切回旧应用版本并不自动回滚已执行的数据库迁移。
- 生产首次安装请使用 `BJR_INSTALL_PRODUCTION=1 bash install.sh /www/wwwroot/baijiarui-bi`，并在初始化接口请求头中提供 `X-Setup-Token`。

## 许可证

[MIT](LICENSE)
