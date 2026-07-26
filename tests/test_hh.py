from job_copilot.hh import parse_vacancy


def test_parse_vacancy_removes_html() -> None:
    parsed = parse_vacancy(
        {
            "id": "1",
            "name": "Engineer",
            "description": "<p>Build <strong>AI</strong></p>",
            "employer": {"name": "Acme"},
            "area": {"id": "2", "name": "СПб"},
            "key_skills": [{"name": "Python"}],
        }
    )
    assert parsed.description == "Build AI"
    assert parsed.key_skills == ["Python"]
    assert parsed.url == "https://hh.ru/vacancy/1"
