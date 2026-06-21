# 完整功能清单与验收项

更新时间：2026-06-20

这份文档按当前代码入口整理 ScholarMind 的具体功能。它用于小组测试、报告撰写和答辩准备。功能是否存在以当前前端路由、API 封装和后端路由为准。

## 0. 全局能力

入口：

- 首页：`/`
- 设置：`/settings`
- 侧边栏：所有页面左侧

具体功能：

- 登录保护：如果配置了 `AUTH_PASSWORD`，进入系统前需要密码登录。
- 登录状态保持：前端保存 token，接口请求自动带认证头。
- 退出登录：侧边栏底部退出按钮清空 token 并回到登录状态。
- 工具导航：侧边栏进入用户画像、论文收集、论文库、Wiki、看板、主题统计。
- 新建对话：侧边栏“新对话”创建新的 Agent 会话。
- 对话历史：侧边栏按日期展示历史会话，支持切换和删除。
- 暗色模式：侧边栏底部切换明暗主题，并保存到本地。
- 未读论文角标：论文库入口显示未读数量。
- 全局任务条：正在运行的分析、抓取、生成任务会显示进度。
- 404 页面：未知路由显示“页面不存在”。

主要接口和文件：

- `POST /auth/login`
- `GET /auth/status`
- `GET /tasks/active`
- `POST /tasks/track`
- `frontend/src/App.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/GlobalTaskBar.tsx`
- `frontend/src/contexts/ConversationContext.tsx`
- `frontend/src/contexts/GlobalTaskContext.tsx`

验收重点：

- 未登录状态能进入登录页，密码正确后进入系统。
- 退出登录后刷新页面不会继续保持登录。
- 侧边栏所有工具入口可跳转，移动端菜单可打开和关闭。
- 明暗主题切换后刷新仍保持。
- 启动一个分析任务后，任务条能出现并更新。

## 1. Agent 首页与对话

入口：`/`

具体功能：

- Agent 流式对话：输入问题后通过 SSE 接收回复。
- 停止生成：回复过程中可以中断生成。
- 重新发送：失败或需要重试时可继续发起请求。
- 快捷提示：首页提供推荐问题和功能提示。
- 工具调用展示：Agent 可以展示搜索调研、下载论文、知识问答、粗读论文、精读论文、生成 Wiki 等工具意图。
- 待确认动作：高风险或需要用户确认的动作通过确认/拒绝按钮处理。
- 论文结果卡片：Agent 返回论文结果时，可点击进入论文详情。
- 画布侧栏：Agent 生成结构化内容时可在右侧画布查看。
- 会话持久化：会话列表、会话详情和删除由后端保存。

主要接口和文件：

- `POST /agent/chat`
- `POST /agent/confirm/{action_id}`
- `POST /agent/reject/{action_id}`
- `GET /agent/conversations`
- `GET /agent/conversations/{conversation_id}`
- `DELETE /agent/conversations/{conversation_id}`
- `frontend/src/pages/Agent.tsx`
- `frontend/src/pages/AgentMessages.tsx`
- `frontend/src/pages/AgentSteps.tsx`
- `apps/api/routers/agent.py`
- `packages/ai/agent_service.py`
- `packages/ai/agent_tools.py`

验收重点：

- 能发送普通问题并收到中文回复。
- 回复过程中停止按钮有效。
- 新建对话后历史会话不丢失。
- 删除会话后侧边栏同步消失。
- Agent 返回论文卡片时能跳到对应论文详情。
- 如果出现待确认动作，确认和拒绝都能正常结束状态。

## 2. 用户画像

入口：`/recommendation`

具体功能：

