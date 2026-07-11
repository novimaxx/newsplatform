# WIRE — мастер-спецификация для сборки (BUILD SPEC)

> Полное техническое задание на систему. По этому документу AI-агент (или разработчик)
> строит проект модуль за модулем. Каждый модуль имеет: назначение, интерфейсы, критерии готовности.
>
> **Связанные документы:**
> - `web-platform-spec.md` — детальная спецификация фронта (web + Mini App). Здесь — ссылки на неё.
> - `internal-brief-for-audit.md` — контекст, продукт, риски, конкуренты.
> - `news-platform-plan.html` — визуальные референсы всех экранов.
>
> **Как строить:** по разделу 12 (порядок). Модули независимы через контракты (раздел 3).
> Каждый сервис — свой контейнер, общаются через БД и очередь. Не начинать модуль,
> пока не выполнены критерии готовности предыдущего, от которого он зависит.

---

## 0. Правила для исполнителя

1. **Не ломать текущую пересылку.** Существующие боты работают в проде. Всё новое —
   параллельно; запись в базу обёрнута так, что её падение не останавливает пересылку.
2. Секреты — только через `.env`. Никаких ключей/сессий в коде и репозитории.
   Telethon-сессии — StringSession в секретах, не файлы `.session` в репо.
3. Каждый сервис — отдельный процесс в docker-compose, перезапускается независимо.
4. Все AI-вызовы — через единый модуль-адаптер с переключением провайдера в конфиге (раздел 6).
5. Логи структурированные (JSON) у каждого сервиса; критические ошибки → алерт в ТГ.
6. Языки: Python 3.12 (сборщики, AI-воркеры), Node.js 20 + TypeScript (доставка, API, боты, фронт).
7. Идемпотентность везде: повтор задания из очереди безопасен (проверять, не сделана ли работа).
8. На каждый модуль — короткий README «как запустить и как проверить» + критерий готовности.
9. Канонический источник правды — этот файл. Не плодить параллельные ТЗ.

---

## 1. Обзор системы

Новостная агрегационная платформа: собирает посты из 1000+ Telegram-каналов и RSS,
складывает в единую базу, размечает AI (тема/язык/реклама/важность), склеивает дубли
в события, доставляет отфильтрованные ленты в Telegram-каналы/группы и на веб.
Плюс AI-редактор для рерайта и публикации в собственные каналы.

**Принцип:** одно ядро (БД + AI) — много выходов. Вход пишет всё без фильтрации,
разметка одна на всех, каждый выход — фильтр поверх базы.

### 1.1 Компоненты

```
┌─ collectors ──────────────┐   ┌─ core ─────────────┐   ┌─ delivery ─────────┐
│ tg-collector (Python)     │   │ PostgreSQL+pgvector│   │ router (Node)      │
│ rss-collector (Node)      │──>│ media storage (R2) │──>│ editor-bot (Node)  │
│ tg-poller (Python)        │   │ queue (Redis/BullMQ)│  │ web-api (Node)     │
└───────────────────────────┘   └────────────────────┘   └────────────────────┘
         │                              ▲                          │
         └──────────────┐   ┌───────────┴──────────┐               │
                        ▼   ▼                       │               ▼
                  ┌─ ai-workers (Node/Python) ──┐   │        web + Mini App
                  │ tagger   (разметка)         │   │        (React, отд. спека)
                  │ deduper  (embeddings)       │───┘
                  │ editor-agent (рерайт)       │
                  └─────────────────────────────┘
```

### 1.2 Стек

| Слой | Технология |
|---|---|
| Сбор ТГ | Python 3.12, Telethon |
| Сбор RSS, доставка, API, боты | Node.js 20, TypeScript |
| AI-воркеры | Node или Python (по задаче) |
| БД | PostgreSQL 16 + pgvector |
| Очередь | Redis + BullMQ |
| Медиа | Cloudflare R2 (S3-совместимо) |
| Фронт | React 18 + TS + Vite (см. `web-platform-spec.md`) |
| Оркестрация | docker-compose |
| Провайдеры AI | конфиг-переключаемые (см. раздел 6) |

### 1.3 Структура монорепо

