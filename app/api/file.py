import logging
from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.file_manage import FileManageService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/file", tags=["file"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传文件"""
    if not file.filename:
        return {"code": 500, "message": "文件不能为空", "data": None}

    try:
        content = await file.read()
        svc = FileManageService(db)
        file_info = await svc.upload_file(content, file.filename, file.content_type or "application/octet-stream")
        return {"code": 200, "message": "", "data": file_info.model_dump()}
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        return {"code": 500, "message": f"文件上传失败: {e}", "data": None}


@router.get("/info/{file_id}")
async def get_file_info(file_id: str, db: AsyncSession = Depends(get_db)):
    """获取文件信息"""
    try:
        svc = FileManageService(db)
        file_info = await svc.get_file_info(file_id)
        if file_info is None:
            return {"code": 500, "message": "文件不存在", "data": None}
        return {"code": 200, "message": "", "data": file_info.model_dump()}
    except Exception as e:
        return {"code": 500, "message": f"获取文件信息失败: {e}", "data": None}


@router.get("/content/{file_id}")
async def get_file_content(file_id: str, db: AsyncSession = Depends(get_db)):
    """获取文件内容"""
    try:
        svc = FileManageService(db)
        content = await svc.get_file_content(file_id)
        return {"code": 200, "message": "", "data": {"content": content, "length": len(content)}}
    except Exception as e:
        return {"code": 500, "message": f"获取文件内容失败: {e}", "data": None}


@router.delete("/{file_id}")
async def delete_file(file_id: str, db: AsyncSession = Depends(get_db)):
    """删除文件"""
    try:
        svc = FileManageService(db)
        await svc.delete_file(file_id)
        return {"code": 200, "message": "文件删除成功", "data": None}
    except Exception as e:
        return {"code": 500, "message": f"删除文件失败: {e}", "data": None}


@router.get("/list")
async def list_files(db: AsyncSession = Depends(get_db)):
    """获取所有文件列表"""
    try:
        svc = FileManageService(db)
        files = await svc.get_all_files()
        count = await svc.get_file_count()
        return {
            "code": 200, "message": "",
            "data": {"count": count, "files": [f.model_dump() for f in files]},
        }
    except Exception as e:
        return {"code": 500, "message": f"获取文件列表失败: {e}", "data": None}


@router.get("/exists/{file_id}")
async def file_exists(file_id: str, db: AsyncSession = Depends(get_db)):
    """检查文件是否存在"""
    try:
        svc = FileManageService(db)
        exists = await svc.exists(file_id)
        return {"code": 200, "message": "", "data": exists}
    except Exception as e:
        return {"code": 500, "message": f"检查文件存在失败: {e}", "data": None}
