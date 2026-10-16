# Аудит зависимостей frontend (issue #22)

## Подтверждённая конфигурация

- `frontend/package.json`: `engines.node = ">=22 <25"`.
- `frontend/Dockerfile`: `node:22-alpine`.
- `.github/workflows/ci.yml` и `.github/workflows/quality-gate.yml`: Node.js 22.
- Источник зависимостей — `frontend/package-lock.json`; проверка выполняет `npm ci --engine-strict`.

## Проверка и критерий приёмки

Workflow `Frontend dependency audit` выполняет `npm audit --json --audit-level=high` по всему дереву, включая devDependencies, и сохраняет `audit-report.json` как artifact. При ошибке реестра, невалидном JSON или недоступном отчёте задача падает, а не формирует ложный «зелёный» результат. Наличие хотя бы одной high/critical уязвимости блокирует эту проверку. Moderate/low требуют оценки, но сами по себе не блокируют.

Локальный эквивалент при доступном npm registry:

```sh
cd frontend
npm ci --engine-strict
npm audit --json > audit-report.json
npm run typecheck
npm run lint
npm run test:run
npm run build
```

Дополнительно перед закрытием #22 нужны: фактический audit before/after, проверка dev/prod exposure, безопасное обновление уязвимых пакетов и lockfile, успешный Compose smoke и зелёные CI/Quality Gate/Frontend dependency audit. Массовый `npm audit fix --force` не допускается. Задачу нельзя считать закрытой только на основании добавления данного workflow.

## Отдельные изменения

Dependabot PR #1 обновляет Vite/Vitest до новой major-линейки. Изменения в нём должны проверяться самостоятельно: не нужно смешивать автоматический major upgrade с настройкой аудита.