- 当前最想追方向选择：包含 LLM、LLM 预训练、LLM 后训练/SFT/RLHF、对齐与偏好优化、推理能力/数学推理、长上下文/记忆、RAG/知识增强、Agent/工具调用、多智能体协作、代码大模型、高效推理/模型压缩、评测/Benchmark、安全/鲁棒/可解释、数据合成/数据治理、MLLM/VLM、多模态推理、图像生成/编辑、视频理解、视频生成、语音交互/语音大模型、音频理解/生成、具身智能/机器人、世界模型、AI4Science、AI Infra/训练系统。
- 其他方向自由填写：支持 HCI、数据库、医学影像、计算社会科学等非 AI 方向。
- 少推方向：支持配置传统语音增强、纯 benchmark、弱开源工作、小修小补方法、只做应用包装、过时架构，也支持自定义。
- 论文类型偏好：方法突破、开源系统、数据集、评测框架、综述地图、产业信号。
- 阅读目标：找 idea、找 baseline、写 paper、做产品判断、建领域地图、找可复现代码。
- 探索风格：稳健可复现、平衡、高风险新想法。
- 补充说明：用自然语言补充当前阶段的研究偏好。
- 保存画像：将表单保存为用户画像。
- AI 生成画像：根据快捷画像和历史问题生成关注偏好、研究方向、阅读目标和追问。
- 画像复用：论文库推荐、Agent 回答、论文精读个性化分析和搜索排序在各自板块读取画像；用户画像页不展示推荐队列或论文推荐卡。

主要接口和文件：

- `GET /recommendation/profile`
- `PUT /recommendation/profile`
- `POST /recommendation/profile/build`
- `frontend/src/pages/Compass.tsx`
- `apps/api/routers/recommendation.py`
- `packages/ai/compass_service.py`

验收重点：

- AI 方向和其他方向都能选择或手填。
- 保存画像后刷新页面仍能看到已保存内容。
- AI 生成画像能生成可读中文，不直接暴露提示词或 JSON。
- 页面不出现推荐队列、推荐分、论文推荐卡或打星反馈控件。

## 3. 论文收集与主题归档

入口：`/collect`

具体功能：

- 统一搜索：即时搜索和多源搜索合并为一个入口。
- 来源选择：用户可选择 arXiv、OpenReview、Semantic Scholar、OpenAlex、DBLP、bioRxiv。
- 新旧偏好：默认排序和时间窗口参考用户画像里的新论文/旧论文比例偏好。
- 候选预览：搜索结果先展示标题、作者、来源、日期、摘要、链接、相关性分数和是否已入库。
- 主题归类：候选论文会预判所属主题；没有匹配主题时按搜索词生成主题名称。
- 人工确认：只有用户勾选并确认后，候选论文才写入本地论文库。
- 按主题入库：确认入库时自动关联到对应主题库；新建主题默认暂停，不会自动抓取。
- 来源统计：展示各论文源的返回数量、去重数量和失败信息。
- 抓取行动记录：入库动作会形成记录，论文库可按行动记录查看对应论文。

主要接口和文件：

- `GET /topics`
- `POST /ingest/search/preview`
- `POST /ingest/search/selected`
- `POST /ingest/arxiv/preview`
- `POST /ingest/arxiv/selected`
- `frontend/src/pages/Collect.tsx`
- `packages/integrations/`

验收重点：

- 搜索前可以选择论文来源，至少 arXiv 能返回候选。
- 搜索结果能区分来源，渠道统计不为空。
- 候选论文不会自动入库，必须勾选并确认。
- 候选能显示预判主题，确认入库后在论文详情或主题筛选中能看到关联。
- 已入库论文会显示已在库，不应被误判为新论文。
- 外部渠道、网络或 API 失败时显示可读错误，不应只有空白。

## 4. 论文库

入口：`/papers`

具体功能：

- 论文列表：分页展示本地论文库。
- 搜索：按标题、摘要、作者等文本搜索。
- 状态筛选：未读、已粗读、已精读等状态。
- 文件夹筛选：全部、未读、已处理、收藏等文件夹。
- 日期筛选：按入库日期快速筛选。
- 行动记录筛选：按某次抓取行动查看论文。
- 标签筛选：按一个或多个标签过滤论文。
- 分类筛选：按论文分类过滤。
- 排序：支持按时间、标题、状态等字段排序。
- 列表/网格视图：切换不同展示密度。
- 收藏：在列表卡片中收藏或取消收藏。
- 批量选择：选择多篇论文。
- 批量粗读：对选中论文逐篇运行粗读。
- 批量向量化：对选中论文逐篇运行 embedding。
- 批量任务追踪：批量粗读和向量化会写入全局任务状态。
- 手动入库：弹窗输入 arXiv 查询词抓取论文。
- Venue 补全：批量补全 venue 信息。
- 标签管理：新建、编辑、删除标签。
- 标签颜色：创建/编辑标签时可选择颜色。
- 标签计数：标签列表显示关联论文数。
- 分页跳转：首页、上一页、具体页、下一页、末页。

