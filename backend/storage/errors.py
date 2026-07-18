class ThreadMessageLimitExceeded(RuntimeError):
    """Raised when persisting another message would exceed a thread's cap."""
