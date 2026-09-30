from __future__ import annotations

from queue import Empty, Queue

import pytest

from tuiloom import ContentSize, ScreenContent

from .test_event_loop import make_loop


def test_layout_and_resize_update_each_responsive_size_on_existing_workers() -> None:
    first_sizes: Queue[ContentSize] = Queue()
    second_sizes: Queue[ContentSize] = Queue()

    def first(size: ContentSize) -> str:
        first_sizes.put(size)
        return "first"

    def second(size: ContentSize) -> str:
        second_sizes.put(size)
        return "second"

    menu, loop, _, renderer = make_loop([], content=ScreenContent.responsive(first))
    a = menu.content_panels[0]
    a.update_layout(width_weight=3)
    b = menu.add_content_panel(ScreenContent.responsive(second))
    try:
        renderer._compose_frame(40, 30)
        assert first_sizes.get(timeout=1).width == 38
        assert second_sizes.get(timeout=1).width == 38
        first_worker, second_worker = a._runtime.worker, b._runtime.worker
        first_viewport, second_viewport = a._runtime.viewport, b._runtime.viewport
        menu.set_content_layout([[a, b]])
        renderer._compose_frame(40, 30)
        first_half = first_sizes.get(timeout=1)
        second_half = second_sizes.get(timeout=1)
        assert (first_half.width, second_half.width) == (28, 8)
        assert first_half.height == second_half.height
        assert (a._runtime.worker, b._runtime.worker) == (first_worker, second_worker)
        assert (a._runtime.viewport, b._runtime.viewport) == (
            first_viewport,
            second_viewport,
        )

        renderer._compose_frame(41, 30)
        assert first_sizes.get(timeout=1).width == 29
        with pytest.raises(Empty):
            second_sizes.get_nowait()
        assert b._runtime.effective_size is not None
        assert b._runtime.effective_size.width == 8
        renderer._compose_frame(41, 34)
        assert first_sizes.get(timeout=1).height > first_half.height
        assert second_sizes.get(timeout=1).height > second_half.height
        a.update_layout(width_weight=1)
        renderer._compose_frame(41, 34)
        assert first_sizes.get(timeout=1).width == 19
        assert second_sizes.get(timeout=1).width == 18
        assert (a._runtime.worker, b._runtime.worker) == (first_worker, second_worker)
    finally:
        loop.close()


def test_relayout_keeps_independent_viewports_scroll_and_content() -> None:
    lines = "\n".join(str(index) for index in range(100))
    menu, loop, _, renderer = make_loop([], content=ScreenContent.static(lines))
    a = menu.content_panels[0]
    b = menu.add_content_panel(ScreenContent.static(lines))
    try:
        renderer._compose_frame(40, 25)
        first, second = a._runtime.viewport, b._runtime.viewport
        assert first is not None and second is not None
        for _ in range(4):
            renderer.scroll_panel(a, "down")
        menu.set_content_layout([[a, b]])
        renderer._compose_frame(40, 25)
        assert a._runtime.viewport is first and b._runtime.viewport is second
        assert (first.offset_y, second.offset_y) == (4, 0)
        assert a._runtime.renderer.rendered_content.lines == [
            str(i) for i in range(100)
        ]
        assert b._runtime.renderer.rendered_content.lines == [
            str(i) for i in range(100)
        ]
    finally:
        loop.close()
