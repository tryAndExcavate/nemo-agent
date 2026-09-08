# dodo-agent (Python/FastAPI Edition)

豆豆智能体 — 多智能体AI平台

基于 FastAPI 的 Python 重构版本，原项目为 Spring Boot 3.2 + Spring AI (Java)。

## 功能

### Agent 能力
- **Web Search Agent** (`/agent/chat/stream`) — 联网搜索智能问答，使用 Tavily 搜索引擎
- **File Q&A Agent** (`/agent/file/stream`) — 文件内容问答，支持 PDF/DOCX/TXT/图片
- **Skills Agent** (`/agent/skills/stream`) — 全能型智能体，集成搜索+文件+技能+文件系统工具
- **Deep Research Agent** (`/agent/deep/stream`) — 深度研究，Plan-Execute-Critique 模式
- **PPT Builder Agent** (`/agent/pptx/stream`) — 模板驱动PPT自动生成

### 上下文长对话管理 🧠
- **Token 计数器** — tiktoken + 粗略估算双模式中文计数
- **触发判断器** — 达到阈值（默认 70%）自动触发压缩
- **BM25 召回器** — jieba 中文分词 + rank_bm25 相关信息检索
- **三层压缩器** — 近期窗口（Tier1）+ BM25 召回（Tier2）+ 摘要压缩（Tier3）
- **摘要持久化** — 摘要结果保存至 `context_summaries` 表，支持历史召回

### Token 消耗统计 ⚡
- 流式调用实时统计输入/输出 tokens 和成本
- 前端展示用量明细（输入/输出/总计/成本）
- JSONL 格式按日分割的用量日志

### 摘要模型可插拔 🔌
- 蓝图页面可配置/清除摘要基座模型
- 会话首次对话后异步调用摘要模型生成标题（不阻塞回复）

### 多会话管理 💬
- **conversations 表** — 活跃会话，`status` 字段标记最后活跃会话并自动上提排序
- **archived_conversations 表** — 归档会话，支持恢复/永久删除（级联清理关联数据）
- **前端侧边栏** — 对话/归档 Tab 切换、下拉菜单（修改标题/归档）、二次确认删除
- 完整 REST API：列表/创建/激活/重命名/归档/恢复/删除

### 其他管理
- 会话管理 (`/session/*`) — 会话查询、列表、删除
- 文件管理 (`/file/*`) — 文件上传、查询、内容获取、删除

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

复制 `.env.example` 为 `.env` 并修改配置：

```bash
cp .env.example .env
```

必填配置：
- `DASHSCOPE_API_KEY` — 阿里云 DashScope API Key
- `MYSQL_*` — MySQL 数据库连接
- `REDIS_*` — Redis 连接
- `TAVILY_API_KEY` — Tavily 搜索引擎 API Key

### 3. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8888 --reload
```

### 4. API 文档

访问 `http://localhost:8888/docs` 查看 Swagger API 文档。

## 前端使用（Frontend）

> 前端处于**渐进式迁移中**：原「CDN Vue3 单页」由 FastAPI 直接托管（当前线上页面），新「Vite + Vue3 SFC 工程」在 `frontend/` 目录逐步搭建，尚未切换为默认入口。

### 一、旧版单页（默认，可直接用）

由 FastAPI 直接读取 `app/static/` 托管，无需任何前端构建：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8888 --reload
# 浏览器打开 http://localhost:8888
```

依赖 CDN：Vue 3、Marked、Highlight.js、DOMPurify、Font Awesome（全部走 `<script>/<link>` CDN）。
前端脚本：`app/static/js/{config,constants,utils,api,app}.js`（全局挂载到 `window.*`）。

### 二、新版 Vue3 工程（Vite，迁移中）

位于 `frontend/`，用于逐步把单页拆分为标准 SFC 组件。要求 Node.js ≥ 18。

```bash
cd frontend
npm install        # 安装依赖
npm run dev        # 开发服务器 → http://localhost:5173
npm run build      # 产物输出到 frontend/dist
```

**开发说明**：
- dev 端口 `5173`，`vite.config.js` 已配置 proxy 将 `/agent /api /file /chat /session /branches /models /base /conversations` 转发到后端 `http://localhost:8888`，因此**开发时需先启动后端**。
- 修改源码后 Vite 热更新（HMR），无需重启。
- 后端 8888 的旧页面全程不受影响，可两者对照排错。

**当前迁移状态**：
- ✅ Phase 0 骨架：5 个全局脚本已转 ES Module（`frontend/src/lib/`），完整模板+逻辑搬入 `frontend/src/App.vue`，构建/开发链路跑通
- ⏳ Phase 1-3：组件化拆分进行中（低风险叶子组件 → 任务模式 → 聊天/分支）
- ⬜ Phase 4：切换到 FastAPI 托管 `frontend/dist` 产物

**新版工程目录**：

