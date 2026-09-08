import logging
from pathlib import Path
from contextlib import asynccontextmanager
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from app.config import settings
from app.api import agent, file, session, models, base, chat, conversations, branches, task, directories
from app.services.task_manager import task_manager
from app.services.stream_manager import init_stream_manager
from app.utils.http_client import close_http_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 静态文件目录
STATIC_DIR = Path(__file__).resolve().parent / "static"
logger.info(f"Static dir: {STATIC_DIR}")
logger.info(f"index.html exists: {(STATIC_DIR / 'index.html').exists()}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Nemo API server...")
    await task_manager.start()

    # 初始化 Redis Stream 管理器
    sm = init_stream_manager(settings.redis_url)
    await sm.start()

    # 初始化数据库，创建所有表（包括 context_summaries）
    from app.database import init_db
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    logger.info(f"Server port: {settings.server_port}")
    logger.info(f"API docs: http://localhost:{settings.server_port}/docs")

    # 注册子智能体
    from app.subagent.bootstrap import register_all_subagents
    register_all_subagents()

    yield
    logger.info("Shutting down...")
    from app.services.stream_manager import get_stream_manager
    sm = get_stream_manager()
    if sm:
        await sm.close()
    await task_manager.stop()
    await close_http_client()


app = FastAPI(
    title="Nemo API",
    description="Nemo - 为小模型设计的多任务生产级Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== API 路由（先注册，避免被静态文件路由覆盖） =====
app.include_router(agent.router)
app.include_router(file.router)
app.include_router(session.router)
app.include_router(models.router)
app.include_router(base.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(branches.router)
app.include_router(task.router)
app.include_router(directories.router)


# ===== 静态文件路由（纯 @app.get 方式，不用 mount） =====
@app.get("/css/{filename:path}")
async def serve_css(filename: str):
    p = (STATIC_DIR / "css" / filename).resolve()
    if not str(p).startswith(str(STATIC_DIR.resolve())):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    if p.is_file():
        return FileResponse(p, media_type="text/css")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/js/{filename:path}")
async def serve_js(filename: str):
    p = (STATIC_DIR / "js" / filename).resolve()
    if not str(p).startswith(str(STATIC_DIR.resolve())):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    if p.is_file():
        return FileResponse(p, media_type="application/javascript")
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/favicon.ico")
async def serve_favicon():
    return HTMLResponse(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def root():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/blueprint.html", response_class=HTMLResponse)
async def blueprint_page():
    """可插拔大模型基座 - 蓝图 / 模型仓库管理页。"""
    bp = STATIC_DIR / "blueprint.html"
    if not bp.is_file():
        return JSONResponse(status_code=404, content={"detail": "blueprint.html Not Found"})
    return HTMLResponse(bp.read_text(encoding="utf-8"))


# ===== 全局异常处理 =====
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": str(exc), "data": None},
    )
