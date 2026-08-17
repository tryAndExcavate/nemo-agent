import httpx
from app.config import settings

_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=300.0)
    return _client


async def close_http_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None
