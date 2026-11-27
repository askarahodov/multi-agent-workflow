# Контроль качества и приёмка

Различайте проверку **репозитория платформы** и независимую приёмку **результатов пользовательского workflow**.

## Репозиторий

Канонический регламент — AGENT_GITFLOW_RULES.md, особенно GF-09. Из корня:

```sh
make lint
make typecheck
make backend-test
make frontend-check
make security
make check
```

Обязательные GitHub checks и фактические jobs проверяются на актуальном candidate SHA; зелёный агрегатор не заменяет отсутствующую проверку. Локальный NOT_RUN не равен PASS. Буквальный `make check` в GitHub CI обязателен на каждом PR: проверяются актуальные head/base, checkout и receipt конкретного запуска. Локальный запуск допустимо заменить подтверждённым эквивалентным CI по GF-09; ручной checkpoint не заменяет PR evidence. Независимое review остаётся обязательным. Подробности: [CI и GitHub](../ci-guide.md). См. [защиту required checks](../security/gitflow-required-checks-gate.md).

## Продуктовая приёмка

Quality-gates и orchestration-server используют собственные контракты; свидетельство должно принадлежать нужной задаче, попытке, commit и доверенному signer. Самоотчёт разработчика, статус задачи, отсутствие ошибок и mock не доказывают независимую приёмку. Release approval — отдельная граница. При отсутствии, несоответствии или истечении evidence результат остаётся непроверенным; не ослаблять gate ради зелёного UI.

- [Локальная ручная приёмка](../qa/LOCAL-MANUAL-ACCEPTANCE.md).
- [Native QA attestation](../qa/issue-11-native-qa-attestation-ru.md).
- [Граница доверия runner](../qa/issue-117-runner-trust-boundary.md).
- [Готовность пилота](../qa/PILOT-READINESS.md).

Старый hermes-quality-gate CLI и пример .github/workflows/quality.yml не являются каноническими командами продукта. Реальные workflows: .github/workflows/ci.yml и .github/workflows/quality-gate.yml; остальные применимые проверки определяет действующая политика. Не заявлять production readiness без стендового evidence.
