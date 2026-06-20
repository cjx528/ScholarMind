# 小组验收分工

这份分工用于大作业协作。每个人优先测试和修自己负责的功能。如果确实需要修改责任范围外的文件，请先在群里说一声，避免互相覆盖。

更完整的功能说明见 [FUNCTION_INVENTORY.md](FUNCTION_INVENTORY.md)。这里按 A/B/C/D 拆成可执行验收清单。

## A：用户画像、个性化推荐、研究雷达

负责页面：

- `/recommendation`
- `/radar`

需要逐项检查：

- 用户画像页面能正常加载已有 profile、推荐模型和推荐队列。
- “现在最想追”方向足够细：LLM、预训练、后训练、对齐、RAG、Agent、多智能体、代码大模型、MLLM/VLM、多模态推理、图像生成/编辑、视频理解/生成、语音交互、音频理解/生成、具身智能、世界模型、AI4Science、AI Infra 等都能选择。
- “其他方向”可自由填写，非 AI 用户能输入 HCI、数据库、医学影像、计算社会科学等方向。
- “暂时少推”“论文类型偏好”“读论文目的”“探索风格”“补充说明”都能填写和保存。
- 保存画像后刷新页面，所有选项和补充说明仍存在。
- AI 生成画像能输出自然中文的关注偏好、推荐方向、阅读目标和追问，不应暴露提示词、JSON 或后端报错文本。
- 推荐队列能显示论文标题、摘要、来源、推荐理由和评分因素。
- 单篇论文重新分析后，画像匹配、方法价值、实验可信度、可复现性、新颖性、近期趋势等因素有可读解释。
- 打星反馈后推荐队列刷新，模型权重或排序有变化。
- 重置推荐模型后，反馈计数和权重恢复默认。
- 研究雷达能显示生成时间、候选数量、精读候选、速读候选、跳过原因。
- 雷达候选项应有标题、来源、理由、BM25/embedding/画像等分数。
- 雷达候选点击后能进入论文详情页。
- 空库或 LLM 失败时页面有明确提示，不白屏。

主要文件：

- `frontend/src/pages/Compass.tsx`
- `frontend/src/pages/DailyRadar.tsx`
- `apps/api/routers/recommendation.py`
- `packages/ai/compass_service.py`
- `packages/ai/daily_radar_service.py`
- `packages/ai/backend_config.py`
- `tests/test_compass_service.py`
- `tests/test_daily_radar_service.py`

建议报告内容：

- 画像设计为什么能支持 AI 和非 AI 方向。
- 推荐反馈如何影响排序。
- 研究雷达如何帮助用户每天决定读什么。

## B：论文收集、主题订阅、多源渠道、OpenReview、学科订阅

负责页面：

- `/collect`

需要逐项检查：

- arXiv 单源搜索能输入 query、最大数量、排序和时间范围，并把论文写入本地库。
- 多源搜索能选择 arXiv、OpenReview、Semantic Scholar、OpenAlex、DBLP、bioRxiv。
- 多源结果能显示来源、标题、作者、摘要、链接和渠道统计。
- 渠道建议能根据 query 返回建议渠道，用户也能手动改选。
- 外部渠道失败时显示可读错误，不应只有空列表或未捕获异常。
- 主题列表能加载已有主题，显示名称、关键词、描述、启停状态、配额和最近抓取信息。
- 新建主题能保存名称、关键词、描述、每日限制、自动精读数量、抓取时间、渠道和启停状态。
- 编辑主题后刷新页面，修改后的字段仍存在。
- 主题启停按钮能改变状态，并影响后续抓取。
- 删除主题后列表刷新，相关按钮状态正确。
- 关键词建议能根据主题描述返回可用关键词。
- 手动抓取主题时按钮进入 loading，抓取结束后显示新增数量或明确失败原因。
- 抓取状态轮询过程中不重复提交，也不导致页面卡死。
- CS 分类订阅能展示分类列表。
- CS 分类能创建订阅、修改 daily limit、启停、删除和手动抓取。
- 抓取产生的行动记录能在论文库按行动记录查看。

主要文件：

