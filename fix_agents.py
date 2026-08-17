"""修复所有 agent 中 async with self.db() as db: 的模式"""
import re
from pathlib import Path

AGENTS_DIR = Path(__file__).parent / "app" / "agents"

for filepath in sorted(AGENTS_DIR.glob("*.py")):
    text = filepath.read_text(encoding="utf-8")
    original = text

    # 1. 删除 `async with self.db() as db:` 行
    text = re.sub(r'[ \t]+async with self\.db\(\) as db:\n', '', text)

    # 2. 缩进去掉一层（原本在 async with 块内的代码多缩进了一级）
    lines = text.split('\n')
    fixed_lines = []
    for line in lines:
        # 如果一个文件夹内的代码有17个空格缩进（原来是嵌套在 async with 里），
        # 给它减少 4 个空格
        if line.startswith('                ') and len(line) > 16:
            line = line[4:]
        fixed_lines.append(line)
    text = '\n'.join(fixed_lines)

    # 3. 替换 svc = XXXService(db) → svc = XXXService(self.db)
    text = re.sub(r'svc = (SessionService|PptInstService|PptTemplateService|FileInfoService)\(db\)',
                  r'svc = \1(self.db)', text)

    # 4. tool 执行中的 load_content_tool(db, **args) → load_content_tool(self.db, **args)
    text = re.sub(r'return await load_content_tool\(db,', 'return await load_content_tool(self.db,', text)

    if text != original:
        filepath.write_text(text, encoding="utf-8")
        print(f"Fixed: {filepath.name}")
    else:
        print(f"Clean: {filepath.name}")

print("Done!")
