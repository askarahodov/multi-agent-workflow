# Карта веток и что где влито (проверено на fd3cb4e)

Дата: 2026-10-13. Задача: t_245d1a99 «очень много веток».
Все факты проверены напрямую через `git` (merge-base --is-ancestor, rev-list), а не по отчётам агентов.

## Короткий вывод

В репозитории **нет одной ветки, в которой собрано всё**. Есть три независимых «линии» работы,
плюс опубликованное состояние `origin/main`. Ни одна из трёх линий НЕ запушена в origin.

- `origin/main` — то, что реально опубликовано.
- `integration/mvp-v1` (fd3cb4e) — самая полная линия ОТНОСИТЕЛЬНО origin: содержит весь origin/main + 12 коммитов (безопасность SEC-001/002/004, консолидация MVP). **Не запушена.**
- `integration/epic-int-final` (ade27d3) — **объединение** mvp-v1 + линии P8.3/quality-gates. Самая полная ветка в репозитории (mvp-v1 + 6 коммитов).
- `epic-int/e9-release` (8f0e48e) — отдельная линия CI/ops, **не влита никуда**.
- `wt/t_16d5878b` (9a0d81a) — фронтенд MVP UI; содержимое почти целиком уже есть в mvp-v1 (пришло через ec2345e), отличается только App.tsx (+153 строк).

## Что удалено (9 слитых локальных веток)

Удалены как полностью влитые в fd3cb4e (проверено: все их SHA — предки mvp-v1):
epic-int/e4-api-unification, epic-int/e8-fixes, wt/t_108a23ca, wt/t_355d3791,
wt/t_8cf664ab, wt/t_9ccebfb9, wt/t_b0269195, wt/t_d7a8932f, wt/t_db1ca632.
Также удалено 7 связанных worktree. Ни одна удалённая ветка не содержала уникальных коммитов — потерь нет.

## Осталось на диске

| Ветка | HEAD | Что это | Уникальные коммиты | Влита в origin/main? |
|---|---|---|---|---|
| `main` | eba4685 | локальная, **позади origin/main на 7** | 0 | — |
| `integration/mvp-v1` | fd3cb4e | текущая рабочая линия (безопасность + MVP) | 12 над origin/main | НЕТ |
| `integration/epic-int-final` | ade27d3 | mvp-v1 + линия P8.3 (самая полная) | 6 над mvp-v1 | НЕТ |
| `epic-int/e1-current-state` | 60cb553 | P8.3 hardening, quality-gates fix, аудиты | 5 над mvp-v1 | НЕТ |
| `epic-int/e9-release` | 8f0e48e | CI quality-gate, `make up`, доки, release notes | 6 над c8e9e4f | НЕТ |
| `wt/t_16d5878b` | 9a0d81a | фронтенд MVP UI (почти дубль) | 1 над c8e9e4f | НЕТ |
| `wt/t_245d1a99`, `wt/t_8c8493ff`, `wt/t_bd041e1d`, `wt/t_ceef09ea` | fd3cb4e | транзитные worktree этой уборки, уникальных коммитов 0 | 0 | НЕТ |
| `origin/dependabot/...-72371e98d1` | b655f92 | remote, открыт PR #1 | 1 | — |

## Три линии работы (главное для «что и где влито»)

Линия A — `integration/mvp-v1`: безопасность (SEC-001 WebSocket auth, SEC-002 TLS/HSTS, SEC-004 envelope encryption)
+ консолидация MVP-артефактов. Содержит весь `origin/main`. Готова к пушу, но не запушена.

Линия B — `epic-int/e1-current-state` → `integration/epic-int-final`: реализация P8.3 runtime-hardening,
исправления quality-gates, аудиты EPIC-INT. **Уже объединена в epic-int-final.**

Линия C — `epic-int/e9-release`: единый CI quality-gate (.github/workflows/quality-gate.yml), `make up`,
приведение доков, release notes. **Нигде не влита** — ни в mvp-v1, ни в epic-int-final, ни в origin/main.

Итог: `integration/epic-int-final` = A ∪ B (без C). Чтобы собрать всё, к epic-int-final нужно добавить линию C.

## Требуются решения (ветки не удалены — содержат уникальную работу)

1. `integration/epic-int-final` — по-видимому, целевая интеграционная ветка. Решить: делать её основной и пушить?
2. `epic-int/e9-release` (линия C) — влить в epic-int-final/mvp-v1 или удалить?
3. `epic-int/e1-current-state` — уже в epic-int-final → можно удалять.
4. `wt/t_16d5878b` — содержимое дублирует mvp-v1 → можно удалять.
5. `origin/dependabot/...` — открыт PR #1, решить merge/close.

Проверить и выполнить после решения: `git branch -d epic-int/e1-current-state wt/t_16d5878b`.

## Прилагаемые артефакты (из дочерних карточек)

- `branch-cleanup.log` — журнал удалений (t_bd041e1d)
- `unmerged-review.md` — таблица неслитых веток (t_ceef09ea)
- `branch-decisions.json` — шаблон решений (t_ceef09ea)
- `branch-inventory.json` — инвентарь веток (t_355d3791)
