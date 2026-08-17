from dataclasses import dataclass


@dataclass
class Segment:
    thinking: bool
    content: str


@dataclass
class ParseResult:
    segments: list[Segment]
    in_think: bool


class ThinkTagParser:
    """Stateless parser that splits LLM streams at <think> / </think> tags."""

    @staticmethod
    def parse(text: str, current_in_think: bool) -> ParseResult:
        segments: list[Segment] = []
        in_think = current_in_think
        i = 0
        buffer = ""

        while i < len(text):
            if not in_think and text[i:].startswith("<think>"):
                if buffer:
                    segments.append(Segment(thinking=False, content=buffer))
                    buffer = ""
                in_think = True
                i += 8
            elif in_think and text[i:].startswith("</think>"):
                if buffer:
                    segments.append(Segment(thinking=True, content=buffer))
                    buffer = ""
                in_think = False
                i += 8
            else:
                buffer += text[i]
                i += 1

        if buffer:
            segments.append(Segment(thinking=in_think, content=buffer))

        return ParseResult(segments=segments, in_think=in_think)

    @staticmethod
    def strip_think_tags(text: str) -> str:
        """Remove <think>...</think> blocks from text."""
        result = text
        while "<think>" in result and "</think>" in result:
            start = result.find("<think>")
            end = result.find("</think>") + 8
            result = result[:start] + result[end:]
        return result.strip()