主要接口和文件：

- `GET /papers/latest`
- `GET /papers/recommended`
- `GET /papers/folder-stats`
- `PATCH /papers/{paper_id}/favorite`
- `POST /papers/venues/enrich`
- `GET /actions`
- `GET /actions/{action_id}/papers`
- `GET /tags`
- `POST /tags`
- `PATCH /tags/{tag_id}`
- `DELETE /tags/{tag_id}`
- `POST /pipelines/skim/{paper_id}`
- `POST /pipelines/embed/{paper_id}`
- `frontend/src/pages/Papers.tsx`
- `apps/api/routers/papers.py`
- `apps/api/routers/tags.py`

验收重点：

- 搜索、状态、日期、标签、行动记录筛选互相组合时结果正确。
- 收藏后切到收藏文件夹能看到论文，取消收藏后消失。
- 标签创建、改名、改色、删除都能刷新到列表。
- 批量粗读/向量化中途失败时能统计成功和失败数量。
- 分页切换不会丢失当前筛选条件。

## 5. 论文详情与解析

入口：`/papers/:id`

具体功能：

- 元数据展示：标题、作者、来源、日期、摘要、主题、状态、标签、收藏状态。
- 收藏：详情页可收藏或取消收藏。
- 标签绑定：详情页可给论文添加或移除已有标签。
- 新建并绑定标签：在详情页创建新标签并直接绑定到当前论文。
- PDF 下载：无本地 PDF 时可触发下载。
- PDF 阅读：打开内置 PDF 阅读器。
- 向量化：对当前论文生成 embedding。
- 粗读：生成 60-100 字左右的快速判断报告和粗读评分。
- 精读：生成方法、实验、消融、风险、创新点等详细分析。
- 推理链：生成问题定义、方法链、实验链、影响评估和论证步骤。
- 一键深度分析：按需要自动执行向量化、粗读、精读和推理链补全。
- 相似论文：基于向量检索相似论文，可跳转到相似论文详情。
- 解析追问：在粗读、精读、推理链区域直接追问。
- 解析上下文标记：追问时显示使用了粗读、精读、推理链等上下文。
- 报告持久化：已有粗读/精读/推理链会从数据库读取，不必重复生成。

主要接口和文件：

- `GET /papers/{paper_id}`
- `POST /papers/{paper_id}/download-pdf`
- `GET /papers/{paper_id}/pdf`
- `POST /pipelines/embed/{paper_id}`
- `POST /pipelines/skim/{paper_id}`
- `POST /pipelines/deep/{paper_id}`
- `POST /papers/{paper_id}/reasoning`
- `GET /papers/{paper_id}/similar`
- `POST /papers/{paper_id}/ask`
- `GET /papers/{paper_id}/tags`
- `POST /papers/{paper_id}/tags`
- `DELETE /papers/{paper_id}/tags/{tag_id}`
- `frontend/src/pages/PaperDetail.tsx`
- `packages/ai/pipelines.py`
- `packages/ai/reasoning_service.py`
- `packages/ai/rag_service.py`

验收重点：

- 无 PDF 时下载按钮可用，下载后能打开阅读器。
- 粗读输出必须是可读中文，不应显示提示词、JSON 包裹或字段名。
- 精读不能只给几句空泛总结，应覆盖方法、实验、局限和风险。
- 推理链与精读应衔接，不重复占位。
- 一键深度分析不会重复跑已有步骤。
- 相似论文需要在向量化后可用，未向量化时应给出明确状态。

## 6. PDF 阅读助手

入口：论文详情页打开 PDF 阅读器

具体功能：

- PDF 渲染：按页展示论文 PDF。
- 页码显示：显示当前页和总页数。
- 缩放控制：支持放大、缩小、重置缩放。
- 全屏：支持阅读器全屏显示。
- 关闭：支持关闭阅读器返回详情页。
- 阅读进度条：底部显示阅读位置。
- 选中文本捕获：选择 PDF 文本后右侧助手显示当前选中文本。
- 快捷动作：翻译成中文、解释这段、总结这段、问这篇论文。
- 自由提问：在输入框中输入关于当前段落、整篇论文或已有解析的问题。
- 上下文接入：请求会带选中文本、页码、来源和分析范围。
- 中文回答：默认回答中文，保留必要英文术语。
- 低置信提示：上下文不足时应明确说明不足。
- 当前会话：v1 只保存在当前页面会话中，不做长期持久化。

