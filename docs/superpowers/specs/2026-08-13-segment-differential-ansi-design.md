# Segment Differential Rendering and ANSI Design

## Goal

Upgrade Tuiloom from complete-line replacement to differential updates of
multiple changed segments within each line. Every visual element must support
ANSI SGR styles and colors together with Unicode grapheme clusters and terminal
display widths.

The implementation must preserve the current renderer structure. It must not
grow into a terminal emulator or allow user content to control cursor movement,
screen erasure, or other terminal state owned by Tuiloom.

## Supported Input

Tuiloom supports ANSI Select Graphic Rendition (SGR) sequences embedded in all
visual text:

- standard and bright 16-color forms;
- 256-color forms;
- 24-bit foreground and background colors;
- bold, faint, italic, underline, blink, inverse, conceal, and strike styles;
- complete and selective resets;
- semicolon and colon parameter forms accepted as SGR sequences.

Other terminal control sequences are removed before rendering. This includes
cursor movement, erasure, scrolling, device control, window title changes, OSC
sequences, and unknown escape sequences. Unsupported sequences do not raise an
exception because malformed generated content must not stop the application.

Unicode geometry includes extended grapheme clusters, combining marks, emoji
ZWJ sequences, flags, variation selectors, and East Asian wide characters.
Tabs expand against tab stops of eight terminal columns. Newlines remain frame
line boundaries. Other unsafe C0 and C1 controls are removed.

## Dependency

Add `wcwidth >= 0.8` as the only runtime dependency required by this feature.
This version provides terminal-sequence iteration, Unicode grapheme iteration,
display-width measurement, ANSI-aware clipping, wrapping, padding, and SGR
propagation.

The separately discussed `regex` dependency is not needed because current
`wcwidth` already implements Unicode grapheme boundaries. Avoiding it keeps the
runtime dependency set minimal.

References:

- <https://wcwidth.readthedocs.io/en/stable/api.html>
- <https://wcwidth.readthedocs.io/en/latest/specs.html>
- <https://pypi.org/project/wcwidth/>

## Architecture

### Terminal text primitives

Create `src/tuiloom/render/terminal_text.py` as the single internal source of
truth for terminal text geometry. It is responsible for:

- retaining valid SGR sequences and stripping every other control sequence;
- splitting text into safe, independently renderable lines;
- propagating an active SGR style across newline boundaries;
- iterating styled Unicode graphemes;
- calculating display width in terminal columns;
- clipping text by terminal-column positions;
- left-padding, right-padding, centering, and wrapping styled text;
- expanding tabs consistently;
- resetting style at line and segment boundaries.

Every renderer uses these primitives. No renderer may use `len()`, ordinary
string slicing, `str.ljust()`, `str.center()`, or `textwrap` to make a terminal
geometry decision.

### Visual line model

A changed line is parsed into styled graphemes. Each grapheme records:

- its original text;
- its terminal width;
- the SGR history active before it;
- the terminal columns it occupies.

The model projects graphemes into comparable visual cells. A two-column
grapheme owns both cells, so a changed range can always be expanded to complete
grapheme boundaries. Zero-width codepoints remain attached to their containing
grapheme rather than becoming independently addressable cells.

SGR history is replayed rather than reduced to a fully semantic style object.
This supports complete and selective SGR operations without reimplementing all
terminal style semantics. Two different histories that produce an equivalent
visual style may compare as different and cause harmless extra output.

### Segment diff

Replace complete-line change calculation with an internal segment diff. A
change has the conceptual shape:

```text
SegmentChange(row, column, content, clear_width)
```

- `row` and `column` are one-based terminal coordinates.
- `content` is safe, self-contained ANSI text for the changed cells.
- `clear_width` is the number of obsolete terminal cells remaining after the
  new content.

The algorithm first compares complete line strings. Identical lines require no
Unicode or ANSI parsing. For each changed row, it compares visual cells at the
same terminal columns, expands differences to grapheme boundaries, and groups
adjacent changed cells. Equal cells between changed regions split the output
into multiple `SegmentChange` objects.

The comparison is positional rather than an edit-distance calculation. An
insertion that shifts a suffix changes every affected screen column until the
old and new visual cells become equal again at the same positions.

Added and removed frame rows remain supported. A removed row produces an empty
replacement segment covering its previous visible width.

## Renderer Integration

### ContentRenderer

Content normalization sanitizes all source types: static strings, line lists,
streams, and dynamic callables. `RenderedContent.width` is the maximum visible
terminal width rather than the maximum Python string length.

Styles spanning newline boundaries in one string are propagated into the
following line. Entries supplied as a `list[str]` are independent logical
lines.

