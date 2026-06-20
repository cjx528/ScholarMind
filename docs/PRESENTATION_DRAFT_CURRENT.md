# 报告与答辩框架

## 标题

ScholarMind：面向科研论文发现、阅读追问与知识沉淀的智能助手

## 1. 背景与问题

科研论文阅读有三个痛点：

- 发现成本高：每天新论文太多，不知道哪些值得精读。
- 阅读成本高：摘要、方法、实验和局限分散在长 PDF 中。
- 沉淀成本高：读完后难以变成可检索、可追问、可复用的研究知识。

ScholarMind 的目标是把“找论文、读论文、问论文、沉淀论文”连成一个闭环。

## 2. 系统目标

- 用用户画像和主题订阅生成个性化研究雷达。
- 用粗读、精读、推理链降低单篇论文理解成本。
- 用 PDF 阅读助手支持划词翻译、解释、总结和追问。
- 用 RAG、Wiki、每日简报和 Agent 做长期知识沉淀。

## 3. 系统架构

前端：

- React + TypeScript + Vite
- 页面包括推荐画像、研究雷达、论文收集、论文库、论文详情、Wiki、简报、设置和统计。

后端：

- FastAPI + SQLAlchemy + SQLite
- 路由包括 papers、recommendation、topics、cs_feeds、pipelines、content、agent、settings、jobs、auth。

AI 服务：

- 推荐画像：`packages/ai/compass_service.py`
- 研究雷达：`packages/ai/daily_radar_service.py`
- 论文解析：`packages/ai/pipelines.py`
- PDF 解析：`packages/ai/pdf_parser.py`
- 推理链：`packages/ai/reasoning_service.py`
- RAG：`packages/ai/rag_service.py`
- Agent：`packages/ai/agent_service.py`

外部论文源：

- arXiv
- OpenReview
- Semantic Scholar
- OpenAlex
- DBLP
- bioRxiv

## 4. 功能模块

### A. 个性化推荐与研究雷达

说明用户画像如何影响推荐队列，研究雷达如何把论文分成精读候选、速读候选和可跳过项。

可展示页面：

- `/recommendation`
- `/radar`

### B. 论文收集与主题订阅

说明主题订阅、多源检索、关键词建议和学科订阅如何帮助用户持续收集论文。

可展示页面：

- `/collect`

### C. 论文阅读与解析追问

说明论文库、论文详情、PDF 阅读助手、粗读、精读、推理链和 RAG 的关系。

可展示页面：

- `/papers`
- `/papers/:id`

建议演示问题：

- 选中英文段落后点击“翻译成中文”。
- 问“这段为什么重要？”
- 在精读报告里问“审稿风险的证据是什么？”

### D. 知识沉淀、Agent 与运维

说明 Wiki、每日简报、Agent、设置、任务和成本统计如何支撑长期使用。

可展示页面：

- `/wiki`
- `/brief`
- `/settings`
- `/dashboard`
- `/statistics`

## 5. 关键实现

### 单篇论文问答

接口：`POST /papers/{paper_id}/ask`

上下文优先级：

1. 用户选中的 PDF 文本。
2. 论文标题、摘要和中文摘要。
3. 粗读报告。
4. 精读报告。
5. 推理链分析。
6. 当前页或附近 PDF 文本。

回答约束：

- 默认中文。
- 信息不足时明确说明上下文不足。
- 不编造论文没有提供的信息。

### 研究雷达

研究雷达用用户画像、主题订阅、候选论文元数据和 LLM refine 生成更可读的推荐分区，让用户优先判断“今天该读什么”。

### 全局配置

LLM Provider 和模型配置放在设置页和 `.env` 中，不绑定单一页面。这样用户画像、推荐、论文解析、PDF 助手和 Agent 都能复用同一套配置。

## 6. 测试与验收

建议列出：

- 后端测试：`python -m pytest`
- 前端构建：`npm.cmd run build`
- 手动验收：按 [TEAM_VALIDATION.md](TEAM_VALIDATION.md) 的 A/B/C/D 分工逐项测试。

重点验收场景：

- 用户画像保存后，研究雷达可生成推荐。
- OpenReview 或 arXiv 抓取可入库。
- 粗读、精读、推理链能生成且质量可读。
- PDF 阅读助手对选中文本返回中文答案。
- Wiki、简报、设置、认证和任务条稳定。

## 7. 总结

ScholarMind 的价值不是单点摘要，而是把科研阅读流程串成闭环：

> 从每日发现，到单篇阅读，再到持续追问和知识沉淀。
