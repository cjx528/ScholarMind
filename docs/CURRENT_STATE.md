# 当前状态

更新时间：2026-06-20

## 项目定位

ScholarMind 是一个科研论文发现与阅读助手。当前版本的核心体验是：

- 帮用户收集、管理和阅读本地论文库。
- 进入论文后能快速获得粗读、精读和推理链分析。
- 阅读 PDF 时能对选中文本或整篇论文继续追问。

## 当前保留的功能

逐项功能、入口、接口和验收点见 [FUNCTION_INVENTORY.md](FUNCTION_INVENTORY.md)。下面只保留模块级状态说明。

### 1. 用户画像

- 页面：`/recommendation`
- 后端：`apps/api/routers/recommendation.py`
- 服务：`packages/ai/compass_service.py`

用户画像页只负责配置、生成和保存用户画像。论文库推荐、Agent 回答、论文精读个性化分析和搜索排序会在各自流程中读取画像作为上下文。LLM 配置属于全局设置，不再只绑定用户画像页面。

### 2. 论文收集与多源渠道

- 页面：`/collect`
- 主题接口：`apps/api/routers/topics.py`
- 集成：`packages/integrations/`

当前收集页把即时搜索和多源搜索合并为一个流程。用户先选择 arXiv、OpenReview、Semantic Scholar、OpenAlex、DBLP、bioRxiv 等来源，搜索后审核候选论文；系统会判断相关性、标记是否已入库，并预分类到主题库。只有用户确认勾选后才写入本地库，入库时自动关联相应主题。

### 3. 论文库与论文详情

- 页面：`/papers`、`/papers/:id`
- 后端：`apps/api/routers/papers.py`

支持论文列表、搜索、筛选、排序、收藏、标签、PDF 下载、相似论文和详情页分析入口。

### 4. 粗读、精读、推理链

- 粗读：`POST /pipelines/skim/{paper_id}`
- 精读：`POST /pipelines/deep/{paper_id}`
- 推理链：`POST /papers/{paper_id}/reasoning`

粗读用于快速判断论文价值，精读用于方法、实验和风险分析，并内嵌基于用户画像的个性化分析。推理链用于梳理论文论证结构。这些内容都可以作为论文助手的追问上下文。

### 5. PDF 阅读助手

- 前端：`frontend/src/components/PdfReader.tsx`
- 单篇问答：`POST /papers/{paper_id}/ask`

阅读器右侧统一为“论文 AI 助手”。选中文本后可快速触发翻译成中文、解释这段、总结这段、问这篇论文。没有选中文本时，也可以围绕整篇论文或已有解析继续提问。


- 全库问答：`POST /rag/ask`
- Wiki：`frontend/src/pages/Wiki.tsx`、`apps/api/routers/content.py`

用于把单篇阅读扩展到长期知识库和可复用 Wiki 内容。

### 8. Agent、设置与运维

- Agent：`frontend/src/pages/Agent*.tsx`、`apps/api/routers/agent.py`
- 设置：`frontend/src/pages/Settings.tsx`、`apps/api/routers/settings.py`
- 运维：`/dashboard`、`/statistics`、`/system/status`、`/metrics/costs`
- 认证：`apps/api/routers/auth.py`

支持对话、工具调用、全局 LLM Provider 设置、任务状态、成本统计、登录密码和邮件配置。

## 已移除或不再作为主入口的功能

- 旧的双栏译文页不再维护。
- 旧视觉说明入口不再展示。
- 旧付费文献渠道实验已从文档和代码主线中移除。
- 独立的隐藏实验页面不再写入当前功能清单。

## 当前主要路由

- `/recommendation`
- `/collect`
- `/dashboard`
- `/papers`
- `/papers/:id`
- `/wiki`
- `/statistics`
- `/settings`

## 当前主要测试

- `tests/test_compass_service.py`
- `tests/test_openreview_client.py`
- `tests/test_paper_ask.py`
- `tests/test_skim_reports.py`

## 本地默认数据路径

- 数据库：`data/scholarmind.db`
- PDF：`data/papers`
- 日志：`logs`
