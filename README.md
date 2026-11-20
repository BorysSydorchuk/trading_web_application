# Trading Journal

Локальний журнал угод для одного користувача Windows: PostgreSQL 16, FastAPI,
окремий worker і React UI українською. MT5 використовується лише для читання;
застосунок не відкриває, не змінює і не закриває ордери.

## 1. Обов'язкове програмне забезпечення

| Що | Підтримувана конфігурація |
| --- | --- |
| Windows | Windows x64; перевірено на Windows 11, PowerShell 5.1 |
| [Git for Windows](https://git-scm.com/download/win) | `git` доступний у PATH |
| [Python](https://www.python.org/downloads/windows/) | **3.12.x**, x64; launcher відхиляє інші minor-версії |
| [Node.js](https://nodejs.org/en/download) + npm | **20.19+ у гілці 20.x або >=22.12**; перевірено Node 24.14.1; npm із комплекту Node |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | доступний як `uv` або `python -m uv`; перевірено 0.13.1 |
| PostgreSQL | **16**, один із двох способів нижче |

Типовий спосіб БД: native PostgreSQL 16 — служба Windows `postgresql-x64-16` на
`127.0.0.1:5433` (встановлення і перенос даних: [docs/native-postgres.md](docs/native-postgres.md)).
Запасний варіант — [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
(`docker compose`, порт 5432, Linux containers і WSL 2 згідно з вимогами Docker).
GNU make необов'язковий для запуску; потрібний лише для розробницьких `make`-команд.
MT5, ключ Claude і модель Whisper **не потрібні** для першого запуску UI.

Після встановлення відкрийте новий звичайний PowerShell із глобальним Python 3.12
у PATH (не Python із `backend/.venv` для встановлення самого uv):

```powershell
git --version
python --version
node --version
npm.cmd --version
python -m uv --version
```

Якщо uv ще немає: `python -m pip install --user uv`, потім знову перевірте його.
`npm.cmd` не потребує дозволу виконувати `npm.ps1`. Не потрібно активувати venv
або змінювати PowerShell ExecutionPolicy.

## 2. Клонування та локальна конфігурація

Якщо репозиторій уже клонований, залишайтеся в його корені й пропустіть цей блок.
Для нового встановлення виконайте його в батьківській папці; URL отримайте у власника,
без паролів/токенів усередині URL:

```powershell
$repositoryUrl = Read-Host 'URL репозиторію'
git clone -- $repositoryUrl trading-journal
Set-Location .\trading-journal
```

**Усі подальші команди — з кореня репозиторію**, де лежать `start.bat` і `README.md`.
Зберігайте проєкт у доступній на запис папці, не в `Program Files`.

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env -ErrorAction Stop
}
notepad.exe .\.env
```

Редагуйте й збережіть `.env` локально як UTF-8; не надсилайте його, не комітьте й не
показуйте у терміналі/скриншотах. Існуючий файл цей блок не перезаписує. Для native
PostgreSQL (типово) ключі `NATIVE_*`, `DATABASE_URL` і `TEST_DATABASE_URL` записує
`scripts/native_pg.py` (`secrets`, потім `switch`; §3) — вручну їх не редагуйте. Для
**нового** Docker-встановлення (запасний варіант) узгодьте ключі нижче; кутові дужки — позначки для ваших локальних
значень, не готові паролі:

```dotenv
POSTGRES_USER=journal
POSTGRES_PASSWORD=<ваш локальний пароль БД>
POSTGRES_DB=trading_journal
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://journal:<URL-encoded пароль>@127.0.0.1:5432/trading_journal
TEST_DATABASE_URL=postgresql+psycopg://journal:<URL-encoded пароль>@127.0.0.1:5432/trading_journal_test
ANTHROPIC_API_KEY=
```

Пароль у URL має бути percent-encoded, якщо містить спеціальні символи (`@`, `:`,
`/`, `#`, `%` тощо); `POSTGRES_PASSWORD` — оригінальне значення. Обидва URL мають
відповідати реальним користувачу/паролю/порту БД. `TEST_DATABASE_URL` ніколи не має
вказувати на БД з вашими угодами або цінними QA-даними.
Налаштування середовища процесу мають пріоритет над `.env`; якщо зміни не діють,
перевірте власні session overrides, не друкуючи їхні секретні значення.

Для вже наявної БД використовуйте її чинні облікові дані: зміна `POSTGRES_PASSWORD`
у файлі **не змінює пароль у вже створеному Docker volume**. Не видаляйте volume
для виправлення доступу; збережіть дані й зверніться до відповідального інженера.

## 3. PostgreSQL — оберіть один спосіб

### Native PostgreSQL 16 (типово)

Служба Windows `postgresql-x64-16`, лише `localhost`, порт **5433**. Усе робить
`scripts/native_pg.py`; повні кроки (з командами від імені адміністратора) —
[docs/native-postgres.md](docs/native-postgres.md). Коротко, з кореня репозиторію:

```powershell
python -m uv run --project backend python scripts/native_pg.py secrets
python -m uv run --project backend python scripts/native_pg.py install-command   # вставити в PowerShell (адмін)
python -m uv run --project backend python scripts/native_pg.py configure --restart  # PowerShell (адмін)
python -m uv run --project backend python scripts/native_pg.py copy      # лише при переносі з Docker
python -m uv run --project backend python scripts/native_pg.py switch
python -m uv run --project backend python scripts/native_pg.py status
```

`configure` створює роль `journal` (LOGIN, CREATEDB — для ізольованих тестових БД; не
SUPERUSER) і бази `trading_journal` та `trading_journal_test` (UTF8, ICU en-US), вмикає
автозапуск служби і змінює пароль `postgres`. Паролі генеруються в `.env` і ніде не
друкуються. `pg_dump`/`pg_restore` launcher і backup-інструменти знаходять самі в
`%PROGRAMFILES%\PostgreSQL\16\bin` — змінювати PATH не потрібно (див. §8, якщо в PATH є
старіша версія). Якщо служба зупинена, `start.bat` намагається її запустити; без прав
адміністратора — запустіть «postgresql-x64-16» у `services.msc`.

### Docker Desktop (запасний варіант)

Повернення на Docker: `stop.bat`, потім
`python -m uv run --project backend python scripts/native_pg.py switch-back`, запустіть
Docker Desktop (дочекайтеся «Engine running») і `start.bat`. Для нового встановлення без
native-сервера:

```powershell
docker --version
docker compose version
docker compose up -d --wait db
```

Compose використовує `postgres:16`, loopback `127.0.0.1:5432`, постійний volume `pgdata`
(ніколи не видаляйте його — це копія даних до переносу). На **першій ініціалізації
порожнього volume** створює БД із `POSTGRES_DB` і окрему `trading_journal_test` через
`docker/postgres-init/01-test-db.sql`. Схему застосунку створить launcher. Не запускайте
інший checkout із тією самою БД/Compose-конфігурацією паралельно. Launcher запускає
Docker лише тоді, коли `DATABASE_URL` вказує не на порт native-сервера (`NATIVE_PG_PORT`,
типово 5433) або native-служба не встановлена.

## 4. Залежності та перший запуск

Можна відразу виконати `./start.bat`: launcher встановлює відсутні/застарілі залежності.
Для явного встановлення за lock-файлами (venv не потрібно активувати):

```powershell
python -m uv sync --project backend --frozen
npm.cmd --prefix frontend ci --no-audit --no-fund
.\start.bat
```

Початкове завантаження Python/npm-пакетів і Docker може зайняти кілька хвилин;
це не warm startup. Launcher перевіряє версії, npm/uv, SQL-з'єднання та ідентичність
БД, YAML/налаштування, права запису data/logs/backups та backup tools. Клієнти
`pg_dump`/`pg_restore` беруться з PATH, інакше з `%PROGRAMFILES%\PostgreSQL\16\bin`; лише
без них (Docker-варіант) — з перевіреного контейнера `db`.

Після перевірок launcher застосовує наявні міграції. Перед pending-міграцією кожної
**не-тестової** БД обов'язковий custom-format `pg_dump` у repo `backups/`, перевірений
через `pg_restore` (TOC і всі блоки даних). Невдалий dump/перевірка зупиняє upgrade.
Тільки явно тестові імена з суфіксом `_test` звільнені від цього dump. Не обходьте
launcher самостійним запуском Alembic і не використовуйте цю пільгу для робочих даних.

API, worker і Vite запускаються разом. Готовність означає здорові API/БД, підтверджений
запуск scheduler worker і відповідь frontend. Браузер відкриє http://127.0.0.1:5173;
консоль повідомить `Готово за … (стан API: ok)`. UI: «Головна» → «Налаштування» →
«Рахунки» → «Додати рахунок». На порожній БД очікується порожній список рахунків.
Відсутній AI/MT5 може мати окреме попередження; API і БД повинні бути здоровими.

## 5. Щоденний запуск і зупинка

```powershell
.\start.bat
```

Без автоматичного відкриття браузера: `./start.bat --no-browser`.
Зупинка з другого PowerShell у **цьому самому корені**:

```powershell
.\stop.bat
```

Також працює Ctrl+C у вікні launcher. Зупиняються лише процеси цього застосунку;
PostgreSQL/Docker і volume залишаються. Повторна зупинка безпечна. Наступний старт
розпізнає попередній запуск цього checkout за PID, часом створення й командним рядком;
чужий процес на 8000/5173 не завершується. Не використовуйте загальне завершення
всіх Python/Node-процесів. Порти API/UI launcher — 8000/5173; зміна лише `API_PORT`
або `TJ_*` не є підтримуваним способом перенести весь звичайний launcher.

Еквівалент без `.bat`: `python scripts/dev.py --no-browser` / `python scripts/dev.py --stop`.
За наявності GNU make: `make dev`, `make stop`, `make install`.
`python scripts/dev.py --ensure-db` перевіряє/мігрує БД і завершується без UI/worker.
Розробницький `make check` потребує нових ізольованих синтетичних test-цілей;
не запускайте його на БД з угодами чи на наявній цінній QA-БД (див. `CLAUDE.md`).

### Запуск у фоні: ярлики, значок у треї, автозапуск (M8-12)

Один раз після першого `start.bat` (він встановлює залежності), з кореня репозиторію:

```powershell
uv run --project backend python scripts\install_shortcuts.py
```

Скрипт створює на робочому столі ярлики «Торговий журнал — Старт» і «Торговий журнал — Стоп»
та вмикає автозапуск з Windows (ярлик у папці «Автозавантаження», без прав адміністратора).
Без автозапуску: додайте `--no-autostart`. Повторний запуск скрипта безпечний: він лагодить
ярлики. Те саме: `make shortcuts` (`make shortcuts NO_AUTOSTART=1`).

- «Старт» запускає журнал без вікон PowerShell і відкриває його в браузері. Значок журналу
  з'являється в області сповіщень (трей).
- Меню значка: «Відкрити журнал», «Показати термінали» / «Сховати термінали», «Логи»,
  «Запускати з Windows», «Зупинити».
- «Стоп» зупиняє все (як `stop.bat`). Повторний «Старт», коли журнал уже працює, лише
  відкриває його.
- Термінали MT5, які запускає журнал, працюють без вікон і без кнопки на панелі задач.
  Термінал, який ви відкрили самі, журнал не чіпає.
- Помилка запуску показується сповіщенням Windows. Подробиці: `logs\launcher.log`
  (вивід launcher) і `logs\tray.log`.
- «Запускати з Windows» і «Показувати термінали MT5» також є в «Налаштування» → «Запуск».

`start.bat` / `stop.bat` працюють як раніше (з вікном консолі).

## 6. Необов'язкові MT5, AI та голос

**Без термінала/AI:** перегляд збережених угод, ручний опис, біас, аналітичні дайджести
й калькулятор за вже синхронізованими specs доступні. Без MT5 немає нової історії,
нових specs або живої оцінки margin; інтерфейс показує стан/дату кешованих даних.
Без Claude-ключа немає AI extraction/summary; порожній `ANTHROPIC_API_KEY` дозволений.
Голос необов'язковий: локальний Whisper потребує окремого завантаження моделі при
першому використанні. Для перевірки встановлення нічого не записуйте/не надсилайте в AI.
Додавання ключа може дозволити й автоматичний worker warm-up (платний API), а не лише
натискання AI-кнопок; налаштовуйте його окремо за усвідомленим рішенням власника.

**Реальні термінали (тільки читання):** [покроково — docs/MT5_SETUP.md](docs/MT5_SETUP.md).
Параметр запуску описаний також у [MetaTrader 5 Help](https://www.metatrader5.com/en/terminal/help/start_advanced/start).
Для кожного рахунку створіть окрему доступну на запис portable-копію MT5, наприклад
`D:\MT5\fn-p1\terminal64.exe`, **поза Program Files**. Запуск із PowerShell:

```powershell
& 'D:\MT5\fn-p1\terminal64.exe' /portable
```

Це лише приклад шляху: спершу підготуйте власну копію термінала. Увійдіть інвесторським
паролем; алгоритмічна торгівля не потрібна. «Налаштування» → «Рахунки» →
«Додати рахунок»: «Логін MT5», «Сервер», «Шлях до терміналу» мають відповідати цій копії.
«Створити»; власник локально додає у `.env` ключ `MT5_PASSWORD_<логін>` із паролем
і перезапускає застосунок. Пароль у форму не вводиться. Worker сам використовує
`portable=True`, читає активні рахунки послідовно; помилки видно у status bar/logs.

**Окремий demo/QA checkout:** `MT5_SOURCE=fixture:backend/tests/fixtures/mt5/basic_week.json`
вибирає synthetic source без термінала. Це імпортує вигадані угоди при налаштованому
fixture-рахунку, тому не вмикайте fixture для своєї робочої БД. Деталі login/server
і dummy-пароля — [опис fixture](backend/tests/fixtures/mt5/README.md).

## 7. Резервні копії та безпечне відновлення

- Worker робить daily backup о **18:00 Europe/Brussels**, з обома DST-переходами,
  лише за здорових API/БД. При вимкненому застосунку/ноутбуці backup не виконується.
  Після запуску — одна остання пропущена копія, без replay усіх днів; наступні 18:00
  зберігаються. Не більше трьох спроб на слот із мінімум п'ятьма хвилинами між ними.
- Daily retention — об'єднання **14 днів, 8 тижнів, 6 місяців**: представники тих
  самих перевірених daily-архівів, періоди Brussels, без додаткових weekly/monthly dump.
  Manual/pre-migration та остання успішна копія автоматично не видаляються.
- `BACKUP_DIR` задає приватне сховище **daily/manual** і журнал scheduler (типово
  repo `backups/`). Змінюйте зі зупиненим застосунком; API й worker мають бачити ту саму
  папку. **Pre-migration** dump залишається у repo `backups/pre-migration-*.dump`,
  незалежно від `BACKUP_DIR`; цей шлях також включайте у свій план збереження.
- Кожна сторінка → нижня панель → «Резервні копії»: останній успіх, невдалі спроби,
  прострочення, наступний запуск/повтор та українська підказка. UI — Brussels, зберігання — UTC.
  Read-only API: `/api/backups/status`; polling статусу не перевіряє SHA-256 заново.

Коли власнику потрібна ручна перевірена копія, з кореня:

```powershell
python -m uv run --project backend python -m app.tools.backup
```

CLI виводить шлях до `archive.dump`; поруч `manifest.json` із SHA-256. Публікація
атомарна, dump перевіряється через `pg_restore`. Не виконуйте цей приклад як експеримент
над чужими/реальними даними без рішення власника. Архіви містять торгову історію:
не комітьте й не публікуйте їх. Копія на тому самому диску не захищає від його втрати;
зберігайте потрібні копії на іншому приватному носії разом із локальною конфігурацією.

При відновленні: зупинити застосунок, зберегти поточну БД/архіви без змін, звірити
ціль, SHA-256 і читабельність архіву; відповідальний інженер спочатку відновлює
**у нову порожню ізольовану БД**, перевіряє schema/кількість записів/значення й лише
після owner-рішення планує перемикання. Немає автоматичного restore поверх робочої БД.
Не видаляйте архіви, scheduler `schedule.json` чи lock-файли, щоб прибрати помилку.
Після аварії звичайний `.lock` потребує перевірки відсутності активного dump/restore;
постійний `.schedule.lock` не є «сміттям». Діагностика — з інженером, без reset БД.

## 8. Логи та типові проблеми

`logs/api.log`, `logs/worker.log`: UTF-8, UTC, 5 MiB + п'ять архівів на ім'я;
консоль `[dev]/[api]/[worker]/[web]` зберігає видимість помилок. `logs/ai_usage.jsonl`
— окрема історія вартості, її не ротують/не очищають разом зі звичайними логами.
Не видаляйте аудіо, backups чи інші runtime-файли для «очищення».

| Симптом | Дія |
| --- | --- |
| Немає Python/Node/npm/uv або неправильна версія | Новий термінал, перевірки §1; `python` саме 3.12.x. `python -m uv` — fallback без PATH для uv.exe |
| `npm.ps1 cannot be loaded` | Використати `npm.cmd`; не послаблювати ExecutionPolicy |
| Docker engine недоступний / не стартував за 60 с | Відкрити Docker Desktop, перевірити Linux engine/WSL 2 і `docker compose version`, повторити старт |
| PostgreSQL недоступний / неправильна ідентичність | Перевірити службу/контейнер, узгоджені URL/порт і чинні локальні credentials; не скидати БД/volume |
| Немає pg_dump/pg_restore | Native: перевірити `C:\Program Files\PostgreSQL\16\bin\pg_dump.exe` (компонент command-line tools); Docker: власний `db` доступний і cluster identity збігається |
| pg_dump/pg_restore «версія 15 або старша» / server version mismatch | У PATH є старіший `pg_dump` (він має пріоритет над `%PROGRAMFILES%\PostgreSQL\16\bin`): `where.exe pg_dump`, приберіть старий шлях із PATH або оновіть ту інсталяцію |
| Служба «postgresql-x64-16» не стартує / 127.0.0.1:5433 недоступний | `services.msc` → «postgresql-x64-16» → Запустити; або `start.bat` від імені адміністратора; `native_pg.py status` |
| Порт 8000/5173 зайнятий іншою програмою | Закрити її штатно або погодити зміну конфігурації; launcher чужі процеси не завершує |
| Невалідний YAML/.env, немає запису або місця на диску | Виправити вказаний файл локальним UTF-8 редактором/права/місце, зберігши дані; не показувати секрети в логах |
| Pre-migration backup failed | Міграція не застосовується; виправити tool/доступ/місце, зберегти наявні архіви, повторити через launcher |
| MT5/AI недоступні | Використовувати збережені дані/ручні форми; налаштовувати optional-сервіс окремо, без тестових платних запитів |
| «Резервні копії» показує помилку/прострочення | Виконати українську підказку; не видаляти state/locks, перевірити healthy API/БД і доступне сховище |

## Перевірене встановлення та межі перевірки

Ізольований clone/нові venv і node_modules, окрема synthetic PostgreSQL БД,
fixture MT5/AI disabled, readiness, «Налаштування» → «Рахунки» і owned shutdown:
[звіт M7-06](docs/reports/M7-06.md). У ньому окремо позначені неперевірені native
installation, чиста Windows VM, перше internet-завантаження й реальний MT5. Перенос на
native PostgreSQL 16 (`docs/native-postgres.md`) власник виконав і перевірив 2026-11-20.
Warm performance на репрезентативній історії — [M7-05](docs/reports/M7-05.md);
це не обіцянка такої самої швидкості cold install.
