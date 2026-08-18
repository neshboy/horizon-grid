"""Shared exception the crawler sources raise on a rate-limit response, so
collector.py can tell "this source got rate-limited" apart from "this source
genuinely found nothing" instead of both collapsing into an empty list.
"""


class SourceRateLimitedError(Exception):
    def __init__(self, source: str, status_code: int) -> None:
        self.source = source
        self.status_code = status_code
        super().__init__(f"{source} rate-limited us (HTTP {status_code})")
