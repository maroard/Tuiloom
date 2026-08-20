import io
import sys
from threading import Event, Thread

import pytest

from tuiloom.output_capture import OutputCapture


def test_capture_routes_background_stdout_and_stderr_but_not_ui_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stdout = io.StringIO()
    original_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    capture = OutputCapture()
    captured: list[str] = []
    active = Event()
    release = Event()

    def task() -> None:
        with capture.route_background_output(captured.append):
            active.set()
            print("task stdout")
            sys.stderr.write("task stderr\n")

            child = Thread(target=lambda: print("child stdout"))
            child.start()
            child.join(timeout=1)
            release.wait(timeout=1)

    with capture.install():
        worker = Thread(target=task)
        worker.start()
        assert active.wait(timeout=1)
        print("ui stdout")
        sys.stderr.write("ui stderr\n")
        release.set()
        worker.join(timeout=1)

    assert "".join(captured) == ("task stdout\ntask stderr\nchild stdout\n")
    assert original_stdout.getvalue() == "ui stdout\n"
    assert original_stderr.getvalue() == "ui stderr\n"


def test_capture_streams_preserve_text_stream_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stdout = io.StringIO()
    original_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    capture = OutputCapture()

    with capture.install():
        assert sys.stdout.encoding == original_stdout.encoding
        assert sys.stderr.encoding == original_stderr.encoding
        assert sys.stdout.isatty() is False
        sys.stdout.flush()
        sys.stderr.flush()


def test_capture_restores_standard_streams_after_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stdout = io.StringIO()
    original_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original_stdout)
    monkeypatch.setattr(sys, "stderr", original_stderr)
    capture = OutputCapture()

    with capture.install():
        assert sys.stdout is not original_stdout
        assert sys.stderr is not original_stderr

    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
