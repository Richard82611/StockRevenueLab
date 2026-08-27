"""Deterministic snapshot serialization and integrity checks."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = 1


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal_snapshot(payload: dict) -> dict:
    body = dict(payload)
    body.pop("sha256", None)
    body["sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    return body


def verify_snapshot(payload: dict) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema")
    expected = payload.get("sha256")
    body = dict(payload)
    body.pop("sha256", None)
    actual = hashlib.sha256(canonical_bytes(body)).hexdigest()
    if not expected or expected != actual:
        raise ValueError("snapshot checksum mismatch")
    if len(payload.get("prices", [])) != payload.get("quality", {}).get("price_rows"):
        raise ValueError("price row count mismatch")
    if len(payload.get("revenues", [])) != payload.get("quality", {}).get("revenue_rows"):
        raise ValueError("revenue row count mismatch")


def write_snapshot(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sealed = seal_snapshot(payload)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            stream.write(canonical_bytes(sealed))


def read_snapshot(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    verify_snapshot(payload)
    return payload
