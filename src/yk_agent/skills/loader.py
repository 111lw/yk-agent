"""技能加载器：读取 skills/<name>/SKILL.md 正文（去 frontmatter）。

加载机制与编写规范见 docs/06-skills-spec.md。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


@lru_cache(maxsize=16)
def load_skill(name: str) -> str:
    """加载技能正文；文件缺失抛 FileNotFoundError（注册错技能名应尽早暴露）。"""
    path = _SKILLS_DIR / name / "SKILL.md"
    return _strip_frontmatter(path.read_text(encoding="utf-8"))
