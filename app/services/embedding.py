"""嵌入向量服务 — DashScope 嵌入 + ChromaDB 向量存储"""
import hashlib
import logging
import chromadb
from openai import AsyncOpenAI
from app.config import settings
from app.utils.overlap_text_splitter import OverlapParagraphTextSplitter

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 9
LARGE_FILE_THRESHOLD = 5000  # 跟 Java 一致


class EmbeddingService:
    def __init__(self):
        # 嵌入客户端（DashScope）
        self.embed_client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.embed_model = settings.dashscope_embedding_model

        # ChromaDB 持久化存储 —— 懒加载，避免启动时 Rust 绑定在部分环境崩溃
        self._chroma_client = None

        # 文案切分器（跟 Java 一致：500 字符，50 重叠）
        self.splitter = OverlapParagraphTextSplitter(chunk_size=500, overlap=50)

    @property
    def chroma_client(self):
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(
                path=settings.chroma_data_path,
            )
        return self._chroma_client

    # ========= 嵌入 =========
    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self.embed_client.embeddings.create(
            model=self.embed_model,
            input=texts,
        )
        return [d.embedding for d in response.data]

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed([text])
        return results[0]

    # ========= 向量存储 =========
    def _get_collection_name(self, file_id: str) -> str:
        safe_id = hashlib.md5(file_id.encode()).hexdigest()[:16]
        return f"rag_{safe_id}"

    def _make_doc_id(self, file_id: str, chunk_idx: int) -> str:
        return f"{file_id}_{chunk_idx}"

    async def embed_and_store(self, file_id: str, chunks: list[dict]) -> int:
        """将切分后的文档嵌入并存入 ChromaDB"""
        if not chunks:
            return 0

        collection_name = self._get_collection_name(file_id)

        # 删除旧 collection（重新入库）
        try:
            self.chroma_client.delete_collection(collection_name)
        except Exception:
            pass

        collection = self.chroma_client.create_collection(
            name=collection_name,
            metadata={"file_id": file_id, "hnsw:space": "cosine"},
        )

        texts = [c["text"] for c in chunks]
        metadatas = [{**c["metadata"], "file_id": file_id} for c in chunks]
        ids = [self._make_doc_id(file_id, i) for i in range(len(chunks))]

        # 分批嵌入
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch_texts = texts[i: i + EMBEDDING_BATCH_SIZE]
            batch_ids = ids[i: i + EMBEDDING_BATCH_SIZE]
            batch_meta = metadatas[i: i + EMBEDDING_BATCH_SIZE]
            embeddings = await self.embed(batch_texts)
            collection.add(ids=batch_ids, embeddings=embeddings, documents=batch_texts, metadatas=batch_meta)

        logger.info(f"向量入库完成: file_id={file_id}, chunks={len(chunks)}")
        return len(chunks)

    # ========= 大文件处理 =========
    def is_large_file(self, text: str) -> bool:
        return len(text) >= LARGE_FILE_THRESHOLD

    async def process_large_file(self, file_id: str, text: str) -> int:
        """处理大文件：切分 → 嵌入 → 存储，返回 chunk 数量"""
        logger.info(f"大文件向量化: file_id={file_id}, text_len={len(text)}")
        chunks = self.splitter.split_documents([{"text": text, "metadata": {"file_id": file_id}}])
        logger.info(f"切分完成: file_id={file_id}, chunks={len(chunks)}")
        return await self.embed_and_store(file_id, chunks)

    # ========= RAG 检索 =========
    async def rag_retrieve(self, file_id: str, question: str, top_k: int = 5) -> list[str]:
        """根据问题检索文件中最相关的文档片段"""
        collection_name = self._get_collection_name(file_id)
        try:
            collection = self.chroma_client.get_collection(collection_name)
        except Exception:
            # 没有向量化，回退到标记直接返回空
            return []

        # 嵌入问题
        query_embedding = await self.embed_single(question)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
        )

        texts: list[str] = []
        seen: set[str] = set()
        if results["documents"] and results["documents"][0]:
            for doc in results["documents"][0]:
                if doc not in seen:
                    seen.add(doc)
                    texts.append(doc)

        logger.info(f"RAG检索: file_id={file_id}, results={len(texts)}")
        return texts

    def delete_collection(self, file_id: str):
        """删除文件对应的向量集合"""
        try:
            self.chroma_client.delete_collection(self._get_collection_name(file_id))
        except Exception:
            pass


# 全局单例
embedding_service = EmbeddingService()
