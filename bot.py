import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, date, time
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "announcements.db")
BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_ID = os.getenv("CHANNEL_ID")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is required in .env")

try:
    CHANNEL_ID_VALUE = int(CHANNEL_ID)
except ValueError:
    CHANNEL_ID_VALUE = CHANNEL_ID  # например "@mychannel"

class AdminReject(StatesGroup):
    waiting_reason = State()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required in .env")

# ---------- DB ----------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS announcement_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator_user_id INTEGER NOT NULL,
  creator_username TEXT,
  title TEXT,
  category TEXT,
  event_date TEXT,        -- YYYY-MM-DD
  time_start TEXT,        -- HH:MM
  time_end TEXT,          -- HH:MM
  location TEXT,
  description TEXT,
  organizer TEXT,
  image_file_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',  -- draft/pending/approved/rejected
  admin_message_id INTEGER,              -- message id in admin chat
  reject_reason TEXT,
  channel_message_id INTEGER,
  published_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE_SQL)
        await db.commit()

async def upsert_draft(user_id: int, username: Optional[str], data: dict) -> int:
    """
    One draft per user for simplicity. If you want multiple drafts, add draft_id to FSM.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        # Check existing draft for user in 'draft' status
        cur = await db.execute(
            "SELECT id FROM announcement_drafts WHERE creator_user_id=? AND status='draft' ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cur.fetchone()
        if row:
            draft_id = row[0]
            await db.execute(
                """
                UPDATE announcement_drafts
                SET creator_username=?, title=?, category=?, event_date=?, time_start=?, time_end=?,
                    location=?, description=?, organizer=?, updated_at=?
                WHERE id=?
                """,
                (
                    username,
                    data.get("title"),
                    data.get("category"),
                    data.get("event_date"),
                    data.get("time_start"),
                    data.get("time_end"),
                    data.get("location"),
                    data.get("description"),
                    data.get("organizer"),
                    now,
                    draft_id,
                )
            )
        else:
            cur = await db.execute(
                """
                INSERT INTO announcement_drafts
                (creator_user_id, creator_username, title, category, event_date, time_start, time_end,
                 location, description, organizer, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    user_id, username,
                    data.get("title"),
                    data.get("category"),
                    data.get("event_date"),
                    data.get("time_start"),
                    data.get("time_end"),
                    data.get("location"),
                    data.get("description"),
                    data.get("organizer"),
                    now, now,
                )
            )
            draft_id = cur.lastrowid

        await db.commit()
        return draft_id

async def set_draft_image_and_pending(draft_id: int, image_file_id: str):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE announcement_drafts
            SET image_file_id=?, status='pending', updated_at=?
            WHERE id=?
            """,
            (image_file_id, now, draft_id)
        )
        await db.commit()

async def set_admin_message_id(draft_id: int, admin_message_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET admin_message_id=?, updated_at=? WHERE id=?",
            (admin_message_id, now, draft_id)
        )
        await db.commit()

async def get_draft(draft_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM announcement_drafts WHERE id=?", (draft_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def set_draft_approved(draft_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='approved', updated_at=? WHERE id=?",
            (now, draft_id)
        )
        await db.commit()

async def set_draft_rejected(draft_id: int, reason: str):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE announcement_drafts SET status='rejected', reject_reason=?, updated_at=? WHERE id=?",
            (reason, now, draft_id)
        )
        await db.commit()

async def set_draft_published(draft_id: int, channel_message_id: int):
    now = datetime.utcnow().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE announcement_drafts
            SET status='published', channel_message_id=?, published_at=?, updated_at=?
            WHERE id=?
            """,
            (channel_message_id, now, now, draft_id)
        )
        await db.commit()

# ---------- Parsing / Validation ----------
DATE_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{4})\s*$")
TIME_RE = re.compile(r"^\s*(\d{2}):(\d{2})\s*$")

def parse_date_ru(s: str) -> Optional[date]:
    m = DATE_RE.match(s)
    if not m:
        return None
    dd, mm, yyyy = map(int, m.groups())
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None

