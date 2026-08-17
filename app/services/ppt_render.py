import json
import tempfile
import subprocess
import os
from app.models.ppt import AiPptInst
from app.services.minio_client import minio_service, generate_object_name
from app.models.schemas import PptSchema


class PptPythonRenderService:
    async def render(self, inst: AiPptInst, schema: PptSchema) -> str:
        schema_json = schema.model_dump_json(ensure_ascii=False)

        # Write schema to temp file if large
        if len(schema_json) > 20 * 1024:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump(json.loads(schema_json), f, ensure_ascii=False)
                schema_path = f.name
        else:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
                f.write(schema_json)
                schema_path = f.name

        template_path = ""
        # Template path needs to be resolved from AiPptTemplate
        # For now use a placeholder

        output_path = tempfile.mktemp(suffix=".pptx")
        try:
            result = subprocess.run(
                ["python", "render_ppt.py", "--schema", schema_path, "--output", output_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"PPT render failed: {result.stderr}")

            with open(output_path, "rb") as f:
                ppt_data = f.read()

            file_id = inst.conversation_id or "output"
            object_name = f"ppt/{file_id}/{file_id}.pptx"
            url = minio_service.upload_file(object_name, ppt_data, "application/vnd.openxmlformats-officedocument.presentationml.document")
            return url
        finally:
            if os.path.exists(schema_path):
                os.unlink(schema_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