```
frontend/
├── package.json        # vue3 / vite / plugin-vue / marked@4 / highlight.js / dompurify
├── vite.config.js      # dev 5173 + 后端 proxy
├── index.html          # Vite 入口
└── src/
    ├── main.js         # 挂载 #app，导入样式与 window.__copyCode
    ├── App.vue         # 单根模板 + <script setup>（含全部旧逻辑，待拆分）
    ├── lib/            # config / constants / api / utils → ES Module
    └── styles/         # style.css + task-mode.css（原样复制）
```

## 项目结构

```
app/
├── main.py              # FastAPI 入口，lifespan, CORS
├── config.py            # pydantic-settings 配置
├── database.py          # SQLAlchemy async engine & session
├── api/                 # REST API 路由
│   ├── agent.py         # 5 个 SSE 流式端点 + /stop
│   ├── file.py          # 文件 CRUD 端点
│   ├── session.py       # 会话 CRUD 端点
│   ├── conversations.py # 多会话管理端点（活跃/归档/激活/重命名/删除）
│   └── base.py          # 摘要模型可插拔配置端点
├── agents/              # Agent 实现
│   ├── base.py          # BaseAgent 基类（usage 累加 + 压缩器懒加载）
│   ├── web_search.py    # WebSearchReActAgent
│   ├── file_qa.py       # FileReActAgent
│   ├── skills.py        # SkillsReActAgent
│   ├── deep_research.py # PlanExecuteAgent
│   └── ppt_builder.py   # PPTBuilderAgent
├── prompts/             # 提示词模板
│   ├── base.py          # 通用提示词
│   ├── react.py         # Web/File/Skills 提示词
│   ├── plan_execute.py  # Deep Research 提示词
│   └── ppt_builder.py   # PPT 提示词
├── models/              # 数据模型
│   ├── session.py       # AiSession ORM
│   ├── file_info.py     # AiFileInfo ORM
│   ├── ppt.py           # AiPptInst, AiPptTemplate ORM
│   ├── conversation.py  # Conversation / ArchivedConversation ORM
│   ├── context_summary.py # ContextSummary ORM
│   └── schemas.py       # Pydantic 请求/响应模型
├── repositories/        # 数据访问层
│   └── conversation_repo.py # 会话 CRUD + 归档/恢复/级联删除
├── services/            # 业务服务
│   ├── session.py       # 会话服务
│   ├── file_info.py     # 文件信息服务
│   ├── file_manage.py   # 文件上传管理
│   ├── file_parser.py   # PDF/DOCX/TXT 解析
│   ├── embedding.py     # 向量嵌入服务
│   ├── minio_client.py  # MinIO 对象存储
│   ├── task_manager.py  # 分布式任务锁 (Redis)
│   ├── ppt_service.py   # PPT 实例/模板服务
│   ├── ppt_render.py    # PPTX 渲染服务
│   └── context_summary_service.py # 摘要 CRUD 服务
├── context/             # 上下文压缩
│   ├── token_counter.py    # Token 计数
│   ├── compression_trigger.py # 触发判断
│   ├── bm25_retriever.py   # BM25 召回
│   └── compressor.py       # 三层压缩器
├── tools/               # LLM 工具定义
│   ├── file_content.py  # 文件内容加载工具
│   ├── file_system.py   # 文件系统工具 (read/write/edit/list/glob)
│   ├── grep_tool.py     # 正则搜索工具
│   ├── bash_tool.py     # Shell 命令工具
│   └── skills_tool.py   # 技能加载工具
├── llm_core/            # LLM 核心
│   ├── store.py         # 模型配置存储（含摘要模型）
│   ├── manager.py       # 模型适配器管理
│   ├── usage.py         # Token 用量与定价模型
│   └── base.py          # ChatRequest / ChatMessage
└── utils/               # 工具
    ├── think_parser.py  # <think/> 标签解析
    ├── http_client.py   # HTTP 客户端
    └── cursor.py        # 游标编解码
```

## 核心数据流

```
用户操作 → 前端 (Vue 3) → REST API → Repository → MySQL
                                        ↓
                                conversations (活跃会话)
                                archived_conversations (归档会话)
                                        ↓
                                ai_session (消息内容, session_id 关联)
                                context_summaries (会话摘要)
```

## 技术栈

- **Web Framework**: FastAPI + Uvicorn
- **LLM**: OpenAI SDK → DashScope (通义千问)
- **Database**: SQLAlchemy 2.0 async + aiomysql (MySQL)
- **Vector Store**: pgvector (PostgreSQL)
- **Cache/Lock**: Redis
- **Object Storage**: MinIO
- **File Parsing**: pypdf + python-docx + python-pptx
- **Context**: rank_bm25 + jieba (中文检索)
- **Frontend**: Vue 3 — 旧版走 CDN 单页（`app/static/`，FastAPI 直接托管）；新版工程 `frontend/` 走 Vite + SFC（迁移中），Marked + Highlight.js + DOMPurify
