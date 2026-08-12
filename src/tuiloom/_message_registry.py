from collections.abc import Callable
from enum import StrEnum

type MessageFactory = Callable[..., str]
type MessageValue = str | MessageFactory


class MessageKey(StrEnum):
    """Identify messages provided internally by Tuiloom."""

    NO_CONTENT_SOURCE = "no_content_source"
    UNKNOWN_COMMAND = "unknown_command"


class MessageRegistry:
    """Store, customize, and selectively disable application messages."""

    def __init__(self) -> None:
        """Create a registry populated with the built-in messages."""
        self._built_in_messages: dict[str, MessageValue] = {}
        self._custom_messages: dict[str, str] = {}
        self._disabled: set[str] = set()

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
            "No content source has been set for this menu "
            f"({menu_name})\n"
            "You can set it by using this method: \n"
            "  'set_content_source(content_source: ContentSource)'\n"
            "  ContentSource being: (\n"
            "    str\n"
            "    | list[str]\n"
            "    | Iterator[str]\n"
            "    | Callable[[], str | list[str]]\n"
            "  )"
        )

    @staticmethod
    def _unknown_command(command: str) -> str:
        """Build the message shown for an unknown command."""
        return f"Unknown command '{command}'"
