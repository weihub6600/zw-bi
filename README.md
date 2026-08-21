# 百嘉瑞 BI — 库存健康度分析系统

面向批发零售业务的库存与销售数据分析平台。系统每天接收并解析门店提供的库存 / 销售 Excel 与 CSV 文件，
自动对商品进行**库存健康度评估**（缺货、滞销、临期、动销率、效期预警等），并提供部门级 / 店铺级多维分析看板。

当前版本：**v15.4.0**（版本目录：`releases/v15.4.0`）

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
| 数据库 | MySQL 5.7+ |
| 前端 | Vue 3 编译产物（`frontend-dist`，静态资源由 FastAPI 托管） |
| 部署 | 宝塔面板 / systemd，发布链 `releases/<version>/` + 符号链接 `current` |

## 目录结构

```
zw-bi/
├── README.md                 # 项目说明（本文件）
├── LICENSE                   # MIT 许可证
├── .github/workflows/ci.yml  # GitHub Actions 持续集成
└── releases/
    └── v15.4.0/              # 发布版本目录（可多个版本并存）
        ├── backend/          # FastAPI 后端
        │   ├── app/          # 应用代码（routes / services / core / cli）
        │   ├── sql/          # schema_tables.sql 与增量迁移 migrations/
        │   └── tests/        # 单元测试（unittest）
        ├── frontend-dist/    # 前端编译产物
        ├── deploy/baota/     # 宝塔部署脚本（update / service / rollback / check）
        ├── scripts/          # release_tool.py 发布工具
        ├── install.sh        # 首次安装脚本
        ├── manifest.json     # 发布文件清单与哈希校验
        └── VERSION           # 版本号
```

## 快速开始

### 本地开发

```bash
# 1. 准备 Python 3.10+ 环境并安装依赖
cd releases/v15.4.0/backend
pip install -r requirements.txt

# 2. 复制环境配置并填写数据库连接
cp ../.env.example ../.env    # Windows: copy ..\.env.example ..\.env

# 3. 初始化数据库结构（首次）
py ../scripts/release_tool.py init-schema

# 4. 启动开发服务器
py -m uvicorn app.main:app --reload --port 8000
```

### 生产部署（宝塔面板）

请参阅 `releases/v15.4.0/README_DEPLOY.txt` 与 `install.sh`。

## 测试

```bash
cd releases/v15.4.0/backend
python -m unittest discover -s tests -p "test_*.py"
```

说明：个别测试需要前端源码目录（`frontend/src`）做前后端一致性检查，
发布包中不含前端源码时会自动跳过，不影响其余测试结果。

## 版本发布

- 每个正式版本以独立目录 `releases/v<版本号>/` 发布，附带 `manifest.json` 文件哈希清单。
- `scripts/release_tool.py` 提供 `verify` / `init-schema` / `migrate` / `backup-db` / `restore-db` 等运维能力。
- 服务器升级通过符号链接 `current` 切换到新版本目录，`deploy/baota/update.sh` 自动执行迁移与回滚。

## 许可证

[MIT](LICENSE)
