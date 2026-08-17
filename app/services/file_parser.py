import io
from pypdf import PdfReader
from docx import Document


class FileParserService:
    MAX_TEXT_LENGTH = 20000

    def parse(self, content: bytes, file_type: str) -> str:
        file_type_lower = file_type.lower()
        if file_type_lower == "pdf":
            return self._parse_pdf(content)
        elif file_type_lower in ("docx", "doc"):
            return self._parse_docx(content)
        elif file_type_lower in ("txt", "md", "py", "java", "json", "xml", "csv"):
            return self._parse_text(content)
        else:
            return self._parse_text(content)

    def _parse_pdf(self, content: bytes) -> str:
        texts = []
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
        result = "\n".join(texts)
        return result[: self.MAX_TEXT_LENGTH]

    def _parse_docx(self, content: bytes) -> str:
        doc = Document(io.BytesIO(content))
        texts = []
        for para in doc.paragraphs:
            if para.text.strip():
                texts.append(para.text)
        result = "\n".join(texts)
        return result[: self.MAX_TEXT_LENGTH]

    def _parse_text(self, content: bytes) -> str:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
        return text[: self.MAX_TEXT_LENGTH]
