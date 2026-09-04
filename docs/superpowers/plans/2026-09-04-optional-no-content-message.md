# Optional No-Content Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop displaying the `NO_CONTENT_SOURCE` footer automatically while preserving the public message key for explicit use, then release Tuiloom 0.2.1.

**Architecture:** Remove the no-content side effect from `TerminalMenu.run()` and retain the message registry and `show_message()` path unchanged. Lock the behavior with a lifecycle regression test, update documentation and package metadata, validate the distribution, and publish through the existing GitHub Release trusted-publishing workflow.

**Tech Stack:** Python 3.12+, pytest, Ruff, mypy, uv, GitHub CLI, GitHub Actions, PyPI trusted publishing

---

### Task 1: Make empty-content menus silent by default

**Files:**
- Modify: `tests/test_menu_modes.py:213-234`
- Modify: `src/tuiloom/terminal_menu.py:501-522`

- [ ] **Step 1: Change the lifecycle test to express the new behavior**

Rename the test and replace its message assertion:

```python
def test_menu_run_builds_resources_without_no_content_message_and_closes_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, menu = make_menu()

    class Loop:
        def __init__(self) -> None:
            self.closed = False

        def run(self) -> None:
            menu._stop_immediately()

        def close(self) -> None:
            self.closed = True

    loop = Loop()
    app._input_handler = object()  # type: ignore[assignment]
    monkeypatch.setattr(menu, "_create_event_loop", lambda: loop)
    menu.run()
    assert loop.closed
    assert menu.screen_context.message is None
    assert menu.show_message(MessageKey.NO_CONTENT_SOURCE)
    assert "No content source" in (menu.screen_context.message or "")
    assert menu._event_loop is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/test_menu_modes.py::test_menu_run_builds_resources_without_no_content_message_and_closes_loop -v
```

Expected: FAIL because the existing lifecycle still populates `screen_context.message`.

- [ ] **Step 3: Remove the automatic message injection**

Delete this block from `TerminalMenu.run()` in `src/tuiloom/terminal_menu.py`:

```python
if not self._content_panels:
    self._show_automatic_message(
        MessageKey.NO_CONTENT_SOURCE,
        menu_name=self.screen_context.menu_name,
    )
```

Keep `MessageKey.NO_CONTENT_SOURCE`, `_MessageRegistry`, `show_message()`, and its contextual `menu_name` formatting unchanged.

- [ ] **Step 4: Run the focused lifecycle and explicit-message tests**

Run:

```bash
uv run pytest tests/test_menu_modes.py::test_menu_run_builds_resources_without_no_content_message_and_closes_loop -v
```

Expected: PASS, proving that the default is silent and explicit message controls still work.

- [ ] **Step 5: Commit the behavior change**

```bash
git add tests/test_menu_modes.py src/tuiloom/terminal_menu.py
git commit -m "fix: keep menus without content silent"
```

### Task 2: Document and version the 0.2.1 release

**Files:**
- Modify: `README.md:13-14`
- Modify: `README.md:44-48`
- Modify: `README.md:305-308`
- Modify: `pyproject.toml:7`
- Modify: `uv.lock:939-940`

- [ ] **Step 1: Update the documented behavior and version**

Change the README release references to `0.2.1` and replace the absent-content paragraph with:

```markdown
A menu constructed with `content_source=None` takes the application's
`global_content_source`. A local source wins when supplied. If neither exists,
the content box is omitted without displaying an automatic message. Applications
can still show `MessageKey.NO_CONTENT_SOURCE` explicitly with `show_message()`.
```

Set the project version in `pyproject.toml`:

```toml
version = "0.2.1"
```

- [ ] **Step 2: Refresh the lockfile**

Run:

```bash
uv lock
```

Expected: the root `tuiloom` package entry in `uv.lock` changes to `version = "0.2.1"` with no unrelated dependency changes.

- [ ] **Step 3: Verify version references**

Run:

```bash
rg -n '0\.2\.0|0\.2\.1|NO_CONTENT_SOURCE.*shown|shown.*NO_CONTENT_SOURCE' README.md pyproject.toml uv.lock
```

Expected: all release references identify 0.2.1 and the README no longer claims the no-content message appears automatically.

- [ ] **Step 4: Commit release metadata**

```bash
git add README.md pyproject.toml uv.lock
git commit -m "chore: release v0.2.1"
```

### Task 3: Validate and publish v0.2.1

**Files:**
- Verify: all source, tests, metadata, and generated distributions

- [ ] **Step 1: Run the complete quality gate**

Run:

```bash
make check
```

Expected: Ruff lint and format checks, strict mypy, pytest, and coverage threshold all pass.

- [ ] **Step 2: Build and validate distributions**

Run:

```bash
rm -rf dist build
make build
```

Expected: `tuiloom-0.2.1.tar.gz` and `tuiloom-0.2.1-py3-none-any.whl` are built and both pass `twine check`.

- [ ] **Step 3: Confirm release state before publishing**

Run:

```bash
git status --short
git log -3 --oneline
git tag --list v0.2.1
gh release view v0.2.1
```

Expected: only the pre-existing untracked `.superpowers/` remains, the intended commits are at HEAD, and neither the tag nor release already exists.

- [ ] **Step 4: Push main and wait for CI**

```bash
git push origin main
gh run list --workflow CI --branch main --limit 1
gh run watch --exit-status
```

Expected: the pushed commit's cross-platform CI succeeds.

- [ ] **Step 5: Publish the GitHub release**

```bash
gh release create v0.2.1 --target main --title "Tuiloom 0.2.1" --notes "Menus without a content source are now silent by default. The public NO_CONTENT_SOURCE message remains available for explicit display."
```

Expected: GitHub creates tag and release `v0.2.1`, triggering `.github/workflows/release.yml`.

- [ ] **Step 6: Verify the publishing workflow**

```bash
gh run list --workflow "Publish to PyPI" --limit 1
gh run watch --exit-status
```

Expected: the build and trusted PyPI publication jobs succeed for `v0.2.1`.

- [ ] **Step 7: Verify the published package**

```bash
python -m pip index versions tuiloom
```

Expected: `0.2.1` is listed as the latest published version.
