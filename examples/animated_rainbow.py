"""Animate one rainbow color across a menu, panel and status bar."""

from tuiloom import (
    AnimatedText,
    AnimationFrame,
    ContentSize,
    MenuDisplay,
    ScreenContent,
    StatusBar,
    TerminalApp,
    TerminalMenu,
    rainbow_color,
    style,
)


def rainbow_title(frame: AnimationFrame) -> str:
    return style("Rainbow", bold=True, foreground=rainbow_color(frame.elapsed))


def rainbow_panel(size: ContentSize, frame: AnimationFrame) -> list[str]:
    glyph = style("●", bold=True, foreground=rainbow_color(frame.elapsed))
    left = " " * max(0, (size.width - 1) // 2)
    return ["", left + glyph, "The same color cycle drives all three surfaces."]


def rainbow_status(width: int, frame: AnimationFrame) -> str:
    return style(
        "Rainbow animation • Esc to quit",
        foreground=rainbow_color(frame.elapsed),
    )


def main() -> None:
    app = TerminalApp("Animation example")
    menu = TerminalMenu(
        app,
        MenuDisplay(
            "rainbow",
            AnimatedText("Rainbow", rainbow_title, fps=15),
            text="One shared, pausable clock controls the colors.",
        ),
    )
    menu.add_content_panel(
        ScreenContent.animated(
            rainbow_panel,
            fps=15,
            min_width=40,
            min_height=3,
        )
    )
    menu.set_status_bar(StatusBar.animated(rainbow_status, fps=15))
    app.set_main_menu(menu)
    app.run()


if __name__ == "__main__":
    main()
