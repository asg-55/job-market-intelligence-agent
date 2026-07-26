from job_copilot.database import Repository
from job_copilot.domain import ScoreResult
from test_scoring import vacancy


def test_repository_deduplicates_vacancy_and_keeps_evaluations(tmp_path) -> None:
    repository = Repository(tmp_path / "test.db")
    result = ScoreResult(80, 80, 80, 80, True, ["Python"], [], [], "good")
    assert repository.save_evaluation(vacancy(), result)
    assert not repository.save_evaluation(vacancy(), result)
    rows = repository.list_vacancies()
    assert len(rows) == 1
    assert rows[0]["score"] == 80
