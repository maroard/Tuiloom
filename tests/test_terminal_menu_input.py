from tuiloom.input_handler.input_event import InputEvent
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.terminal_app import TerminalApp
from tuiloom.terminal_menu import TerminalMenu


class RecordingTerminalRenderer(TerminalRenderer):
    """Record input buffers without writing to a terminal."""

    def __init__(self) -> None:
        self.input_buffers: list[str] = []

    def render(self, input_buffer: str = "") -> None:
        self.input_buffers.append(input_buffer)


def make_menu() -> TerminalMenu:
    app = TerminalApp("App")
    return app.set_main_menu("Menu")


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
