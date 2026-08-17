# dodo-agent (Python/FastAPI Edition)

豆豆智能体 — 多智能体AI平台

基于 FastAPI 的 Python 重构版本，原项目为 Spring Boot 3.2 + Spring AI (Java)。

## 功能

- **Web Search Agent** (`/agent/chat/stream`) — 联网搜索智能问答，使用 Tavily 搜索引擎
- **File Q&A Agent** (`/agent/file/stream`) — 文件内容问答，支持 PDF/DOCX/TXT/图片
- **Skills Agent** (`/agent/skills/stream`) — 全能型智能体，集成搜索+文件+技能+文件系统工具
- **Deep Research Agent** (`/agent/deep/stream`) — 深度研究，Plan-Execute-Critique 模式
- **PPT Builder Agent** (`/agent/pptx/stream`) — 模板驱动PPT自动生成
- **Session Management** (`/session/*`) — 会话查询、列表、删除
- **File Management** (`/file/*`) — 文件上传、查询、内容获取、删除

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

## 项目结构

```
app/
├── main.py              # FastAPI 入口，lifespan, CORS
├── config.py            # pydantic-settings 配置
├── database.py          # SQLAlchemy async engine & session
├── api/                 # REST API 路由
│   ├── agent.py         # 5 个 SSE 流式端点 + /stop
│   ├── file.py          # 文件 CRUD 端点
│   └── session.py       # 会话 CRUD 端点
├── agents/              # Agent 实现
│   ├── base.py          # BaseAgent 基类
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
│   └── schemas.py       # Pydantic 请求/响应模型
├── services/            # 业务服务
│   ├── session.py       # 会话服务
│   ├── file_info.py     # 文件信息服务
│   ├── file_manage.py   # 文件上传管理
│   ├── file_parser.py   # PDF/DOCX/TXT 解析
│   ├── embedding.py     # 向量嵌入服务
│   ├── minio_client.py  # MinIO 对象存储
│   ├── task_manager.py  # 分布式任务锁 (Redis)
│   ├── ppt_service.py   # PPT 实例/模板服务
│   └── ppt_render.py    # PPTX 渲染服务
├── tools/               # LLM 工具定义
│   ├── file_content.py  # 文件内容加载工具
│   ├── file_system.py   # 文件系统工具 (read/write/edit/list/glob)
│   ├── grep_tool.py     # 正则搜索工具
│   ├── bash_tool.py     # Shell 命令工具
│   └── skills_tool.py   # 技能加载工具
├── context/             # 上下文管理
│   ├── compactor.py     # 上下文压缩
│   └── token_estimator.py # Token 估算
└── utils/               # 工具
    ├── think_parser.py  # <think/> 标签解析
    └── http_client.py   # HTTP 客户端
```

## 技术栈

- **Web Framework**: FastAPI + Uvicorn
- **LLM**: OpenAI SDK → DashScope (通义千问)
- **Database**: SQLAlchemy 2.0 async + aiomysql (MySQL)
- **Vector Store**: pgvector (PostgreSQL)
- **Cache/Lock**: Redis
- **Object Storage**: MinIO
- **File Parsing**: pypdf + python-docx + python-pptx

## 与原 Java 版本的对应关系

| Java | Python |
|------|--------|
| Spring Boot | FastAPI + Uvicorn |
| Spring AI ChatClient | openai.AsyncOpenAI |
| MyBatis-Plus | SQLAlchemy 2.0 |
| Redisson RBucket | redis-py SETNX |
| Sinks.Many + Flux | AsyncGenerator + StreamingResponse |
| BeanOutputConverter | Pydantic |
| @RestControllerAdvice | FastAPI exception_handler |
