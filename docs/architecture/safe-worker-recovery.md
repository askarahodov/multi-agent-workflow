# Fail-closed recovery of interrupted native execution (#36)

## Почему это важно

До этой правки `OrchestrationEngine.recover()` автоматически переводил
`in_progress` задачу в `pending`. Но файловый инструмент мог уже
записать изменения до аварии. Новый LLM-запрос после рестарта может
сгенерировать новый `tool_call_id` — SQLite ledger #27 не может
обнаружить семантически повторённое действие с новым ID.

## Новое поведение по умолчанию

При старте orchestration-server (`recover_on_startup=True`) или
вызове авторизованного `POST /admin/recover`:

- Незавершённый `TaskAttempt` получает статус `interrupted`.
- Соответствующая задача помечается `blocked`, а **не** `pending`.
- Назначенный агент освобождается; `retry_at` очищается, но задача
  **не** выполняется повторно автоматически.
- `SagaEvent=task.recovery_quarantined` фиксирует постоянную обезличенную
  причину `interrupted_attempt_requires_reconciliation`.
- `completed` задачи и unrelated pending задачи не затрагиваются.
- Повторный recover идемпотентен и не создаёт ещё один переход.

## Действия оператора

1. Проверить последние `CLAIMED`/`SUCCEEDED` tool IDs в **защищённом**
   журнале вне workspace, журналы gateway и фактические артефакты.
2. Выяснить, произошли ли side effects до аварии; повторная генерация
   нового tool ID не доказывает отсутствие дублей.
3. Создать **новую** проверенную task/run для остатка работы только после
   reconciliation, с новым workspace/политиками/лимитами.
4. Не снимать карантин массово и не делать скрытый auto-retry.

Этот срез **не реализует** полноценный UI ручной reconciliation, отдельный
production worker daemon или distributed exactly-once. Эти задачи остаются
блокерами #33/#11.

```bash
cd orchestration-server
python -m pytest tests/test_safe_recovery.py -q
```

В CI тесты доказывают quarantine, idempotence, отсутствие вызова runner
для заблокированной задачи, продолжение других pending задач и
сохранение подтверждённой completed задачи.
