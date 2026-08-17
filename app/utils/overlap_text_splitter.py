"""段落重叠文本切分器 — 对应 Java OverlapParagraphTextSplitter"""


class OverlapParagraphTextSplitter:
    """按段落切分 + 块间重叠，使语义不丢失"""

    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        if chunk_size <= 0:
            raise ValueError("chunkSize 必须大于 0")
        if overlap < 0:
            raise ValueError("overlap 不能为负数")
        if overlap >= chunk_size:
            raise ValueError("overlap 不能大于等于 chunkSize")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split_text(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        paragraphs = text.split("\n")
        chunks: list[str] = []
        current = ""

        for paragraph in paragraphs:
            if not paragraph.strip():
                continue

            pos = 0
            while pos < len(paragraph):
                remaining = self.chunk_size - len(current)
                end = min(pos + remaining, len(paragraph))
                current += paragraph[pos:end]

                if len(current) >= self.chunk_size:
                    chunks.append(current)
                    # 重叠部分
                    overlap_text = current[max(0, len(current) - self.overlap):] if self.overlap > 0 else ""
                    current = overlap_text

                pos = end

        if current:
            chunks.append(current)

        return chunks

    def split_documents(self, documents: list[dict]) -> list[dict]:
        """批量切分文档，每个 chunk 带元数据"""
        result: list[dict] = []
        for doc in documents:
            chunks = self.split_text(doc["text"])
            for i, chunk in enumerate(chunks):
                result.append({
                    "text": chunk,
                    "metadata": {
                        **(doc.get("metadata", {})),
                        "chunk_id": i,
                    },
                })
        return result
