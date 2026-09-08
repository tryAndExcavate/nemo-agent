# Nemo - 为小模型设计的多任务生产级Agent

**N**arrow context · **E**fficient memory · **M**ulti-agent · **O**rchestration


## 命名含义

- **N - Narrow context（窄上下文）** — 面对小模型的现实约束，通过精准的上下文压缩与检索提升对话质量
- **E - Efficient memory（高效记忆）** — 按需检索，不浪费，通过精准召回与摘要压缩实现记忆的高效利用
- **M - Multi-agent（多智能体）** — 子 Agent 系统，支持动态派遣调度、只读隔离记忆、深度环检测
- **O - Orchestration（编排）** — 主 Agent 调度记忆 Agent，通过 QueryEngine 任务模式实现复杂任务编排

## 🎉 最近更新

### v2.0 - 子智能体系统 & 任务管理（2026年9月）

✨ **重大功能更新**：

1. **子智能体系统** - 新增 `subagent/memory` 模块，实现派遣调度、深度环检测、只读隔离记忆；memory-retriever 子智能体带执行预算限制，独立 QueryEngine 无残留落盘

2. **QueryEngine 任务模式** - Global/QueryEngine 双层状态，任务启停锁、Redis Stream 事件流转、AOP 切面记忆 Agent 开关接口与前端控制

3. **对话分支管理** - 分支手风琴功能：新增/删除分支、拖拽删除分支、草稿分支编辑器，支持递归删除和活跃状态恢复

4. **SSE 流保活与竞态修复** - 60s heartbeat 保活、CancelledError 处理、修正 `_persist` 逻辑避免旧任务 done 事件污染

5. **任务统计** - Token、耗时采集、done 事件输出、meta 持久化、前端统计徽章展示

6. **UI 优化** - 新增新建任务按钮、子 Agent 模型插槽、接口补充统计字段

---

## 功能特性

### 🤖 Agent 能力

- **Web Search Agent** (`/agent/chat/stream`) — 联网搜索智能问答，使用 Tavily 搜索引擎
- **File Q&A Agent** (`/agent/file/stream`) — 文件内容问答，支持 PDF/DOCX/TXT/图片
- **Skills Agent** (`/agent/skills/stream`) — 全能型智能体，集成搜索+文件+技能+文件系统工具
- **Deep Research Agent** (`/agent/deep/stream`) — 深度研究，Plan-Execute-Critique 模式
- **PPT Builder Agent** (`/agent/pptx/stream`) — 模板驱动PPT自动生成
- **QueryEngine Agent** (`/agent/task/stream`) — 任务模式，支持任务启停锁、Redis Stream事件流转

### 🔄 子智能体系统 (SubAgent)

- **派遣调度** — 动态派遣子智能体处理特定任务
- **深度环检测** — 防止子智能体循环调用
- **只读隔离记忆** — 子智能体拥有独立的隔离记忆空间
- **memory-retriever 子智能体** — 带执行预算限制的内存检索子智能体
- **独立 QueryEngine** — 子智能体使用独立的 QueryEngine，执行完即销毁，无残留落盘
- **可插拔模型** — 支持为子智能体配置独立的模型

### 🌳 对话分支管理

- **分支手风琴** — 手风琴标签栏"＋ 新增分支"按钮（depth0 竖排 rail + depth≥1 横排 pill）
- **并排分支** — 工具栏"➕ 新增并排分支"按钮，跟随当前活跃节点层级创建
- **草稿分支编辑器** — textarea + 发送/取消 + draft-badge 徽章
- **拖拽删除分支** — rail 标签向右拖 / pill 标签向上拖，超阈值变红飞走
- **递归删除** — 后端自动递归删后代 + 恢复活跃状态

### 📊 任务管理与统计

- **任务模式** — Global/QueryEngine 双层状态管理
- **任务启停锁** — Redis 分布式锁，确保任务互斥执行
- **Token 统计** — 流式调用实时统计输入/输出 tokens 和成本
- **耗时采集** — 任务执行耗时自动采集
- **done 事件输出** — 任务完成事件持久化和前端展示
- **统计徽章** — 前端展示任务统计信息（Token、耗时、成本）