def parse_time_hhmm(s: str) -> Optional[time]:
    m = TIME_RE.match(s)
    if not m:
        return None
    hh, mi = map(int, m.groups())
    try:
        return time(hh, mi)
    except ValueError:
        return None

def format_preview(data: dict) -> str:
    # Под твой стиль "АФИША | ..." (можно потом точнее)
    lines = []
    if data.get("category"):
        lines.append(f"АФИША | {data['category']}")
    if data.get("title"):
        lines.append("")
        lines.append(data["title"])
    if data.get("event_date") and data.get("time_start") and data.get("time_end"):
        # показываем как в примере: "22:00 - 01:00, 15.11.2025"
        d = datetime.strptime(data["event_date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        lines.append("")
        lines.append(f"{data['time_start']} - {data['time_end']}, {d}")
    if data.get("location"):
        lines.append(data["location"])
    if data.get("description"):
        lines.append("")
        lines.append(data["description"])
    if data.get("organizer"):
        lines.append("")
        lines.append(f"Организатор: {data['organizer']}")
    return "\n".join(lines).strip()

# ---------- FSM ----------
class Form(StatesGroup):
    title = State()
    category = State()
    event_date = State()
    time_start = State()
    time_end = State()
    location = State()
    description = State()
    organizer = State()
    image = State()
    done = State()

CATEGORIES = [
    "ТРИЛИСТНИК",
    "D&D",
    "КИНО",
    "ЛЕКЦИЯ",
    "ИГРЫ",
    "ДРУГОЕ",
]

def kb_categories() -> InlineKeyboardMarkup:
    rows = []
    for c in CATEGORIES:
        rows.append([InlineKeyboardButton(text=c, callback_data=f"cat:{c}")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
    ])

def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать анонс", callback_data="new")]
    ])

def kb_send_to_moderation() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Отправить на модерацию", callback_data="send_to_mod")],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
    ])

def kb_admin_moderation(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"adm:approve:{draft_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm:reject:{draft_id}")
        ]
    ])

# ---------- Bot handlers ----------
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет. Я соберу анонс по шагам.\nНажми «Создать анонс».",
        reply_markup=kb_start(),
    )

@dp.callback_query(F.data == "new")
async def new_announcement(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Form.title)
    await cb.message.answer("Название мероприятия? (пример: Интерстеллар)", reply_markup=kb_cancel())
    await cb.answer()

@dp.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Ок, отменил. Если нужно — /start")
    await cb.answer()

