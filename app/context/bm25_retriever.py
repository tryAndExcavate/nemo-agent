"""BM25 相关性召回器 - 会话内历史消息的相关性检索。"""
import re
from typing import List, Dict, Set
from app.context.token_counter import TokenCounter

# 尝试导入 jieba 和 rank_bm25
try:
    import jieba
    from rank_bm25 import BM25Okapi
    HAS_BM25_DEPS = True
except ImportError:
    HAS_BM25_DEPS = False
    jieba = None
    BM25Okapi = None

# 常见中英文停用词
STOPWORDS = {
    "的", "了", "是", "在", "我", "你", "他", "她", "它", "这", "那", "和", "与",
    "就", "都", "而", "及", "或", "一个", "没有", "我们", "你们", "他们", "自己",
    "什么", "怎么", "为什么", "吗", "呢", "啊", "吧", "the", "a", "an", "is",
    "are", "was", "were", "to", "of", "and", "in", "on", "for", "it", "this",
}


def tokenize(text: str) -> List[str]:
    """中英文混合分词：中文用jieba切词，英文按单词切分，统一转小写并过滤停用词。"""
    if not HAS_BM25_DEPS:
        # 降级：如果没有安装 jieba，简单按字符分割
        return list(text.lower())[:100]

    text = text.lower()
    words = jieba.lcut(text)
    tokens = []
    for w in words:
        w = w.strip()
        if not w or w in STOPWORDS:
            continue
        if re.fullmatch(r"[^\w]+", w):
            continue
        tokens.append(w)
    return tokens


class BM25Retriever:
    """会话内相关性召回，每次触发压缩时临时构建 BM25 索引。"""

    def __init__(self, top_k: int = 5, min_score: float = 1.0):
        self.top_k = top_k
        self.min_score = min_score

    def retrieve(
        self,
        candidates: List[Dict],
        query_text: str,
        exclude_ids: Set[int],
        token_budget: int,
        provider: str = "openai",
    ) -> List[Dict]:
        """从候选消息中检索与查询相关的历史消息。

        Args:
            candidates: 候选消息列表，每条含 id/role/content
            query_text: 查询文本（当前用户输入）
            exclude_ids: 已经在 Tier1 近期窗口里的消息 ID，检索时排除
            token_budget: token 预算
            provider: 模型 provider

        Returns:
            按相关度从高到低排列的相关消息列表
        """
        if not HAS_BM25_DEPS:
            return []

        pool = [c for c in candidates if c.get("id") not in exclude_ids and len(c.get("content", "").strip()) >= 4]
        if not pool:
            return []

        corpus_tokens = [tokenize(c.get("content", "")) for c in pool]
        valid = [(c, toks) for c, toks in zip(pool, corpus_tokens) if toks]
        if not valid:
            return []

        pool = [v[0] for v in valid]
        corpus_tokens = [v[1] for v in valid]

        bm25 = BM25Okapi(corpus_tokens)
        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []

        scores = bm25.get_scores(query_tokens)

        scored = [
            (score, msg) for score, msg in zip(scores, pool) if score >= self.min_score
        ]
        scored.sort(key=lambda x: -x[0])

        # 按相关度从高到低贪心装填，直到达到 token 预算或数量上限
        selected, used_tokens = [], 0
        for score, msg in scored[:self.top_k * 3]:  # 多取一些候选，再按预算精筛
            t = TokenCounter.count(msg.get("content", ""), provider)
            if used_tokens + t > token_budget or len(selected) >= self.top_k:
                break
            used_tokens += t
            selected.append({**msg, "relevance_score": round(float(score), 3)})

        return selected
