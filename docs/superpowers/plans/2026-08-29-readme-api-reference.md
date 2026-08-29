# Complete README API Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current README with a progressive user guide and complete
reference for every public API in Tuiloom 0.1.1.

**Architecture:** Keep one canonical user document. Lead readers from
installation through a runnable menu and focused feature guides, then provide an
exhaustive signature-based reference derived from `tuiloom.__all__` and the
public API tests. Document public behavior and lifecycle constraints while
excluding implementation-only workers and renderers.

**Tech Stack:** GitHub-flavored Markdown, Python 3.12+, Tuiloom 0.1.1, Ruff,
MyPy, pytest, Twine.

---

## File structure

- Modify: `README.md` — canonical installation guide, tutorials, behavior
  documentation, and exhaustive API reference.
- Reference: `src/tuiloom/__init__.py` — authoritative export list.
- Reference: `tests/test_public_api.py` — authoritative public member inventory.
- Reference: `src/tuiloom/terminal_app.py` — application semantics.
- Reference: `src/tuiloom/terminal_menu.py` — menu signatures and lifecycle.
- Reference: `src/tuiloom/command.py`, `src/tuiloom/key_binding.py`,
  `src/tuiloom/screen_context/screen_context.py`,
  `src/tuiloom/_message_registry.py`, and `src/tuiloom/formatting.py` — public
  value objects, aliases, messages, and hyperlinks.

### Task 1: Rewrite the onboarding path

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace stale project status with published metadata**

Add badges linking to PyPI, the CI workflow, supported Python versions, and the
MIT license. State that the current release is 0.1.1, requires Python 3.12 or
newer, and is tested on Linux and macOS. Remove the pre-PyPI warning.

- [ ] **Step 2: Add a navigable table of contents**

Use stable section headings for Installation, Quick start, Core concepts,
Feature guides, API reference, Runtime constraints, and Development.

- [ ] **Step 3: Replace the first example with a runnable typed application**

The example must import only `CommandContext`, `ScreenContext`, `TerminalApp`,
and `TerminalMenu`; create a root menu; add a command receiving
`CommandContext`; register the main menu; and call `app.run()`.

- [ ] **Step 4: Explain the ownership and runtime model**

State that menus belong to one application, submenus must share that owner,
`set_main_menu()` changes the automatic exit label to `Quit`, and
`TerminalApp.run()` is blocking, requires a real interactive terminal, and must
run on Python's main thread.

- [ ] **Step 5: Check the onboarding diff**

Run:

```bash
git diff --check -- README.md
```

Expected: exit status 0 and no output.

### Task 2: Build complete feature guides

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document screen state, navigation, focus, and visibility**

Cover all `ScreenContext` fields, positive minimum-width validation, automatic
Back/Quit row, looping selection, Tab focus, four-direction content scrolling,
solid/dotted focus borders, `content_spacing`, `show`, and the reduced input set
while hidden.

- [ ] **Step 2: Document commands, handles, and submenus**

Show `add_command()` and `add_menu()` returning stable `MenuCommand` handles.
Show label/callback mutation, zero-based movement, enable/disable, exit-label
mutation, immutable `commands`, and handle ownership validation.

- [ ] **Step 3: Document all content forms and scrolling policies**

Define exactly:

```python
ContentSource = (
    str
    | list[str]
    | Iterator[str]
    | Callable[[], str | list[str]]
)
AutoScrollMode = Literal["smart", "strict"]
```

Explain local versus inherited content, no-content rendering, `smart`, `strict`,
and `None`, iterator/dynamic active-work rules, the `description` parameter, and
last-request-wins cooperative replacement.

- [ ] **Step 4: Document captured output and safe shutdown**

Provide a typed `run_with_output()` example. Explain one task per application,
UI-thread callbacks, strict auto-scroll during capture, restored content state,
Python stdout/stderr capture limits, the three root-exit choices, discarded
cancelled outcomes, non-daemon worker joining, irreversible stop, and indefinite
wait for native code that never returns.

- [ ] **Step 5: Document input, alerts, messages, bindings, and hyperlinks**

Include visible and hidden input with grapheme-safe editing; blocking and
confirmable alerts; all five `MessageKey` values and local/global suppression;
default `KeyMap` actions; `KeyBinding` aliases and terminal modifier limits;
global command registration and menu overrides; and `hyperlink()` URL/text
safety rules.

- [ ] **Step 6: Check guide examples against public names**

Run:

