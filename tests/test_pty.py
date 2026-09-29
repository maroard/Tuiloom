from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import pytest


def _read_until(master: int, process: subprocess.Popen[bytes], needle: bytes) -> bytes:
    output = bytearray()
    deadline = monotonic() + 5
    while monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
            if needle in output:
                return bytes(output)
        if process.poll() is not None:
            break
    raise AssertionError(f"PTY output did not contain {needle!r}: {bytes(output)!r}")


def _spawn(script: str) -> tuple[subprocess.Popen[bytes], int]:
    master, slave = pty.openpty()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    environment.setdefault("TERM", "xterm-256color")
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
    )
    os.close(slave)
    return process, master


def _read_to_exit(
    master: int,
    process: subprocess.Popen[bytes],
    *,
    timeout: float = 2,
) -> bytes:
    output = bytearray()
    deadline = monotonic() + timeout
    while monotonic() < deadline and process.poll() is None:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
    process.wait(timeout=max(0.1, deadline - monotonic()))
    while True:
        readable, _, _ = select.select([master], [], [], 0)
        if not readable:
            return bytes(output)
        try:
            chunk = os.read(master, 8192)
        except OSError:
            return bytes(output)
        if not chunk:
            return bytes(output)
        output.extend(chunk)


def _finish(process: subprocess.Popen[bytes], master: int) -> bytes:
    try:
        output = _read_until(master, process, b"RESTORED")
        assert process.wait(timeout=2) == 0
        return output
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


def test_read_to_exit_stops_draining_at_pty_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = 0

    class ExitedProcess:
        def poll(self) -> int:
            return 0

        def wait(self, timeout: float) -> int:
            return 0

    def read_once_then_fail(file_descriptor: int, size: int) -> bytes:
        nonlocal reads
        reads += 1
        if reads > 1:
            raise AssertionError("PTY was read again after EOF")
        return b""

    monkeypatch.setattr(select, "select", lambda *args: ([1], [], []))
    monkeypatch.setattr(os, "read", read_once_then_fail)

    assert _read_to_exit(1, ExitedProcess()) == b""  # type: ignore[arg-type]
    assert reads == 1


def test_pty_unicode_navigation_and_terminal_restoration() -> None:
    script = """
from tuiloom import ScreenContent, MenuDisplay, TerminalApp, TerminalMenu
app = TerminalApp("Unicode App")
menu = TerminalMenu(
    app,
    MenuDisplay("main", "Menu界"),
)
menu.add_content_panel(ScreenContent.static("café 👨‍👩‍👧"))
menu.add_command("Activate", lambda context: context.menu.stop())
app.set_main_menu(menu)
app.run()
print("RESTORED")
"""
    process, master = _spawn(script)
    initial = _read_until(master, process, b"Activate")
    os.write(master, b"\r")
    final = initial + _finish(process, master)
    assert "Menu界".encode() in final
    assert "café 👨‍👩‍👧".encode() in final
    assert b"\x1b[?1049l" in final


@pytest.mark.parametrize("no_color", [False, True])
def test_pty_focus_return_redraws_status_and_preserves_input(
    monkeypatch: pytest.MonkeyPatch, no_color: bool
) -> None:
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    script = """
from tuiloom import ScreenContent, MenuDisplay, TerminalApp, TerminalMenu
app = TerminalApp("App")
menu = TerminalMenu(app, MenuDisplay("main", "Main"), presentation="overlay")
menu.add_content_panel(ScreenContent.static("Graph"))
menu.set_status_bar("DONE | Turn 15")
menu.enter_input_mode("Name: ", lambda text: menu.stop())
app.set_main_menu(menu)
app.run()
print("RESTORED", menu._display_input_buffer())
"""
    process, master = _spawn(script)
    try:
        initial = _read_until(master, process, b"Name:")
        assert b"\x1b[?1004$p" not in initial  # No negotiation or late query responses.
        assert b"\x1b[?1004s\x1b[?1004h" in initial
        os.write(master, "é".encode())
        _read_until(master, process, "é".encode())
        os.write(master, b"\x1b[O\x1b[")  # Leave, then a fragmented return report.
        sleep(0.005)
        os.write(master, b"I")
        restored = _read_until(master, process, b"DONE | Turn 15")
        assert b"\x1b[H\x1b[J" in restored
        assert "é".encode() in restored
        os.write(master, b"\r")
        final = _read_to_exit(master, process)
        assert process.returncode == 0
        assert b"\x1b[?1004r" in final
        assert b"\x1b[?1049l" in final
        assert "RESTORED é".encode() in final
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


