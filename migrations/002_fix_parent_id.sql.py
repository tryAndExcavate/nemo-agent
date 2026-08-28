"""
修复已有 ai_session 记录的 parent_id：
为每个 session_id 内按 create_time 排序，第一条保持 NULL，后续每条的 parent_id 指向前一条的 id。
"""
import asyncio
import logging
from sqlalchemy import text
from app.database import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    db = async_session_factory()
    try:
        # 查出所有 distinct session_id
        result = await db.execute(text("SELECT DISTINCT session_id FROM ai_session"))
        sessions = [row[0] for row in result.fetchall()]
        logger.info(f"需要修复 {len(sessions)} 个会话")

        total_updated = 0
        for sid in sessions:
            # 按时间排序获取该会话所有消息
            stmt = text(
                "SELECT id FROM ai_session WHERE session_id = :sid ORDER BY create_time ASC"
            )
            res = await db.execute(stmt, {"sid": sid})
            ids = [row[0] for row in res.fetchall()]

            for i, msg_id in enumerate(ids):
                if i == 0:
                    continue  # 第一条保持 parent_id = NULL
                parent_id = ids[i - 1]
                await db.execute(
                    text("UPDATE ai_session SET parent_id = :pid WHERE id = :id AND parent_id IS NULL"),
                    {"pid": parent_id, "id": msg_id},
                )
                total_updated += 1

        await db.commit()
        logger.info(f"迁移完成，更新了 {total_updated} 条记录")
    except Exception as e:
        await db.rollback()
        logger.error(f"迁移失败: {e}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(migrate())
