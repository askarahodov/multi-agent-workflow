# Реестр документации

Машинный источник: `docs/governance/documentation-inventory.json`. Срез: `8fd7d5f7881ded3dc3b99a946ce016b562b9ee51`, плюс изменения текущего PR. Сфера — все tracked Markdown, JSON, YAML внутри docs, включая evidence. Владелец указан как область ответственности по [OWNERSHIP](../architecture/OWNERSHIP.md), не назначение конкретного человека.

| Статус | Значение |
|---|---|
| canonical | Редактируемый источник; не означает Accepted или подтверждённый runtime |
| historical | Сохранённый исходный отчёт/срез, не инструкция |
| superseded | Адрес совместимости, источник указан отдельно |
| draft | Материал для проверки/согласования |

Языковые статусы: ru (проверенная русская редакция), technical-exception (технический материал), historical-original (сохранение evidence), translation-required (явный долг), unknown (язык и актуальность ещё не проверены). Каждое исключение и долг имеют причину. Review: UNKNOWN либо source-checked для изменённых страниц; независимая приёмка не заявлена.

Локальный контроль из корня: `node --test scripts/check-doc-inventory.test.mjs`, затем `node scripts/check-doc-inventory.mjs`. Новые документы требуют записи в реестре. Не изменять evidence ради прохождения проверок. Политика — [порядок сопровождения](documentation-policy.md).