def test_pty_hidden_input_submits_unicode_and_backspaces_a_grapheme() -> None:
    script = """
from tuiloom import ScreenContent, MenuDisplay, TerminalApp, TerminalMenu
app = TerminalApp("Input App")
menu = TerminalMenu(app, MenuDisplay("main", "Input"))
values = []
def begin(context):
    def submit(value):
        values.append(value)
        menu.leave_input_mode()
        menu.stop()
    menu.enter_input_mode("Password: ", submit, hidden=True)
menu.add_command("Secret", begin)
app.set_main_menu(menu)
app.run()
print(f"VALUE={values[0]!r}")
print("RESTORED")
"""
    process, master = _spawn(script)
    _read_until(master, process, b"Secret")
    os.write(master, b"\r")
    visible = _read_until(master, process, b"Password:")
    os.write(master, "e\u0301👨‍👩‍👧".encode())
    os.write(master, b"\x7f\r")
    final = visible + _finish(process, master)
    assert b"Password:" in final
    assert "VALUE='é'".encode() in final


def test_pty_renders_two_labeled_content_panels() -> None:
    script = """
from tuiloom import ScreenContent, MenuDisplay, TerminalApp, TerminalMenu

app = TerminalApp("App")
menu = TerminalMenu(
    app,
    MenuDisplay("main", "Main"),
)
menu.add_content_panel(ScreenContent.static("alpha"), description="Alpha")
menu.add_content_panel(ScreenContent.static("beta"), description="Beta")
app.set_main_menu(menu)
app.run()
print("RESTORED")
"""
    process, master = _spawn(script)
    initial = _read_until(master, process, b"Beta")
    os.write(master, b"\x1b")
    final = initial + _finish(process, master)
    assert b"Alpha" in final
    assert b"alpha" in final
    assert b"Beta" in final
    assert b"beta" in final
    assert b"Main" in final


def test_pty_overlay_global_toggle_restores_content_and_keeps_diff() -> None:
    script = """
from tuiloom import KeyBinding, ScreenContent, MenuDisplay, TerminalApp, TerminalMenu
app = TerminalApp("Overlay")
menu = TerminalMenu(
    app, MenuDisplay("main", "Main", width=16), presentation="overlay"
)
menu.add_content_panel(
    ScreenContent.static("\\n".join(["界" * 50] * 30)), description="Graph"
)
menu.add_content_panel(ScreenContent.static("logs"), description="Logs")
menu.set_status_bar("READY")
events = []
def toggle(context):
    menu.toggle_menu()
    events.append(menu.menu_visible)
menu.add_command("Launch", lambda context: menu.stop())
app.add_global_command(KeyBinding("g"), "Toggle", toggle)
app.set_main_menu(menu)
menu.hide_menu()
app.run()
print(f"EVENTS={events}")
print("RESTORED")
"""
    process, master = _spawn(script)
    try:
        _read_until(master, process, b"READY")
        os.write(master, b"g")
        opened = _read_until(master, process, b"Launch")
        assert b"\x1b[J" not in opened
        os.write(master, b"g")
        restored = _read_until(master, process, "界界".encode())
        assert b"\x1b[J" not in restored
        os.write(master, b"g")
        _read_until(master, process, b"Launch")
        os.write(master, b"\r")
        final = _read_until(master, process, b"RESTORED")
        assert process.wait(timeout=2) == 0
        assert b"EVENTS=[True, False, True]" in final
        assert b"\x1b[?1049l" in final
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


