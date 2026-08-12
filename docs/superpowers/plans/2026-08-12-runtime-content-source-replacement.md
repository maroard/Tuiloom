# Runtime Content Source Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make runtime content-source replacement effective in Tuiloom and stream every Call-Me-Maybe prompt through one lazy iterator.

**Architecture:** `TerminalMenu` creates the source-specific `ContentRenderer`; `TerminalRenderer.set_content_renderer()` atomically swaps it, clears the viewport, and invalidates the frame cache. Call-Me-Maybe installs one outer iterator whose `yield from` expressions consume each decoder stream in order.

**Tech Stack:** Python 3.12, iterators, pytest, Ruff, mypy

---

### Task 1: Tuiloom runtime renderer replacement

**Files:**
- Modify: `src/tuiloom/render/terminal_renderer.py`
- Modify: `src/tuiloom/terminal_menu.py`
- Modify: `tests/render/test_terminal_renderer.py`
- Modify: `tests/test_terminal_menu_input.py`

- [ ] **Step 1: Write failing renderer replacement tests**

Add a test that primes `_previous_lines`, `_previous_terminal_size`, and a
viewport, calls `set_content_renderer(new_renderer)`, then asserts the new
renderer is stored and all cached rendering state is `None`:

```python
def test_setting_content_renderer_resets_viewport_and_frame_cache(...) -> None:
    renderer = make_renderer(monkeypatch, StringIO())
    renderer.render()
    renderer.viewport = Viewport(RenderedContent(["old"], 3, 1, True), 3, 1)
    new_content_renderer = ContentRenderer(iter(["new"]))

    renderer.set_content_renderer(new_content_renderer)

    assert renderer.content_renderer is new_content_renderer
    assert renderer.viewport is None
    assert renderer._previous_lines is None
    assert renderer._previous_terminal_size is None
```

- [ ] **Step 2: Run the focused test and observe `AttributeError`**

Run: `.venv/bin/pytest tests/render/test_terminal_renderer.py::test_setting_content_renderer_resets_viewport_and_frame_cache -v`

Expected: FAIL because `set_content_renderer()` does not exist.

- [ ] **Step 3: Implement the renderer boundary**

```python
def set_content_renderer(self, content_renderer: ContentRenderer) -> None:
    """Replace active content and reset source-specific rendering state."""
    self.content_renderer = content_renderer
    self.viewport = None
    self.invalidate()
```

- [ ] **Step 4: Verify the renderer test passes**

Run: `.venv/bin/pytest tests/render/test_terminal_renderer.py -q`

Expected: all renderer tests pass.

- [ ] **Step 5: Write failing menu replacement tests**

Add tests that call `set_content_source()` before active rendering and during
active rendering. For the active case, assert `menu.content_renderer` and
`menu.terminal_renderer.content_renderer` reference the same new object, then
call `update()` and assert the iterator chunk is consumed.

- [ ] **Step 6: Run the focused tests and observe the stale renderer failure**

Run: `.venv/bin/pytest tests/test_terminal_menu_input.py -v`

Expected: the runtime replacement test fails because the active renderer still
owns its old `ContentRenderer`.

- [ ] **Step 7: Implement active source replacement**

Extend `TerminalMenu.set_content_source()`:

```python
self._content_source = content_source

if self.terminal_renderer is None:
    return

self.content_renderer = ContentRenderer(content_source)
self.terminal_renderer.set_content_renderer(self.content_renderer)
```

- [ ] **Step 8: Verify Tuiloom behavior and commit**

Run: `.venv/bin/pytest tests/test_terminal_menu_input.py tests/render/test_terminal_renderer.py tests/render/test_content_renderer.py -q`

Expected: all focused tests pass.

Commit only Tuiloom implementation and test files with message
`feat: replace menu content source at runtime`.

### Task 2: Call-Me-Maybe combined prompt stream

**Files:**
- Modify: `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe/src/__main__.py`
- Create: `/home/maroard/Bureau/42/Cercle-3/Call-Me-Maybe/tests/test_terminal_commands.py`

- [ ] **Step 1: Write a failing lazy multi-prompt test**

Use lightweight fake decoder, prompt builder, menu, and context objects. Invoke
the returned command and assert it installs exactly one iterator without
calling `decoder.stream`. Consume the iterator and assert calls occur in prompt
order and output equals:

```python
[
    "Prompt: first\n\n",
    "generated:first",
    "\n\n",
    "Prompt: second\n\n",
    "generated:second",
    "\n\n",
]
```

- [ ] **Step 2: Run the test and observe eager source replacement**

Run: `uv run pytest tests/test_terminal_commands.py -v`

Expected: FAIL because two sources are installed eagerly and no combined
iterator exists.

- [ ] **Step 3: Implement one outer generator**

Add a nested iterator factory inside `make_generate_command()`:

```python
def stream_prompts() -> Iterator[str]:
    for prompt in prompts:
        instructions = prompt_builder.get_prompt(prompt)
        yield f"Prompt: {prompt}\n\n"
        yield from decoder.stream(instructions)
        yield "\n\n"

def generate(context: CommandContext) -> None:
    context.menu.set_content_source(stream_prompts())
```

Import `Iterator` from `collections.abc` and remove now-unused Tuiloom imports
without changing the surrounding application structure.

- [ ] **Step 4: Verify Call-Me-Maybe focused tests**

Run: `uv run pytest tests/test_terminal_commands.py tests/test_constrained_decoder.py -q`

Expected: all focused tests pass.

Do not commit Call-Me-Maybe because `src/__main__.py` already contains user
changes that must remain user-owned.

### Task 3: Cross-project verification

**Files:**
- No new files.

- [ ] **Step 1: Verify Tuiloom**

Run: `.venv/bin/pytest -q && .venv/bin/ruff format --check src tests && .venv/bin/ruff check src tests && .venv/bin/mypy`

Expected: all commands pass, subject to unrelated user formatting only if those
files remain outside the changed-file check.

- [ ] **Step 2: Verify Call-Me-Maybe**

Run: `uv run pytest -q && uv run mypy src`

Expected: all tests and type checks pass. If existing project-wide lint or type
errors are unrelated, run and report a changed-file check separately.

- [ ] **Step 3: Inspect ownership and diffs**

Run `git status --short` and `git diff --check` in both repositories. Confirm
Tuiloom's pre-existing `MessageKey` edits and all pre-existing Call-Me-Maybe
integration changes remain intact and are not accidentally included in a
Tuiloom feature commit.
