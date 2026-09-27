"""Storage round-trip against whatever is behind S3_ENDPOINT.

Skipped when nothing is listening, so CI stays green without a bucket. Run
`make up` and these exercise SeaweedFS for real; production swaps the
endpoint for R2 and the same calls apply.
"""

import socket
from urllib.parse import urlparse

import pytest

from greenroom import storage
from greenroom.config import settings


def _s3_reachable() -> bool:
    url = urlparse(settings.s3_endpoint)
    try:
        socket.create_connection((url.hostname, url.port or 80), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _s3_reachable(), reason="no S3 at S3_ENDPOINT; run make up")


def test_put_then_get_returns_the_same_bytes():
    key = "tests/roundtrip.bin"
    body = b"greenroom phase 3 \x00\xff binary safe"

    uri = storage.put(key, body)
    assert uri == f"s3://{settings.s3_bucket}/{key}"
    assert storage.get(key) == body


def test_put_overwrites_rather_than_appending():
    key = "tests/overwrite.txt"
    storage.put(key, b"first")
    storage.put(key, b"second")
    assert storage.get(key) == b"second"


def test_ensure_bucket_is_safe_to_call_twice():
    storage.ensure_bucket()
    storage.ensure_bucket()  # must not raise on an existing bucket
