# Настройки OpenRouter в веб-интерфейсе (Issue #7)

Раздел **8. Настройки** использует API `agent-management`, а не хранит ключи в браузере.

1. Для подключения OpenRouter задайте стабильный `AUTH_ENCRYPTION_KEY` через backend configuration и убедитесь, что ключ не использует development fallback. Не помещайте API key в `VITE_*`, URL или Git.
2. Откройте раздел «Настройки» и создайте подключение. API key передаётся только в `POST /api/v1/providers` и не показывается после сохранения.
3. Выберите сохранённого провайдера и создайте модель по её точному OpenRouter model ID.
4. Для смены ключа введите новое значение и нажмите «Заменить ключ». Пустое поле ничего не меняет.
5. Проверка подключения запускается **только по кнопке** с подтверждением возможной оплаты и ограниченным `max_tokens=8`.

В режиме разработки Vite проксирует `/api/v1/providers`, `/api/v1/model-profiles` и `/api/v1/completions` в `AGENT_MGMT_UPSTREAM` (по умолчанию localhost:8001). В production используйте маршрутизацию внешнего gateway с проверкой аутентификации; `AUTH_ENABLED=false` допустим только в изолированной локальной среде.

Текущий интерфейс ещё не заменяет полноценный проектный binding выбранной модели к конкретному агенту и не предоставляет все действия по жизненному циклу provider/profile. До закрытия #7 обязательны тесты перезагрузки/secret redaction, ручная диагностика отказов, API-права, binding модели к агенту и проверка в Windows CMD/Linux.

## Параметры исполнения и приоритет выбора

- Профиль модели содержит `model_id`, `temperature` и `max_tokens`. Параметры сохраняются в backend, а не в браузере.
- По умолчанию назначенный `AgentDefinition.default_model_profile_id` наследуется `AgentInstance.model_profile_id` при создании экземпляра.
- При `POST /api/v1/completions` без явного `model_profile_id` применяется модель экземпляра агента, если он указан, иначе профиль по умолчанию провайдера. Явный `model_profile_id` имеет приоритет над настройкой экземпляра.
- Явные `temperature` и `max_tokens` в completion имеют приоритет над параметрами профиля.
- Перезапуск сервиса с прежней SQLite DB сохраняет провайдеров, модельные профили и привязки агентов. Ключи хранятся зашифрованными; для расшифровки необходимо сохранить неизменный `AUTH_ENCRYPTION_KEY`.

## Проверка на Windows CMD и Linux

Из корня репозитория при установленном Docker Compose:

```cmd
docker compose up -d --build
docker compose ps
```

Для Linux:

```sh
docker compose up -d --build
docker compose ps
```

Для тестирования без платного OpenRouter API используйте offline mock-провайдер в backend тестах. Прямой online-запрос не выполняется автоматически.

## Автоматизированные acceptance checks

- `agent-management/tests/test_settings_acceptance.py` — перезапуск SQLite, key rotation, отсутствие секрета в API.
- `agent-management/tests/test_settings_model_binding.py` — реально выбранный модельный профиль в offline completion.
- `agent-management/tests/test_settings_profile_parameters.py` — параметры модели и приоритет явного override.
- `frontend/src/mvp/sections/SettingsSection.test.tsx` — UI-секрет не сохраняется в browser storage, online-проверка не запускается сама.