### Viewport

Horizontal clipping operates on terminal columns and never divides a wide
grapheme. If a viewport boundary intersects a two-column grapheme, the occupied
but unavailable cell is represented by a plain space. Output is padded to the
viewport width using visible-cell measurements.

Vertical behavior and scrolling bounds remain unchanged, except that the
horizontal maximum uses visible content width.

### MenuRenderer

All user-controlled visual fields use terminal-aware helpers:

- application name and title;
- descriptive text;
- command labels and keys;
- messages and alerts;
- normal and alert prompts.

Automatic menu width uses visible widths. Explicit menu width remains an inner
terminal-column width. Wrapping, single-column alignment, two-column alignment,
and centering preserve SGR while keeping borders aligned.

The complete `ScreenContext` continues to be synchronized before every frame.

### TerminalRenderer

Frame composition stores safe ANSI line strings in the existing previous-frame
cache. Terminal width checks and cursor restoration use display-cell width.

The first frame, terminal resize, source replacement, and explicit invalidation
still trigger a complete redraw. Subsequent frames call the segment diff.

For a differential update, the renderer hides the cursor once and writes every
segment in order. Each segment:

1. moves to its one-based row and column;
2. emits an SGR reset;
3. restores the style required at the segment start;
4. writes its content and internal style transitions;
5. emits an SGR reset;
6. erases `clear_width` residual cells without moving the cursor.

After all segments, the renderer restores the input cursor using the visible
width of the final frame line and shows the cursor. Existing flushing behavior
is retained.

As a final safety boundary, the terminal writer sanitizes externally derived
frame text even though upstream renderers already normalize their inputs.

## Data Flow

```text
ContentSource / ScreenContext / input buffer
                    |
                    v
        terminal_text normalization
                    |
                    v
 ContentRenderer + Viewport + MenuRenderer
                    |
                    v
          complete logical frame
                    |
          unchanged line check
                    |
                    v
      visual cells for changed lines only
                    |
                    v
           SegmentChange objects
                    |
                    v
          targeted terminal writes
```

## Performance

Every frame performs a linear comparison of line strings. Unicode and ANSI
analysis is limited to changed lines. Terminal output is proportional to the
number and size of changed visual segments rather than the number or size of
changed lines.

No persistent terminal grid, observer graph, dirty-field system, or terminal
emulation state is introduced.

## Error and Safety Behavior

- Unsupported escape and control sequences are silently stripped.
- Valid SGR sequences with unusual parameters are retained as opaque style
  operations.
- A display-width result that cannot be represented safely is normalized to a
  zero-width or replacement-safe form rather than passed through as terminal
  control.
- An invalid content source type continues to raise the existing `TypeError`.
- Renderer invalidation and terminal-size fallback retain their current
  behavior.

## Testing

### Terminal text primitives

- strip cursor movement, erasure, OSC, C0, and C1 controls;
- retain standard, 256-color, true-color, and colon-form SGR;
- measure plain text, combining accents, CJK, ZWJ emoji, and flags;
- expand tabs at the configured stops;
- clip without splitting wide graphemes;
- preserve styles through clipping, wrapping, padding, and newlines;
- reset every independently rendered line.

### Segment diff

- one change produces one segment at the correct column;
- two disjoint changes produce two segments;
- identical lines produce no segment;
- insertion and deletion update every shifted positional cell;
- trailing removal reports the correct clear width;
- style-only changes are detected;
- grapheme changes expand to complete width boundaries;
- added, removed, and empty trailing rows remain distinguishable.

### Renderers

- content dimensions use visible terminal columns;
- viewport scrolling and clipping handle styled Unicode;
- every menu element supports styled wide text without border drift;
- automatic and explicit menu widths remain correct;
- ANSI and Unicode input buffers restore the cursor at the visible position;
- segment writes use precise cursor coordinates and residual erasure;
- resize and invalidation still perform a complete redraw;
- unsafe ANSI never reaches captured terminal output.

The complete existing Tuiloom test suite and the editable Call-Me-Maybe
integration tests must pass after the upgrade.

## Limits

- OSC hyperlinks and non-SGR terminal features are intentionally unsupported.
- Visually equivalent but differently encoded SGR histories may cause extra
  segment writes.
- Terminal emulators disagree on the width of some modern or ambiguous Unicode
  graphemes. Tuiloom follows the current `wcwidth` model, but cannot guarantee
  identical geometry on every historical terminal.
- This feature does not add bidirectional-text layout or terminal-specific
  shaping beyond the grapheme and width behavior supplied by `wcwidth`.
