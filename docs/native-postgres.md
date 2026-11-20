# Перехід на нативний PostgreSQL 16 (без Docker)

Нативна служба Windows `postgresql-x64-16`, лише `localhost`, порт **5433** (Docker лишається
на 5432 як запасний варіант; том Docker `pgdata` ніколи не видаляйте).
Усі команди: звичайний PowerShell у корені репозиторію (`D:\Trading Scripts\WEB_application`),
крім кроків, позначених **(адмін)**: там PowerShell «Запуск від імені адміністратора» і
`cd "D:\Trading Scripts\WEB_application"`. Скрипт ніколи не показує паролі.

## Кроки

1. Зупиніть застосунок: `stop.bat` (Docker Desktop лишається запущеним — з нього копіюємо дані).
2. Паролі в `.env`: `python -m uv run --project backend python scripts/native_pg.py secrets`
3. Показати команду встановлення: `python -m uv run --project backend python scripts/native_pg.py install-command`
4. **(адмін)** Вставте показаний фрагмент PowerShell (`$pw = ...`, `winget install ...`,
   `Remove-Variable pw`) і дочекайтеся кінця встановлення (кілька хвилин).
5. **(адмін)** Налаштування: `python -m uv run --project backend python scripts/native_pg.py configure --restart`
   (роль `journal`, бази `trading_journal` і `trading_journal_test` з ICU-локаллю en-US — сортування
   тексту як у Docker; лише localhost, автозапуск служби, перезапуск служби). Також змінює пароль
   суперкористувача `postgres` на новий (записує в `.env`): старий міг лишитися в журналі
   інсталятора в `%TEMP%` і більше не дійсний. `--no-rotate` — не змінювати пароль.
6. Копія даних з Docker і перевірка: `python -m uv run --project backend python scripts/native_pg.py copy`
   — спочатку перевірена резервна копія `backups/pre-native-<UTC>.dump`, потім відновлення і
   таблиця порівняння (кількість рядків кожної таблиці, md5 ключових таблиць, ревізія alembic).
   Будь-яка «РІЗНИЦЯ» → код виходу 1: **не** переходьте до кроку 7, надішліть вивід.
   Якщо нативна база вже не порожня (повторна копія): додайте `--replace`.
7. Перемкнути застосунок: `python -m uv run --project backend python scripts/native_pg.py switch`
8. Запуск: `start.bat`
9. Перевірка: `python -m uv run --project backend python scripts/native_pg.py status` → «Активна БД
   застосунку: native (порт 5433)»; у браузері «Головна» і «Журнал» показують ваші угоди.
10. Коли все працює: закрийте Docker Desktop (значок у треї → «Quit Docker Desktop») і вимкніть
    його автозапуск: Docker Desktop → Settings → General → зняти «Start Docker Desktop when you
    sign in to your computer» → «Apply & restart» (або Диспетчер завдань → «Автозавантаження» →
    Docker Desktop → «Вимкнути»).

Якщо `start.bat` пише, що службу «postgresql-x64-16» не вдалося запустити: Win+R →
`services.msc` → «postgresql-x64-16» → «Запустити» (або один раз `start.bat` від імені
адміністратора).

## Як повернутися на Docker

1. `stop.bat`
2. `python -m uv run --project backend python scripts/native_pg.py switch-back`
3. Запустіть Docker Desktop, дочекайтеся «Engine running».
4. `start.bat`

Дані, записані в нативну базу після кроку 7, у Docker не потрапляють (за потреби — повторний
перенос у зворотний бік, окреме завдання).
