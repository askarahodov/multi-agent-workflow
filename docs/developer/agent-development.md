# Разработка агентов и инструментов

Различайте разработчика платформы и исполняемого продуктового агента. Продуктовый агент имеет серверное описание, модель, ToolPolicy и доверенный execution binding; наличие профиля не означает наличие живого worker или разрешение на вызов модели.

## Путь разработчика

1. Прочитать [границы компонентов](../architecture/OWNERSHIP.md) и [ADR-111](../adr/ADR-111-native-sdlc-dependencies.md).
2. Для provider, credentials и tool dispatch использовать существующий agent-management; цикл сообщений принадлежит packages/agent-runtime; состояние задач и leased attempts — orchestration-server.
3. Использовать существующие контракты и [справочник профилей](../user-guide/agent-profiles.md). Не создавать альтернативный registry или scheduler.
4. Для native tools сверить [границу dispatch](../security/native-tool-dispatch.md), [файловую изоляцию](../security/scoped-filesystem.md) и [доверенное выполнение команд](../security/trusted-command-boundary.md). Не передавать секреты в task prompt или tool output.
5. Покрыть позитивные и негативные сценарии: scope, неизвестный инструмент, запрещённый путь, истёкший lease, повторное выполнение, ошибку провайдера и восстановление. Доказательства связывать с точной попыткой и SHA.

## Проверки

Из корня: `make backend-test`, `make frontend-check`, `make security` по применимости; полный `make check` и CI — по AGENT_GITFLOW_RULES.md. Для реального worker использовать [операторский runbook](../NATIVE_WORKER_ACCEPTANCE_RU.md); live provider и изменение защищённого окружения требуют разрешения. Старые примеры Hermes Agent SDK и генерации профиля из произвольного YAML не являются поддерживаемым native API. Инструменты локальной координации описаны отдельно в [Kanban](kanban-integration.md).
