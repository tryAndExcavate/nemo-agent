import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.models.ppt import AiPptInst, AiPptTemplate
from app.services.minio_client import minio_service
from app.models.schemas import PptSchema


class PptPythonRenderService:
    """调用完善版 render_ppt.py 渲染 PPT。

    脚本契约：
      - 必填 --template <模板pptx>（真实模板文件路径）
      - --output <输出路径>
      - schema 通过环境变量 PPT_SCHEMA（或 PPT_SCHEMA_FILE）传入
      - schema 字段为 camelCase（pageType/pageDesc/templatePageIndex/fontLimit）
    """

    # render 脚本与调用方同目录，绝对定位，避免工作目录问题
    _RENDER_SCRIPT = Path(__file__).resolve().parent / "render_ppt.py"

    async def render(self, inst: AiPptInst, schema: PptSchema, template: AiPptTemplate | None = None) -> str:
        # 定位模板文件：优先模板配置里的 file_path，否则回退到项目 templates 目录
        template_path = self._resolve_template_path(template)
        if not template_path:
            raise RuntimeError("未找到可用的 PPT 模板文件（请在 app/templates/ 下放置模板，或配置 ai_ppt_template.file_path）")

        # schema 序列化为 camelCase（脚本读 templatePageIndex/fontLimit 等）
        schema_json = schema.model_dump_json(by_alias=True, ensure_ascii=False)

        output_path = tempfile.mktemp(suffix=".pptx")
        env = {**os.environ, "PPT_SCHEMA": schema_json}
        try:
            result = subprocess.run(
                ["python", str(self._RENDER_SCRIPT), "--template", template_path, "--output", output_path],
                capture_output=True, text=True, env=env, timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"PPT render failed: {result.stderr or result.stdout}")
            if not os.path.exists(output_path):
                raise RuntimeError("PPT render 未生成输出文件")

            with open(output_path, "rb") as f:
                ppt_data = f.read()

            file_id = inst.conversation_id or "output"
            object_name = f"ppt/{file_id}/{file_id}.pptx"
            url = minio_service.upload_file(
                object_name, ppt_data,
                "application/vnd.openxmlformats-officedocument.presentationml.document",
            )
            print(url + "!!!!!")
            return url
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def _resolve_template_path(self, template: AiPptTemplate | None) -> str | None:
        candidates: list[str] = []
        if template:
            if template.file_path:
                candidates.append(template.file_path)
            candidates.append(str(Path(__file__).resolve().parent.parent / "templates" / f"{template.template_code}.pptx"))
        else:
            # 模板对象缺失时，兜底到 templates 目录下的任意 pptx
            tpl_dir = Path(__file__).resolve().parent.parent / "templates"
            if tpl_dir.is_dir():
                candidates.extend(str(p) for p in tpl_dir.glob("*.pptx"))
        for c in candidates:
            if c and Path(c).is_file():
                return c
        return None