### 🔄 SSE 流保活与竞态修复

- **60s heartbeat 保活** — 长连接心跳检测，防止连接超时
- **CancelledError 处理** — 客户端断开时优雅处理
- **竞态修复** — 避免旧任务 done 事件污染

### 🧠 上下文长对话管理

- **Token 计数器** — tiktoken + 粗略估算双模式中文计数
- **触发判断器** — 达到阈值（默认 70%）自动触发压缩
- **BM25 召回器** — jieba 中文分词 + rank_bm25 相关信息检索
- **三层压缩器** — 近期窗口（Tier1）+ BM25 召回（Tier2）+ 摘要压缩（Tier3）
- **摘要持久化** — 摘要结果保存至 `context_summaries` 表，支持历史召回

### ⚡ Token 消耗统计

- 流式调用实时统计输入/输出 tokens 和成本
- 前端展示用量明细（输入/输出/总计/成本）
- JSONL 格式按日分割的用量日志

### 🔌 摘要模型可插拔

- 蓝图页面可配置/清除摘要基座模型
- 会话首次对话后异步调用摘要模型生成标题（不阻塞回复）

### 💬 多会话管理

- **conversations 表** — 活跃会话，`status` 字段标记最后活跃会话并自动上提排序
- **archived_conversations 表** — 归档会话，支持恢复/永久删除（级联清理关联数据）
- **前端侧边栏** — 对话/归档 Tab 切换、下拉菜单（修改标题/归档）、二次确认删除
- 完整 REST API：列表/创建/激活/重命名/归档/恢复/删除

### 🔧 其他管理

