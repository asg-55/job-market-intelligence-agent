import json

import pytest
from pydantic import ValidationError

from job_copilot.config import CandidateProfile
from job_copilot.profile_store import ProfileStore


def test_store_creates_profile_from_template(tmp_path) -> None:
    template = tmp_path / "profile.example.json"
    template.write_text(
        json.dumps({"name": "Template", "skills": ["Python"]}), encoding="utf-8"
    )
    profile_path = tmp_path / "private" / "profile.json"

    store = ProfileStore(profile_path, template)

    assert profile_path.exists()
    assert store.load().name == "Template"


def test_store_hot_reloads_manual_file_changes(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    store = ProfileStore(profile_path)
    store.save(CandidateProfile(name="Before", skills=["Python"]))

    profile_path.write_text(
        json.dumps({"name": "After", "skills": ["Python", "Docker"]}),
        encoding="utf-8",
    )

    assert store.load().name == "After"
    assert store.load().skills == ["Python", "Docker"]


def test_patch_keeps_unspecified_fields_and_changes_version(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profile.json")
    before = store.save(CandidateProfile(name="Alex", skills=["Python"]))

    after = store.patch({"remote_only": True})

    assert after.name == "Alex"
    assert after.skills == ["Python"]
    assert after.remote_only
    assert after.fingerprint() != before.fingerprint()


def test_search_profiles_replace_legacy_searches_and_require_unique_keys() -> None:
    candidate = CandidateProfile(
        searches=[{"text": "legacy query"}],
        search_profiles=[
            {
                "key": "ai-product",
                "name": "AI Product",
                "resume_id": 3,
                "searches": [{"text": "AI product engineer"}],
            },
            {
                "key": "disabled",
                "name": "Disabled",
                "enabled": False,
                "searches": [{"text": "unused"}],
            },
        ],
    )

    active = candidate.active_searches()
    assert len(active) == 1
    assert active[0][0] is not None
    assert active[0][0].resume_id == 3
    assert active[0][1].text == "AI product engineer"

    with pytest.raises(ValidationError, match="keys must be unique"):
        CandidateProfile(
            search_profiles=[
                {"key": "same", "name": "First", "searches": [{"text": "one"}]},
                {"key": "same", "name": "Second", "searches": [{"text": "two"}]},
            ]
        )
