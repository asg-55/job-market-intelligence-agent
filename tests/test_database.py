from test_scoring import vacancy

from job_copilot.database import Repository
from job_copilot.domain import ScoreResult


def test_repository_deduplicates_vacancy_and_keeps_evaluations(tmp_path) -> None:
    repository = Repository(tmp_path / "test.db")
    result = ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good")
    assert repository.save_evaluation(vacancy(), result)
    assert not repository.save_evaluation(vacancy(), result)
    rows = repository.list_vacancies()
    assert len(rows) == 1
    assert rows[0]["score"] == 80
    assert rows[0]["source"] == "hh"


def test_vacancy_list_returns_latest_feedback(tmp_path) -> None:
    repository = Repository(tmp_path / "feedback.db")
    result = ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good")
    repository.save_evaluation(vacancy(), result)
    repository.add_feedback("42", "fit")
    repository.add_feedback("42", "applied", "Sent on Monday")

    row = repository.list_vacancies()[0]

    assert row["feedback_action"] == "applied"
    assert row["feedback_note"] == "Sent on Monday"


def test_analytics_overview_uses_latest_scores_feedback_and_runs(tmp_path) -> None:
    repository = Repository(tmp_path / "analytics.db")
    strong = ScoreResult(82, 82, 82, 82, True, ["Python"], [], [], "strong")
    weak = ScoreResult(35, 35, 35, 35, False, [], ["Python"], [], "weak")
    repository.save_evaluation(vacancy(), strong, "profile:v1")
    repository.save_evaluation(
        vacancy(id="remotive:7", source="remotive"), weak, "profile:v1"
    )
    repository.add_feedback("42", "fit")
    repository.add_feedback("42", "applied")
    repository.save_monitor_run(
        "automation",
        "profile:v1",
        {"found": 2, "new": 2, "notified": 1, "source_status": "ok"},
    )

    overview = repository.analytics_overview()

    assert overview["total_vacancies"] == 2
    assert overview["passed_filters"] == 1
    assert overview["source_counts"] == {"hh": 1, "remotive": 1}
    assert overview["feedback_counts"] == {"applied": 1}
    assert overview["score_buckets"]["under_40"] == 1
    assert overview["score_buckets"]["80_plus"] == 1
    assert overview["recent_runs"][0]["trigger"] == "automation"
    assert overview["recent_runs"][0]["summary"]["notified"] == 1
