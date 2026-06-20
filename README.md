# ScholarMind

ScholarMind 是一个面向科研论文发现、阅读和追问的课程项目。当前版本围绕“每天发现该读什么、读论文时能继续追问、读完后能沉淀知识”组织功能，而不是只做论文列表或一次性摘要。

## 当前功能

完整逐项清单见 [docs/FUNCTION_INVENTORY.md](docs/FUNCTION_INVENTORY.md)。这里列当前用户可见的主要功能。

### 全局与 Agent

- 登录认证：可通过 `AUTH_PASSWORD` 开启站点密码，前端自动保存和携带 token。
- 侧边栏：支持工具导航、新对话、对话历史、删除会话、未读论文角标、全局任务进度、明暗主题切换和退出登录。
- Agent 首页：支持流式对话、停止生成、会话历史、论文结果卡片、工具调用步骤、待确认动作、快捷问题和右侧画布。
- Agent 工具意图：覆盖搜索调研、下载论文、知识问答、粗读论文、精读论文、生成 Wiki 等任务。

### 用户画像、推荐与研究雷达

- 用户画像：支持选择和自定义研究方向、少推方向、论文类型偏好、阅读目标、探索风格和补充说明。
- AI 方向细分：内置 LLM、预训练、后训练、对齐、RAG、Agent、多智能体、代码大模型、MLLM/VLM、多模态推理、图像生成/编辑、视频理解/生成、语音交互、音频生成、具身智能、世界模型、AI4Science、AI Infra 等方向。
- 非 AI 方向：可自由填写 HCI、数据库、医学影像、计算社会科学等其他研究方向。
- AI 生成画像：根据快捷画像和历史回答生成可读的关注偏好、研究方向、阅读目标和追问。
- 画像复用：论文库推荐、研究雷达、Agent 回答、论文解析和搜索排序会读取用户画像作为上下文。
- 研究雷达：按精读候选、速读候选、跳过原因展示每日候选论文，显示 BM25、embedding、画像分数和 LLM refine 状态。

### 论文收集与多源抓取

- 统一搜索：即时搜索和多源搜索已合并，可在一次搜索中选择 arXiv、OpenReview、Semantic Scholar、OpenAlex、DBLP、bioRxiv。
- 候选审核：搜索结果先作为候选展示，显示来源、作者、摘要、相关性、是否已入库和主题归类，不会直接写入本地库。
- 按主题入库：用户确认勾选后再入库，论文会关联到匹配的主题库；没有匹配主题时按搜索词创建暂停状态的主题。
- 新论文优先：搜索时间窗口和排序会参考用户画像里的新旧论文偏好。
- 行动记录：抓取任务会形成记录，论文库可按行动记录查看对应论文。

### 论文库、详情与阅读

- 论文库：支持搜索、状态筛选、文件夹筛选、日期筛选、标签筛选、行动记录筛选、分类筛选、排序、分页、列表/网格视图。
- 收藏：论文库和详情页都支持收藏/取消收藏。
- 标签：支持标签新建、编辑、删除、颜色选择、计数展示，以及给论文绑定/解绑标签。
- 批量处理：支持批量粗读、批量向量化，并写入全局任务进度。
- 论文详情：展示标题、作者、来源、日期、摘要、主题、状态、标签、收藏、PDF 状态和已有分析结果。
- PDF 下载和阅读：可下载 PDF，打开内置阅读器，支持页码、缩放、重置缩放、全屏、关闭和阅读进度。
- 粗读：生成快速判断报告和评分。
- 精读：生成方法、实验、消融、创新、局限、风险等分析。
- 推理链：生成问题定义、方法链、实验链、影响评估和论证步骤。
- 一键深度分析：自动补齐向量化、粗读、精读和推理链。
- 相似论文：向量化后可检索相似论文并跳转详情。
- PDF 阅读助手：选中文本后可翻译成中文、解释这段、总结这段、围绕这段提问；也可不选文本直接问整篇论文或已有解析。
- 解析追问：粗读、精读、推理链区域都能继续追问，统一走单篇论文问答上下文。

### 知识沉淀与运维

- 单篇论文问答：`/papers/{id}/ask` 使用选中文本、论文元数据、粗读、精读、推理链和 PDF 正文回答问题。
- 全库问答：`/rag/ask` 面向本地论文库做知识问答。
- Wiki：支持单篇论文 Wiki、主题 Wiki、异步生成、主题/论文任务并行、历史记录、详情查看和删除。
- 设置：支持全局 AI 后端、LLM Provider、模型、API Key、Codex CLI、邮件 SMTP 和健康检查配置。
- 看板：展示系统状态、今日摘要、成本分析、Pipeline 运行记录和最近活动。
- 主题统计：按主题、日期、来源、venue、状态等维度查看论文分布。

