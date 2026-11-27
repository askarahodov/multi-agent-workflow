# Оценка качества агентов (Agent Evals)

Версия 0.1.0, проект для согласования #341. Источники ролей: [паспорта](role-passports.md), [реестр контрактов](../architecture/contract-registry.md), [конституция](constitution.md). Не новый registry профилей и не runtime authority.

## Offline baseline

В `services/quality-gates/tests/fixtures/agent-evals-v1.json` — 14 безопасных версионированных сценариев: 12 ролей и два workflow (handoff и recovery). Входы — синтетические факты, ожидаемые требования, handoff, тесты, границы tool calls, необходимость human intervention. Сценарий injection содержит только синтетические данные. Scripted adapter не вызывает провайдер, shell, сеть или файловые инструменты. Оценщик сравнивает наблюдения с отдельным oracle; self-verdict запрещён. Любой запрещённый запрос считается критической регрессией, даже если runtime его отклонил. Не путать этот known-answer replay с тестом реальной модели или доказательством runtime isolation.

```sh
cd services/quality-gates
python -m pytest tests/test_agent_evals.py -q
python -m quality_gates.agent_evals --catalog tests/fixtures/agent-evals-v1.json --passports ../../docs/governance/role-passports.json
```

Этот тест входит в обязательный backend pytest quality-gates, также выполняется в make check. Регрессия либо неполный набор наблюдений делают тест красным. Offline порог — 100% сценариев и ноль critical policy violations. SHA256 канонического JSON fixture (не форматирования), model/profile/skill/policy binding включены в отчёт; offline skill неизвестен, стоимость и latency null, live_quality NOT_RUN. Набор малый, синтетический; показатели реального агента неизвестны.

## Approved live eval

Только после явного согласования #327/#330: отдельный оператор утверждает план с exact fixture/model/profile/skill/policy SHA, независимым наблюдателем, 2–20 повторениями, лимитами стоимости в microUSD, latency в ms, human intervention, pass threshold в basis points (10000 = 100%). Ни один критический policy violation не допустим даже при достигнутом среднем пороге. Runner/collector обязан получать результаты тестов, tool events, cost/latency от доверенных источников, а не из текста агента. Не хранить сырые prompts, ключи, секреты или пользовательские данные. Отдельно проверяются доступ, разрешение и бюджет перед любым live запуском. Данная реализация не запускает live и не резервирует бюджет.

`quality_gates.agent_evals.evaluate` принимает полный набор наблюдений, строго сверяет повторения, binding, SHA плана и наблюдателя каждой записи, структуру decision record, отклоняет unknown cost/latency, пропуски, дубли, self-review, подмену SHA и превышение лимитов. Выдаёт pass count, sample size, median/max latency, total cost и critical violations. Это структурная обработка **непроверенных** записей; approval_ref не доказывает независимую identity. Report всегда promotion_authorized=false, promotion_gate=BLOCKED, live_quality=UNVERIFIED для live observations. Не принимать этот результат за подписанную QA аттестацию.

## Продвижение модели/профиля

Offline regression gate должен быть PASS; live thresholds и independent verdict утверждаются владельцами, а не моделью. Реальное продвижение профиля требует доверенного enforcement #327/#329/#330/#331, проверенного collector и exact promotion receipt. До них любое продвижение по данному отчёту заблокировано; production/платные вызовы не разрешены. При изменении fixture, модели или политики повторить полную выборку; старый SHA не подходит. Rollback — вернуться к последней отдельно утверждённой версии, не снижать пороги для прохождения. Отчёт об ограничениях: 14 синтетических задач не представляют распределение реальных проектов, оценка не измеряет человеческое качество ответов, реальную стоимость, устойчивость модели или статистическую значимость. Live baseline NOT_RUN; утверждённые пороги и integration в lifecycle ещё требуют согласования.
