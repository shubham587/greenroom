"""Storage round-trip against whatever is behind S3_ENDPOINT.

Skipped when nothing is listening, so CI stays green without a bucket. Run
`make up` and these exercise SeaweedFS for real; production swaps the
endpoint for R2 and the same calls apply.
"""

import urllib.error
import urllib.request

import pytest

from greenroom import storage
from greenroom.config import settings


def _s3_reachable() -> bool:
    """Ask for an HTTP response, not just a socket.

    A TCP connect is not enough: Docker Desktop will happily accept a
    connection on a forwarded port with nothing serving behind it, so a
    socket check reported the store reachable while every call hung. Skip
    on what the tests actually need.
    """
    try:
        with urllib.request.urlopen(settings.s3_endpoint, timeout=2) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True  # it answered, which is all we needed to know
    except Exception:
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