```
wire/
├─ services/
│  ├─ collector-tg/     # юзерботы: события + поллинг + запись в БД + медиа в R2
│  ├─ collector-rss/    # RSS → БД (доработка существующего)
│  ├─ ai-workers/       # tagger, deduper, editor-agent
│  ├─ router/           # доставка по маршрутам (Bot API)
│  ├─ editor-bot/       # AI-редактор: approve-флоу в админ-канал
│  └─ api/              # REST + WebSocket для фронта, Mini App, админки
├─ web/                 # фронт (см. web-platform-spec.md)
├─ packages/
│  ├─ ai/               # адаптер провайдеров (раздел 6)
│  └─ shared/           # общие типы (Event/Route/Source), константы тем
├─ deploy/docker-compose.yml
├─ .env.example         # все переменные (раздел 6 + доступы к БД/R2/TG)
└─ Makefile             # make up / logs / migrate / check
```

Миграции — `dbmate` или `node-pg-migrate`, в `services/api/migrations/`.

---

## 2. Схема базы данных

```sql
-- TG-АККАУНТЫ-СБОРЩИКИ (аккаунт = набор источников, НЕ тема)
CREATE TABLE tg_accounts (
  id            BIGSERIAL PRIMARY KEY,
  label         TEXT NOT NULL,              -- 'collector-1', 'reserve', ...
  phone         TEXT,
  role          TEXT NOT NULL DEFAULT 'collector', -- 'collector'|'poller'|'reserve'|'reader'
  status        TEXT NOT NULL DEFAULT 'active',    -- 'active'|'floodwait'|'dead'
  premium       BOOLEAN DEFAULT false,
  source_count  INT DEFAULT 0,             -- сколько источников назначено (для балансировки)
  last_seen_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- ИСТОЧНИКИ
CREATE TABLE sources (
  id            BIGSERIAL PRIMARY KEY,
  tg_id         BIGINT UNIQUE,              -- id канала в TG (без -100)
  access_hash   BIGINT,
  username      TEXT,                       -- без @, NULL для приватных
  title         TEXT NOT NULL,
  kind          TEXT NOT NULL,              -- 'tg' | 'rss'
  rss_url       TEXT,                       -- для kind='rss'
  scope         TEXT NOT NULL DEFAULT 'pool', -- 'pool' | 'client'
  account_id    BIGINT REFERENCES tg_accounts(id), -- КАКОЙ аккаунт читает (можно менять без кода)
  backup_account_id BIGINT REFERENCES tg_accounts(id), -- дубль для критичных источников
  read_mode     TEXT NOT NULL DEFAULT 'subscribe', -- 'subscribe' | 'poll'
  priority      SMALLINT DEFAULT 3,        -- 1..5, при падении аккаунта приоритетные — на резерв первыми
  topics_hint   TEXT[],                     -- ручная подсказка тем (НЕ определяет архитектуру)
  status        TEXT NOT NULL DEFAULT 'active', -- 'active'|'silent'|'dead'|'checking'|'rejected'
  subscribers   INT,
  last_post_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);
-- Аккаунт читает НАБОР источников; тема вешается на пост после получения, не на аккаунт.
-- Источник переносится между аккаунтами сменой account_id (без правки кода).
-- При падении аккаунта: его источники с высоким priority → backup/reserve автоматически.

-- СЫРЫЕ ПОСТЫ (всё, без фильтрации)
CREATE TABLE posts (
  id            BIGSERIAL PRIMARY KEY,
  source_id     BIGINT REFERENCES sources(id),
  tg_message_id BIGINT,                     -- id сообщения в канале
  grouped_id    BIGINT,                     -- альбом
  text          TEXT,
  entities      JSONB,                      -- telegram entities (форматирование)
  media         JSONB,                      -- [{kind,r2_key,thumb_key,w,h,dur,blurhash}]
  views         INT,
  forwards      INT,
  posted_at     TIMESTAMPTZ NOT NULL,
  fetched_at    TIMESTAMPTZ DEFAULT now(),
  -- статус фильтрации: НИЧЕГО не удаляем, помечаем причину
  status        TEXT NOT NULL DEFAULT 'new', -- 'new'|'filtered'|'labeled'
  filter_reason TEXT,                       -- 'referral_ad'|'stopword'|'exact_dup'|'tech_noise'|NULL
  filter_version TEXT,                      -- 'rules_v3' — чтобы переприменить фильтр при обновлении
  raw           JSONB,                      -- полный сырой объект на всякий
  UNIQUE(source_id, tg_message_id)
);
CREATE INDEX ON posts (posted_at DESC);
CREATE INDEX ON posts (grouped_id) WHERE grouped_id IS NOT NULL;
CREATE INDEX ON posts (status);
-- Отфильтрованный пост сохраняется с причиной → можно проверить ошибку фильтра,
-- восстановить новость, переприменить новую версию правил.

-- РАЗМЕТКА (1:1 к posts, отдельно — чтобы переразмечать не трогая сырьё)
CREATE TABLE post_labels (
  post_id       BIGINT PRIMARY KEY REFERENCES posts(id),
  topics        TEXT[],                     -- мультилейбл
  language      TEXT,
  is_ad         BOOLEAN,
  importance    SMALLINT,                   -- 1..5
  embedding     vector(1024),               -- для дедупа
  model         TEXT,                       -- какой моделью размечено
  labeled_at    TIMESTAMPTZ DEFAULT now(),
  corrected     BOOLEAN DEFAULT false       -- поправлено оператором
);
CREATE INDEX ON post_labels USING ivfflat (embedding vector_cosine_ops);

-- СОБЫТИЯ (склеенные дубли)
CREATE TABLE events (
  id            BIGSERIAL PRIMARY KEY,
  title         TEXT,
  primary_post  BIGINT REFERENCES posts(id), -- лучший/первый пост
  topics        TEXT[],
  importance    SMALLINT,
  first_post_at TIMESTAMPTZ,               -- время самого раннего
  updated_at    TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE event_posts (                  -- какие посты в событии
  event_id      BIGINT REFERENCES events(id),
  post_id       BIGINT REFERENCES posts(id),
  PRIMARY KEY(event_id, post_id)
);

-- КЛИЕНТЫ / АККАУНТЫ
CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  tg_user_id    BIGINT UNIQUE,
  name          TEXT,
  role          TEXT DEFAULT 'client',      -- 'client'|'admin'
  blocked       BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- ПОДПИСКИ / ТАРИФЫ (сущности в MVP сразу, автооплата — позже)
CREATE TABLE subscriptions (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  plan          TEXT NOT NULL DEFAULT 'start', -- 'start'|'pro'|'editorial'|'internal'
  status        TEXT NOT NULL DEFAULT 'trial', -- 'trial'|'active'|'expired'|'blocked'
  trial_ends_at TIMESTAMPTZ,
  ends_at       TIMESTAMPTZ,               -- после даты — функции блокируются
  limits        JSONB,                     -- {routes:N, my_sources:N, groups:N} — лимиты тарифа
  granted_by    BIGINT REFERENCES users(id), -- админ может назначить подписку вручную
  created_at    TIMESTAMPTZ DEFAULT now()
);
-- Проверка лимитов и срока — при создании маршрута/источника и в middleware доставки.

-- ВАШИ ИЗДАНИЯ (каналы, которые обслуживает AI-редактор; на старте 2–3)
CREATE TABLE editions (
  id            BIGSERIAL PRIMARY KEY,
  title         TEXT NOT NULL,             -- «Мир за минуту»
  dest_chat_id  BIGINT NOT NULL,           -- куда публикует редактор
  style_prompt  TEXT,                      -- профиль стиля (голос канала)
  style_samples JSONB,                     -- примеры лучших постов (few-shot стиля)
  topics        TEXT[],                    -- что для этого издания «интересно»
  owner_id      BIGINT REFERENCES users(id),
  active        BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- МАРШРУТЫ ДОСТАВКИ
CREATE TABLE routes (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  dest_kind     TEXT,                       -- 'channel'|'group'|'dm'
  dest_chat_id  BIGINT,
  dest_title    TEXT,
  topics        TEXT[],
  filters       JSONB,                      -- {hide_ads,merge_duplicates,min_importance,languages,keywords,sources_whitelist}
  format        TEXT,                       -- 'original'|'card'|'digest'
  digest_cfg    JSONB,
  enabled       BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- ЛОГ ДОСТАВКИ (дедуп доставки + статистика + анти-повтор)
CREATE TABLE deliveries (
  id            BIGSERIAL PRIMARY KEY,
  route_id      BIGINT REFERENCES routes(id),
  event_id      BIGINT REFERENCES events(id),
  post_id       BIGINT REFERENCES posts(id),
  delivered_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE(route_id, event_id)               -- одно событие в маршрут — один раз
);

-- КОНТРОЛЬ КАЧЕСТВА РАЗМЕТКИ (ручная выборка оператора)
CREATE TABLE quality_checks (
  id            BIGSERIAL PRIMARY KEY,
  post_id       BIGINT REFERENCES posts(id),
  checked_by    BIGINT REFERENCES users(id),
  ai_topics     TEXT[], correct_topics TEXT[],
  ai_is_ad      BOOLEAN, correct_is_ad BOOLEAN,
  checked_at    TIMESTAMPTZ DEFAULT now()
);

-- МЕТРИКИ ДНЯ (для пульта оператора)
CREATE TABLE daily_metrics (
  day               DATE PRIMARY KEY,
  posts_received    INT DEFAULT 0,
  filtered_out      INT DEFAULT 0,
  labeled           INT DEFAULT 0,
  ads_detected      INT DEFAULT 0,
  events_created    INT DEFAULT 0,
  duplicates_merged INT DEFAULT 0,
  delivered         INT DEFAULT 0,
  ai_cost_usd       NUMERIC(8,3) DEFAULT 0
);

-- ЖУРНАЛ АДМИН-ДЕЙСТВИЙ (аудит-лог)
CREATE TABLE admin_log (
  id            BIGSERIAL PRIMARY KEY,
  actor_id      BIGINT REFERENCES users(id),
  action        TEXT NOT NULL,             -- 'grant_subscription'|'block_user'|'merge_events'|...
  target        JSONB,                     -- на кого/что подействовали
  at            TIMESTAMPTZ DEFAULT now()
);

-- РЕШЕНИЯ РЕДАКТОРА (память вкуса, привязаны к изданию)
CREATE TABLE editor_decisions (
  id            BIGSERIAL PRIMARY KEY,
  edition_id    BIGINT REFERENCES editions(id),
  event_id      BIGINT REFERENCES events(id),
  decision      TEXT,                       -- 'publish'|'rewrite'|'skip'
  ai_draft      TEXT,                       -- что предложил AI
  final_text    TEXT,                       -- что реально опубликовали (после правок)
  final_media   JSONB,                      -- какое медиа выбрали/заменили
  scheduled_at  TIMESTAMPTZ,                -- отложенная публикация
  decided_by    BIGINT REFERENCES users(id),
  decided_at    TIMESTAMPTZ DEFAULT now()
);
```