@dp.message(Form.title)
async def on_title(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 120:
        await message.answer("Название должно быть 2–120 символов. Попробуй ещё раз.")
        return
    await state.update_data(title=text)
    await state.set_state(Form.category)
    await message.answer("Выбери тип/рубрику:", reply_markup=kb_categories())

@dp.callback_query(Form.category, F.data.startswith("cat:"))
async def on_category(cb: CallbackQuery, state: FSMContext):
    category = cb.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(Form.event_date)
    await cb.message.answer("Дата? Формат: ДД.ММ.ГГГГ (пример: 15.11.2025)", reply_markup=kb_cancel())
    await cb.answer()

@dp.message(Form.event_date)
async def on_event_date(message: Message, state: FSMContext):
    d = parse_date_ru(message.text or "")
    if not d:
        await message.answer("Не похоже на дату. Формат: ДД.ММ.ГГГГ (пример: 15.11.2025)")
        return
    await state.update_data(event_date=d.isoformat())
    await state.set_state(Form.time_start)
    await message.answer("Время начала? Формат: ЧЧ:ММ (пример: 19:00)", reply_markup=kb_cancel())

@dp.message(Form.time_start)
async def on_time_start(message: Message, state: FSMContext):
    t = parse_time_hhmm(message.text or "")
    if not t:
        await message.answer("Не похоже на время. Формат: ЧЧ:ММ (пример: 19:00)")
        return
    await state.update_data(time_start=t.strftime("%H:%M"))
    await state.set_state(Form.time_end)
    await message.answer("Время окончания? Формат: ЧЧ:ММ (пример: 00:00)", reply_markup=kb_cancel())

@dp.message(Form.time_end)
async def on_time_end(message: Message, state: FSMContext):
    t = parse_time_hhmm(message.text or "")
    if not t:
        await message.answer("Не похоже на время. Формат: ЧЧ:ММ (пример: 00:00)")
        return

    data = await state.get_data()
    t_start = datetime.strptime(data["time_start"], "%H:%M").time()
    # Конец может быть "на следующий день" (как 22:00-01:00). Поэтому строгую проверку не делаем.
    await state.update_data(time_end=t.strftime("%H:%M"))

    await state.set_state(Form.location)
    await message.answer("Локация? (пример: досуговая / адрес / ссылка)", reply_markup=kb_cancel())

@dp.message(Form.location)
async def on_location(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 120:
        await message.answer("Локация должна быть 2–120 символов. Попробуй ещё раз.")
        return
    await state.update_data(location=text)
    await state.set_state(Form.description)
    await message.answer("Короткое описание (1–800 символов). Можно в несколько строк.", reply_markup=kb_cancel())

@dp.message(Form.description)
async def on_description(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 1 or len(text) > 800:
        await message.answer("Описание должно быть 1–800 символов.")
        return
    await state.update_data(description=text)
    await state.set_state(Form.organizer)

    default_org = f"@{message.from_user.username}" if message.from_user and message.from_user.username else None
    if default_org:
        await state.update_data(organizer=default_org)
        await message.answer(
            f"Организатор? Сейчас стоит {default_org}\n"
            f"Если ок — отправь «ок». Если нужно другое — пришли текст (например @ник / ссылка / контакт).",
            reply_markup=kb_cancel(),
        )
    else:
        await message.answer("Организатор? (например: @ник / ссылка / контакт)", reply_markup=kb_cancel())

@dp.message(Form.organizer)
async def on_organizer(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.lower() == "ок":
        data = await state.get_data()
        if not data.get("organizer"):
            await message.answer("Организатор не задан. Пришли контакт (например @ник).")
            return
    else:
        if len(text) < 2 or len(text) > 120:
            await message.answer("Организатор должен быть 2–120 символов.")
            return
        await state.update_data(organizer=text)

    data = await state.get_data()

    # Save draft
    draft_id = await upsert_draft(
        user_id=message.from_user.id,
        username=message.from_user.username if message.from_user else None,
        data=data
    )

    preview = format_preview(data)
    
    await state.update_data(draft_id=draft_id)
    await state.set_state(Form.image)

    await message.answer(
        f"Черновик сохранён (id={draft_id}). Предпросмотр:\n\n{preview}\n\n"
        f"Теперь пришли картинку (постер/афишу) одним фото.",
        reply_markup=kb_cancel()
    )

@dp.message(Form.image, F.photo)
async def on_image(message: Message, state: FSMContext):
    data = await state.get_data()
    draft_id = data.get("draft_id")
    if not draft_id:
        await message.answer("Не нашёл draft_id, начни заново: /start")
        await state.clear()
        return

    # Берём самое большое фото
    photo = message.photo[-1]
    image_file_id = photo.file_id

    await set_draft_image_and_pending(draft_id, image_file_id)

    # Обновляем state и показываем превью пользователю
    data["image_file_id"] = image_file_id
    preview_text = format_preview(data)

    await message.answer_photo(
        photo=image_file_id,
        caption=f"Предпросмотр (как будет выглядеть пост):\n\n{preview_text}"
    )
    await message.answer(
        "Если всё ок — отправляй на модерацию.",
        reply_markup=kb_send_to_moderation()
    )

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
if not ADMIN_CHAT_ID:
    raise RuntimeError("ADMIN_CHAT_ID is required in .env")

@dp.callback_query(F.data == "send_to_mod")
async def send_to_moderation(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    draft_id = data.get("draft_id")
    if not draft_id:
        await cb.answer("Нет черновика. /start", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft or not draft.get("image_file_id"):
        await cb.answer("Нужна картинка.", show_alert=True)
        return

    caption = format_preview(draft)

    admin_msg = await bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=draft["image_file_id"],
        caption=f"Новый анонс на модерацию (draft_id={draft_id})\n\n{caption}",
        reply_markup=kb_admin_moderation(draft_id)
    )
    await set_admin_message_id(draft_id, admin_msg.message_id)

    await cb.message.answer("Отправил админу на модерацию ✅")
    await cb.answer()
    await state.set_state(Form.done)


@dp.message(Form.image)
async def on_image_wrong(message: Message):
    await message.answer("Нужна именно картинка (фото). Пришли постер одним фото.")

@dp.callback_query(F.data.startswith("adm:approve:"))
async def admin_approve(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != ADMIN_CHAT_ID:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    draft_id = int(cb.data.split(":")[2])
    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Черновик не найден.", show_alert=True)
        return
    if not draft.get("image_file_id"):
        await cb.answer("Нет картинки.", show_alert=True)
        return

    # Сформируем подпись поста (без "Новый анонс...")
    caption = format_preview(draft)

    # 1) Публикуем в канал
    try:
        ch_msg = await bot.send_photo(
            chat_id=CHANNEL_ID_VALUE,
            photo=draft["image_file_id"],
            caption=caption
        )
    except Exception as e:
        # Частая причина — бот не админ или нет прав постить
        await cb.answer("Не смог запостить в канал (права/ID канала).", show_alert=True)
        # полезно админу увидеть ошибку в чате
        await bot.send_message(ADMIN_CHAT_ID, f"Ошибка публикации draft_id={draft_id}: {e}")
        return

    # 2) Сохраняем статус
    await set_draft_published(draft_id, ch_msg.message_id)

    # 3) Уведомляем автора
    await bot.send_message(
        chat_id=draft["creator_user_id"],
        text=f"Твой анонс опубликован ✅ (id={draft_id})"
    )

    # 4) Помечаем админскую карточку
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.edit_caption((cb.message.caption or "") + f"\n\n✅ PUBLISHED (msg_id={ch_msg.message_id})")
    except Exception:
        pass

    await cb.answer("Опубликовано")

@dp.callback_query(F.data.startswith("adm:reject:"))
async def admin_reject_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_CHAT_ID:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    draft_id = int(cb.data.split(":")[2])
    await state.set_state(AdminReject.waiting_reason)
    await state.update_data(reject_draft_id=draft_id, reject_admin_msg_id=cb.message.message_id)
    await cb.message.answer(f"Ок. Пришли причину отклонения для draft_id={draft_id} (одним сообщением).")
    await cb.answer()

@dp.message(AdminReject.waiting_reason)
async def admin_reject_reason(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_CHAT_ID:
        return

    reason = (message.text or "").strip()
    if len(reason) < 2:
        await message.answer("Причина слишком короткая. Напиши нормально.")
        return

    data = await state.get_data()
    draft_id = int(data["reject_draft_id"])
    draft = await get_draft(draft_id)
    if not draft:
        await message.answer("Черновик не найден.")
        await state.clear()
        return

    await set_draft_rejected(draft_id, reason)

    await bot.send_message(
        chat_id=draft["creator_user_id"],
        text=f"Твой анонс (id={draft_id}) отклонён ❌\nПричина: {reason}\n\nИсправь и отправь заново (позже добавим кнопку «редактировать»)."
    )

    # можно пометить сообщение админа
    try:
        await bot.edit_message_caption(
            chat_id=ADMIN_CHAT_ID,
            message_id=int(data.get("reject_admin_msg_id")),
            caption=(await get_draft(draft_id) and f"{format_preview(draft)}\n\n❌ REJECTED: {reason}") or None
        )
    except Exception:
        pass

    await message.answer("Ок, отправил пользователю причину.")
    await state.clear()


# ---------- main ----------
async def main():
    await init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
