from threading import Thread

from tuiloom.output_capture import OutputCapture
from tuiloom.output_task import OutputTaskSession


def test_session_replays_output_to_a_view_created_after_writes() -> None:
    session = OutputTaskSession()
    session.append_output("10%\r")
    session.append_output("20%\n")
    session.finish_success(None)

    assert list(session.iter_output()) == ["10%\r", "20%\n"]


def test_session_view_waits_for_new_output_until_completion() -> None:
    session = OutputTaskSession()
    received: list[str] = []
    reader = Thread(target=lambda: received.extend(session.iter_output()))
    reader.start()

    session.append_output("downloading")
    session.finish_success(42)
    reader.join(timeout=1)

    assert received == ["downloading"]
    assert session.outcome is not None
    assert session.outcome.result == 42
    assert session.outcome.error is None


def test_session_stores_failure_and_finishes_every_output_view() -> None:
    session = OutputTaskSession()
    first_view = session.iter_output()
    error = ValueError("broken")

    session.append_output("before failure")
    session.finish_error(error)

    assert list(first_view) == ["before failure"]
    assert list(session.iter_output()) == ["before failure"]
    assert session.outcome is not None
    assert session.outcome.error is error


def test_closing_one_output_view_does_not_complete_the_session() -> None:
    session = OutputTaskSession()
    view = session.iter_output()

    view.close()  # type: ignore[attr-defined]
    session.append_output("still running")
    session.finish_success(None)

    assert list(session.iter_output()) == ["still running"]


def test_session_normalizes_system_exit_and_publishes_once() -> None:
    session = OutputTaskSession()
    capture = OutputCapture()
    published: list[OutputTaskSession] = []

    def stop() -> None:
        raise SystemExit("stopped")

    with capture.install():
        session.start(stop, capture, published.append)
        assert session.join(timeout=1) is True

    assert session.outcome is not None
    assert isinstance(session.outcome.error, RuntimeError)
    assert "SystemExit" in str(session.outcome.error)
    assert isinstance(session.outcome.error.__cause__, SystemExit)
    assert list(session.iter_output()) == []
    assert published == [session]


def test_session_keeps_ordinary_action_exception() -> None:
    session = OutputTaskSession()
    capture = OutputCapture()
    published: list[OutputTaskSession] = []
    error = ValueError("broken")

    def fail() -> None:
        raise error

    with capture.install():
        session.start(fail, capture, published.append)
        assert session.join(timeout=1) is True

    assert session.outcome is not None
    assert session.outcome.error is error
    assert published == [session]