---

## 3. Контракты между сервисами

Сервисы не вызывают друг друга напрямую — общаются через **БД + очередь**.

**Очереди (BullMQ):**
- `posts.new` — collector кладёт `{post_id}` после записи сырого поста.
- `labels.done` — tagger кладёт `{post_id}` после разметки → триггерит deduper.
- `events.ready` — deduper кладёт `{event_id}` (новое/обновлённое) → триггерит router и editor-agent.
- `delivery.send` — router кладёт задание доставки `{route_id, event_id, post_id, format}`.

**Правило идемпотентности:** каждый воркер проверяет, не сделана ли работа
(есть ли label у post_id, есть ли delivery по паре route+event) — повтор задания безопасен.

**Web-API контракт** (REST + WS) — полностью в `web-platform-spec.md` раздел 6.
Сущности Event/Route/Source/Me там же — БД-таблицы выше маппятся на них 1:1.

---

## 4. МОДУЛЬ: Коллекторы

### 4.0 Мультиаккаунт (архитектура сбора)
- **4 активных аккаунта-сборщика** (по 200–300 источников) + **1 резервный** (холодный).
- Аккаунт = **набор назначенных источников** (`sources.account_id`), НЕ тема. Тематические
  группы можно использовать как удобный старт распределения, но система не считает аккаунт
  «спортивным» — тема вешается на пост после получения.
