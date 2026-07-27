from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .domain import ScoreResult, Vacancy


class Repository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vacancies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    employer TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    payload_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vacancy_id TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vacancy_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
                );
                """
            )

    def has_vacancy(self, vacancy_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
        return row is not None

    def has_evaluation(self, vacancy_id: str, profile_version: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM evaluations
                   WHERE vacancy_id = ? AND profile_version = ? LIMIT 1""",
                (vacancy_id, profile_version),
            ).fetchone()
        return row is not None

    def save_evaluation(
        self, vacancy: Vacancy, result: ScoreResult, profile_version: str = "v1"
    ) -> bool:
        is_new = not self.has_vacancy(vacancy.id)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO vacancies(id, name, employer, url, published_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, employer=excluded.employer, url=excluded.url,
                    published_at=excluded.published_at, payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    vacancy.id,
                    vacancy.name,
                    vacancy.employer,
                    vacancy.url,
                    vacancy.published_at,
                    json.dumps(vacancy.to_dict(), ensure_ascii=False),
                ),
            )
            connection.execute(
                """INSERT INTO evaluations(vacancy_id, profile_version, score, result_json)
                   VALUES (?, ?, ?, ?)""",
                (
                    vacancy.id,
                    profile_version,
                    result.total_score,
                    json.dumps(result.to_dict(), ensure_ascii=False),
                ),
            )
        return is_new

    def add_feedback(self, vacancy_id: str, action: str, note: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO feedback(vacancy_id, action, note) VALUES (?, ?, ?)",
                (vacancy_id, action, note),
            )

    def list_vacancies(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT v.id, v.name, v.employer, v.url, v.published_at,
                       e.score, e.result_json, e.created_at
                FROM vacancies v
                JOIN evaluations e ON e.id = (
                    SELECT MAX(id) FROM evaluations WHERE vacancy_id = v.id
                )
                ORDER BY e.score DESC, e.created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            result.append(item)
        return result
