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


## Этап #38: журнал решений администратора

После восстановления администратор может прочитать список quarantined задач:

```text
GET /api/v1/admin/recovery-quarantine
GET /api/v1/admin/tasks/{task_id}/reconciliation
POST /api/v1/admin/tasks/{task_id}/reconciliation
```

Для всех трёх маршрутов требуется роль `admin`; запись недоступна
ключам `read` и `write`. POST принимает:

```json
{
  "decision": "UNKNOWN",
  "evidence_ref": "qa-artifacts/incident-123",
  "evidence_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

`evidence_ref` — безопасный идентификатор сохранённого доказательства,
`evidence_sha256` — проверенная оператором SHA-256 контрольная сумма.
**Сервис пока не скачивает и не проверяет артефакт**: это строго
фиксируемое подтверждение со стороны авторизованного оператора, а не
автоматическая экспертиза. Факт проверки артефакта необходимо
подтверждать вне системы. Не вставлять ключи, содержимое файлов или
секретные URL в ссылку на доказательство.

Разрешены решения `UNKNOWN`, `CONFIRMED_SIDE_EFFECT`,
`CONFIRMED_NO_SIDE_EFFECT`. Первое можно уточнить одним из двух
подтверждённых. Подтверждённые решения неизменяемы.
Актуальное решение живёт в `task_reconciliations` (одна строка на
задачу), а история — в неизменяемых `task.reconciliation_attested`
событиях SagaEvent. Оператор устанавливается из `AuthContext.subject`,
не из запроса. Конкурирующие попытки подтверждения не могут
создать два успешных решения.

**Любое решение оставляет исходную задачу в `blocked`.**
Система не создаёт новую попытку, не вызывает LLM и не запускает
инструменты. Чтобы выполнить остаток работы, оператор отдельно
создаёт новую workflow task после сопоставления исходных артефактов
и `CLAIMED` ledger-записей.

Для существующей БД необходимо применить новую таблицу
`task_reconciliations` при миграции или `create_all` на старте сервиса.
В production необходимо использовать управляемые SQL-миграции.
Чтение Ledger-статусов, доказательства и UI принятия решения требуют
отдельного этапа — не считать этот API готовым unattended recovery.

```bash
cd orchestration-server
python -m pytest tests/test_reconciliation.py tests/test_reconciliation_api.py -q
```
