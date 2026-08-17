import re


class TokenEstimator:
    """Estimates token count: CJK chars ~1.5 chars/token, non-CJK ~4 chars/token."""

    CJK_PATTERN = re.compile(r"[一-鿿㐀-䶿豈-﫿぀-ゟ゠-ヿ가-힯]")

    @staticmethod
    def estimate(text: str) -> int:
        if not text:
            return 0
        cjk_chars = len(TokenEstimator.CJK_PATTERN.findall(text))
        non_cjk_chars = len(text) - cjk_chars
        return int(cjk_chars / 1.5 + non_cjk_chars / 4)

    @staticmethod
    def estimate_messages(messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += TokenEstimator.estimate(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += TokenEstimator.estimate(part["text"])
        return total
