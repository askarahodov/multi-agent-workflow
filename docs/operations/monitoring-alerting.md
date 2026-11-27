# Мониторинг и оповещения

Не путать health контейнера, состояние задачи, доступность worker, verdict QA, расходы и реальный результат разработки. Для dev используйте `make ps`, `make logs`, health endpoints из [руководства развёртывания](deployment-guide.md) и серверный журнал попыток. Не выводить API keys, stream tickets, prompt secrets, proxy userinfo или provider credentials в логи.

## Что контролировать

| Сигнал | Что проверять |
|---|---|
| Доступность | Health каждого сервиса, ошибки и перезапуски |
| Исполнение | Очередь ready, lease/attempt, blocked, quarantine, recovery |
| Качество | Независимый verdict с точным task/attempt/SHA; UNKNOWN не зелёный |
| Провайдер | Ошибки, latency и usage только из подтверждённого источника |
| Хранилища | Доступность, целостность, заполнение, проверенное восстановление |

Prometheus/VictoriaMetrics, Loki, Grafana, trace correlation и SLO — требования #331. Не считать приведённые в прежней редакции metric names, Tempo, PagerDuty и dashboards фактически поставляемыми. До утверждения каталога метрик и стендового evidence нельзя использовать их как рабочие alert expressions. События и состояния native runtime описаны в [журнале](../NATIVE_AGENT_LOOP_JOURNAL_RU.md) и [ADR-111](../adr/ADR-111-native-sdlc-dependencies.md).
