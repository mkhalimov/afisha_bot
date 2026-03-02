import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_CHAT_ID
from db import (
    count_user_pending_drafts,
    delete_draft,
    get_draft,
    get_user_drafts,
    reset_draft_to_edit,
    set_admin_message_id,
    set_draft_image,
    set_draft_pending,
    upsert_draft,
)
from formatting import format_preview, format_preview_safe, parse_date_ru, parse_time_hhmm
from keyboards import (
    kb_admin_moderation,
    kb_cancel,
    kb_categories,
    kb_confirm_delete,
    kb_edit_rejected,
    kb_my_drafts,
    kb_send_to_moderation,
    kb_start,
)
from states import Form

logger = logging.getLogger(__name__)

user_router = Router()

STATUS_EMOJI = {
    "draft": "📝",
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
    "published": "📢",
}


@user_router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет. Я соберу анонс по шагам.\nНажми «Создать анонс».",
        reply_markup=kb_start(),
    )


@user_router.callback_query(F.data == "new")
async def new_announcement(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Form.title)
    await cb.message.answer("Название мероприятия? (пример: Интерстеллар)", reply_markup=kb_cancel())
    await cb.answer()


@user_router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Ок, отменил.", reply_markup=kb_start())
    await cb.answer()


# ---- My drafts ----

@user_router.callback_query(F.data == "my_drafts")
async def my_drafts(cb: CallbackQuery):
    drafts = await get_user_drafts(cb.from_user.id)
    if not drafts:
        await cb.message.answer("У тебя пока нет анонсов.", reply_markup=kb_start())
        await cb.answer()
        return

    lines = ["Твои анонсы:\n"]
    for d in drafts[:10]:
        emoji = STATUS_EMOJI.get(d["status"], "❓")
        title = d.get("title") or "(без названия)"
        date_str = ""
        if d.get("event_date"):
            try:
                date_str = " — " + datetime.strptime(d["event_date"], "%Y-%m-%d").strftime("%d.%m.%Y")
            except ValueError:
                pass
        lines.append(f"{emoji} #{d['id']} {title}{date_str}")

    keyboard = kb_my_drafts(drafts[:10])
    await cb.message.answer("\n".join(lines), reply_markup=keyboard)
    await cb.answer()


# ---- Drop draft (user) ----

@user_router.callback_query(F.data.startswith("draft_drop:"))
async def draft_drop_request(cb: CallbackQuery):
    try:
        draft_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Анонс не найден.", show_alert=True)
        return
    if draft["creator_user_id"] != cb.from_user.id:
        await cb.answer("Это не ваш анонс.", show_alert=True)
        return
    if draft["status"] not in ("draft", "pending", "rejected"):
        await cb.answer("Этот анонс нельзя удалить.", show_alert=True)
        return

    title = draft.get("title") or f"#{draft_id}"
    await cb.message.answer(
        f"Удалить анонс #{draft_id} «{title}»?\nЭто нельзя отменить.",
        reply_markup=kb_confirm_delete(draft_id),
    )
    await cb.answer()


@user_router.callback_query(F.data.startswith("draft_drop_ok:"))
async def draft_drop_confirm(cb: CallbackQuery, state: FSMContext):
    try:
        draft_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Анонс не найден.", show_alert=True)
        return
    if draft["creator_user_id"] != cb.from_user.id:
        await cb.answer("Это не ваш анонс.", show_alert=True)
        return
    if draft["status"] not in ("draft", "pending", "rejected"):
        await cb.answer("Этот анонс нельзя удалить.", show_alert=True)
        return

    await delete_draft(draft_id)
    # Discard FSM data if user was editing this draft
    fsm_data = await state.get_data()
    if fsm_data.get("draft_id") == draft_id:
        await state.clear()

    await cb.message.edit_text(f"Анонс #{draft_id} удалён.")
    await cb.answer()
    logger.info("Draft deleted by user: id=%d user_id=%d", draft_id, cb.from_user.id)


# ---- FSM form steps ----

