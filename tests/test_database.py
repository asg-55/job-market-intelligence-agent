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


def test_vacancy_list_returns_latest_feedback(tmp_path) -> None:
    repository = Repository(tmp_path / "feedback.db")
    result = ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good")
    repository.save_evaluation(vacancy(), result)
    repository.add_feedback("42", "fit")
    repository.add_feedback("42", "applied", "Sent on Monday")

    row = repository.list_vacancies()[0]

    assert row["feedback_action"] == "applied"
    assert row["feedback_note"] == "Sent on Monday"
