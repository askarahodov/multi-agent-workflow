# Готовность пилота: приёмка по доказательствам (#11, #8)

**Граница пилота:** один оператор на доверенной локальной машине, непубличные сервисы и контролируемый проект. Это не production security approval. Не коммитить API keys, tokens, provider responses с секретами или приватное содержимое workspace.

## Существующие технические проверки

Из чистого checkout с Docker Compose, Git и Python:

```sh
python -m pytest tests/test_pilot_readiness.py -q
python scripts/check_native_qa_compose.py
python scripts/check_native_qa_compose.py --live-sdlc
```

Compose checks оценивают разрешённую конфигурацию без запуска контейнеров. Выполнить native cross-service CI и protected Compose boot/restart smoke по `.github/workflows/native-agent-e2e.yml`. Сохранить workflow URL, точный commit SHA и build/run IDs. Зелёный CI необходим, но недостаточен.

## Live-приёмка с разрешением оператора (возможен платный OpenRouter)

1. Подготовить документированные private key files, QA signing keys и отдельный operator approval secret вне Git. Использовать protected Compose overlays: autonomous dispatch, QA dispatch, trusted Git runtime, OpenRouter provider egress, release approval. Настроить реальную QA test command; намеренно падающая команда по умолчанию не годится. Ограничить опубликованные порты и внешнюю сеть.
2. Сохранить чистый `docker compose config`, build, container health, authenticated API responses и браузерное UI evidence. Подтвердить отсутствие Hermes/другого agent CLI в PATH/HOME.
3. В реальном браузере создать project/workflow и запустить development run; записать durable ID, events, начальные task states. Не подменять прямым изменением БД или mock UI.
4. С явно согласованными OpenRouter credentials и бюджетом проверить реальный provider request и native tool invocation в изолированном workspace. Сохранить очищенные tool/provider evidence; проверить Git commit доверенным orchestration verifier. Scripted/offline provider не удовлетворяет этому условию.
5. Отправить намеренно невалидный completion для доказательства Contract Gate rejection, затем проверить валидную Git-bound submission и переход к следующей стадии. Записать HTTP codes и неизменяемые evidence.
6. Провести независимый QA отдельными credentials; проверить test output, gate receipt и изоляцию от worker identity. Получить operator approval только через отдельную release-approval boundary; QA или worker не выдают его неявно.
7. Перезапустить стек, проверить сохранение run/task states, artifacts, event journal и UI. Проверить interruption worker, retry и recovery без повторной приёмки.
8. Независимый security reviewer проверяет proxy/query-string redaction, key rotation/revocation, network/volume isolation, ограничения privileged Docker local-only профиля и rollback. Не включать SSE/WS tickets лишь потому, что CI зелёный.

## Схема доказательств и решение

Создать приватный очищенный JSON-отчёт (не коммитить) с `schema_version: 1`, полным 40-символьным `commit_sha` и объектом `checks`. В каждом элементе `status: PASS|FAIL|BLOCKED` и строка `evidence`: HTTPS link без URL userinfo, query, fragment либо путь относительно private evidence root. Signed URLs с credentials остаются в приватном evidence store и не входят в JSON. Для `live_openrouter_tool_call`, `independent_qa`, `security_signoff` обязателен указанный `reviewer`.

**Каждый PASS полной CLI-проверки** должен иметь экспортированный очищенный локальный evidence artifact и поле `sha256` с точным 64-символьным lowercase hex SHA-256. CLI проверяет существование, безопасный относительный путь, размер и hash, отказывает при symlink/hardlink/traversal и несовпадении. Артефакты не коммитятся. HTTPS references годятся для планирования (`--check-structure-only`), но offline CLI не может хешировать их: они не принимаются как integrity-verified PASS. Для полной проверки сохранить локально экспортированную, просмотренную и очищенную копию.

Для полной проверки байтов использовать Linux/WSL или иной POSIX host с `dir_fd`, `O_DIRECTORY`, `O_NOFOLLOW`, `O_NONBLOCK`. Весь путь открывается через зафиксированные directory descriptors, запрещаются symlink swaps, файлы открываются nonblocking для отказа raced FIFO. На неподдерживаемых платформах (включая native Windows Python) полная проверка fail-closed, а не заявляет race-safe verification; Windows CMD может запускать Linux verifier через WSL, Docker или защищённый Linux host. Structure-only кроссплатформен. Evidence root — приватный каталог оператора без других writers во время аудита.

Обязательные check IDs: `clean_compose`, `browser_project_run`, `live_openrouter_tool_call`, `git_commit_verified`, `contract_gate_negative`, `independent_qa`, `release_approval`, `restart_persistence`, `no_external_agent_cli`, `security_signoff`.

```sh
# Проверить структуру до сбора evidence; не доказательство приёмки
python scripts/check_pilot_readiness.py /private/pilot/report.json --check-structure-only
# Каждый PASS подтверждается реальным очищенным файлом внутри этого каталога
python scripts/check_pilot_readiness.py /private/pilot/report.json --artifact-root /private/pilot/artifacts
```

Пример записи (файл `browser_project_run.json` в приватном root; заменить digest результатом `sha256sum browser_project_run.json` реальных байтов, не использовать placeholder):

```json
{
  "status": "PASS",
  "evidence": "browser_project_run.json",
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

Отсутствующая проверка, FAIL/BLOCKED, отсутствие `--artifact-root`, отсутствующий/нехешированный, слишком большой или изменённый файл дают ненулевой exit. Reviewer проверяет содержимое и связь с точным Git SHA, live run ID, provider request, stage transitions, Git verifier, QA signer и operator approval. SHA-256 проверяет лишь сохранённые байты: он не аутентифицирует producer, не превращает mock в live и не заменяет независимое review.

При отказе verifier печатает лишь фиксированные check IDs и диагностические категории: недоверенные malformed statuses, paths и содержимое artifacts не выводятся в терминал или CI. Оператор отдельно проверяет приватный исходный материал по согласованному процессу redaction. `--check-structure-only` намеренно не проверяет байты. Успешный full gate прямо сообщает `LIVE AUTHENTICITY AND INDEPENDENT APPROVAL NOT VERIFIED`.

Отчёт описывает реальный пилот только после разрешённого live provider run, независимой проверки и всех PASS. Без этих фактов решение — **BLOCKED**, даже если файлы и hash совпали.

Не закрывать #11/#8 по одному реестру. Первый пилот остаётся локальным/доверенным до принятия deployment-specific решения по Docker host-access risk (#3).
