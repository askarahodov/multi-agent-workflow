# Trusted command boundary — ограниченный этап #20

Добавлен независимый `TrustedCommandExecutor` для запуска **только точных, заранее разрешённых argv**. Это ещё **не** полноценный shell/Git/HTTP tool dispatcher и не основание для закрытия #20.

## Границы доверия

- Путь к бинарному файлу, рабочая директория, разрешённые argv и policy устанавливаются доверенным control plane, не LLM.
- Только прямой запуск argv через `subprocess.run(..., shell=False)`. Не используются `sh -c`, интерпретация командной строки, PATH-поиск исполняемого файла или наследуемое окружение.
- `ToolPolicyEngine.enforce` вызывается до старта subprocess, причём проверяет имя **и все аргументы**, а не просто имя бинарного файла.
- Для Git поддерживаются только запросы `status --porcelain=v1 --untracked-files=no` и `rev-parse --is-inside-work-tree`. Отклоняются настройки через `-c`, внешние diff и любые неразрешённые операции.
- Запрещены имена внешних AI CLI (`hermes`, `codex`, `claude` и другие).
- Ограничены длительность выполнения и размер *принятого* ответа; stderr не возвращается модели. Ограничение размера проверяется после сбора вывода, поэтому отдельная жёсткая memory/CPU sandbox-политика ещё необходима.
- Работает только на POSIX, в доверенном контейнере с отключёнными привилегиями. Запуск в workspace с доступом к секретам, Docker socket или host mounts не разрешён.

## Что остаётся до закрытия #20

Не подключать эту библиотеку напрямую к model-driven вызовам. Нужны процессная sandbox-изоляция, проверка безопасности Git-репозиториев и runtime-тесты гонок workspace; отдельный HTTP executor с HTTPS host/IP allowlist, pinning разрешённого адреса после DNS lookup, запретом внутренних адресов и redirect, ограничениями response bytes и timeout. Требуются durable deny/result journal и корреляция с попыткой.

Тесты: `python -m pytest agent-management/tests/test_trusted_commands.py -q` из корня репозитория при установленном пакете.

См. также [ограниченный файловый dispatcher](native-tool-dispatch.md).