```bash
uv run python - <<'PY'
import tuiloom

expected = {
    "AutoScrollMode", "CommandBehavior", "CommandContext", "ContentSource",
    "GlobalCommand", "InputBehavior", "KeyBinding", "KeyMap", "MenuCommand",
    "MessageKey", "ScreenContext", "TerminalApp", "TerminalMenu", "hyperlink",
}
assert set(tuiloom.__all__) == expected
print("all 14 public exports accounted for")
PY
```

Expected: `all 14 public exports accounted for`.

### Task 3: Add the exhaustive API reference

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Reference aliases and value objects**

Document `ContentSource`, `AutoScrollMode`, `CommandBehavior`, `InputBehavior`,
`ScreenContext`, `KeyBinding`, `CommandContext`, `MenuCommand`, `GlobalCommand`,
and `MessageKey`. Include every dataclass/handle field or read-only property and
state that handles are mutated through their owning application/menu.

- [ ] **Step 2: Reference every `KeyMap` member**

Include `KeyMap()`, read-only `bindings`, dynamic action properties (`focus`,
`up`, `down`, `left`, `right`, `activate`, `back`), `set_binding()`, and
`action_for()`. Explain collision validation and atomic mutation.

- [ ] **Step 3: Reference every `TerminalApp` member**

Include the constructor; `name`, `global_content_source`, `keymap`,
`global_commands`, and `main_menu`; `set_main_menu()`; all four global-command
registration/mutation methods; all three message methods; and `run()`. Record
return values, ownership checks, collisions, and lifecycle errors.

- [ ] **Step 4: Reference every `TerminalMenu` member**

Include the constructor; `app`, `screen_context`, `commands`, `is_main`, `show`,
and `auto_scroll`; all command and submenu methods; all global-command override
methods; `set_content_source()`; `run_with_output()`; input methods; alert
methods; all message methods; `run()`; and `stop()`. Preserve exact parameter
defaults and identify setters versus read-only properties.

- [ ] **Step 5: Reference `hyperlink()` and runtime restrictions**

Include its `(text: str, url: str) -> str` signature, accepted URL schemes,
rejected control characters, text sanitization, preserved safe SGR styles, and
`ValueError` behavior. Consolidate main-thread, real-terminal, capture, and
cooperative-thread limitations in a discoverable runtime section.

- [ ] **Step 6: Mechanically compare documented members to the inventory**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
from tests.test_public_api import test_public_api_contains_only_intentional_symbols

readme = Path("README.md").read_text()
required = {
    "TerminalApp": (
        "set_main_menu", "add_global_command", "set_global_command_binding",
        "set_global_command_label", "set_global_command_behavior",
        "add_message", "disable_message", "enable_message", "run",
    ),
    "TerminalMenu": (
        "add_command", "add_menu", "set_command_label", "set_command_behavior",
        "move_command", "disable_command", "enable_command", "set_exit_label",
        "set_global_command_behavior", "clear_global_command_behavior",
        "disable_global_command", "enable_global_command", "set_content_source",
        "run_with_output", "enter_input_mode", "leave_input_mode", "show_alert",
        "clear_alert", "show_message", "clear_message", "disable_message",
        "enable_message", "is_message_enabled", "run", "stop",
    ),
    "KeyMap": ("bindings", "set_binding", "action_for"),
}
for owner, members in required.items():
    assert owner in readme
    for member in members:
        assert f"{member}(" in readme or f"`{member}`" in readme, (owner, member)
test_public_api_contains_only_intentional_symbols()
print("README member inventory complete")
PY
```

Expected: `README member inventory complete`.

### Task 4: Verify and publish the documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Scan for stale and placeholder language**

Run:

```bash
! rg -n "not published|pre-PyPI|Force quit" README.md
```

Expected: exit status 0 and no output.

- [ ] **Step 2: Validate Markdown whitespace and repository checks**

Run:

```bash
git diff --check
env UV_CACHE_DIR=/tmp/tuiloom-uv-cache make check
```

Expected: no whitespace errors; Ruff and MyPy succeed; all tests pass; coverage
stays above 90%.

- [ ] **Step 3: Inspect the final scope**

Run:

```bash
git status --short
git diff --stat HEAD
git diff -- README.md
```

Expected: only `README.md` is uncommitted, with the intended documentation
rewrite.

- [ ] **Step 4: Commit the README**

Run:

```bash
git add README.md
git commit -m "docs: expand README into complete API guide"
```

Expected: one documentation commit modifying `README.md`.

- [ ] **Step 5: Push and verify synchronization**

Run:

```bash
git push origin main
git status --short --branch
```

Expected: push succeeds and local `main` matches `origin/main` with a clean
working tree.