- 会话管理 (`/session/*`) — 会话查询、列表、删除
- 文件管理 (`/file/*`) — 文件上传、查询、内容获取、删除
- 模型管理 (`/models/*`) — 模型配置、可插拔基座模型

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
```

依赖 CDN：Vue 3、Marked、Highlight.js、DOMPurify、Font Awesome（全部走 `<script>/<link>` CDN）。
前端脚本：`app/static/js/{config,constants,utils,api,app}.js`（全局挂载到 `window.*`）。

### 二、新版 Vue3 工程

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
│   ├── base.py          # 摘要模型可插拔配置端点
│   ├── branches.py      # 对话分支 CRUD 端点
│   ├── chat.py          # 对话端点
│   ├── conversations.py # 多会话管理端点（活跃/归档/激活/重命名/删除）
│   ├── directories.py   # 目录管理端点
│   ├── file.py          # 文件 CRUD 端点
│   ├── models.py        # 模型配置端点
│   ├── session.py       # 会话 CRUD 端点
│   └── task.py          # 任务管理端点（启动/停止/查询）
├── agents/              # Agent 实现
│   ├── base.py          # BaseAgent 基类（usage 累加 + 压缩器懒加载）
│   ├── web_search.py    # WebSearchReActAgent
│   ├── file_qa.py       # FileReActAgent
│   ├── skills.py        # SkillsReActAgent
│   ├── deep_research.py # PlanExecuteAgent
│   ├── ppt_builder.py   # PPTBuilderAgent
│   └── query_engine.py  # QueryEngine 任务模式实现
├── subagent/            # 子智能体系统
│   ├── bootstrap.py     # 子智能体引导和初始化
│   ├── definition.py    # 子智能体定义数据结构
│   ├── policy.py        # 子智能体派遣策略（深度环检测等）
│   ├── registry.py      # 子智能体注册中心
│   └── runner.py        # 子智能体执行器（隔离 QueryEngine）
├── memory/              # 记忆系统
│   └── ...              # 子智能体只读隔离记忆实现
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
├── storage/             # 存储管理
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
- **Cache/Lock**: Redis（任务锁、SSE Stream、事件流转）
- **Object Storage**: MinIO
- **File Parsing**: pypdf + python-docx + python-pptx
- **Context**: rank_bm25 + jieba (中文检索)
- **Frontend**: Vue 3 — 旧版走 CDN 单页（`app/static/`，FastAPI 直接托管）；新版工程 `frontend/` 走 Vite + SFC（迁移中），Marked + Highlight.js + DOMPurify
- **流式通信**: SSE (Server-Sent Events) + Heartbeat 保活
- **子智能体**: 隔离 QueryEngine + 只读记忆 + 深度环检测

---

## 📋 简历项目介绍

### **Nemo - 为小模型设计的多任务生产级Agent**

**项目周期**：2024年 - 至今  
**技术栈**：Python | FastAPI | Vue3 | Redis | MySQL | SQLAlchemy | SSE

#### 项目简介
基于 FastAPI 构建的企业级多智能体 AI 对话平台（Nemo：**N**arrow context · **E**fficient memory · **M**ulti-agent · **O**rchestration），支持联网搜索、文件问答、深度研究、PPT 自动生成、子智能体派遣等多种 AI 能力，实现复杂任务的智能分解与执行。

#### 核心职责与技术亮点

**1. 子智能体系统设计与实现（Multi-agent & Orchestration）**
- 设计并实现了可扩展的子智能体框架，支持动态派遣调度、深度环检测防止循环调用
- 实现只读隔离记忆机制，确保子智能体拥有独立的上下文空间，支持预算限制的资源控制
- 采用独立 QueryEngine 架构，子智能体执行完即销毁，避免状态残留

**2. 任务管理与分布式锁机制（Orchestration）**
- 设计 Global/QueryEngine 双层状态管理模型，基于 Redis 实现任务启停锁和分布式互斥
- 构建 Redis Stream 事件流转系统，实现异步任务的实时状态追踪与事件分发
- 集成 Token 统计、耗时采集、done 事件持久化，支持前端实时展示任务统计信息

**3. 上下文长对话管理（Narrow context & Efficient memory）**
- 设计三层上下文压缩机制：近期窗口 + BM25 召回 + 摘要压缩，自动触发压缩（70% 阈值）
- 实现基于 jieba 分词和 rank_bm25 的中文语义检索，支持摘要持久化与历史召回
- 通过 tiktoken + 粗略估算双模式实现精准的 Token 计数

**4. SSE 流式通信与竞态修复**
- 实现 60s heartbeat 保活机制，防止长连接超时断开
- 处理 CancelledError 异常，实现客户端断开时的优雅降级
- 修正竞态问题，避免旧任务 done 事件污染新任务状态

**5. 前端架构与组件化**
- 采用 Vue3 + Vite 渐进式迁移架构，实现旧版 CDN 单页与新版 SFC 工程的平滑切换
- 设计对话分支管理系统（分支手风琴、草稿编辑器、拖拽删除），支持递归删除和活跃状态恢复
- 实现 SSE 流式展示、任务统计徽章、多会话管理（活跃/归档/恢复）

#### 核心技术栈
- **后端**：FastAPI + SQLAlchemy 2.0 (async) + Redis + MySQL + MinIO
- **前端**：Vue3 + Vite + Marked + Highlight.js + DOMPurify
- **AI/LLM**：OpenAI SDK + DashScope (通义千问) + Tavily Search
- **通信**：SSE (Server-Sent Events) + REST API

---

**简短版本（适合技术简历的单段介绍）**：

> **Nemo - 为小模型设计的多任务生产级Agent** (Python/FastAPI/Vue3)  
> **N**arrow context · **E**fficient memory · **M**ulti-agent · **O**rchestration  
> 设计并实现企业级多智能体 AI 对话平台，集成 5 种专业 Agent（联网搜索、文件问答、深度研究、PPT 生成、任务管理），支持子智能体动态派遣与隔离执行。采用 Redis Stream 实现分布式任务流转与状态管理，设计三层上下文压缩机制解决长对话问题，通过 SSE + heartbeat 保活机制实现实时流式响应。项目从 Spring Boot 重构至 FastAPI，支持 Vue3 渐进式迁移架构。
