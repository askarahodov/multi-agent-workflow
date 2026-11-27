# Пилот независимой автоматизированной приёмки GitHub

Решение владельца: подготовить проверяемый независимый автоматизированный review для GF-09, не выдавая self-review или CI за approval. Реализация в существующем PR #350; не создавать дополнительную ветку при превышении WIP.

## Режим пилота

До принятия изменения политики на защищённом main действует GF-09 прежней версии. PR, меняющий саму политику, не может применить новый критерий к себе. Сначала независимый reviewer согласует bootstrap и владелец подтверждает scope. Обязательные GitHub protections сохраняются. Никакого выставления APPROVED от имени автора, прав на merge, записи статусов или обхода ruleset.

Аудитор запускается с доверенного чистого checkout exact main: `python3 scripts/git/review-evidence-gate.py --pr 351 --head <полный SHA>`. GH CLI использует существующую read-only аутентификацию; необходимы read contents/checks/actions/pull requests/issues. Скрипт проверяет:

- same-repository ready PR, точный head и актуальную base main, отсутствие отставания, единственный разрешённый файл из immutable compare main...head; не использовать mutable /pulls/N/files, который допускает ABA-гонку;
- подлинный Codex GitHub App (id 1144995, owner OpenAI id 14957082) и bot identity 199175422 по GitHub API, единственный структурированный summary, завершённое code review без findings именно на полном SHA; GraphQL IssueComment подтверждает body, node ID, author/editor и updatedAt в одном снимке. Редактор должен быть тем же Codex Bot (либо явно неотредактированное тело); неизвестный редактор, расхождение REST/GraphQL или изменение снимка блокируют evidence;
- все review threads через пагинацию GraphQL, отсутствие действующего CHANGES_REQUESTED, обязательные checks от GitHub Actions app 15368, все требуемые и фактически запущенные workflows на head;
- повторную проверку head/base и неизменности снимка комментария перед выдачей результата. При ошибке API, stale SHA, незавершённой проверке, отсутствующем evidence или выходе за allowlist — BLOCKED.

Начальная область намеренно минимальна: только добавление/изменение `docs/architecture/enterprise-gap-audit.md` (ненормативный архитектурный аудит #322). Остальные пути, включая политику/CI, security/auth/runtime, контракты, PRD и deployments, требуют обычного независимого approval. Расширение allowlist — отдельное согласованное изменение доверенной политики. Решения о TO-BE, NFR, live QA и релизе остаются у уполномоченных людей. Автоматизированное ревью не заменяет их.

`EVIDENCE_READY` означает проверенные независимые code review + CI evidence, **не** разрешение merge или закрытие Issue. Поле merge_authorized всегда false. После защищённого принятия политики владельцем этот отчёт может служить доказательством автоматизированного review для строго разрешённой области, если все остальные GF-09 условия и фактические GitHub approvals выполнены. Новый commit/base требует свежей проверки. Проверка не является атомарной с merge: оператор/доверенный coordinator проверяет head/base и действующие защиты непосредственно перед операцией с exact head. Отсутствие required approving review в GitHub ruleset не является разрешением игнорировать действующий GF-09.

## Автоматизированный запуск

Workflow `.github/workflows/review-evidence-audit.yml` запускается из принятого default branch при создании/обновлении структурированного комментария доверенного Codex App либо вручную (`workflow_dispatch`, exact PR/head). Token имеет только read permissions; checkout только `refs/heads/main`, без credentials в checkout. События до merge bootstrap не активируют workflow. GitHub не привязывает этот read-only job к candidate SHA как обязательный status check; точный SHA записан в JSON результата. Это audit evidence, не native GitHub approval и не автоматический merge.

## Проверка и rollout

1. Тесты `python3 -m pytest scripts/git/tests/test_review_evidence_gate.py -q` в существующем GitFlow CI без секретов.
2. Независимое review именно PR #350, подтверждение политического решения и безопасная интеграция по старой процедуре.
3. На защищённом main провести live read-only audit #351 и отрицательный тест для PR с изменением policy/security.
4. Только после успешного пилота обсуждать расширение scope или отдельный доверенный required check; не модифицировать ruleset автоматически. Сохранить доказательства, причины NOT_RUN, внешние approval и cleanup receipt.

## Маршрутизация автоматических событий

Автоматический запуск выполняется только на структурированном summary завершённого Codex review. Сначала доверенный main классифицирует актуальный PR на основе read-only API и immutable diff. `NOT_APPLICABLE` (draft/closed, другой target/repo или изменения вне единственного разрешённого пути) означает, что **аудит не выполнялся**, его шаг пропущен; успешный шаг маршрутизации не является успешным review. JSON всегда содержит merge_authorized=false, codex_comment_id=null; требуется обычное независимое согласование и CI. `ELIGIBLE` лишь запускает полный строгий аудит. Недостоверные данные, неполный diff, изменение снимка или ошибка API — `BLOCKED`, exit 1. Ручной workflow_dispatch всегда выполняет строгий аудит, включая отрицательный тест для изменений вне пилота; такой тест обязан закончиться BLOCKED. Параллельность только внутри квалифицированного job: чужой комментарий не отменяет активный аудит. Отдельный повторный запуск после завершения CI нужен, если review закончилось раньше тестов. Старые red audit runs остаются историей, не переписываются.
