from importlib.resources import files
from inspect import getdoc

import tuiloom
from tuiloom import CommandContext, ScreenContext, TerminalApp, TerminalMenu


def doc_lines(member: object) -> list[str]:
    doc = getattr(member, "__doc__", None)
    assert doc is not None
    return [line for line in doc.strip().splitlines() if line.strip()]


def test_public_api_contains_only_supported_symbols() -> None:
    expected = {
        "Command",
        "CommandBehavior",
        "CommandContext",
        "CommandDict",
        "ContentSource",
        "ScreenContext",
        "TerminalApp",
        "TerminalMenu",
    }
    assert set(tuiloom.__all__) == expected
    assert all(getattr(tuiloom, name) is not None for name in expected)
    assert not hasattr(tuiloom, "MessageRegistry")


def test_package_declares_inline_typing() -> None:
    assert files("tuiloom").joinpath("py.typed").is_file()


def test_every_public_class_has_documentation() -> None:
    for public_class in (
        CommandContext,
        ScreenContext,
        TerminalApp,
        TerminalMenu,
    ):
        assert getdoc(public_class), public_class.__name__
        assert len(doc_lines(public_class)) > 2, public_class.__name__


def test_every_user_facing_method_has_documentation() -> None:
    user_facing_methods = {
        TerminalApp: (
            "__init__",
            "set_main_menu",
            "add_global_command",
            "add_message",
            "disable_message",
            "enable_message",
            "run",
        ),
        TerminalMenu: (
            "__init__",
            "is_main",
            "add_command",
            "add_menu",
            "set_content_source",
            "disable_message",
            "enable_message",
            "is_message_enabled",
            "set_exit_command_label",
            "run",
            "stop",
        ),
    }

    for public_class, method_names in user_facing_methods.items():
        for method_name in method_names:
            method = getattr(public_class, method_name)
            if isinstance(method, property):
                method = method.fget
            assert getdoc(method), f"{public_class.__name__}.{method_name}"
            assert len(doc_lines(method)) > 2, f"{public_class.__name__}.{method_name}"