def test_pty_multi_level_navigation_back_reopen_and_quit() -> None:
    script = """
from tuiloom import MenuDisplay, TerminalApp, TerminalMenu

app = TerminalApp("Journey App")
root = TerminalMenu(app, MenuDisplay("root", "Root"))
child = TerminalMenu(app, MenuDisplay("child", "Child"))
leaf = TerminalMenu(app, MenuDisplay("leaf", "Leaf"))
root.add_submenu(child, "Open child")
child.add_submenu(leaf, "Open leaf")
app.set_main_menu(root)
app.run()
print("RESTORED")
"""
    process, master = _spawn(script)
    try:
        _read_until(master, process, b"Open child")
        os.write(master, b"\r")
        _read_until(master, process, b"Open leaf")
        os.write(master, b"\r")
        leaf_frame = _read_until(master, process, b"Leaf")
        assert b"Back" in leaf_frame

        os.write(master, b"\x1b")
        _read_until(master, process, b"Open leaf")
        os.write(master, b"\x1b")
        root_frame = _read_until(master, process, b"Open child")
        assert b"Quit" in root_frame

        os.write(master, b"\r")
        reopened = _read_until(master, process, b"Open leaf")
        assert b"Child" in reopened
        os.write(master, b"\x1b")
        _read_until(master, process, b"Open child")
        os.write(master, b"\x1b")
        final = _finish(process, master)

        assert b"RESTORED" in final
        assert b"\x1b[?1049l" in final
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        try:
            os.close(master)
        except OSError:
            pass


def test_force_quit_restores_terminal_and_kills_blocked_output_task() -> None:
    script = """
from threading import Event
from tuiloom import MenuDisplay, TerminalApp, TerminalMenu

app = TerminalApp("App")
menu = TerminalMenu(app, MenuDisplay("main", "Main"))
def block_forever():
    print("TASK_STARTED")
    Event().wait()
menu.add_command(
    "Start",
    lambda context: menu.start_output_task(
        block_forever,
        on_success=lambda result: None,
        on_error=lambda error: None,
        description="Blocked",
    ),
)
app.set_main_menu(menu)
app.run()
"""
    process, master = _spawn(script)
    try:
        _read_until(master, process, b"Start")
        os.write(master, b"\r")
        _read_until(master, process, b"TASK_STARTED")
        os.write(master, b"\x1b")
        choice = _read_until(master, process, b"Force quit")
        os.write(master, b"\r")
        final = choice + _read_to_exit(master, process)

        assert process.returncode == 0
        assert b"\x1b[?1049l" in final
        assert b"Stopping operation" not in final
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_pty_status_resize_update_and_navigation_preserve_terminal() -> None:
    import termios

    script = """
from tuiloom import MenuDisplay, StatusBar, TerminalApp, TerminalMenu
app = TerminalApp("App")
root = TerminalMenu(app, MenuDisplay("root", "Root"))
child = TerminalMenu(app, MenuDisplay("child", "Child"))
root.set_status_bar(StatusBar.responsive(lambda width: f"WIDTH={width}"))
child.set_status_bar("CHILD STATUS")
root.add_submenu(child, "Open child")
child.add_command("Clear status", lambda context: child.clear_status_bar())
app.set_main_menu(root)
app.run()
print("RESTORED")
"""
    process, master = _spawn(script)
    try:
        termios.tcsetwinsize(master, (24, 60))
        _read_until(master, process, b"WIDTH=60")
        termios.tcsetwinsize(master, (18, 30))
        _read_until(master, process, b"WIDTH=30")
        os.write(master, b"\r")
        _read_until(master, process, b"CHILD STATUS")
        os.write(master, b"\r")
        cleared = _read_until(master, process, b"Clear status")
        assert b"CHILD STATUS" not in cleared
        os.write(master, b"\x1b")
        _read_until(master, process, b"WIDTH=30")
        os.write(master, b"\x1b")
        final = _read_until(master, process, b"RESTORED")
        assert process.wait(timeout=2) == 0
        assert b"\x1b[?1049l" in final
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


def test_pty_status_callback_failure_restores_terminal() -> None:
    script = """
from tuiloom import MenuDisplay, StatusBar, TerminalApp, TerminalMenu
app = TerminalApp("App")
menu = TerminalMenu(app, MenuDisplay("main", "Main"))
def fail():
    raise ValueError("status failure")
menu.set_status_bar(StatusBar.dynamic(fail))
app.set_main_menu(menu)
try:
    app.run()
except ValueError as error:
    print(str(error))
print("RESTORED")
"""
    process, master = _spawn(script)
    final = _finish(process, master)
    assert b"status failure" in final
    assert b"\x1b[?1049l" in final
