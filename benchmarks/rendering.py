import os
from io import StringIO
from time import perf_counter

import tuiloom.render.terminal_renderer as terminal_renderer_module
from tuiloom.command import CommandContext
from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.menu_renderer import MenuRenderer
from tuiloom.render.terminal_renderer import TerminalRenderer
from tuiloom.screen_context.screen_context import ScreenContext


def do_nothing(context: CommandContext) -> None:
    """Provide one command callback for the benchmark menu."""


def make_renderer(content_renderer: ContentRenderer) -> TerminalRenderer:
    """Create a fixed-size benchmark renderer."""
    context = ScreenContext(
        app_name="Benchmark",
        menu_name="Main",
        title="Rendering",
        width=50,
        commands={"0": (do_nothing, "Quit")},
    )
    return TerminalRenderer(
        menu_renderer=MenuRenderer(context),
        content_renderer=content_renderer,
        spacing=1,
    )


def benchmark_clean_frames() -> None:
    """Measure attempted renders over unchanged static content."""
    content = ("x" * 80 + "\n") * 100
    renderer = make_renderer(ContentRenderer(content))
    compositions = 0
    original = renderer._compose_frame

    def count(input_buffer: str, width: int, height: int) -> list[str]:
        nonlocal compositions
        compositions += 1
        return original(input_buffer, width, height)

    renderer._compose_frame = count  # type: ignore[method-assign]
    renderer.render()
    started = perf_counter()

    for _ in range(500):
        renderer.render()

    elapsed = perf_counter() - started
    print(
        "clean frames: "
        f"{elapsed:.4f}s, {elapsed / 500 * 1000:.4f}ms/attempt, "
        f"{compositions} composition"
    )


def benchmark_stream_batches() -> None:
    """Measure 4,000 chunks delivered in bounded visual batches."""
    renderer = ContentRenderer(iter(()))
    chunks = ["x"] * 4_000
    started = perf_counter()
    batches = 0

    for start in range(0, len(chunks), 64):
        renderer.append_stream_batch(chunks[start : start + 64])
        batches += 1

    elapsed = perf_counter() - started
    print(
        "stream batches: "
        f"{elapsed:.4f}s, {elapsed / len(chunks) * 1000:.4f}ms/chunk, "
        f"{batches} batches"
    )


def main() -> None:
    """Run rendering benchmarks with fixed terminal dependencies."""
    original_stdout = terminal_renderer_module.stdout
    original_size = terminal_renderer_module.get_terminal_size
    terminal_renderer_module.stdout = StringIO()
    terminal_renderer_module.get_terminal_size = lambda: os.terminal_size((100, 30))

    try:
        benchmark_clean_frames()
        benchmark_stream_batches()
    finally:
        terminal_renderer_module.stdout = original_stdout
        terminal_renderer_module.get_terminal_size = original_size


if __name__ == "__main__":
    main()
