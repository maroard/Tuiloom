from collections.abc import Callable
from enum import StrEnum

type MessageFactory = Callable[..., str]
type MessageValue = str | MessageFactory


class MessageKey(StrEnum):
    """Identify built-in messages that may be shown or disabled.

    Members are immutable string values accepted by ``TerminalMenu.show_message()``
    and the application's ``enable_message()`` and ``disable_message()`` methods.
    Custom messages use their registered string keys instead. Task-exit controls
    are independent menu actions, not registered messages.

    Args:
        values: Single built-in string value for enum conversion, for example
            ``MessageKey("no_content_source")``; an existing member also returns
            that member. Access named members directly to avoid conversion.

    Attributes:
        NO_CONTENT_SOURCE: Read-only ``"no_content_source"`` key for the
            contextual message explaining that a menu has no content source.
        UNKNOWN_COMMAND: Read-only ``"unknown_command"`` key for discarded
            textual command input, retained for integrations. Disabled by default.

    Raises:
        ValueError: If enum conversion is given an unknown built-in value.
    """

    NO_CONTENT_SOURCE = "no_content_source"
    UNKNOWN_COMMAND = "unknown_command"


class MessageRegistry:
    """Store, customize, and selectively disable application messages."""

    def __init__(self) -> None:
        """Create a registry populated with the built-in messages."""
        self._built_in_messages: dict[str, MessageValue] = {}
        self._custom_messages: dict[str, str] = {}
        self._disabled: set[str] = {MessageKey.UNKNOWN_COMMAND}

        self._register_built_in_messages()

    # Keep every built-in message registration in one visible place.
    def _register_built_in_messages(self) -> None:
        """Populate the registry with Tuiloom's built-in messages."""
        self._add_built_in_message(
            MessageKey.NO_CONTENT_SOURCE,
            self._no_content_source_message,
        )

        self._add_built_in_message(
            MessageKey.UNKNOWN_COMMAND,
            self._unknown_command,
        )

    # Register a message owned by the library.
    def _add_built_in_message(
        self,
        key: str,
        message: MessageValue,
    ) -> None:
        """Register one message owned by the library."""
        self._validate_new_key(key)
        self._built_in_messages[key] = message

    # Register a custom, user-owned message.
    def add_message(self, key: str, text: str) -> None:
        """Register a custom static message under a unique key."""
        self._validate_new_key(key)
        self._custom_messages[key] = text

    def disable(self, key: str) -> None:
        """Disable a registered message globally."""
        self._validate_existing_key(key)
        self._disabled.add(key)

    def enable(self, key: str) -> None:
        """Re-enable a registered message globally."""
        self._validate_existing_key(key)
        self._disabled.discard(key)

    def get(self, key: str, **context: object) -> str | None:
        """Resolve an enabled message using any required context."""
        if key in self._disabled:
            return None

        message = self._built_in_messages.get(key)

        if message is None:
            message = self._custom_messages.get(key)

        if callable(message):
            return message(**context)

        return message

    def validate_key(self, key: str) -> None:
        """Raise ``KeyError`` unless ``key`` is registered."""
        self._validate_existing_key(key)

    def is_enabled(self, key: str) -> bool:
        """Validate and report global enablement."""
        self._validate_existing_key(key)
        return key not in self._disabled

    def _validate_new_key(self, key: str) -> None:
        """Reject empty or already registered message keys."""
        if not key:
            raise ValueError("A message key cannot be empty")

        if key in self._built_in_messages or key in self._custom_messages:
            raise ValueError(f"A message already exists for key: {key}")

    def _validate_existing_key(self, key: str) -> None:
        """Reject message keys that are not registered."""
        if key not in self._built_in_messages and key not in self._custom_messages:
            raise KeyError(f"Unknown message key: {key}")

    @staticmethod
    def _no_content_source_message(menu_name: str) -> str:
        """Build the message shown when a menu has no content source."""
        return (
            "No content has been set for this menu "
            f"({menu_name})\n"
            "You can add a panel by using this method: \n"
            "  'add_content_panel(content: ScreenContent)'\n"
            "  Build it with ScreenContent.static(), lines(), stream(),\n"
            "  dynamic(), or responsive()."
        )

    @staticmethod
    def _unknown_command(command: str) -> str:
        """Build the message shown for an unknown command."""
        return f"Unknown command '{command}'"
