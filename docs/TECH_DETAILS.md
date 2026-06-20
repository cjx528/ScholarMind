# 技术细节

## 技术栈

- 后端：FastAPI、SQLAlchemy、Pydantic、SQLite。
- 前端：React、TypeScript、Vite。
- AI 能力：统一通过 `packages/ai/backend_config.py` 和 `packages/integrations/llm_client.py` 调用不同 LLM Provider。
- 论文源：arXiv、OpenReview、Semantic Scholar、OpenAlex、DBLP、bioRxiv。
- 存储：默认使用本地 SQLite，PDF 和简报存储在 `data/` 下。

## 后端入口

- 应用入口：`apps/api/main.py`
- 健康检查：`GET /health`
- OpenAPI：`http://127.0.0.1:8000/docs`

已注册的主要路由：

- `apps/api/routers/system.py`
- `apps/api/routers/papers.py`
- `apps/api/routers/recommendation.py`
- `apps/api/routers/topics.py`
- `apps/api/routers/tags.py`
- `apps/api/routers/cs_feeds.py`
- `apps/api/routers/agent.py`
- `apps/api/routers/content.py`
- `apps/api/routers/pipelines.py`
- `apps/api/routers/settings.py`
- `apps/api/routers/jobs.py`
- `apps/api/routers/auth.py`
- `apps/api/routers/sensemaking.py`
- `apps/api/routers/llm_configs.py`

## 前端入口

- 应用入口：`frontend/src/App.tsx`
- 导航栏：`frontend/src/components/Sidebar.tsx`
- API 封装：`frontend/src/services/api.ts`
- 全局任务条：`frontend/src/components/GlobalTaskBar.tsx`

当前主页面：

- `frontend/src/pages/Compass.tsx`
- `frontend/src/pages/DailyRadar.tsx`
- `frontend/src/pages/Collect.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Papers.tsx`
- `frontend/src/pages/PaperDetail.tsx`
- `frontend/src/pages/Wiki.tsx`
- `frontend/src/pages/DailyBrief.tsx`
- `frontend/src/pages/Statistics.tsx`
- `frontend/src/pages/Settings.tsx`

## 推荐发现数据流

1. 用户在 `/recommendation` 填写研究方向、关键词和偏好。
2. 后端保存到推荐画像。
3. `/collect` 的主题订阅按关键词和渠道抓取论文。
4. `packages/integrations/aggregator.py` 与各渠道客户端返回候选论文。
5. `packages/ai/daily_radar_service.py` 生成研究雷达分区。
6. 用户反馈通过 `/recommendation/feedback` 影响后续排序。

相关文件：

- `frontend/src/pages/Compass.tsx`
- `frontend/src/pages/DailyRadar.tsx`
- `frontend/src/pages/Collect.tsx`
- `frontend/src/contexts/ChannelContext.tsx`
- `apps/api/routers/recommendation.py`
- `apps/api/routers/topics.py`
- `apps/api/routers/cs_feeds.py`
- `packages/ai/compass_service.py`
- `packages/ai/daily_radar_service.py`
- `packages/ai/daily_runner.py`
- `packages/integrations/`

## 阅读理解数据流

1. 用户在 `/papers` 进入论文详情。
2. 后端加载论文元数据、摘要、PDF 路径和已有分析结果。
3. 用户可以触发粗读、精读、推理链和相似论文。
4. PDF 阅读器中的 AI 助手调用 `POST /papers/{paper_id}/ask`。
5. 后端按优先级拼接选中文本、论文元数据、粗读、精读、推理链和 PDF 附近文本。
6. LLM 返回中文回答，并标注使用到的上下文类型。

相关接口：

- `GET /papers/latest`
- `GET /papers/{paper_id}`
- `GET /papers/{paper_id}/pdf`
- `POST /papers/{paper_id}/download-pdf`
- `POST /pipelines/skim/{paper_id}`
- `POST /pipelines/deep/{paper_id}`
- `POST /papers/{paper_id}/reasoning`
- `POST /papers/{paper_id}/ask`
- `GET /papers/{paper_id}/similar`

相关文件：

- `frontend/src/pages/Papers.tsx`
- `frontend/src/pages/PaperDetail.tsx`
- `frontend/src/components/PdfReader.tsx`
- `apps/api/routers/papers.py`
- `apps/api/routers/pipelines.py`
- `apps/api/routers/tags.py`
- `packages/ai/pdf_parser.py`
- `packages/ai/reasoning_service.py`
- `packages/ai/rag_service.py`

## 单篇论文问答接口

请求：

```json
{
  "question": "请解释这段为什么重要",
  "selected_text": "optional selected text",
  "source": "pdf_reader",
  "analysis_scope": ["skim", "deep", "reasoning"],
  "page_number": 1
}
```

响应：

```json
{
  "answer": "中文回答",
  "used_context": ["selected_text", "paper_meta", "skim"],
  "confidence": 0.72
}
```

约束：

- 默认中文回答。
- 如果上下文不足，要明确说明“当前上下文不足”。
- 该接口用于阅读器和解析追问；全库问题继续走 `POST /rag/ask`。

## 知识沉淀数据流

- `POST /rag/ask`：全库问答。
- `GET /wiki/paper/{paper_id}`：单篇论文 Wiki。
- `GET /wiki/topic`：主题 Wiki。
- `POST /tasks/wiki/topic`：异步生成主题 Wiki。
- `POST /brief/daily`：生成每日研究简报。
- `GET /generated/list`：查看生成内容。

相关文件：

- `frontend/src/pages/Wiki.tsx`
- `frontend/src/pages/DailyBrief.tsx`
- `apps/api/routers/content.py`
- `packages/ai/rag_service.py`
- `packages/ai/graph_service.py`
- `packages/ai/brief_service.py`

## Agent 与系统能力

- `POST /agent/chat`：Agent 对话。
- `GET /agent/conversations`：会话列表。
- `GET /agent/conversations/{conversation_id}`：会话详情。
- `POST /agent/confirm/{action_id}`：确认待执行动作。
- `POST /agent/reject/{action_id}`：拒绝待执行动作。
- `GET /tasks/active`：活跃任务。
- `GET /system/status`：系统状态。
- `GET /metrics/costs`：成本统计。

相关文件：

- `frontend/src/pages/Agent.tsx`
- `frontend/src/pages/AgentMessages.tsx`
- `frontend/src/pages/AgentSteps.tsx`
- `frontend/src/components/GlobalTaskBar.tsx`
- `apps/api/routers/agent.py`
- `apps/api/routers/jobs.py`
- `apps/api/routers/system.py`
- `packages/ai/agent_service.py`
- `packages/ai/agent_tools.py`

## 配置与认证

- 全局 LLM 设置：`frontend/src/pages/Settings.tsx`、`apps/api/routers/settings.py`
- LLM 配置接口：`apps/api/routers/llm_configs.py`
- 站点密码登录：`apps/api/routers/auth.py`
- 邮件配置：`/settings/email-configs`
- 简报配置：`/settings/daily-report-config`

`.env` 中至少需要配置一个可用 LLM API Key。课程演示默认使用智谱配置，真实 Key 由项目维护者线下发放。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m compileall apps packages scripts infra
.\.venv\Scripts\python.exe -m pytest
cd frontend
npm.cmd run build
```
