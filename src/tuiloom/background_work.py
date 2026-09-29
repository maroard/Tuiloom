from typing import Protocol


class BackgroundWork(Protocol):
    """Describe worker lifecycle operations used internally during terminal exit.

    This structural typing protocol is implemented by content-source workers
    and captured-output task sessions. It defines the lifecycle surface used
    for exit controls and cleanup, not a public task-handle API:
    ``TerminalMenu.start_output_task()`` returns ``None``. Implementations can
    expose additional source or outcome operations outside this protocol.

    Cancellation is cooperative and does not prove that a worker stopped. A
    blocking producer or task action can keep running until it returns; normal
    terminal teardown must join it before releasing terminal state. ``join()``
    blocks its caller, so timed calls are useful when waiting must be bounded.
    This protocol is not runtime-checkable with ``isinstance()``.

    Attributes:
        description: Text identifying the work in progress or exit controls.
            Concrete workers and task sessions provide their configured label.
    """

    @property
    def description(self) -> str:
        """Inspect the configured label identifying this work to the user.

        Returns:
            Description text used by progress displays or exit controls.
            Reading it does not wait for work to finish.
        """
        ...

    def cancel(self) -> None:
        """Stop future publication and request source cancellation where supported.

        Source workers wake their internal waits and invoke a callable
        ``source.cancel()`` hook once, on the caller's thread. Captured task
        sessions discard future output and wake output readers without
        interrupting the action or calling an action-cancellation hook. Already
        buffered output may remain available. Cancellation alone does not join
        the worker, remove a panel or discard an application's outcome callbacks;
        application shutdown performs those steps separately.

        Concrete cancellation is idempotent, but a blocking producer or source
        hook can still delay the caller or worker. Check ``is_alive()`` or use
        ``join()`` to establish that the underlying thread has stopped.

        Raises:
            BaseException: If a concrete source's cancellation hook raises.
                The original failure propagates to the cancellation caller.
        """
        ...

    def is_alive(self) -> bool:
        """Check whether the underlying worker thread is currently executing.

        This is a momentary observation, not a cancellation or completion
        barrier. It does not say whether queued output has been rendered or an
        application has dispatched the worker's outcome callback.

        Returns:
            ``True`` while the thread is alive; ``False`` before startup or
            after it has terminated.
        """
        ...

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the worker thread and report whether it has stopped.

        Joining does not request cancellation, process queued output, dispatch
        outcome callbacks or propagate the action's stored exception. It blocks
        the caller; call it from a lifecycle or cleanup context rather than an
        ordinary UI callback that must remain responsive. Source workers treat
        an unstarted thread as already stopped; captured task sessions require
        startup before joining.

        Args:
            timeout: Maximum wait in seconds, or ``None`` (the default) to wait
                indefinitely. Zero or negative values check without waiting.

        Returns:
            ``True`` if the thread is stopped when checked after the wait, or
            ``False`` if it is still alive when the timeout expires.

        Raises:
            RuntimeError: If a captured task session has not been started, or
                joining would wait on the caller's own worker thread.
        """
        ...
