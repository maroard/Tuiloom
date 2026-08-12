import pytest

from tuiloom.render.rendered_content import RenderedContent
from tuiloom.render.terminal_text import display_width
from tuiloom.render.viewport import Viewport


def content() -> RenderedContent:
    return RenderedContent(
        lines=["abcdef", "ghijkl", "mnopqr"],
        width=6,
        height=3,
        finished=True,
    )


def test_render_crops_content_and_pads_missing_lines() -> None:
    viewport = Viewport(content(), width=4, height=4)

    assert viewport.render() == "abcd\nghij\nmnop\n    "


def test_scrolling_is_clamped_to_content_bounds() -> None:
    viewport = Viewport(content(), width=3, height=2)

    for _ in range(10):
        viewport.scroll_right()
        viewport.scroll_down()
    assert viewport.render() == "jkl\npqr"

    for _ in range(10):
        viewport.scroll_left()
        viewport.scroll_up()
    assert viewport.render() == "abc\nghi"


@pytest.mark.parametrize("width,height", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_dimensions_must_be_positive(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        Viewport(content(), width=width, height=height)


def test_dimensions_must_be_integers() -> None:
    with pytest.raises(TypeError, match="must be int"):
        Viewport(content(), width=3.0, height=1)  # type: ignore[arg-type]


def test_viewport_clips_and_pads_styled_wide_text_by_columns() -> None:
    rendered = RenderedContent(
        lines=["\x1b[31mA界B\x1b[0m"],
        width=4,
        height=1,
        finished=True,
    )
    viewport = Viewport(rendered, width=3, height=1)

    assert display_width(viewport.render()) == 3
    assert "\x1b[31m" in viewport.render()


def test_horizontal_scroll_does_not_split_wide_grapheme() -> None:
    rendered = RenderedContent(
        lines=["A界B"], width=4, height=1, finished=True
    )
    viewport = Viewport(rendered, width=2, height=1)
    viewport.scroll_right()

    assert viewport.render() == "界"
    assert display_width(viewport.render()) == 2
