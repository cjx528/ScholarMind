# Docker 部署说明

适用场景：在一台机器上快速启动 ScholarMind 前端、后端和 worker。

## 准备环境变量

在仓库根目录复制配置文件：

```powershell
Copy-Item .env.example .env
```

至少配置一个可用的 LLM API Key。课程演示默认使用智谱配置：

```env
LLM_PROVIDER=zhipu
ZHIPU_API_KEY=

LLM_MODEL_SKIM=glm-4.7-flash
LLM_MODEL_DEEP=glm-5.1
LLM_MODEL_VISION=glm-4.6v
LLM_MODEL_FALLBACK=glm-4.7-flash

EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_MODEL=embedding-3
```

如果需要登录保护：

```env
AUTH_PASSWORD=your_password_here
AUTH_SECRET_KEY=change-this-to-a-random-secret
```

不要把包含真实 Key 的 `.env` 提交到 GitHub。

## 启动

```powershell
docker compose up -d --build
```

默认服务：

- 前端：`http://127.0.0.1:3002`
- 后端：`http://127.0.0.1:8002`
- 后端健康检查：`http://127.0.0.1:8002/health`
- 后端接口文档：`http://127.0.0.1:8002/docs`

## 查看状态

```powershell
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f worker
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8002/health
```

## 数据卷

`docker-compose.yml` 默认使用：

- `scholarmind_data`：数据库、PDF、简报输出。
- `scholarmind_logs`：后端和 worker 日志。

如需备份数据卷，请先停止服务：

```powershell
docker compose down
```

## 更新部署

```powershell
git pull
docker compose up -d --build
```

如果只改前端或后端，也可以重建指定服务：

```powershell
docker compose up -d --build frontend
docker compose up -d --build backend
```

## 停止

```powershell
docker compose down
```

如需连同匿名容器一并清理：

```powershell
docker compose down --remove-orphans
```

不要随意删除数据卷，除非已经确认不需要本地论文库和简报数据。
