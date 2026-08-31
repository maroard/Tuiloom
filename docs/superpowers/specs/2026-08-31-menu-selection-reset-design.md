# Menu Selection Reset Design

## Problem

`TerminalMenu.run()` currently normalizes the existing selection instead of
resetting it. When a submenu closes and is opened again, its marker remains on
the last selected command as long as that command is still enabled.

## Behavior

Every call to `TerminalMenu.run()` resets the menu marker to the first enabled
command in visual order before the first frame is rendered.

Disabled commands are never selectable:

- opening or reopening a menu skips disabled commands from the top;
- Up and Down navigation continues to skip disabled commands;
- disabling the selected command immediately moves the marker to the first
  selectable entry;
- if no command is enabled, the marker selects the automatic `Back` or `Quit`
  row.

The reset affects only command selection and menu/content focus. It does not
recreate the menu or clear its content, messages, command configuration, or
other application state.

## Implementation

At the start of `TerminalMenu.run()`, set the selection index to zero before
calling the existing `_normalize_selection()` method. The existing selectable
index calculation already excludes every disabled command and always includes
the final exit row.

This keeps the rule centralized in the menu lifecycle. Parent menus and
`add_menu()` do not need special knowledge of submenu selection state.

## Verification

Tests will prove that:

- reopening a menu after selecting a lower command resets the marker to the
  first enabled command;
- a disabled first command is skipped in favor of the next enabled command;
- a menu whose commands are all disabled selects its exit row;
- existing navigation and dynamic disable behavior remain unchanged.