- Балансировка по нагрузке/FloodWait/priority; критичные источники дублируются на 2 аккаунтах
  (`backup_account_id`).
- **Failover:** аккаунт упал (`tg_accounts.status='dead'`) → его источники с высоким `priority`
  автоматически переназначаются на резерв; в админке видно, какой аккаунт читает каждый источник,
  источник переносится сменой `account_id` без правки кода.
- Каждый collector-процесс работает от своего аккаунта, читает только назначенные ему источники.

### 4.1 tg-collector (Python/Telethon) — есть частично
- Основа — текущий `userbot.py`, размноженный на аккаунты. Слушает `events.NewMessage`
  по назначенным источникам.
- Для каждого поста: собрать text + **entities** + media + views/forwards + grouped_id.
- **Скачать медиа** → загрузить в R2 → сохранить ключи. Альбомы: буфер по grouped_id (0.5с).
- Записать в `posts` (UPSERT по source_id+tg_message_id) → положить `{post_id}` в `posts.new`.
- Запись в БД **не блокирует** и **не ломает** существующую пересылку (try/catch, пересылка первична).
- **Детектор пропусков:** если tg_message_id прыгнул (1001→1004), дозапросить 1002–1003.
- Готово: новый пост из ТГ появляется в `posts` с медиа в R2 за ≤3 сек, entities сохранены.