主要接口和文件：

- `GET /papers/{paper_id}/pdf`
- `POST /papers/{paper_id}/ask`
- `POST /papers/{paper_id}/ai/explain`
- `frontend/src/components/PdfReader.tsx`
- `frontend/src/pages/PaperDetail.tsx`
- `apps/api/routers/papers.py`
- `packages/ai/pdf_parser.py`
- `packages/ai/rag_service.py`

验收重点：

- PDF 能加载、翻页、缩放、全屏和关闭。
- 选中英文段落后，助手顶部显示选中文本摘要。
- 点击“翻译成中文”返回自然中文，而不是英文复述。
- 点击“解释这段”“总结这段”能使用选中文本。
- 输入“这段为什么重要”能结合上下文回答。
- 后端 404 或 LLM 失败时，前端不显示 `[object Object]`。

## 7. RAG、Wiki 与生成内容

入口：

- Wiki：`/wiki`
- 论文详情和 Agent 内也可触发相关能力

具体功能：

- 全库问答：`/rag/ask` 根据本地论文库回答问题。
- 单篇论文 Wiki：按论文生成结构化 Wiki 内容。
- 主题 Wiki：输入关键词生成主题级 Wiki。
- 异步 Wiki：主题 Wiki 和论文 Wiki 都通过任务系统生成并轮询状态。
- 并行生成：主题 Wiki 与论文 Wiki 可以同时生成，页面分别保留进度。
- 热点趋势：获取热门趋势和新兴趋势。
- 生成内容历史：查看已生成的 Wiki 等内容。
- 内容详情：点击历史项查看完整内容。
- 删除历史内容：删除不再需要的生成内容。

主要接口和文件：

- `POST /rag/ask`
- `GET /wiki/paper/{paper_id}`
- `GET /wiki/topic`
- `POST /tasks/wiki/topic`
- `POST /tasks/wiki/paper/{paper_id}`
- `GET /trends/hot`
- `GET /trends/emerging`
- `GET /generated/list`
- `GET /generated/{content_id}`
- `DELETE /generated/{content_id}`
- `frontend/src/pages/Wiki.tsx`
- `apps/api/routers/content.py`
- `packages/ai/rag_service.py`
- `packages/ai/graph_service.py`

验收重点：

- 全库问答能引用本地论文信息，不应完全脱离论文库。
- 主题 Wiki 和论文 Wiki 生成任务都可显示进度，完成后可查看结果。
- 主题 Wiki 和论文 Wiki 同时生成时互不覆盖任务状态。
- 历史内容列表可打开详情和删除。
- 空库时应提示先收集论文，而不是生成虚假内容。

## 8. 设置、邮件与配置

入口：`/settings`

具体功能：

- AI 后端选择：支持选择 LLM 后端或本地 Codex CLI 后端。
- Codex CLI 路径配置：可填写本地 CLI 路径。
- Codex 超时配置：可设置超时时间。
- LLM Provider 列表：查看已配置 Provider。
- Provider 预设：小米、智谱、OpenAI、Anthropic 预置 base url 和模型字段。
- 新增 Provider：填写名称、provider、API Key、base url、文本模型、视觉模型、embedding 模型、备用模型。
- 编辑 Provider：修改模型、base url 和 API Key。
- 激活 Provider：设置全局 active provider。
- 停用 Provider：取消当前 active provider。
- 删除 Provider：删除未激活配置。
- API Key 隐藏显示：表单内支持显示/隐藏 Key。
- 邮件配置列表：查看 SMTP 配置。
- 新增邮件配置：填写 SMTP 服务器、端口、TLS、发件邮箱、用户名、密码等。
- 邮箱预设：读取常见邮箱 SMTP preset。
- 编辑邮件配置：修改 SMTP 信息。
- 激活邮件配置：设置默认发送邮箱。
- 测试邮件配置：发起测试请求。
- 删除邮件配置：删除未激活邮箱。
- 邮件发送开关：启用或禁用邮件发送。
- 精读数量限制：设置自动精读上限。
- 系统健康检查：设置页内可触发系统状态检查。

