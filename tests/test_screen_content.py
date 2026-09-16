from collections.abc import Iterator

import pytest

from tuiloom import ContentSize, ScreenContent
from tuiloom.render.content_renderer import ContentRenderer


def test_explicit_factories_classify_each_content_variant() -> None:
    stream: Iterator[str] = iter(["chunk"])

    def dynamic() -> str:
        return "dynamic"

    def responsive(size: ContentSize) -> str:
        return f"{size.width}x{size.height}"

    values = (
        (ScreenContent.static("text"), "static", "static"),
        (ScreenContent.lines(["one", "two"]), "lines", "static"),
        (ScreenContent.stream(stream), "stream", "streaming"),
        (ScreenContent.dynamic(dynamic), "dynamic", "dynamic"),
        (
            ScreenContent.responsive(responsive),
            "responsive",
            "responsive",
        ),
    )

    for content, kind, renderer_state in values:
        assert content._kind == kind
        assert ContentRenderer(content).state == renderer_state


def test_screen_content_must_be_built_with_a_named_factory() -> None:
    with pytest.raises(TypeError, match="named ScreenContent factory"):
        ScreenContent()


def test_lines_keeps_an_immutable_copy() -> None:
    lines = ["one", "two"]
    content = ScreenContent.lines(lines)

    lines.append("three")

    assert content._static_value() == ("one", "two")


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (ScreenContent.static, ["not text"]),
        (ScreenContent.lines, ("not", "a list")),
        (ScreenContent.lines, ["valid", 3]),
        (ScreenContent.stream, ["not", "an iterator"]),
        (ScreenContent.dynamic, "not callable"),
    ],
)
def test_factories_reject_the_wrong_input_kind(
    factory: object,
    value: object,
) -> None:
    with pytest.raises(TypeError):
        factory(value)  # type: ignore[operator]


@pytest.mark.parametrize("name", ["min_width", "min_height"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "4"])
def test_responsive_minimums_require_positive_non_boolean_integers(
    name: str,
    value: object,
) -> None:
    options = {name: value}
    with pytest.raises((TypeError, ValueError)):
        ScreenContent.responsive(lambda size: "", **options)  # type: ignore[arg-type]


def test_responsive_configuration_is_frozen_and_explicit() -> None:
    def renderer(size: ContentSize) -> list[str]:
        return [str(size.width), str(size.height)]

    content = ScreenContent.responsive(
        renderer,
        min_width=40,
        min_height=20,
        refresh_mode="continuous",
    )

    assert content._responsive() is renderer
    assert (content.min_width, content.min_height) == (40, 20)
    assert content.refresh_mode == "continuous"
    with pytest.raises(AttributeError):
        content.min_width = 1  # type: ignore[misc]


def test_responsive_rejects_unknown_refresh_mode() -> None:
    with pytest.raises(ValueError, match="refresh_mode"):
        ScreenContent.responsive(
            lambda size: "",
            refresh_mode="manual",  # type: ignore[arg-type]
        )


def test_content_size_is_a_frozen_value() -> None:
    size = ContentSize(40, 20)

    assert size == ContentSize(width=40, height=20)
    with pytest.raises(AttributeError):
        size.width = 80  # type: ignore[misc]
