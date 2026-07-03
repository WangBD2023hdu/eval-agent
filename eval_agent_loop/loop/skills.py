from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import AgentLoopError


REQUIRED_SKILLS = ("inference", "evaluation", "task")
TASK_SKILL_DEFAULTS = {
    "omnidocbench_v1_6": "omnidocbench_task",
}


def load_skill_context(skills_dir: str | Path, job: Any) -> dict[str, Any]:
    """Load only the skill documents needed by this job's task chain."""
    root = Path(skills_dir)
    selected: dict[str, str] = {}
    skill_paths: dict[str, Path] = {}
    for name in REQUIRED_SKILLS:
        skill_path = root / name / "SKILL.md"
        if not skill_path.exists():
            raise AgentLoopError(f"missing required skill file: {skill_path}")
        selected[name] = skill_path.read_text(encoding="utf-8")
        skill_paths[name] = skill_path

    for category, skill_name in _referenced_skill_names(job).items():
        if not skill_name:
            continue
        key = _skill_key(category, skill_name)
        skill_path = root / key / "SKILL.md"
        if not skill_path.exists():
            raise AgentLoopError(f"missing referenced skill file for {category}: {skill_path}")
        selected[key] = skill_path.read_text(encoding="utf-8")
        skill_paths[key] = skill_path

    context = select_skill_context(selected, job)
    _attach_skill_paths(context, skill_paths)
    context["available_skill_names"] = _discover_skill_names(root)
    return context


def select_skill_context(skills: dict[str, str], job: Any) -> dict[str, Any]:
    """Select the task skill and the inference/evaluation skills it references."""
    context: dict[str, Any] = {
        "available_skill_names": sorted(skills),
    }
    for category in REQUIRED_SKILLS:
        if category in skills:
            context[f"base_{category}_skill"] = {
                "name": category,
                "content": skills[category],
            }

    references = _referenced_skill_names(job)
    if references["task"]:
        context["active_task_skill"] = _require_skill_entry(skills, "task", references["task"])
    if references["inference"]:
        context["referenced_inference_skill"] = _require_skill_entry(skills, "inference", references["inference"])
    if references["evaluation"]:
        context["referenced_evaluation_skill"] = _require_skill_entry(skills, "evaluation", references["evaluation"])
    return context


def default_task_skill_name(task_name: str | None) -> str | None:
    if not task_name:
        return None
    if task_name in TASK_SKILL_DEFAULTS:
        return TASK_SKILL_DEFAULTS[task_name]
    if "omnidocbench" in task_name.lower():
        return "omnidocbench_task"
    return task_name


def _referenced_skill_names(job: Any) -> dict[str, str | None]:
    job_obj = job if isinstance(job, dict) else {}
    task_obj = job_obj.get("task") if isinstance(job_obj.get("task"), dict) else {}
    inference_obj = job_obj.get("inference") if isinstance(job_obj.get("inference"), dict) else {}
    evaluation_obj = job_obj.get("evaluation") if isinstance(job_obj.get("evaluation"), dict) else {}
    task_name = task_obj.get("name") if isinstance(task_obj.get("name"), str) else None
    return {
        "task": _optional_string(task_obj.get("skill")) or default_task_skill_name(task_name),
        "inference": _optional_string(inference_obj.get("skill")),
        "evaluation": _optional_string(evaluation_obj.get("skill")),
    }


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _require_skill_entry(skills: dict[str, str], category: str, skill_name: str) -> dict[str, str]:
    key = _skill_key(category, skill_name)
    if key not in skills:
        raise AgentLoopError(f"job references missing skill: {key}")
    return {
        "name": key,
        "content": skills[key],
    }


def _skill_key(category: str, skill_name: str) -> str:
    return skill_name if "/" in skill_name else f"{category}/{skill_name}"


def _discover_skill_names(root: Path) -> list[str]:
    names: list[str] = []
    for category in REQUIRED_SKILLS:
        if (root / category / "SKILL.md").exists():
            names.append(category)
        for nested_skill_path in sorted((root / category).glob("*/SKILL.md")):
            names.append(f"{category}/{nested_skill_path.parent.name}")
    return sorted(names)


def _attach_skill_paths(context: dict[str, Any], skill_paths: dict[str, Path]) -> None:
    for value in context.values():
        if not isinstance(value, dict):
            continue
        name = value.get("name")
        if not isinstance(name, str) or name not in skill_paths:
            continue
        skill_path = skill_paths[name].resolve()
        skill_dir = skill_path.parent
        value["path"] = str(skill_path)
        value["skill_dir"] = str(skill_dir)
        value["script_dir"] = str(skill_dir / "scripts")
