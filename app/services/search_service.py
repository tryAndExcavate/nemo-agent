"""Tavily 搜索引擎 — 使用标准 REST API + 结果解析"""
import json
from app.config import settings
from app.utils.http_client import get_http_client

TAVILY_API_URL = "https://api.tavily.com/search"


async def tavily_search(query: str, search_depth: str = "basic") -> tuple[str, list[dict]]:
    """
    调用 Tavily REST API 搜索。

    返回:
        (tool_response, references)
        - tool_response: 原始 JSON 字符串，包装成 MCP 兼容格式给 LLM 看
        - references:   list[{url, title, content}] 给前端展示
    """
    client = await get_http_client()
    response = await client.post(
        TAVILY_API_URL,
        json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 5,
        },
    )
    response.raise_for_status()
    result = response.json()

    raw_results = result.get("results", [])
    answer = result.get("answer", "")

    # 1. 构建 LLM 工具返回（MCP 兼容格式）
    tool_response = json.dumps([{
        "text": json.dumps({
            "results": raw_results,
            "answer": answer,
        }, ensure_ascii=False)
    }], ensure_ascii=False)

    # 2. 提取引用来源给前端展示
    references = []
    for item in raw_results:
        url = item.get("url", "")
        title = item.get("title", "")
        content = item.get("content", "")
        if url:
            references.append({"url": url, "title": title, "content": content})

    return tool_response, references
