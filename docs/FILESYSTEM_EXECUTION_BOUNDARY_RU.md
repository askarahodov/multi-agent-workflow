# Граница файловых инструментов агента — контроль Issue #5

Состояние после аудита: исполнение `read_file` и `write_file` осуществляется через `ScopedFilesystemExecutor` непосредственно перед I/O, а не через `ToolPolicyEngine.classify_fs()`. `classify_fs` не является границей авторизации.

## Проверяемые инварианты

- Корень workspace определяется доверенной платформой, а не сообщением модели.
- Перед открытием файла проверяются разрешения конкретной операции; использование `..`, абсолютных путей вне workspace и защищённых `.env`, `.git`, `.ssh` запрещается.
- На POSIX используется открытие компонентов через дескрипторы каталогов и `O_NOFOLLOW`; симлинки на control-plane SQLite, сокеты и секреты не разыменовываются.
- Запрещены не-файловые инструменты (shell/git/http) в текущем штатном `NativeFilesystemDispatcher`; их расширение относится к Issue #20 и требует отдельной boundary.
- Неизвестная операция отклоняется до вызова underlying filesystem, даже если её аргументы выглядят как допустимая запись.
- На Windows файловый executor **fail closed**: текущая POSIX реализация не переносится путём отключения `O_NOFOLLOW`. При запуске Docker Compose на Windows он работает в Linux-контейнере.

## Проверки

В Linux из корня репозитория с установленным Python окружением:

```sh
python -m pytest agent-management/tests/test_scoped_fs.py agent-management/tests/test_native_tool_dispatch.py agent-management/tests/test_issue5_negative_boundary.py -q
```

В Windows CMD запускайте тесты в Linux-контейнере проекта; без POSIX реализации на Windows прямое файловое исполнение должно отклоняться.

Тесты из `test_issue5_negative_boundary.py` покрывают отклонение shell/git/network/http вызовов до файлового I/O, lexical traversal, защищённые пути, непредусмотренные внешние записи, сохранение корректной разрешённой записи и попытки доступа к платформенной SQLite через симлинк.

**Граница ответственности:** эти проверки не являются доказательством безопасности отдельного shell/git/http executor. Такие операции и их SSRF/sandbox проверки ведутся отдельно в Issue #20 / PR #87/#88. Отключать policy enforcement ради локального запуска нельзя.
