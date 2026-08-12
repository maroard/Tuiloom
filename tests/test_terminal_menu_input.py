from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu


class RecordingTerminalRenderer(TerminalRenderer):
    """Record input buffers without writing to a terminal."""

    def __init__(self) -> None:
        self.input_buffers: list[str] = []
        self.invalidations = 0

    def render(self, input_buffer: str = "") -> None:
        self.input_buffers.append(input_buffer)

    def invalidate(self) -> None:
        self.invalidations += 1


class RecordingMenuRenderer:
    """Record context refreshes without formatting a menu."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.contexts: list[object] = []

    def update_screen_context(self, screen_context: object) -> None:
        self.contexts.append(screen_context)
        self.events.append("refresh")


class OrderedTerminalRenderer(RecordingTerminalRenderer):
    """Record terminal rendering in a shared event sequence."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def render(self, input_buffer: str = "") -> None:
        self.events.append("render")
        super().render(input_buffer)


def make_menu() -> TerminalMenu:
    app = TerminalApp("App")
    return app.set_main_menu("Menu")


def test_menu_refreshes_screen_context_before_rendering() -> None:
    menu = make_menu()
    events: list[str] = []
    menu_renderer = RecordingMenuRenderer(events)
    terminal_renderer = OrderedTerminalRenderer(events)
    menu.menu_renderer = menu_renderer  # type: ignore[assignment]
    menu.terminal_renderer = terminal_renderer
    menu.screen_context.message = "Credits"

    menu._render()

    assert menu_renderer.contexts == [menu.screen_context]
    assert events == ["refresh", "render"]


def test_menu_forwards_typed_input_to_terminal_renderer() -> None:
    menu = make_menu()
    renderer = RecordingTerminalRenderer()
    menu.terminal_renderer = renderer

    menu._handle_char(InputEvent("char", "a"))
    menu._render()

    assert renderer.input_buffers == ["a"]


def test_menu_forwards_input_after_backspace_to_terminal_renderer() -> None:
    menu = make_menu()
    renderer = RecordingTerminalRenderer()
    menu.terminal_renderer = renderer
    menu._input_buffer = "ab"

    menu._handle_backspace()
    menu._render()

    assert renderer.input_buffers == ["a"]


def test_menu_invalidates_cached_frame_after_command_execution() -> None:
    menu = make_menu()
    renderer = RecordingTerminalRenderer()
    menu.terminal_renderer = renderer
    menu.add_command("Open", lambda context: None, index=1)
    menu._input_buffer = "1"

    menu._handle_enter()

    assert renderer.invalidations == 1


def test_menu_stores_content_source_before_rendering_starts() -> None:
    menu = make_menu()
    stream = iter(["chunk"])

    menu.set_content_source(stream)

    assert menu._content_source is stream
    assert menu.content_renderer is None


def test_menu_replaces_active_content_renderer_and_consumes_new_stream() -> None:
    menu = make_menu()
    menu.running = True
    old_content_renderer = ContentRenderer("old")
    terminal_renderer = TerminalRenderer(
        menu_renderer=MenuRenderer(menu.screen_context),
        content_renderer=old_content_renderer,
        spacing=1,
    )
    menu.content_renderer = old_content_renderer
    menu.terminal_renderer = terminal_renderer
    stream = iter(["chunk"])

    menu.set_content_source(stream)

    assert menu.content_renderer is terminal_renderer.content_renderer
    assert menu.content_renderer is not old_content_renderer
    assert menu.content_renderer.update().lines == ["chunk"]


def test_stopped_menu_stores_source_without_replacing_stale_renderer() -> None:
    menu = make_menu()
    old_content_renderer = ContentRenderer("old")
    terminal_renderer = TerminalRenderer(
        menu_renderer=MenuRenderer(menu.screen_context),
        content_renderer=old_content_renderer,
        spacing=1,
    )
    menu.content_renderer = old_content_renderer
    menu.terminal_renderer = terminal_renderer
    stream = iter(["chunk"])

    menu.set_content_source(stream)

    assert menu._content_source is stream
    assert menu.content_renderer is old_content_renderer
    assert terminal_renderer.content_renderer is old_content_renderer
