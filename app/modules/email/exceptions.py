"""
Email processing exception hierarchy.

RetryableEmailError   — transient failures, should retry (up to MAX_RETRIES, then DLQ)
  DownstreamCommitError — AI done but gRPC create failed, also retryable
PermanentEmailError   — non-retryable, go directly to DLQ
"""


class RetryableEmailError(Exception):
    """Transient error; consumer should retry up to MAX_RETRIES then route to DLQ.

    Examples: Gemini 429, timeout, gRPC UNAVAILABLE/DEADLINE_EXCEEDED,
              GetState unavailable.
    """


class DownstreamCommitError(RetryableEmailError):
    """AI processing succeeded but gRPC create call failed.

    Treated as retryable so the message is re-attempted; after MAX_RETRIES
    the message goes to the DLQ for manual inspection.
    """


class PermanentEmailError(Exception):
    """Non-retryable error; consumer routes directly to DLQ without retry.

    Examples: extraction produced empty items[], malformed payload that
              cannot be fixed by retrying.
    """
