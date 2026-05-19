from src.open_llm_vtuber.scene_action_skill import resolve_scene_action_from_text


def test_resolves_treadmill_walk_command_from_soul_md():
    resolution = resolve_scene_action_from_text("Can you walk on the treadmill?")

    assert resolution is not None
    assert resolution.action == "walkOn"
    assert resolution.object_id == "treadmill"


def test_resolves_objectless_action_from_soul_md():
    resolution = resolve_scene_action_from_text("please dance")

    assert resolution is not None
    assert resolution.action == "dance"
    assert resolution.target == "none"
