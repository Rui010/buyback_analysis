from pathlib import Path

import pytest

from tests.buyback_analysis.fixture_manifest import (
    FixtureManifest,
    load_all_manifests,
    load_manifest,
    validate_manifest,
)


EXPECTED_CODES = {"2146", "3038", "3350", "5449", "6199", "6574", "6676"}


def test_all_representative_manifests_are_valid():
    manifests = load_all_manifests()

    assert {manifest.code for manifest in manifests} == EXPECTED_CODES
    assert all(manifest.data.get("fixture_status", "verified") == "verified" for manifest in manifests)


def test_verified_documents_have_hashes_and_expected_events():
    manifests = load_all_manifests()

    for manifest in manifests:
        for document in manifest.documents:
            assert len(document["source_sha256"]) == 64
            assert document["expected_event_types"]


def test_load_manifest_rejects_missing_required_document_field(tmp_path: Path):
    path = tmp_path / "source_manifest.toml"
    path.write_text(
        '\n'.join(
            [
                'fixture_version = "1"',
                'code = "1234"',
                'company_name = "Example"',
                'purpose = "validation"',
                '[[documents]]',
                'role = "origin"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing field: url"):
        load_manifest(path)


def test_validate_manifest_rejects_invalid_verified_hash(tmp_path: Path):
    manifest = FixtureManifest(
        path=tmp_path / "source_manifest.toml",
        data={
            "fixture_version": "1",
            "code": "1234",
            "company_name": "Example",
            "purpose": "validation",
            "documents": [
                {
                    "role": "origin",
                    "url": "https://www.release.tdnet.info/inbs/example.pdf",
                    "disclosure_date": "2026-01-01",
                    "title": "Example",
                    "source_status": "verified_unc",
                    "source_sha256": "not-a-hash",
                    "expected_event_types": ["new_plan"],
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        validate_manifest(manifest)
