from types import MappingProxyType

import pytest

from tuiloom import KeyBinding, KeyMap, TerminalApp


def test_key_binding_is_immutable_and_normalizes_special_names() -> None:
    binding = KeyBinding("ESC", ctrl=True)
    assert binding == KeyBinding("escape", ctrl=True)
    with pytest.raises(AttributeError):
        binding.key = "x"  # type: ignore[misc]


@pytest.mark.parametrize("key", ["", 3])
def test_key_binding_rejects_invalid_keys(key: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        KeyBinding(key)  # type: ignore[arg-type]


def test_key_binding_rejects_non_boolean_modifiers() -> None:
    with pytest.raises(TypeError):
        KeyBinding("x", ctrl=1)  # type: ignore[arg-type]


def test_default_keymap_and_read_only_view() -> None:
    keymap = KeyMap()
    assert keymap.focus == KeyBinding("tab")
    assert keymap.activate == KeyBinding("enter")
    assert keymap.back == KeyBinding("escape")
    assert isinstance(keymap.bindings, MappingProxyType)
    with pytest.raises(TypeError):
        keymap.bindings["focus"] = KeyBinding("f")  # type: ignore[index]


def test_keymap_mutation_is_atomic_on_system_collision() -> None:
    keymap = KeyMap()
    previous = keymap.up
    with pytest.raises(ValueError, match="already used"):
        keymap.set_binding("up", keymap.down)
    assert keymap.up is previous


def test_keymap_rejects_unknown_actions_and_wrong_values() -> None:
    keymap = KeyMap()
    with pytest.raises(KeyError):
        keymap.set_binding("missing", KeyBinding("m"))
    with pytest.raises(TypeError):
        keymap.set_binding("up", "u")  # type: ignore[arg-type]
    assert keymap.action_for(KeyBinding("not-bound")) is None
    with pytest.raises(AttributeError):
        _ = keymap.missing


def test_application_global_and_system_collisions_are_atomic() -> None:
    app = TerminalApp("App")
    command = app.add_global_command(KeyBinding("x"), "X", lambda context: None)

    with pytest.raises(ValueError, match="global command"):
        app.add_global_command(KeyBinding("x"), "Again", lambda context: None)
    assert app.global_commands == (command,)

    previous = app.keymap.up
    with pytest.raises(ValueError, match="global command"):
        app.keymap.set_binding("up", KeyBinding("x"))
    assert app.keymap.up is previous

    with pytest.raises(ValueError, match="reserved"):
        app.set_global_command_binding(command, KeyBinding("enter"))
    assert command.binding == KeyBinding("x")