### 4.2 tg-poller (Python) — новый
- Читает публичные каналы **без подписки** (по username, `get_messages`).
- Для `sources.read_mode='poll'`: цикл каждые 30–60 с, забирает новое с последнего `tg_message_id`.
- Та же запись в `posts` + `posts.new`.
- Готово: клиентский публичный канал читается без вступления, посты попадают в базу.

### 4.3 rss-collector (Node) — адаптация существующего
- Парсит `sources.rss_url` (kind='rss') по интервалу. Дедуп по ссылке/хэшу.
- Тот же формат записи в `posts` (media — по возможности, из og:image/enclosure).
- Готово: RSS-новости в той же таблице posts, неотличимы по формату от ТГ.

---

## 5. МОДУЛЬ: AI-разметка (tagger)

- Слушает `posts.new`. **Пре-фильтр ДО AI** (бесплатно). Отфильтрованное **НЕ удаляем** —
  ставим `posts.status='filtered'` + `filter_reason` + `filter_version` (можно проверить
  ошибку фильтра, восстановить новость, переприменить новую версию правил):
  - реферальная/явная реклама, стоп-слова, рефссылки → `filter_reason='referral_ad'|'stopword'`;
  - технический мусор → `'tech_noise'`;
  - точный повтор (хэш) недавнего поста → `'exact_dup'`;
  - пост из источника вне активных маршрутов → отложить (настраиваемо).
  - Сильные существующие фильтры = первый дешёвый слой; AI подключается там, где правила не справляются.
- Оставшееся → провайдер (раздел 6): промпт возвращает строгий JSON
  `{topics:[...], language, is_ad, importance}`.
- Посчитать **embedding** (провайдер embeddings) → записать в `post_labels`.
- Положить `{post_id}` в `labels.done`.
- **Батч:** несрочные посты копить и слать пачкой (Batch API, −50%). Срочные (важность-эвристика
  по источнику) — сразу.
- Готово: 95%+ постов размечены за ≤5 мин; JSON всегда валиден (ретрай при кривом ответе);
  переключение провайдера — через .env без правки кода.

**Промпт разметки (шаблон, кэшируемая часть = системная):**
```
SYSTEM (cached): Ты классификатор новостей. Верни СТРОГО JSON без пояснений:
{"topics": string[], "language": "ru|uk|en|other", "is_ad": bool, "importance": 1-5}
Темы (мультилейбл): war, crypto, finance, world, politics, tech, sport, esport, incidents, other.
importance: 5=срочная/масштабная, 1=проходная. is_ad: скрытая/нативная реклама тоже true.
USER: <текст поста + [есть N фото/видео]>
```

---

## 6. Провайдеры AI (конфиг-переключаемые)

