"""Object storage, spoken to as S3 everywhere.

SeaweedFS locally, Cloudflare R2 in production. Same boto3 calls either side;
only the endpoint changes, which is why S3_ENDPOINT is a variable rather than
a constant.
"""

from __future__ import annotations

import contextlib
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from greenroom.config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    # already there is the common case, and not an error
    with contextlib.suppress(ClientError):
        client().create_bucket(Bucket=settings.s3_bucket)


def put(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    ensure_bucket()
    client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return f"s3://{settings.s3_bucket}/{key}"


def get(key: str) -> bytes:
    return client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
