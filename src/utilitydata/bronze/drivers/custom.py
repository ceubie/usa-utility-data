"""Account for a source whose bytes are collected outside the standard drivers.

A custom source is not downloaded. The refresh compares the files the registry
already names with the last good snapshot.
"""

from utilitydata.bronze.drivers.local import fetch_local
from utilitydata.bronze.drivers.protocol import FetchRequest, FetchResult


def fetch_custom(request: FetchRequest) -> FetchResult:
    """Hash the declared local files. The transport is not called."""
    return fetch_local(request)
