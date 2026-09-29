"""Attempt independent teardown actions before propagating their failures."""

from collections.abc import Callable, Iterable


def run_cleanup(
    actions: Iterable[Callable[[], object]],
    *,
    message: str,
    prior_error: BaseException | None = None,
) -> None:
    """Run every action and retain an original failure when cleanup also fails."""
    errors: list[BaseException] = []
    for action in actions:
        try:
            action()
        except BaseException as error:
            errors.append(error)
    if not errors:
        return
    if prior_error is not None:
        errors.insert(0, prior_error)
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup(message, errors) from None
