from inspect import signature

import pytest

from tuiloom import (
    CommandBehavior,
    CommandContext,
    ScreenContext,
    TerminalApp,
    TerminalMenu,
)


def make_menu(app: TerminalApp, name: str = "Menu") -> TerminalMenu:
    return TerminalMenu(
        app,
        ScreenContext(app_name="Example", menu_name=name, title=name),
    )


def enter(menu: TerminalMenu, command: str) -> None:
    menu._input_buffer = command
    menu._handle_enter()


def test_local_command_receives_fresh_context_for_each_execution() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    contexts: list[CommandContext] = []
    menu.add_command("Capture", contexts.append, index=10)

    enter(menu, "10")
    enter(menu, "10")

    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert all(context.app is app for context in contexts)
    assert all(context.menu is menu for context in contexts)
    assert all(context.command_key == "10" for context in contexts)


def test_business_dependencies_can_be_captured_by_a_closure() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    def make_generate_command(prefix: str) -> CommandBehavior:
        def generate(context: CommandContext) -> None:
            context.menu.set_content_source(f"{prefix}: generated")

        return generate

    menu.add_command("Generate", make_generate_command("Result"), index=1)
    enter(menu, "1")

    assert menu._content_source == "Result: generated"


def test_unknown_command_keeps_existing_message() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    enter(menu, "missing")

    assert menu.screen_context.message == "Unknown command 'missing'"


def test_callback_exceptions_propagate() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)

    def fail(context: CommandContext) -> None:
        raise RuntimeError(f"failed {context.command_key}")

    menu.add_command("Fail", fail, index=1)

    with pytest.raises(RuntimeError, match="failed 1"):
        enter(menu, "1")


def test_zero_command_stops_menu_without_changing_stop_signature() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    menu.running = True

    enter(menu, "0")

    assert menu.running is False
    assert not signature(menu.stop).parameters


def test_submenu_command_runs_zero_argument_bound_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = TerminalApp("Example")
    parent = make_menu(app, "Parent")
    submenu = make_menu(app, "Child")
    calls: list[str] = []

    def run_submenu() -> None:
        calls.append("child")

    monkeypatch.setattr(submenu, "run", run_submenu)
    parent.add_menu(submenu, "Open child", index=1)

    enter(parent, "1")

    assert calls == ["child"]
    assert not signature(submenu.run).parameters


def test_global_command_receives_normalized_key_and_originating_menu() -> None:
    app = TerminalApp("Example")
    first_menu = make_menu(app, "First")
    second_menu = make_menu(app, "Second")
    contexts: list[CommandContext] = []
    app.add_global_command("x", "Capture", contexts.append)

    enter(second_menu, "x")

    assert len(contexts) == 1
    assert contexts[0].app is app
    assert contexts[0].menu is second_menu
    assert contexts[0].menu is not first_menu
    assert contexts[0].command_key == "X"


def test_global_command_gets_a_new_context_for_each_execution() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    contexts: list[CommandContext] = []
    app.add_global_command("x", "Capture", contexts.append)

    enter(menu, "X")
    enter(menu, "X")

    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]


@pytest.mark.parametrize("command", ["XY", "XX"])
def test_global_input_is_never_split_into_characters(command: str) -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command(
        "x",
        "Run X",
        lambda context: calls.append(context.command_key),
    )
    app.add_global_command(
        "y",
        "Run Y",
        lambda context: calls.append(context.command_key),
    )

    enter(menu, command)

    assert calls == []
    assert menu.screen_context.message == f"Unknown command '{command}'"


def test_one_character_input_executes_exactly_one_global_command() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command(
        "x",
        "Run X",
        lambda context: calls.append(context.command_key),
    )

    enter(menu, "X")

    assert calls == ["X"]


def test_global_command_keeps_priority_over_colliding_local_command() -> None:
    app = TerminalApp("Example")
    menu = make_menu(app)
    calls: list[str] = []
    app.add_global_command(
        "x",
        "Global",
        lambda context: calls.append("global"),
    )
    menu.add_command(
        "Local",
        lambda context: calls.append("local"),
        index=1,
    )
    menu.commands["X"] = menu.commands.pop("1")

    enter(menu, "X")

    assert calls == ["global"]
