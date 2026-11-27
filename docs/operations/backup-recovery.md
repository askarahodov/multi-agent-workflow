# Резервное копирование и восстановление

Dev Compose использует отдельные SQLite базы orchestration-server, agent-management и quality-gates в каталогах сервисов; PostgreSQL volume существует отдельно. Не путать с Hermes Kanban DB. Перед резервированием определить фактические пути и хранилища по активной конфигурации, согласовать окно и остановить writers. Не удалять исходные базы или volumes.

## План для локального стенда

1. Зафиксировать SHA, manifests, список баз, storage, artifact/evidence и версию схемы; отдельно зафиксировать безопасные ссылки на ключи, не помещать секреты в Git.
2. Остановить исполнение новых задач, дождаться или безопасно остановить попытки по [runbook восстановления](../architecture/safe-worker-recovery.md). Согласовать консистентность БД, Git/evidence и tool ledger.
3. Использовать SQLite online backup API либо согласованный offline snapshot; не копировать только основной SQLite-файл при активном WAL. Для PostgreSQL — согласованную процедуру dump/snapshot на фактической базе.
4. Проверить контрольные суммы и целостность **распакованной копии**, шифрование, права, срок хранения и доступность encryption key. Не проверять gzip как SQLite.
5. Восстанавливать сначала в отдельную среду с отключёнными live calls. Проверить миграции, project/run/task/attempt, journal, Git/evidence, credentials без раскрытия, leases и отказ на чужой scope. Только затем принимать решение о возврате сервиса.

Это план, а не доказанный production DR. RPO/RTO, HA, backup automation и стендовый restore drill остаются #332. См. [локальную приёмку](../qa/LOCAL-MANUAL-ACCEPTANCE.md) и [развёртывание](deployment-guide.md).