`.env`:
```
AI_TAGGER_PROVIDER=gemini-flash-lite   # | gpt-nano | claude-haiku
AI_EMBED_PROVIDER=voyage-3-lite        # | openai-3-small
AI_EDITOR_PROVIDER=claude-sonnet
BATCH_MODE=true
```
- Единый интерфейс `AIProvider { tag(text): Labels; embed(text): number[]; complete(prompt): string }`.
- Реализации за интерфейсом; смена провайдера = смена env, ноль правок вызывающего кода.
- Ретраи с backoff, таймауты, учёт стоимости (лог токенов → метрики пульта).

---

## 7. МОДУЛЬ: Дедупликация (deduper)

- Слушает `labels.done`. Берёт embedding поста.
- Ищет в `post_labels` похожие (pgvector cosine) среди постов **за окно 2–4 ч**
  с **пересечением topics** и similarity > порога (старт: 0.86, вынести в конфиг).
- Если нашёл событие → добавить в `event_posts`, обновить `events.updated_at`, счётчик источников;
  `first_post_at` = min. Если нет → создать `event` (primary_post = этот).
- Положить `{event_id}` в `events.ready`.
- **Консервативно:** сомнение → новое событие, не склейка. Порог, окно — в конфиге.
- (Опц., этап 2) LLM-судья для пограничных пар (0.80–0.86): дешёвая модель «одно событие? да/нет».
- Готово: одно реальное событие из N каналов = один `event`; ложные склейки < заданного %
  на ручной выборке; «первым сообщил» корректен.

---

## 8. МОДУЛЬ: Доставка (router + delivery)

- router слушает `events.ready`. Для каждого активного `route`:
  - проверить фильтры (topics ∩, min_importance, hide_ads, languages, keywords, whitelist);
  - проверить `deliveries` — событие уже слали в этот маршрут? (UNIQUE route+event);
  - если `merge_duplicates=false` — слать каждый пост-дубль (по post_id), иначе одно событие;
  - положить в `delivery.send` с нужным `format`.
- delivery-воркер шлёт в Telegram по формату:
  - `original` — переслать/скопировать пост как есть (текст+entities+media);
  - `card` — собрать карточку (заголовок, метки, «⧉ N источников», ссылка);
  - `digest` — накапливать, слать по расписанию `digest_cfg` (топ за период).
- FloodWait-обработка, очередь на аккаунт-отправитель, ретраи.
- Записать в `deliveries`.
- Готово: клиент получает отфильтрованную ленту в своём формате; повторов нет;
  переключатель «склеивать/все» работает.

---

## 9. МОДУЛЬ: AI-редактор (editor-agent + editor-bot)

- Обслуживает **ваши издания** (`editions`, на старте **2–3 канала**), каждое со своим
  профилем стиля. Клиентам не продаётся в MVP (сущности заложены — включим позже).
- editor-agent слушает `events.ready`, для каждого активного `edition` фильтрует «интересное»
  (критерии = `editions.topics` + few-shot из `editor_decisions` где decision=publish
  для этого издания + `editions.style_samples`).
- Для кандидата: сгенерировать черновик в стиле издания (провайдер editor, Sonnet;
  `editions.style_prompt` + примеры).
- editor-bot шлёт в редакционную очередь (админ-канал): карточка + черновик + кнопки ✅/✏️/❌.
- ✅ → публикация в `editions.dest_chat_id`; ✏️ → открыть студию (веб); ❌ → skip.
- Любое решение → `editor_decisions` (привязано к изданию, подмешивается в отбор = память вкуса).
- **Для MVP память простая:** сохраняем решения + периодически лучшие примеры добавляем
  в `editions.style_samples`. Сложная автономная «память вкуса» — не нужна на старте.
- **Студия «Редактировать»** (веб, см. `web-platform-spec.md` 4.6): ручной рерайт любого
  события, AI-варианты заголовка/текста, замена медиа, публикация в канал/группу/ЛС.
- Готово: кандидаты приходят с черновиком; approve публикует; решения влияют на следующий отбор.

---

## 10. МОДУЛЬ: Web + Mini App

Полностью описан в **`web-platform-spec.md`**. Ключевое для сборки ядра:
- Фронт разрабатывается **mock-first** (MSW) параллельно ядру.
- web-api (Node) реализует контракт из `web-platform-spec.md` раздел 6 поверх БД выше.
- Real-time: WS публикует `event.new`/`event.updated` из очереди `events.ready`.
- Пульт оператора `/ops` читает метрики (раздел 11).

