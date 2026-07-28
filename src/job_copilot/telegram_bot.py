from __future__ import annotations

import html
from io import BytesIO
from pathlib import PurePath
from typing import Any

import httpx
from docx import Document
from pypdf import PdfReader

from .database import Repository
from .profile_store import ProfileStore
from .telegram import TelegramNotifier

MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_RESUME_CHARS = 30_000


class TelegramBotController:
    """Guided Telegram flows for profile preferences and resume uploads."""

    def __init__(
        self,
        repository: Repository,
        profile_store: ProfileStore,
        notifier: TelegramNotifier,
        *,
        public_app_url: str | None = None,
    ) -> None:
        self.repository = repository
        self.profile_store = profile_store
        self.notifier = notifier
        self.public_app_url = public_app_url

    async def handle_message(self, message: dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower() if text else ""

        if command == "/cancel":
            self.repository.clear_telegram_session(chat_id)
            await self.notifier.send_text("Действие отменено.")
            return
        if command in {"/start", "/help"}:
            self.repository.clear_telegram_session(chat_id)
            await self._welcome()
            return
        if command == "/add_resume":
            self.repository.save_telegram_session(chat_id, "resume_name")
            await self.notifier.send_text(
                "Как назвать это резюме? Например: <b>AI Product Engineer</b>."
            )
            return
        if command == "/resumes":
            await self._list_resumes()
            return
        if command == "/preferences":
            self.repository.save_telegram_session(chat_id, "preferences")
            await self.notifier.send_text(
                "Опишите обычным сообщением, какую работу вы ищете: роли, формат, задачи и "
                "важные ограничения. Я сохраню текст в профиле."
            )
            return
        if command == "/profile":
            await self._show_profile()
            return
        if command == "/app":
            await self._send_app_link()
            return

        session = self.repository.get_telegram_session(chat_id)
        if session is None:
            await self.notifier.send_text(
                "Не понял сообщение. Используйте /help — я покажу доступные действия."
            )
            return
        await self._continue_session(chat_id, session, message, text)

    async def _welcome(self) -> None:
        markup = None
        if self.public_app_url:
            markup = {
                "inline_keyboard": [
                    [{"text": "Открыть кабинет", "web_app": {"url": self.public_app_url}}]
                ]
            }
        await self.notifier.send_text(
            "<b>AI Job Search Copilot</b>\n\n"
            "Я помогу вести профиль и несколько резюме без ручной работы с файлами проекта.\n\n"
            "/add_resume — добавить PDF, DOCX или TXT\n"
            "/resumes — список резюме\n"
            "/preferences — описать пожелания\n"
            "/profile — посмотреть профиль\n"
            "/app — открыть кабинет\n"
            "/cancel — отменить текущий диалог",
            markup,
        )

    async def _list_resumes(self) -> None:
        resumes = self.repository.list_resumes()
        if not resumes:
            await self.notifier.send_text(
                "Активных резюме пока нет. Используйте /add_resume, чтобы добавить первое."
            )
            return
        lines = ["<b>Ваши резюме</b>"]
        for item in resumes:
            roles = ", ".join(item["target_roles"]) or "роли не указаны"
            lines.append(
                f"#{item['id']} · <b>{html.escape(item['name'])}</b> · v{item['version']}\n"
                f"{html.escape(roles)}"
            )
        await self.notifier.send_text("\n\n".join(lines))

    async def _show_profile(self) -> None:
        profile = self.profile_store.load()
        roles = ", ".join(profile.target_roles) or "не указаны"
        skills = ", ".join(profile.skills[:12]) or "не указаны"
        preferences = profile.preferences or "не заполнены"
        await self.notifier.send_text(
            f"<b>{html.escape(profile.name)}</b>\n"
            f"Целевые роли: {html.escape(roles)}\n"
            f"Навыки: {html.escape(skills)}\n"
            f"Пожелания: {html.escape(preferences)}"
        )

    async def _send_app_link(self) -> None:
        if not self.public_app_url:
            await self.notifier.send_text(
                "Кабинет пока доступен локально: http://localhost:8000/app. "
                "Кнопка в Telegram появится после настройки безопасного HTTPS-адреса."
            )
            return
        await self.notifier.send_text(
            "Откройте кабинет:",
            {
                "inline_keyboard": [
                    [{"text": "Открыть кабинет", "web_app": {"url": self.public_app_url}}]
                ]
            },
        )

    async def _continue_session(
        self,
        chat_id: str,
        session: dict[str, Any],
        message: dict[str, Any],
        text: str,
    ) -> None:
        state = session["state"]
        data = session["data"]
        if state == "preferences":
            if not text:
                await self.notifier.send_text("Пришлите пожелания текстовым сообщением.")
                return
            self.profile_store.patch({"preferences": text[:5000]})
            self.repository.clear_telegram_session(chat_id)
            await self.notifier.send_text(
                "Пожелания сохранены. Посмотреть их можно через /profile."
            )
            return
        if state == "resume_name":
            if not 1 <= len(text) <= 120:
                await self.notifier.send_text("Название должно содержать от 1 до 120 символов.")
                return
            data["name"] = text
            self.repository.save_telegram_session(chat_id, "resume_roles", data)
            await self.notifier.send_text(
                "Для каких ролей подходит резюме? Перечислите через запятую."
            )
            return
        if state == "resume_roles":
            roles = [item.strip() for item in text.split(",") if item.strip()]
            if not roles or len(roles) > 20:
                await self.notifier.send_text("Укажите от 1 до 20 ролей через запятую.")
                return
            data["target_roles"] = roles
            self.repository.save_telegram_session(chat_id, "resume_document", data)
            await self.notifier.send_text(
                "Теперь прикрепите файл резюме в формате PDF, DOCX или TXT, не больше 5 МБ."
            )
            return
        if state == "resume_document":
            await self._save_document(chat_id, data, message)
            return
        self.repository.clear_telegram_session(chat_id)
        await self.notifier.send_text("Диалог устарел. Начните заново с /help.")

    async def _save_document(
        self, chat_id: str, data: dict[str, Any], message: dict[str, Any]
    ) -> None:
        document = message.get("document")
        if not document:
            await self.notifier.send_text("Нужно прикрепить файл PDF, DOCX или TXT.")
            return
        if int(document.get("file_size", 0)) > MAX_RESUME_BYTES:
            await self.notifier.send_text("Файл больше 5 МБ. Пришлите более компактную версию.")
            return
        try:
            raw = await self.notifier.download_file(document["file_id"])
            if len(raw) > MAX_RESUME_BYTES:
                raise ValueError("Файл больше 5 МБ")
            content = extract_resume_text(raw, document.get("file_name", "resume"))
            resume = self.repository.create_resume(
                data["name"], data["target_roles"], content
            )
        except httpx.HTTPError:
            await self.notifier.send_text(
                "Не удалось скачать документ из Telegram. Попробуйте отправить файл ещё раз."
            )
            return
        except (KeyError, ValueError) as error:
            await self.notifier.send_text(f"Не удалось добавить резюме: {html.escape(str(error))}")
            return
        self.repository.clear_telegram_session(chat_id)
        await self.notifier.send_text(
            f"Готово: <b>{html.escape(resume['name'])}</b> сохранено как резюме "
            f"#{resume['id']}, версия {resume['version']}."
        )


def extract_resume_text(raw: bytes, filename: str) -> str:
    suffix = PurePath(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)
        elif suffix == ".docx":
            text = "\n".join(paragraph.text for paragraph in Document(BytesIO(raw)).paragraphs)
        elif suffix in {".txt", ".md"}:
            text = raw.decode("utf-8-sig")
        else:
            raise ValueError("Поддерживаются только PDF, DOCX и TXT")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("Не удалось прочитать документ") from error
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) < 50:
        raise ValueError("В документе найдено слишком мало текста")
    return normalized[:MAX_RESUME_CHARS]
