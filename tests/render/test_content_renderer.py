import pytest

from tuiloom.render.content_renderer import ContentRenderer
from tuiloom.render.terminal_text import normalize_line


def test_static_content_is_rendered_immediately() -> None:
    renderer = ContentRenderer("first\nsecond")

    content = renderer.update()

    assert content.lines == ["first", "second"]
    assert (content.width, content.height) == (6, 2)
    assert content.finished is True


def test_dynamic_content_is_replaced_only_when_result_is_delivered() -> None:
    renderer = ContentRenderer(lambda: "unused")

    assert renderer.update().lines == [""]

    renderer.replace_dynamic_content("first")
    assert renderer.update().lines == ["first"]

    renderer.replace_dynamic_content("second\nline")
    assert renderer.update().lines == ["second", "line"]


def test_streamed_content_changes_only_when_chunks_are_appended() -> None:
    renderer = ContentRenderer(iter(["unused"]))

    initial = renderer.update()
    assert initial.lines == [""]
    assert initial.revision == 0

    renderer.append_stream_batch(["first", "\nsecond"])
    changed = renderer.update()

    assert changed.lines == ["first", "second"]
    assert changed.revision == 1
    assert renderer.update().revision == 1


def test_invalid_static_content_raises_type_error() -> None:
    with pytest.raises(TypeError, match="Content source must be"):
        ContentRenderer(["valid", 42])  # type: ignore[list-item]


def test_invalid_streamed_batch_chunk_raises_type_error() -> None:
    renderer = ContentRenderer(iter(()))

    with pytest.raises(TypeError, match="chunks must be str"):
        renderer.append_stream_batch([42])  # type: ignore[list-item]


def test_content_dimensions_use_visible_width_and_safe_ansi() -> None:
    renderer = ContentRenderer("\x1b[31m界\x1b[0m\x1b[2J\ne\u0301")

    content = renderer.update()

    assert content.width == 2
    assert "\x1b[31m" in content.lines[0]
    assert "\x1b[2J" not in content.lines[0]


def test_streamed_style_is_propagated_across_lines() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["\x1b[35mfirst", "\nsecond"])
    content = renderer.update()

    assert content.lines[1].startswith("\x1b[35m")


def test_stream_batch_preserves_split_ansi_and_unicode_tail() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["\x1b[35", "mA👨‍"])
    renderer.append_stream_batch(["👩‍👧", "\nsecond"])
    content = renderer.update()

    assert "\x1b[35m" in content.lines[0]
    assert "👨‍👩‍👧" in content.lines[0]
    assert content.lines[1].startswith("\x1b[35m")


def test_stream_revision_changes_once_per_nonempty_batch() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["a", "b", "c"])
    first_revision = renderer.update().revision
    renderer.append_stream_batch([])

    assert first_revision == 1
    assert renderer.update().revision == first_revision


def test_stream_completion_marks_content_finished() -> None:
    renderer = ContentRenderer(iter(()))
    renderer.append_stream_batch(["done"])

    renderer.finish_stream()

    assert renderer.update().finished is True


def test_stream_carriage_return_replaces_active_progress_line() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["Downloading 10%", "\rDownloading 20%"])

    assert renderer.update().lines == ["Downloading 20%"]


def test_stream_carriage_return_replaces_line_within_one_chunk() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["Downloading 10%\rDownloading 100%"])

    assert renderer.update().lines == ["Downloading 100%"]


def test_stream_crlf_commits_a_line_instead_of_replacing_it() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["first\r\nsecond"])

    assert renderer.update().lines == ["first", "second"]


def test_stream_crlf_split_across_batches_still_commits_line() -> None:
    renderer = ContentRenderer(iter(()))

    renderer.append_stream_batch(["first\r"])
    renderer.append_stream_batch(["\nsecond"])

    assert renderer.update().lines == ["first", "second"]


def test_stream_normalization_does_not_reprocess_complete_active_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalized_lengths: list[int] = []
    original = normalize_line

    def record(text: str) -> str:
        normalized_lengths.append(len(text))
        return original(text)

    monkeypatch.setattr("tuiloom.render.content_renderer.normalize_line", record)
    renderer = ContentRenderer(iter(()))

    for _ in range(20):
        renderer.append_stream_batch(["x"] * 64)

    assert max(normalized_lengths) <= 64
