# Первый запуск: пошаговая инструкция

Секреты никогда не отправляйте в чат, issue или commit. Они хранятся только в локальном
`.env`; этот файл уже исключён из Git.

Профиль не является одноразовой анкетой. Его можно менять в любой момент вручную в
`config/profile.json` или через API. Новый профиль применяется к следующему запуску поиска;
пересобирать и перезапускать контейнеры не нужно.

## 1. Подключить GitHub CLI

В PowerShell выполните:

```powershell
gh auth login
```

Выберите `GitHub.com`, затем `HTTPS` и `Login with a web browser`. Скопируйте показанный CLI
одноразовый код, подтвердите вход в браузере и проверьте результат:

```powershell
gh auth status
```

Персональный access token вручную создавать не требуется.

## 2. Создать локальные настройки

Из корня проекта:

```powershell
Copy-Item .env.example .env
Copy-Item config/profile.example.json config/profile.json
```

Откройте `.env` и замените email в `HH_USER_AGENT` на свой. Это контакт разработчика, который
требует HH API; пароль от HH здесь не нужен. `config/profile.json` заполните реальными
навыками, ограничениями и только проверяемыми фактами.

## 3. Создать Telegram-бота

1. В Telegram найдите верифицированного бота `@BotFather`.
2. Отправьте `/newbot`.
3. Задайте отображаемое имя, например `My Job Search Copilot`.
4. Задайте username, обязательно заканчивающийся на `bot`, например `alex_job_copilot_bot`.
5. BotFather пришлёт токен. Скопируйте его в `.env` после `TELEGRAM_BOT_TOKEN=`.
6. Не публикуйте токен. Если он утёк, используйте `/revoke` в BotFather.
7. Откройте созданного бота и отправьте ему `/start`.

Теперь получите chat ID без копирования токена в командную строку:

```powershell
docker compose run --rm copilot job-copilot telegram-chat-id
```

Скопируйте выведенное число в `.env` после `TELEGRAM_CHAT_ID=`.

Для первых уведомлений этого достаточно. Feedback-кнопки требуют публичного HTTPS webhook;
его лучше настроить отдельным этапом. Не заполняйте `TELEGRAM_WEBHOOK_SECRET`, пока такого
адреса нет.

## 4. HH API

Для публичного поиска вакансий регистрация приложения и OAuth-токен не нужны. На первом этапе
достаточно корректного `HH_USER_AGENT`. Не заполняйте `HH_ACCESS_TOKEN`.

OAuth понадобится позже, только если проект будет читать данные вашего аккаунта HH или
готовить действия соискателя через авторизованные методы. Автоматический отклик в MVP
намеренно отключён.

## 5. Локальная LLM в Docker

Этот шаг можно отложить: без модели сервис использует объяснимый baseline. Для LLM запустите
Ollama и скачайте Qwen 3.5 9B (около нескольких гигабайт):

```powershell
docker compose --profile local-llm up -d ollama
docker compose exec ollama ollama pull qwen3.5:9b
```

После загрузки задайте в `.env`:

```dotenv
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen3.5:9b
```

`LLM_API_KEY=ollama` — совместимый placeholder, а не секрет облачного сервиса.

## 6. Запустить проект

```powershell
docker compose up --build -d copilot worker
docker compose ps
docker compose logs --tail 100 worker
```

API и Swagger будут доступны по адресу `http://localhost:8000/docs`. Ручной запуск поиска:

```powershell
docker compose run --rm worker job-copilot run --pages 1
```

В Swagger раскройте раздел `profile`: `GET /profile` показывает текущий профиль,
`PUT /profile` полностью заменяет его, а `PATCH /profile` меняет только переданные поля.
Сохранение атомарное, поэтому worker не прочитает наполовину записанный JSON. После изменения
профиля уже известная вакансия может быть оценена заново; версия профиля сохраняется в аудите.

## 7. Создать черновик сопроводительного письма

Сначала добавьте реальные утверждения о своём опыте в `verified_facts` профиля и убедитесь,
что `LLM_MODEL` настроен. Затем в Swagger вызовите `POST /vacancies/{id}/cover-letter`:

```json
{"language": "ru", "tone": "professional"}
```

Ответ содержит текст, статус `draft` и `fact_trace` — список фактов, поддерживающих каждый
содержательный абзац. Сервис не отправляет письмо работодателю. Сохранённый черновик можно
повторно получить через `GET /cover-letters/{draft_id}`.

Если Telegram не получает сообщение, сначала проверьте, что найденная вакансия новая, прошла
жёсткие фильтры и набрала не меньше `MIN_NOTIFICATION_SCORE`.
