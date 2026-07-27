# AI Job Search Copilot

Портфельный и прикладной проект: сервис мониторит вакансии через официальный HH API,
сравнивает их с профилем кандидата, сохраняет объяснимую оценку и отправляет лучшие новые
варианты в Telegram.

## Что уже работает

- несколько поисковых запросов к HH API без HTML-парсинга;
- получение полного текста вакансии и дедупликация;
- жёсткие фильтры по региону, формату, опыту, зарплате и стоп-словам;
- объяснимый скоринг роли, навыков и условий;
- опциональный structured LLM-анализ через Ollama/OpenAI-compatible API;
- история оценок в SQLite для будущих evals;
- постоянно редактируемый профиль с hot reload и версионированием оценок;
- Telegram-карточка с кнопками и API для обратной связи;
- HTTP API и разовый CLI-запуск;
- тесты ключевой бизнес-логики и Docker-образ.

Продуктовые границы и метрики описаны в [docs/PRODUCT.md](docs/PRODUCT.md).
Подробная инструкция для первого запуска находится в [docs/SETUP_RU.md](docs/SETUP_RU.md).

## Быстрый старт (Docker-first)

Основной способ работы требует только Docker Desktop.

```powershell
Copy-Item config/profile.example.json config/profile.json
Copy-Item .env.example .env
docker compose up --build -d copilot worker
```

Отредактируйте `config/profile.json` и обязательно замените контакт в `HH_USER_AGENT`.
Токен HH для публичного поиска не нужен. Для Telegram создайте бота через BotFather, напишите
ему сообщение и укажите `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`.

`copilot` поднимает HTTP API, а `worker` запускает мониторинг сразу и затем каждые 12 часов.
Разовый ручной запуск тоже выполняется в контейнере:

```bash
docker compose run --rm worker job-copilot run --pages 1
```

### Локальная LLM в Docker

LLM необязательна: при пустом `LLM_MODEL` работает только детерминированный baseline. Чтобы
подключить Ollama и Qwen 3.5 9B:

```bash
docker compose --profile local-llm up -d ollama
docker compose exec ollama ollama pull qwen3.5:9b
```

После загрузки укажите `LLM_MODEL=qwen3.5:9b` в `.env` и перезапустите `copilot` и `worker`.
Модель получает только вакансию, навыки и подтверждённые факты профиля. Ответ проверяется
Pydantic-схемой, смешивается с baseline и сохраняется вместе с моделью и версией промпта.

После запуска доступны Swagger UI на `http://localhost:8000/docs` и методы:

- `POST /monitor/run` — выполнить мониторинг;
- `GET /vacancies` — показать ранжированные вакансии;
- `GET`, `PUT`, `PATCH /profile` — читать и изменять живой профиль без перезапуска;
- `POST /vacancies/{id}/feedback` — сохранить `fit`, `skip`, `applied`, `rejected` или `interview`.

Кнопки обратной связи в Telegram используют `POST /telegram/webhook`. Для них нужен публичный
HTTPS-адрес сервиса. Создайте случайный `TELEGRAM_WEBHOOK_SECRET`, затем зарегистрируйте URL:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/telegram/webhook","secret_token":"<SECRET>"}'
```

Интервал задаётся аргументом `--interval` команды worker. Оркестрация отделена от
бизнес-логики: позднее worker можно заменить n8n, вызывающим стабильный HTTP API.

## Как считается оценка

Сначала применяются обязательные ограничения. Затем итог складывается из навыков (55%),
соответствия роли (25%) и условий (20%). Провал жёсткого фильтра ограничивает оценку 39
баллами. Это baseline: его можно измерить на пользовательской обратной связи до подключения
более дорогого LLM/embedding-слоя.

## Безопасность и честность

Проект не делает автоматических откликов и не меняет основное резюме. Будущий генератор писем
будет использовать только `verified_facts` профиля и сохранять подтверждение пользователя.
Секреты читаются из `.env`, который исключён из Git.

## Roadmap

- Telegram webhook и обработка callback-кнопок;
- OpenAI-compatible structured evaluator (облачная модель или локальный Ollama);
- сопроводительное письмо с трассировкой использованных фактов;
- генерация отдельной адаптированной копии резюме;
- feedback-driven evals, embeddings и аналитический dashboard.

## Проверка

```bash
docker compose --profile test build tests
docker compose --profile test run --rm tests
```

GitHub Actions выполняет те же проверки в Docker для каждого push и pull request.

Источники API: [официальная документация HH](https://api.hh.ru/openapi/redoc) и
[Telegram Bot API](https://core.telegram.org/bots/api).