- `frontend/src/pages/Collect.tsx`
- `frontend/src/pages/CSFeeds.tsx`
- `frontend/src/components/search/MultiSourceSearchBar.tsx`
- `frontend/src/components/search/SearchResultsList.tsx`
- `frontend/src/components/topics/TopicChannelSelector.tsx`
- `frontend/src/contexts/ChannelContext.tsx`
- `apps/api/routers/topics.py`
- `apps/api/routers/cs_feeds.py`
- `apps/api/routers/papers.py`
- `packages/ai/daily_runner.py`
- `packages/ai/pipelines.py`
- `packages/integrations/arxiv_channel.py`
- `packages/integrations/openreview_channel.py`
- `packages/integrations/openreview_client.py`
- `packages/integrations/semantic_scholar_search_channel.py`
- `packages/integrations/openalex_search_channel.py`
- `packages/integrations/dblp_channel.py`
- `packages/integrations/biorxiv_channel.py`
- `packages/worker/smart_router.py`
- `tests/test_openreview_client.py`

建议报告内容：

- 多源渠道为什么比单一 arXiv 更适合每日发现。
- 主题订阅的数据结构和抓取流程。
- OpenReview 接入方式和失败降级策略。

## C：论文库、论文详情、PDF 阅读助手、解析与 RAG

负责页面：

- `/papers`
- `/papers/:id`
- PDF 阅读器弹窗

需要逐项检查：

- 论文库能显示分页论文列表，空库时有清晰空状态。
- 搜索、状态筛选、文件夹筛选、日期筛选、标签筛选、行动记录筛选、分类筛选能独立和组合使用。
- 排序和分页切换后，筛选条件不丢失。
- 列表/网格视图切换正常。
- 收藏/取消收藏后，收藏文件夹和卡片状态同步更新。
- 标签能新建、编辑、删除、选择颜色和显示论文数量。
- 多标签筛选结果正确。
- 批量选择论文后，批量粗读和批量向量化能写入全局任务进度。
- 批量任务部分失败时，成功和失败数量有明确提示。
- Venue 补全按钮能返回更新数量或可读错误。
- 论文详情能展示标题、作者、来源、日期、摘要、主题、状态、标签和收藏状态。
- 详情页能绑定/解绑已有标签，也能新建标签后直接绑定。
- 无 PDF 时下载按钮可用，下载成功后能打开 PDF。
- PDF 阅读器能加载、显示页码、缩放、重置缩放、全屏、关闭和显示阅读进度。
- 选中 PDF 英文段落后，助手顶部显示选中文本摘要。
- PDF 助手“翻译成中文”必须返回中文，不应继续英文复述。
- PDF 助手“解释这段”“总结这段”“问这篇论文”能使用选中文本。
- PDF 助手请求失败时不显示 `[object Object]` 或原始后端异常。
- 粗读输出是可读中文，不应显示提示词、JSON 代码块或字段名。
- 精读应覆盖方法、实验、消融、风险、创新点，不应只有几句空泛总结。
- 推理链应包含问题定义、方法链、实验链、影响评估和论证步骤。
- 一键深度分析能按缺失情况补齐向量化、粗读、精读、推理链，不重复跑已有步骤。
- 相似论文在向量化后可用，未向量化时有明确状态。
- 粗读、精读、推理链区域的“追问解析”能带上对应上下文。
- 单篇论文问答默认中文，信息不足时明确说明上下文不足。
- 全库 RAG 问答能根据本地论文库回答，不脱离论文内容编造。

主要文件：

- `frontend/src/pages/Papers.tsx`
- `frontend/src/pages/PaperDetail.tsx`
- `frontend/src/components/PdfReader.tsx`
- `frontend/src/components/ToolPanel/PaperAssistantPanel.tsx`
- `apps/api/routers/papers.py`
- `apps/api/routers/pipelines.py`
- `apps/api/routers/tags.py`
- `packages/ai/pdf_parser.py`
- `packages/ai/pipelines.py`
- `packages/ai/reasoning_service.py`
- `packages/ai/rag_service.py`
- `tests/test_paper_ask.py`
- `tests/test_skim_reports.py`

建议报告内容：

- 论文库如何支撑筛选、标签和批量处理。
- 粗读、精读、推理链之间的区别和衔接。
- PDF 阅读助手如何解决阅读过程中的即时提问。