---

## 11. МОДУЛЬ: Админ-панель, наблюдаемость, пульт оператора

Единая админка команды (роль admin). Разделы:

**Система (пульт оператора):**
- **Метрики:** обработано постов, отсеяно рекламы (по filter_reason), склеено событий,
  доставлено, расход AI ($ по логу токенов), длина очередей, аптайм воркеров.
- **Состояние конвейера:** статусы всех сервисов, heartbeat'ы, ошибки доставки.
- **Здоровье источников:** `last_post_at` старше нормы → 'silent'; ошибки доступа → 'dead'.
- **Контроль качества разметки:** случайные 50 постов/нед → оператор подтверждает/правит
  topics → `post_labels.corrected=true` → правки в few-shot tagger'а.
- **Merge / Unmerge событий:** ручная склейка/расклейка спорных случаев.
- **Алерты в служебный ТГ-чат:** воркер упал, очередь растёт, аккаунт отвалился, канал молчит.

**Аккаунты-сборщики:**
- Список `tg_accounts` со статусом, нагрузкой (`source_count`), FloodWait.
- Видно, какой аккаунт читает каждый источник; перенос источника между аккаунтами
  (смена `account_id`) кнопкой; ручной запуск failover на резерв.

**Источники:**
- Каталог пула + клиентские; распределение по аккаунтам; priority; статусы; блокировка источника.

**Пользователи и подписки:**
- Список пользователей, их маршруты, подключённые группы/каналы.
- Тариф и статус подписки; **ручное назначение подписки** (`subscriptions.granted_by`),
  trial, дата окончания, лимиты; блокировка пользователя.

**Журнал действий:** все административные операции (кто, что, когда) — аудит-лог.

- Готово: команда управляет всей системой из одной админки; оператор видит состояние
  и получает алерты пушем; подписки и лимиты применяются.

---

## 12. Порядок сборки

Строить по зависимостям. Каждый шаг заканчивается рабочим, проверяемым результатом.

1. **Инфра:** docker-compose (postgres+pgvector, redis, приложения), .env, миграции (раздел 2).
2. **tg-collector → БД + R2** (модуль 4.1). Проверка: посты с медиа и entities в базе,
   пересылка не сломана.
3. **rss-collector** (4.3) — RSS в ту же таблицу.
4. **tagger + провайдеры** (5, 6) — разметка появляется в post_labels, JSON валиден.
5. **deduper** (7) — события склеиваются, «первым сообщил» верен.
6. **web-api + WS** (10) — контракт отдаёт ленту/события из БД; фронт съезжает с MSW на него.
7. **router + delivery** (8) — маршруты доставляют в ТГ, повторов нет.
8. **editor-agent + editor-bot + студия** (9).
9. **tg-poller** (4.2) — клиентские публичные каналы без подписки.
10. **пульт + алерты + контроль качества** (11).
11. **фронт-экраны** по `web-platform-spec.md` (параллельно с 4 через MSW).

## 13. Definition of Done (система)

- [ ] Пост из ТГ/RSS: сырьё в `posts` (медиа в R2, entities), метки в `post_labels`,
      склеен в `event` — весь путь ≤ 5 мин.
- [ ] Маршрут доставляет отфильтрованную ленту в ТГ; событие в маршрут — ровно один раз;
      форматы original/card/digest работают; переключатель дублей работает.
- [ ] AI-редактор: кандидат с черновиком → approve → публикация; решение влияет на отбор.
- [ ] Web + Mini App работают на живом API (не MSW); лента live через WS.
- [ ] Пульт: статусы, расход AI, здоровье источников, контроль качества; алерты в ТГ.
- [ ] Провайдер AI на любой задаче меняется через .env без правок кода.
- [ ] Падение любого воркера/базы не роняет сбор и текущую пересылку.
- [ ] Юзербот-аккаунты: ≥2, failover, детектор пропусков, восстановление задокументировано.

---

*Строить модулями по разделу 12. Контракты (раздел 3) фиксированы — менять только осознанно,
синхронно в БД, очередях и `web-platform-spec.md`. Продуктовый контекст и риски —
в `internal-brief-for-audit.md`.*
