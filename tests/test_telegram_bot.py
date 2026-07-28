import asyncio

from job_copilot.config import CandidateProfile
from job_copilot.database import Repository
from job_copilot.profile_store import ProfileStore
from job_copilot.telegram_bot import TelegramBotController, extract_resume_text


class FakeNotifier:
    def __init__(self, document: bytes = b"") -> None:
        self.document = document
        self.messages: list[tuple[str, dict | None]] = []

    async def send_text(self, text: str, reply_markup: dict | None = None) -> None:
        self.messages.append((text, reply_markup))

    async def download_file(self, file_id: str) -> bytes:
        assert file_id == "telegram-file"
        return self.document


def test_bot_accepts_preferences_as_regular_message(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "bot.db")
        store = ProfileStore(tmp_path / "profile.json")
        store.save(CandidateProfile(name="Alex"))
        notifier = FakeNotifier()
        bot = TelegramBotController(repository, store, notifier)

        await bot.handle_message({"chat": {"id": 123}, "text": "/preferences"})
        await bot.handle_message(
            {"chat": {"id": 123}, "text": "Ищу удалённую AI product роль без релокации"}
        )

        assert store.load().preferences == "Ищу удалённую AI product роль без релокации"
        assert repository.get_telegram_session("123") is None
        assert "Пожелания сохранены" in notifier.messages[-1][0]

    asyncio.run(scenario())


def test_bot_guides_user_through_resume_upload(tmp_path) -> None:
    async def scenario() -> None:
        repository = Repository(tmp_path / "resume-bot.db")
        store = ProfileStore(tmp_path / "profile.json")
        notifier = FakeNotifier(
            ("Python developer with RAG, Docker and FastAPI experience. " * 3).encode()
        )
        bot = TelegramBotController(repository, store, notifier)
        chat = {"id": 321}

        await bot.handle_message({"chat": chat, "text": "/add_resume"})
        await bot.handle_message({"chat": chat, "text": "AI Engineer"})
        await bot.handle_message({"chat": chat, "text": "AI Engineer, LLM Engineer"})
        await bot.handle_message(
            {
                "chat": chat,
                "document": {
                    "file_id": "telegram-file",
                    "file_name": "resume.txt",
                    "file_size": 180,
                },
            }
        )

        resumes = repository.list_resumes()
        assert len(resumes) == 1
        assert resumes[0]["name"] == "AI Engineer"
        assert resumes[0]["target_roles"] == ["AI Engineer", "LLM Engineer"]
        assert repository.get_telegram_session("321") is None
        assert "сохранено как резюме #1" in notifier.messages[-1][0]

    asyncio.run(scenario())


def test_resume_extractor_rejects_unsupported_file() -> None:
    try:
        extract_resume_text(b"content", "resume.exe")
    except ValueError as error:
        assert "PDF, DOCX и TXT" in str(error)
    else:
        raise AssertionError("Unsupported resume format must be rejected")
