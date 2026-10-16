# #11 — независимая QA-аттестация native SDLC

## Контракт доверия

В строгом режиме `Orchestration Server` остаётся владельцем состояний и зависимостей задач. Отдельный `Quality Gates` запускает `tester`, `reviewer` и `security`, сохраняет evidence, а ADMIN-оператор выпускает подписанное HMAC-SHA256 свидетельство только после трёх успешных проверок. Агент с обычным WRITE-ключом не может выдавать свидетельства или перескакивать следующую стадию.

## Настройка

- Quality Gates: `AUTH_ENABLED=true`, операторский `ADMIN_API_KEYS` и приватный `QG_QA_ATTESTATION_KEY` (ASCII 32–128 символов).
- Orchestration Server: `ORCH_ATTEMPT_LEASE_ENABLED=1` и `ORCH_QA_ATTESTATION_KEY` с тем же ключом подписи.
- Worker: только собственный WRITE-ключ и lease, **без** QA ADMIN-ключа и секретов подписи.
- Не размещать секреты в Git, workspace, логах, аргументах команд или запросах модели. Строгий режим без lease отключать нельзя.

Опция сохраняет совместимость со старыми сценариями; режим без неё **не удовлетворяет** критерию независимых QA gates задачи #11.

## Последовательность после каждой стадии

1. Native worker делает настоящие tool calls, commit в отдельном worktree и передаёт JSON Contract Gate. Orchestration сохраняет успешную попытку и `worker_reported` Git SHA, но блокирует захват зависимой задачи.
2. Независимый оператор проверяет именно Git artifact этой попытки, запускает QG `tester`, `reviewer`, `security` в доверенной среде. В БД QA должны присутствовать успешные последние gate runs с отдельными evidence items.
3. Оператор вызывает `POST /api/v1/tasks/{task_id}/qa-attestation` в Quality Gates под ADMIN-ключом, с JSON `{"attempt_id":"ATTEMPT_ID","commit_sha":"COMMIT_SHA"}`.
4. Quality Gates проверяет результаты в своей БД и выдаёт `task_id`, `attempt_id`, `commit_sha`, `gate_run_ids`, `issued_by`, `issued_at` и `signature`. Подпись защищает канонический JSON; срок для доставки — один час.
5. Оператор передаёт ответ целиком в `POST /api/v1/tasks/{task_id}/qa-attestation` Orchestration Server под отдельным ADMIN-ключом. Сервер сверяет HMAC, время, task, completed attempt, Contract Gate и persisted SHA; сохраняет immutable `task_qa_attestations` и `task.qa_attested` в журнале.
6. Следующая задача становится доступна для `claim` только после QA всех prerequisites. Последний run становится `completed` только после QA *всех* его стадий, включая release-prep. Перезапуск не сбрасывает verified QA.

Запрещены автоматический повтор аттестации и импорт произвольного JSON от worker как «QA passed».

## Необходимые ограничения

- Подпись подтверждает, что проверенные QA runs действительно зарегистрированы независимым сервисом, но **сама по себе не доказывает, что сканировались байты указанного Git SHA**. Оператор обязан монтировать/проверять артефакт этого SHA. Сервер сохраняет исходный статус Git `worker_reported`; независимая Git-verification по-прежнему нужна.
- ADMIN API key должен оставаться у человека/отдельного QA-контроллера, никогда у AI worker.
- QA receipt **не является human release approval**. Подтверждение релиза требует отдельного санкционированного действия человека.
- Live OpenRouter, полная UI-приёмка и чистый Compose остаются отдельными недоказанными критериями #11.

## Запуск регрессионных проверок

`python -m pytest quality-gates/tests/test_qa_attestation.py -q`
`python -m pytest orchestration-server/tests/test_sdlc_dependencies.py -q`

Негативные сценарии: отсутствие аттестации, failed/missing QA run, неверные signature/sha/task, WRITE-ключ worker, dev auth и повторная запись, перезапуск между стадиями.
