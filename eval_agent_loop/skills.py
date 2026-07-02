from __future__ import annotations

from pathlib import Path

from .errors import AgentLoopError


REQUIRED_SKILLS = ("inference", "evaluation", "task")


def load_skill_bundle(skills_dir: str | Path) -> dict[str, str]:
    root = Path(skills_dir)
    bundle: dict[str, str] = {}
    for name in REQUIRED_SKILLS:
        category_dir = root / name
        skill_path = category_dir / "SKILL.md"
        if not skill_path.exists():
            raise AgentLoopError(f"missing required skill file: {skill_path}")
        bundle[name] = skill_path.read_text(encoding="utf-8")
        for nested_skill_path in sorted(category_dir.glob("*/SKILL.md")):
            nested_name = nested_skill_path.parent.name
            bundle[f"{name}/{nested_name}"] = nested_skill_path.read_text(encoding="utf-8")
    return bundle
