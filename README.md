# MinerU Web Console

自托管的文档转换控制台：调用 MinerU 4.x 服务把 PDF / 图片 / Office 文档转成 Markdown，带网页界面、任务管理、结果下载与用户认证。

## 功能特性

- **在线配置 MinerU 地址**：界面「设置」中可修改 MinerU 4.x 服务地址，改动实时写入宿主机卷，重启容器不失效。
- **多文件上传**：支持 PDF、图片（png/jpg/tif/bmp/webp）、Office（doc/docx/xls/xlsx/ppt/pptx），一次可传多个。
- **任务化转换**：每个上传批次作为一个任务，后台轮询 MinerU 状态并实时展示（上传中 / 处理中 / 已完成 / 部分完成 / 失败）。
- **结果下载**：任务完成（或部分完成）后可一键下载打包的转换结果（markdown.md、middle_json.json、structured_content.json、图片等）。
- **用户名密码认证**：HMAC 签名 Bearer Token（7 天有效期），密码以 PBKDF2 哈希存储，不落明文。
- **持久化**：配置 / 任务库 / 转换结果 / 日志全部外挂到宿主机 `/data`，容器重建不丢数据。
- **UTC+8 时区**：日志时间戳统一为 Asia/Shanghai。

## 技术架构

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + uvicorn |
| 存储 | SQLite（WAL 模式） |
| 认证 | 自签 HMAC-SHA256 Token + PBKDF2 密码哈希 |
| MinerU 客户端 | requests（OpenAI 风格 `/v1/tasks` 接口） |
| 前端 | 原生 HTML / CSS / JS（无构建步骤） |

## 目录结构

```
mineru-web/
├── app/
│   ├── main.py            # FastAPI 路由（认证/配置/任务/下载/静态）
│   ├── config.py          # 持久化配置（JSON 落盘 + 密码哈希 + Token）
│   ├── db.py              # SQLite 任务/文件表
│   ├── auth.py            # Bearer Token 依赖
│   ├── mineru_client.py   # MinerU 4.x API 客户端
│   ├── task_manager.py    # 任务生命周期（创建/上传/轮询/下载/解包）
│   ├── logging_setup.py   # 日志（stdout + 滚动文件，UTC+8 时间戳）
│   └── static/            # index.html / style.css / app.js / fonts
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .dockerignore
```

## 快速部署

```bash
# 1. 上传项目到服务器（此处以 /root/mineru-web 为例）
# 2. 构建镜像（建议用 legacy builder，避免 buildkit 重拉 base 镜像）
cd /root/mineru-web
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build
# 3. 启动
docker compose up -d
# 4. 访问 http://<服务器>:28081
```

数据卷挂载：`./data:/data`，宿主机 `/root/mineru-web/data` 下包含：

- `config/config.json` —— 配置（含密码哈希、secret、默认参数）
- `tasks.db` —— 任务与文件注册表（SQLite WAL）
- `results/<task_id>/` —— 每个任务的转换结果（解包后）
- `logs/app.log` —— 应用日志（10MB 滚动，保留 5 份）

## 配置说明

首次启动默认值可通过环境变量覆盖（`docker-compose.yml`）：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MINERU_WEB_BASE_URL` | `http://172.171.16.221:28001` | MinerU 4.x 服务地址（可在界面在线改） |
| `MINERU_WEB_USERNAME` | `admin` | 初始用户名 |
| `MINERU_WEB_PASSWORD` | `admin123` | 初始密码（仅首次生成哈希时生效） |
| `MINERU_WEB_DATA_DIR` | `/data` | 数据目录 |
| `TZ` | `Asia/Shanghai` | 时区 |

> 默认凭据：**admin / admin123**。登录后可在「设置」中修改用户名/密码。修改后的密码哈希持久化在 `config.json` 中。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（免认证） |
| POST | `/api/login` | 登录，返回 `{token, username}` |
| GET | `/api/me` | 当前用户 |
| GET/PUT | `/api/config` | 读取 / 更新配置 |
| POST | `/api/config/test` | 测试 MinerU 连接 |
| POST | `/api/tasks` | 创建任务（multipart：`files` + `tier` + `output_formats`） |
| GET | `/api/tasks` | 任务列表（含各文件状态） |
| GET/DELETE | `/api/tasks/{id}` | 查询 / 删除任务 |
| GET | `/api/tasks/{id}/download` | 下载整个任务结果（zip） |
| GET | `/api/tasks/{id}/files/{name}/download` | 下载单文件结果（zip） |

解析档位 `tier`：`flash`（快速，文字层 PDF）/ `basic` / `standard`（VLM/OCR，需 GPU）。
输出格式 `output_formats`：`default`（Markdown）/ `docx` / `html` / `latex`。

## ⚠️ 重要：Docker 网段冲突（部署踩坑）

本宿主机 Docker 默认地址池会分配 `192.168.x.0/20` 这样的子网，**可能与办公网段（如 `192.168.130.0/24`）冲突**：

- 现象：新服务 `docker compose up` 后，宿主机突然无法被办公网访问（ping 不通、SSH 断），但宿主机本机/内网仍能互相访问。
- 根因：Docker 新建的 bridge 网段（如 `192.168.128.0/20`）覆盖了办公网源地址，宿主机把回包路由进了 Docker bridge，而不是物理网卡。
- 修复：`docker compose down` 移除冲突网络即可恢复；并在 `docker-compose.yml` 中**显式指定非冲突网段**（本项目已固定为 `10.200.0.0/16`）。

因此**任何**在此宿主机新建的 compose 服务，都应显式 `networks.ipam.config.subnet`，避免再踩坑。更彻底的做法是调整 Docker daemon 的 `default-address-pool`（需重启 docker，会中断所有容器）。

## 使用说明

1. 浏览器打开 `http://<服务器>:28081`，用 admin 登录。
2. 拖拽或点击上传文件，选择解析档位与输出格式。
3. 点击「开始转换」，任务出现在右侧列表并实时刷新状态。
4. 完成后点击「下载全部」获取打包结果；也可删除任务。
5. 右上角状态胶囊可随时测试 MinerU 连接；「设置」中可改 MinerU 地址与登录凭据。
