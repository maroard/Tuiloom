from collections.abc import Iterator

import pytest

from tuiloom.render.content_renderer import ContentRenderer


def test_static_content_is_rendered_immediately() -> None:
    renderer = ContentRenderer("first\nsecond")

    content = renderer.update()

    assert content.lines == ["first", "second"]
    assert (content.width, content.height) == (6, 2)
    assert content.finished is True


def test_dynamic_content_is_replaced_on_each_update() -> None:
    values = iter(["first", "second\nline"])
    renderer = ContentRenderer(lambda: next(values))

    first = renderer.update()
    assert first.lines == ["first"]

    second = renderer.update()
    assert second.lines == ["second", "line"]
    assert second.finished is False


def test_streamed_content_accumulates_chunks_and_finishes() -> None:
    chunks: Iterator[str] = iter(["first", "\nsecond"])
    renderer = ContentRenderer(chunks)

    first = renderer.update()
    assert first.lines == ["first"]

    second = renderer.update()
    assert second.lines == ["first", "second"]

    third = renderer.update()
    assert third.finished is True


def test_invalid_static_content_raises_type_error() -> None:
    with pytest.raises(TypeError, match="Content source must be"):
        ContentRenderer(["valid", 42])  # type: ignore[list-item]


def test_invalid_streamed_chunk_raises_type_error() -> None:
    chunks: Iterator[str] = iter([42])  # type: ignore[list-item]
    renderer = ContentRenderer(chunks)

    with pytest.raises(TypeError, match="chunks must be str"):
        renderer.update()


def test_content_dimensions_use_visible_width_and_safe_ansi() -> None:
    renderer = ContentRenderer("\x1b[31m界\x1b[0m\x1b[2J\ne\u0301")

    content = renderer.update()

    assert content.width == 2
    assert "\x1b[31m" in content.lines[0]
    assert "\x1b[2J" not in content.lines[0]


def test_streamed_style_is_propagated_across_lines() -> None:
    renderer = ContentRenderer(iter(["\x1b[35mfirst", "\nsecond"]))

    renderer.update()
    content = renderer.update()

    assert content.lines[1].startswith("\x1b[35m")
