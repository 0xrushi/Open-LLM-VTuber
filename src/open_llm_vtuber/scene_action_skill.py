import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SceneActionResolution:
    action: str
    object_id: Optional[str] = None
    target: str = "object"


@dataclass(frozen=True)
class SceneObjectAlias:
    object_id: str
    aliases: list[str]


@dataclass(frozen=True)
class SceneActionIntent:
    action: str
    intents: list[str]
    default_object_id: Optional[str] = None
    required_object_aliases: tuple[str, ...] = ()
    fallback_object_aliases: tuple[str, ...] = ()
    fallback_object_id: Optional[str] = None
    target: str = "object"


@dataclass(frozen=True)
class SceneActionSkill:
    objects: list[SceneObjectAlias]
    actions: list[SceneActionIntent]


SCENE_ACTION_SOUL_PATH = (
    Path(__file__).resolve().parents[2]
    / "Open-LLM-VTuber-Web"
    / "src"
    / "renderer"
    / "src"
    / "skills"
    / "scene-actions"
    / "soul.md"
)


def _split_phrases(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _parse_fields(block: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block:
        normalized = re.sub(r"^- ", "", line).strip()
        if ":" not in normalized:
            continue
        key, value = normalized.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _parse_list_section(source: str, heading: str) -> list[dict[str, str]]:
    heading_match = re.search(rf"^## {re.escape(heading)}\s*$", source, re.MULTILINE)
    if not heading_match:
        return []

    section_start = heading_match.end()
    next_heading = re.search(r"^## ", source[section_start:], re.MULTILINE)
    section = (
        source[section_start : section_start + next_heading.start()]
        if next_heading
        else source[section_start:]
    )

    entries: list[list[str]] = []
    current: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            if current:
                entries.append(current)
            current = [line]
        elif current and line.strip():
            current.append(line)
    if current:
        entries.append(current)

    return [_parse_fields(entry) for entry in entries]


def parse_scene_action_skill(source: str) -> SceneActionSkill:
    objects = [
        SceneObjectAlias(object_id=fields["id"], aliases=_split_phrases(fields.get("aliases")))
        for fields in _parse_list_section(source, "Objects")
        if fields.get("id") and _split_phrases(fields.get("aliases"))
    ]
    actions = [
        SceneActionIntent(
            action=fields["action"],
            intents=_split_phrases(fields.get("intents")),
            default_object_id=fields.get("defaultObjectId"),
            required_object_aliases=tuple(_split_phrases(fields.get("requiredObjectAliases"))),
            fallback_object_aliases=tuple(_split_phrases(fields.get("fallbackObjectAliases"))),
            fallback_object_id=fields.get("fallbackObjectId"),
            target="none" if fields.get("target") == "none" else "object",
        )
        for fields in _parse_list_section(source, "Actions")
        if fields.get("action") and _split_phrases(fields.get("intents"))
    ]
    return SceneActionSkill(objects=objects, actions=actions)


def _phrase_matches(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = phrase.lower().strip()
    if not normalized_phrase:
        return False
    return re.search(
        rf"(^|[^a-z0-9]){re.escape(normalized_phrase)}([^a-z0-9]|$)",
        normalized_text,
        re.IGNORECASE,
    ) is not None


def _any_phrase_matches(normalized_text: str, phrases: tuple[str, ...] | list[str]) -> bool:
    return any(_phrase_matches(normalized_text, phrase) for phrase in phrases)


def load_scene_action_skill(path: Path = SCENE_ACTION_SOUL_PATH) -> SceneActionSkill:
    return parse_scene_action_skill(path.read_text(encoding="utf-8"))


def resolve_scene_action_from_text(text: str, skill: Optional[SceneActionSkill] = None) -> Optional[SceneActionResolution]:
    normalized_text = text.lower()
    active_skill = skill or load_scene_action_skill()

    object_id = ""
    for scene_object in active_skill.objects:
        if _any_phrase_matches(normalized_text, scene_object.aliases):
            object_id = scene_object.object_id
            break

    for intent in active_skill.actions:
        if not _any_phrase_matches(normalized_text, intent.intents):
            continue
        if intent.required_object_aliases and not _any_phrase_matches(normalized_text, intent.required_object_aliases):
            continue
        if intent.action == "stand":
            return SceneActionResolution(action="stand", target="none")

        fallback_object_id = (
            intent.fallback_object_id
            if intent.fallback_object_id and _any_phrase_matches(normalized_text, intent.fallback_object_aliases)
            else None
        )
        resolved_object_id = object_id or intent.default_object_id or fallback_object_id
        if intent.target != "none" and not resolved_object_id:
            continue
        return SceneActionResolution(
            action=intent.action,
            object_id=resolved_object_id,
            target=intent.target,
        )

    return None
