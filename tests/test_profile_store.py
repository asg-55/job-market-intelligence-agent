import json

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
