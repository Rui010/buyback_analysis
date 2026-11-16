"""Helpers for loading and validating buyback plan fixture manifests."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_ROOT = Path(__file__).parents[1] / "fixtures" / "buyback_plan_events"
TDNET_URL_PREFIX = "https://www.release.tdnet.info/inbs/"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VERIFIED_SOURCE_STATUSES = {"verified_download", "verified_unc"}
ALLOWED_SOURCE_STATUSES = VERIFIED_SOURCE_STATUSES | {"source_missing"}


@dataclass(frozen=True)
class FixtureManifest:
    path: Path
    data: dict[str, Any]

    @property
    def code(self) -> str:
        return self.data["code"]

    @property
    def documents(self) -> list[dict[str, Any]]:
        return self.data["documents"]


def load_manifest(path: Path) -> FixtureManifest:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    manifest = FixtureManifest(path=path, data=data)
    validate_manifest(manifest)
    return manifest


def load_all_manifests(root: Path = MANIFEST_ROOT) -> list[FixtureManifest]:
    manifests = [load_manifest(path) for path in sorted(root.glob("*/source_manifest.toml"))]
    codes = [manifest.code for manifest in manifests]
    if len(codes) != len(set(codes)):
        raise ValueError("fixture manifest codes must be unique")

    urls = [document["url"] for manifest in manifests for document in manifest.documents]
    if len(urls) != len(set(urls)):
        raise ValueError("fixture document URLs must be unique across manifests")
    return manifests


def validate_manifest(manifest: FixtureManifest) -> None:
    data = manifest.data
    errors: list[str] = []

    for field in ("fixture_version", "code", "company_name", "purpose", "documents"):
        if field not in data:
            errors.append(f"missing root field: {field}")

    code = data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"\d{4}", code):
        errors.append("code must be a four-digit string")

    documents = data.get("documents")
    if not isinstance(documents, list) or not documents:
        errors.append("documents must be a non-empty array")
        documents = []

    seen_urls: set[str] = set()
    for index, document in enumerate(documents):
        prefix = f"documents[{index}]"
        for field in (
            "role",
            "url",
            "disclosure_date",
            "title",
            "source_status",
            "expected_event_types",
        ):
            if field not in document:
                errors.append(f"{prefix} missing field: {field}")

        url = document.get("url")
        if not isinstance(url, str) or not url.startswith(TDNET_URL_PREFIX):
            errors.append(f"{prefix}.url must be a TDnet PDF URL")
        elif url in seen_urls:
            errors.append(f"{prefix}.url is duplicated in the manifest")
        else:
            seen_urls.add(url)

        event_types = document.get("expected_event_types")
        if not isinstance(event_types, list) or not event_types or not all(
            isinstance(event_type, str) and event_type for event_type in event_types
        ):
            errors.append(f"{prefix}.expected_event_types must be a non-empty string array")

        source_status = document.get("source_status")
        if source_status not in ALLOWED_SOURCE_STATUSES:
            errors.append(f"{prefix}.source_status is invalid: {source_status}")
        if source_status in VERIFIED_SOURCE_STATUSES:
            source_hash = document.get("source_sha256")
            if not isinstance(source_hash, str) or not SHA256_PATTERN.fullmatch(source_hash):
                errors.append(f"{prefix}.source_sha256 must be lowercase SHA-256")

    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise ValueError(f"invalid fixture manifest {manifest.path}:\n{joined}")