主要接口和文件：

- `GET /settings/ai-backend`
- `PUT /settings/ai-backend`
- `GET /settings/llm-providers`
- `GET /settings/llm-providers/active`
- `POST /settings/llm-providers`
- `PATCH /settings/llm-providers/{config_id}`
- `DELETE /settings/llm-providers/{config_id}`
- `POST /settings/llm-providers/{config_id}/activate`
- `POST /settings/llm-providers/deactivate`
- `GET /settings/email-configs`
- `POST /settings/email-configs`
- `PATCH /settings/email-configs/{config_id}`
- `DELETE /settings/email-configs/{config_id}`
- `POST /settings/email-configs/{config_id}/activate`
- `POST /settings/email-configs/{config_id}/test`
- `GET /settings/smtp-presets`
- `frontend/src/pages/Settings.tsx`
- `apps/api/routers/settings.py`
- `apps/api/routers/llm_configs.py`

验收重点：

- 新增智谱 Provider 后能激活，其他 AI 功能使用该配置。
- API Key 不应明文显示在列表中。
- 编辑 Provider 后模型字段保存正确。
- 邮箱配置能新增、测试、激活、编辑和删除。
- 健康检查能返回数据库和统计信息。

## 9. 看板、统计与运维任务

入口：

- 看板：`/dashboard`
- 主题统计：`/statistics`

具体功能：

- 系统状态：展示后端健康、数据库状态、论文/主题数量。
- 成本分析：按时间范围展示 token、调用次数和费用估算。
- 最近活动：展示最近抓取和处理行动。
- 手动每日抓取：触发 `/jobs/daily/run-once`。
- 批量处理未读：触发 `/jobs/batch-process-unread`。
- 主题统计：查看每个主题的论文数量、未读、粗读、精读占比。
- 分布统计：按日期、来源、venue、状态等维度查看论文分布。
- 刷新统计：手动重新加载数据。

主要接口和文件：

- `GET /system/status`
- `GET /metrics/costs`
- `GET /pipelines/runs`
- `POST /jobs/daily/run-once`
- `POST /jobs/batch-process-unread`
- `GET /topics/stats`
- `GET /topics/distribution`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Statistics.tsx`
- `apps/api/routers/system.py`
- `apps/api/routers/jobs.py`
- `apps/api/routers/topics.py`

验收重点：

- 看板能在无任务、有任务、任务失败时正常显示。
- 成本统计能切换天数并显示调用分类。
- Pipeline 记录能看到最近运行条目。
- 主题统计的总数与论文库筛选结果大体一致。
- 批量处理未读需要有进度和完成提示。

## 10. 数据、任务与后台能力

这些能力多数没有独立页面，但支撑前端主流程。

具体功能：

- PDF 存储：本地保存到 `data/papers`。
- SQLite 数据库：默认 `data/scholarmind.db`。
- Pipeline 记录：保存粗读、精读、向量化、RAG、Agent 等运行信息。
- 任务状态：后台任务可登记进度、成功、失败和结果。
- 引用导入：从论文参考文献批量导入候选论文。
- 论文源聚合：统一多个论文源返回格式。
- Venue 推断：补全或规范化 venue 字段。
- 成本保护：按调用预算限制 LLM 请求。
- 空闲处理：系统空闲时批量处理未读论文。

主要文件：

- `packages/storage/models.py`
- `packages/storage/db.py`
- `packages/ai/pipelines.py`
- `packages/ai/daily_runner.py`
- `packages/ai/idle_processor.py`
- `packages/ai/cost_guard.py`
- `packages/integrations/aggregator.py`
- `packages/integrations/venue_inference.py`
- `apps/worker/main.py`

验收重点：

- 数据库首次启动能自动初始化表。
- 重启后论文、标签、画像、配置和生成内容不丢失。
- 后台任务失败时能记录错误，而不是静默消失。
- `.env` 缺少 LLM Key 时，非 AI 功能仍能打开，AI 功能有明确提示。