## D：Agent、Wiki、研究简报、设置、看板、认证、全局任务

负责页面：

- `/`
- `/wiki`
- `/brief`
- `/settings`
- `/dashboard`
- `/statistics`
- 侧边栏和全局任务条

需要逐项检查：

- 登录保护开启后，未登录用户只能看到登录页。
- 登录成功后进入系统，退出登录后刷新仍保持未登录状态。
- 侧边栏工具入口都能跳转：用户画像、研究雷达、论文收集、论文库、Wiki、研究简报、看板、主题统计。
- 侧边栏新建对话、切换历史会话、删除会话正常。
- 明暗主题切换后刷新仍保持。
- Agent 能发送问题并收到流式中文回复。
- Agent 回复过程中停止生成有效。
- Agent 失败后能重试或继续输入。
- Agent 工具步骤能展示搜索调研、下载论文、知识问答、粗读、精读、生成 Wiki、生成简报等意图。
- Agent 待确认动作的确认和拒绝都能完成状态流转。
- Agent 返回论文结果卡片时能跳到论文详情。
- Wiki 能生成单篇论文 Wiki。
- Wiki 能按关键词生成主题 Wiki，并支持异步任务进度。
- Wiki 历史记录能打开详情和删除。
- 研究简报能手动生成，显示提交、生成中、完成或失败状态。
- 简报历史列表能打开详情和删除。
- 设置页能选择 AI 后端，配置 Codex CLI 路径和超时。
- LLM Provider 能新增、编辑、激活、停用、删除。
- Provider 列表不明文展示 API Key。
- 邮件 SMTP 能新增、编辑、激活、测试和删除。
- 日报配置能修改启停、邮件发送、收件人、Cron、自动精读、精读数量、是否包含论文详情。
- 立即运行日报按钮能提交任务或给出明确错误。
- 设置页健康检查能返回数据库、主题和论文统计。
- 看板能展示系统状态、今日摘要、成本分析、Pipeline 运行记录和最近活动。
- 看板中的成本标签和调用类型与当前功能一致。
- 主题统计能展示主题状态分布、日期分布、来源分布、venue 分布和状态分布。
- 全局任务条能显示任务标题、进度和完成/失败状态。

主要文件：

- `frontend/src/pages/Agent.tsx`
- `frontend/src/pages/AgentMessages.tsx`
- `frontend/src/pages/AgentSteps.tsx`
- `frontend/src/pages/Wiki.tsx`
- `frontend/src/pages/DailyBrief.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Statistics.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/GlobalTaskBar.tsx`
- `apps/api/routers/agent.py`
- `apps/api/routers/content.py`
- `apps/api/routers/settings.py`
- `apps/api/routers/jobs.py`
- `apps/api/routers/system.py`
- `apps/api/routers/auth.py`
- `apps/api/routers/llm_configs.py`
- `packages/ai/agent_service.py`
- `packages/ai/agent_tools.py`
- `packages/ai/brief_service.py`
- `packages/ai/graph_service.py`

建议报告内容：

- Agent 如何把系统能力包装成自然语言入口。
- Wiki 和简报如何把论文阅读结果沉淀成长期材料。
- 设置、认证、看板、成本统计如何保证系统可运行和可维护。

## 公共验收要求

- 所有页面刷新后不能白屏。
- 所有 loading 状态结束后必须能回到可操作状态。
- 所有失败都要有可读错误提示。
- AI 输出默认中文，不应泄露内部提示词。
- 如果外部 API 或 LLM 不可用，应说明原因，不编造结果。
- 修改自己负责范围外的文件要在群里说明。

## 群里可以直接发的话

我已经把代码传到 GitHub 了，仓库是 `https://github.com/cjx528/ScholarMind`。功能清单和 A/B/C/D 分工已经重新细化到页面、动作和验收项，大家按自己认领的部分逐项测试：能不能用、输出质量是否够、失败时有没有明确提示。如果发现 bug，就优先在自己负责的文件范围内修；如果必须改到标注之外的代码文件，请在群里说一下，避免互相覆盖。明天我会把报告框架写好，也辛苦大家把各自负责的板块补充完善。
