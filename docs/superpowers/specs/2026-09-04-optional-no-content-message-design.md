# Optional No-Content Message Design

## Goal

Menus created without a content source should render normally without automatically
showing the `NO_CONTENT_SOURCE` footer message.

## Compatibility

`MessageKey.NO_CONTENT_SOURCE`, its registered text, and
`TerminalMenu.show_message(MessageKey.NO_CONTENT_SOURCE)` remain public and keep
their current behavior. This makes the change suitable for the patch release
0.2.1: applications that explicitly request the message are unaffected.

## Behavior

`TerminalMenu.run()` will no longer call the automatic-message path when the menu
has no content panels. Such a menu will display its title, descriptive text,
commands, and Back or Quit row with no warning footer.

Other automatic messages, including unknown-command feedback, remain unchanged.
Adding or replacing content sources remains unchanged.

## Documentation and Release

The README will describe absent content as valid and silent by default while
retaining the explicit `show_message()` example and message-key reference. Package
metadata and the documented version will be updated from 0.2.0 to 0.2.1.

The release is complete when the focused regression test and the full project
checks pass, the distribution artifacts validate, the changes are committed and
pushed, and GitHub release `v0.2.1` is published so the existing trusted-publishing
workflow can upload the package to PyPI.

## Testing

A menu with no content source must begin with `screen_context.message is None`.
An explicit call to `show_message(MessageKey.NO_CONTENT_SOURCE)` must still show
the registered message. The existing full lint, formatting, typing, test, and
package-build checks must remain green.
