/**
 * All user-visible UI strings (Ukrainian). Components must not hardcode text.
 * Keys under `errors` match API error codes from docs/api.md.
 */
export const uk = {
  app: {
    name: 'Торговий журнал',
    shortName: 'TJ',
  },
  nav: {
    label: 'Головна навігація',
    home: 'Головна',
    inbox: 'Потрібен опис',
    journal: 'Журнал',
    bias: 'Біас',
    digests: 'Дайджести',
    calculator: 'Калькулятор',
    settings: 'Налаштування',
  },
  pages: {
    home: {
      title: 'Головна',
      description:
        'Тут буде огляд дня: біас на сесії, P&L відносно лімітів, відкриті позиції та стан синхронізації. Зʼявиться в наступних етапах.',
    },
    inbox: {
      title: 'Потрібен опис',
      description:
        'Тут будуть угоди, які чекають на опис або на початковий стоп. Зʼявиться в наступних етапах.',
    },
    journal: {
      title: 'Журнал',
      description: 'Тут буде таблиця всіх угод з фільтрами. Зʼявиться в наступних етапах.',
    },
    bias: {
      title: 'Біас',
      description:
        'Тут будуть очікування на Лондонську та Нью-Йоркську сесії. Зʼявиться в наступних етапах.',
    },
    digests: {
      title: 'Дайджести',
      description: 'Тут будуть тижневі та місячні підсумки. Зʼявиться в наступних етапах.',
    },
    calculator: {
      title: 'Калькулятор',
      description: 'Тут буде калькулятор розміру позиції. Зʼявиться в наступних етапах.',
    },
    settings: {
      title: 'Налаштування',
      description:
        'Тут будуть рахунки, правила та параметри застосунку. Зʼявиться в наступних етапах.',
    },
    notFound: {
      title: 'Сторінку не знайдено',
      description: 'Такої сторінки не існує. Перевірте адресу або поверніться на головну.',
      backHome: 'На головну',
    },
  },
  statusBar: {
    label: 'Стан сервера',
    checking: 'Перевірка зʼєднання…',
    ok: 'Сервер і БД працюють',
    dbDown: 'БД недоступна',
    serverDown: 'Сервер недоступний',
    lastCheck: 'Остання перевірка',
    version: 'Версія API',
  },
  errorBoundary: {
    title: 'Щось пішло не так',
    description:
      'Під час відображення сторінки сталася помилка. Дані не втрачено. Спробуйте перезавантажити сторінку.',
    reload: 'Перезавантажити',
    backHome: 'На головну',
  },
  errors: {
    validation_error: 'Дані заповнено некоректно. Перевірте позначені поля.',
    not_found: 'Запис не знайдено.',
    db_unavailable: 'База даних недоступна. Перевірте, чи запущено PostgreSQL.',
    internal_error: 'Внутрішня помилка сервера. Подробиці в logs/.',
    network_error: 'Сервер недоступний. Перевірте, чи запущено бекенд.',
    unknown: 'Невідома помилка. Спробуйте ще раз.',
  },
} as const

export type Uk = typeof uk
/** API error codes that have a Ukrainian message. */
export type KnownErrorCode = Exclude<keyof Uk['errors'], 'unknown'>