当前版本已经移除旧的双栏译文页、旧视觉说明入口和旧付费文献渠道实验。阅读器主入口统一为 PDF AI 助手。

## 目录结构

```text
apps/api/                 FastAPI 后端路由
apps/worker/              后台任务入口
frontend/                 React + Vite 前端
packages/ai/              推荐、雷达、解析、RAG、Agent 等核心服务
packages/integrations/    论文源和外部服务集成
packages/storage/         数据模型和数据库访问
tests/                    后端核心功能测试
docs/                     当前文档、答辩材料和分工说明
data/                     本地数据库、PDF，默认不提交
```

## 本地运行

要求：

- Python 3.11 或更新版本
- Node.js 18 或更新版本
- Git

克隆仓库：

```powershell
git clone https://github.com/cjx528/ScholarMind.git
cd ScholarMind
```

创建并配置环境变量：

```powershell
Copy-Item .env.example .env
```

课程演示时可以使用项目维护者统一发放的 `.env`。不要把真实 API Key 提交到 GitHub。默认示例使用智谱模型：

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
EMBEDDING_DIMENSIONS=1024
```

安装后端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,llm,pdf]"
```

安装前端：

```powershell
cd frontend
npm.cmd install
cd ..
```

启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

启动前端：

```powershell
cd frontend
npm.cmd run dev -- --host 127.0.0.1
```

访问地址：

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:8000/health`
- 后端接口文档：`http://127.0.0.1:8000/docs`

## 常用验证命令

```powershell
.\.venv\Scripts\python.exe -m compileall apps packages scripts infra
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm.cmd run build
```

如果只改文档，可以至少运行：

```powershell
git diff --check
```

## 核心接口

- `GET /health`：后端健康检查。
- `GET /papers/latest`：论文库列表。
- `GET /papers/{paper_id}`：论文详情。
- `POST /papers/{paper_id}/ask`：单篇论文 AI 助手问答。
- `POST /pipelines/skim/{paper_id}`：生成粗读报告。
- `POST /pipelines/deep/{paper_id}`：生成精读报告。
- `POST /papers/{paper_id}/reasoning`：生成推理链分析。
- `POST /rag/ask`：全库问答。
- `GET /recommendation/daily-radar`：研究雷达。
- `POST /ingest/search/preview`：多源搜索候选预览，不直接入库。
- `POST /ingest/search/selected`：确认候选论文后按主题入库。
- `POST /tasks/wiki/topic`、`POST /tasks/wiki/paper/{paper_id}`：异步生成 Wiki。
- `POST /agent/chat`：Agent 对话。

更完整的接口和数据流见 [docs/TECH_DETAILS.md](docs/TECH_DETAILS.md)。

## 小组分工建议

详细分工见 [docs/TEAM_VALIDATION.md](docs/TEAM_VALIDATION.md)。

- A：用户画像、个性化推荐、研究雷达。
- B：论文收集、多源搜索、主题归档、OpenReview。
- C：论文库、论文详情、PDF 阅读助手、粗读、精读、推理链、RAG、标签。
- D：Agent、Wiki、设置、运维、认证、全局任务。

每个人优先测试和修自己负责的功能。若修改了责任范围外的代码文件，需要在群里说明，避免互相覆盖。

## 当前文档

- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md)：当前功能状态和已移除内容。
- [docs/FUNCTION_INVENTORY.md](docs/FUNCTION_INVENTORY.md)：完整功能清单和逐项验收点。
- [docs/TEAM_VALIDATION.md](docs/TEAM_VALIDATION.md)：小组验收分工。
- [docs/COURSE_PRESENTATION_GUIDE.md](docs/COURSE_PRESENTATION_GUIDE.md)：课堂展示路线。
- [docs/PRESENTATION_DRAFT_CURRENT.md](docs/PRESENTATION_DRAFT_CURRENT.md)：报告和答辩框架。
- [docs/TECH_DETAILS.md](docs/TECH_DETAILS.md)：后端接口、服务和数据流。
- [docs/deployment/DOCKER_DEPLOYMENT.md](docs/deployment/DOCKER_DEPLOYMENT.md)：Docker 部署说明。

## 数据与安全

- 默认数据库：`data/scholarmind.db`
- PDF 存储：`data/papers`
- 日志目录：`logs`
- `.env`、`data/`、`logs/` 不应提交真实敏感内容。
