from math import inf, nan

import pytest

from tuiloom import AnimatedText, AnimationFrame, rainbow_color
from tuiloom.animation import AnimationTimeline


def test_animation_frame_is_immutable() -> None:
    frame = AnimationFrame(elapsed=0.5, index=6)
    assert (frame.elapsed, frame.index) == (0.5, 6)
    with pytest.raises(AttributeError):
        frame.index = 7  # type: ignore[misc]


def test_timeline_pauses_and_resumes_without_phase_jump() -> None:
    timeline = AnimationTimeline(10.0)
    assert timeline.elapsed(10.5) == 0.5
    timeline.set_active(False, 10.5)
    assert timeline.elapsed(20.0) == 0.5
    timeline.set_active(True, 20.0)
    assert timeline.elapsed(20.25) == 0.75


def test_animated_text_keeps_renderer_and_rate() -> None:
    source = AnimatedText("fallback", lambda frame: str(frame.index), fps=12)
    assert isinstance(source, str)
    assert source == "fallback"
    assert source.renderer(AnimationFrame(0.25, 3)) == "3"
    assert source.fps == 12
    with pytest.raises(AttributeError):
        source.fps = 24
    with pytest.raises(AttributeError):
        del source.fps


@pytest.mark.parametrize("fps", [0, -1, 61, True, nan, inf, "12"])
def test_animated_text_rejects_invalid_rates(fps: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AnimatedText("x", lambda frame: "x", fps=fps)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("stop", "rgb"),
    [
        (0, (255, 0, 0)),
        (1, (255, 127, 0)),
        (2, (255, 255, 0)),
        (3, (0, 255, 0)),
        (4, (0, 0, 255)),
        (5, (75, 0, 130)),
        (6, (143, 0, 255)),
        (7, (255, 0, 0)),
    ],
)
def test_rainbow_color_cycles_through_seven_stops(
    stop: int, rgb: tuple[int, int, int]
) -> None:
    assert rainbow_color(stop * 0.3, period=2.1) == rgb


def test_rainbow_color_interpolates_between_stops() -> None:
    assert rainbow_color(0.15, period=2.1) == (255, 64, 0)


@pytest.mark.parametrize("elapsed,period", [(-1, 2.1), (nan, 2.1), (0, 0), (0, inf)])
def test_rainbow_color_rejects_invalid_time(elapsed: float, period: float) -> None:
    with pytest.raises((TypeError, ValueError)):
        rainbow_color(elapsed, period=period)
