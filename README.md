# Telegram Announcement Bot

Бот для создания анонсов мероприятий с модерацией через администраторов.

## Быстрый старт

### 1. Клонировать репозиторий и перейти в папку

```bash
git clone <repo-url>
cd bot
```

### 2. Создать файл `.env`

```bash
cp .env.example .env
```

Заполни `.env` (см. раздел ниже).

### 3. Создать папку для базы данных

```bash
mkdir -p data
```

### 4. Запустить через Docker Compose

```bash
docker compose up --build
```

Или в фоне:

```bash
docker compose up --build -d
```

Посмотреть логи:

```bash
docker compose logs -f
```

---

## Запуск без Docker

```bash
pip install -r requirements.txt
python main.py
```

---

## Параметры `.env`

### `BOT_TOKEN`

Токен Telegram-бота.

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`
3. Задай имя и username бота
4. BotFather пришлёт токен вида `7123456789:AAF...`

```
BOT_TOKEN=7123456789:AAF_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

### `CHANNEL_ID`

ID канала, куда бот будет публиковать одобренные анонсы.

**Способ 1 — username канала** (если канал публичный):
```
CHANNEL_ID=@mychannel
```

**Способ 2 — числовой ID** (работает для публичных и приватных каналов):
1. Перешли любое сообщение из канала боту [@userinfobot](https://t.me/userinfobot)
2. Он покажет ID вида `-1001234567890`

Или добавь [@getidsbot](https://t.me/getidsbot) в канал, он напишет ID.

```
CHANNEL_ID=-1001234567890
```

> Бот должен быть **администратором** канала с правом публикации сообщений.

---

### `ADMIN_IDS`

Список Telegram user ID людей, которые могут одобрять/отклонять анонсы.
Несколько ID разделяются запятой.

**Как узнать свой user ID:**
1. Напиши боту [@userinfobot](https://t.me/userinfobot)
2. Он ответит твоим ID вида `123456789`

```
ADMIN_IDS=123456789,987654321
```

> Это **личные** ID пользователей (положительные числа), а не ID чата/группы.

---

### `ADMIN_CHAT_ID`

ID группы/чата, куда бот отправляет анонсы на модерацию (с кнопками Approve/Reject).

**Как узнать ID группы:**
1. Добавь [@getidsbot](https://t.me/getidsbot) или [@userinfobot](https://t.me/userinfobot) в группу
2. Отправь любое сообщение — бот ответит ID группы вида `-1009876543210`

```
ADMIN_CHAT_ID=-1009876543210
```

> Бот должен быть участником этой группы и иметь возможность писать в неё.

---

### `DB_PATH`

Путь к файлу SQLite базы данных. При запуске через Docker значение по умолчанию подходит — база хранится в volume `./data/`.

```
DB_PATH=data/announcements.db
```

---

## Полный пример `.env`

```env
BOT_TOKEN=7123456789:AAF_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CHANNEL_ID=-1001234567890
ADMIN_IDS=123456789,987654321
ADMIN_CHAT_ID=-1009876543210
DB_PATH=data/announcements.db
```

---

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Начать создание анонса |
| `/my_drafts` | Посмотреть свои анонсы и их статусы |

### Статусы анонса

| Статус | Значение |
|--------|----------|
| 📝 draft | Черновик, не отправлен |
| ⏳ pending | На модерации |
| ✅ approved | Одобрен |
| ❌ rejected | Отклонён (можно редактировать) |
| 📢 published | Опубликован в канале |

---

## Структура проекта

```
bot/
├── main.py          # Точка входа
├── config.py        # Загрузка переменных окружения
├── db.py            # Работа с базой данных
├── states.py        # FSM-состояния
├── formatting.py    # Форматирование превью анонса
├── keyboards.py     # Inline-клавиатуры
├── middleware.py    # Rate-limiting (1 сообщение/сек)
├── handlers/
│   ├── user.py      # Пользовательские хэндлеры
│   └── admin.py     # Хэндлеры модерации
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