@user_router.message(Form.title)
async def on_title(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 120:
        await message.answer("Название должно быть 2–120 символов. Попробуй ещё раз.")
        return
    await state.update_data(title=text)
    await state.set_state(Form.category)
    await message.answer("Выбери тип/рубрику:", reply_markup=kb_categories())


@user_router.callback_query(Form.category, F.data.startswith("cat:"))
async def on_category(cb: CallbackQuery, state: FSMContext):
    category = cb.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(Form.event_date)
    await cb.message.answer("Дата? Формат: ДД.ММ.ГГГГ (пример: 15.11.2025)", reply_markup=kb_cancel())
    await cb.answer()


@user_router.message(Form.event_date)
async def on_event_date(message: Message, state: FSMContext):
    d = parse_date_ru(message.text or "")
    if not d:
        await message.answer("Не похоже на дату. Формат: ДД.ММ.ГГГГ (пример: 15.11.2025)")
        return
    await state.update_data(event_date=d.isoformat())
    await state.set_state(Form.time_start)
    await message.answer("Время начала? Формат: ЧЧ:ММ (пример: 19:00)", reply_markup=kb_cancel())


@user_router.message(Form.time_start)
async def on_time_start(message: Message, state: FSMContext):
    t = parse_time_hhmm(message.text or "")
    if not t:
        await message.answer("Не похоже на время. Формат: ЧЧ:ММ (пример: 19:00)")
        return
    await state.update_data(time_start=t.strftime("%H:%M"))
    await state.set_state(Form.time_end)
    await message.answer("Время окончания? Формат: ЧЧ:ММ (пример: 00:00)", reply_markup=kb_cancel())


@user_router.message(Form.time_end)
async def on_time_end(message: Message, state: FSMContext):
    t = parse_time_hhmm(message.text or "")
    if not t:
        await message.answer("Не похоже на время. Формат: ЧЧ:ММ (пример: 00:00)")
        return
    await state.update_data(time_end=t.strftime("%H:%M"))
    await state.set_state(Form.location)
    await message.answer("Локация? (пример: досуговая / адрес / ссылка)", reply_markup=kb_cancel())


@user_router.message(Form.location)
async def on_location(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 120:
        await message.answer("Локация должна быть 2–120 символов. Попробуй ещё раз.")
        return
    await state.update_data(location=text)
    await state.set_state(Form.description)
    await message.answer("Короткое описание (1–800 символов). Можно в несколько строк.", reply_markup=kb_cancel())


@user_router.message(Form.description)
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


@user_router.message(Form.organizer)
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
    logger.info("Draft saved: id=%d user_id=%d", draft_id, message.from_user.id)


@user_router.message(Form.image, F.photo)
async def on_image(message: Message, state: FSMContext):
    data = await state.get_data()
    draft_id = data.get("draft_id")
    if not draft_id:
        await message.answer("Не нашёл draft_id, начни заново.", reply_markup=kb_start())
        await state.clear()
        return

    photo = message.photo[-1]

    if photo.file_size and photo.file_size > 5_000_000:
        await message.answer("Файл слишком большой (>5 МБ). Пришли изображение меньшего размера.")
        return

    image_file_id = photo.file_id
    await set_draft_image(draft_id, image_file_id)

    data["image_file_id"] = image_file_id
    preview_text = format_preview_safe(data)

    await message.answer_photo(
        photo=image_file_id,
        caption=f"Предпросмотр (как будет выглядеть пост):\n\n{preview_text}"
    )
    await message.answer("Если всё ок — отправляй на модерацию.", reply_markup=kb_send_to_moderation())


@user_router.message(Form.image)
async def on_image_wrong(message: Message):
    await message.answer("Нужна именно картинка (фото). Пришли постер одним фото.")


@user_router.callback_query(F.data == "send_to_mod")
async def send_to_moderation(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    draft_id = data.get("draft_id")
    if not draft_id:
        await cb.answer("Нет черновика.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft or not draft.get("image_file_id"):
        await cb.answer("Нужна картинка.", show_alert=True)
        return

    pending_count = await count_user_pending_drafts(cb.from_user.id)
    if pending_count >= 1:
        await cb.answer(
            "У вас уже есть анонс на модерации. Дождитесь решения.",
            show_alert=True
        )
        return

    await set_draft_pending(draft_id)

    caption = format_preview_safe(draft)
    mod_caption = f"Новый анонс на модерацию (draft_id={draft_id})\n\n{caption}"
    if len(mod_caption) > 1024:
        mod_caption = mod_caption[:1023] + "…"

    admin_msg = await bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=draft["image_file_id"],
        caption=mod_caption,
        reply_markup=kb_admin_moderation(draft_id)
    )
    await set_admin_message_id(draft_id, admin_msg.message_id)

    await cb.message.answer("Отправлено на модерацию ✅", reply_markup=kb_start())
    await cb.answer()
    await state.set_state(Form.done)
    logger.info("Draft submitted to moderation: id=%d user_id=%d", draft_id, cb.from_user.id)


# ---- Edit rejected draft ----

@user_router.callback_query(F.data.startswith("edit_draft:"))
async def edit_rejected_draft(cb: CallbackQuery, state: FSMContext):
    try:
        draft_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Черновик не найден.", show_alert=True)
        return
    if draft["creator_user_id"] != cb.from_user.id:
        await cb.answer("Это не ваш анонс.", show_alert=True)
        return
    if draft["status"] != "rejected":
        await cb.answer("Этот анонс нельзя редактировать.", show_alert=True)
        return

    await reset_draft_to_edit(draft_id)

    await state.set_data({
        "draft_id": draft_id,
        "title": draft.get("title"),
        "category": draft.get("category"),
        "event_date": draft.get("event_date"),
        "time_start": draft.get("time_start"),
        "time_end": draft.get("time_end"),
        "location": draft.get("location"),
        "description": draft.get("description"),
        "organizer": draft.get("organizer"),
    })
    await state.set_state(Form.title)

    current_title = draft.get("title") or ""
    await cb.message.answer(
        f"Редактируем анонс #{draft_id}.\n"
        f"Текущее название: «{current_title}»\n\n"
        f"Введи новое название или отправь его же снова:",
        reply_markup=kb_cancel()
    )
    await cb.answer()
    logger.info("User editing rejected draft: id=%d user_id=%d", draft_id, cb.from_user.id)
