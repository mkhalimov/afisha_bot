import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_CHAT_ID, ADMIN_IDS, CHANNEL_ID
from db import delete_draft, get_draft, set_draft_published, set_draft_rejected
from formatting import format_preview_safe
from keyboards import kb_admin_confirm_delete, kb_edit_rejected, kb_start
from states import AdminReject

logger = logging.getLogger(__name__)

admin_router = Router()


@admin_router.callback_query(F.data.startswith("adm:approve:"))
async def admin_approve(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    try:
        draft_id = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Черновик не найден.", show_alert=True)
        return
    if not draft.get("image_file_id"):
        await cb.answer("Нет картинки.", show_alert=True)
        return

    caption = format_preview_safe(draft)

    try:
        ch_msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=draft["image_file_id"],
            caption=caption
        )
    except Exception as e:
        await cb.answer("Не смог запостить в канал (права/ID канала).", show_alert=True)
        await bot.send_message(ADMIN_CHAT_ID, f"Ошибка публикации draft_id={draft_id}: {e}")
        return

    await set_draft_published(draft_id, ch_msg.message_id)

    await bot.send_message(
        chat_id=draft["creator_user_id"],
        text=f"Твой анонс опубликован ✅ (id={draft_id})",
        reply_markup=kb_start(),
    )

    try:
        new_caption = ((cb.message.caption or "") + f"\n\n✅ ОПУБЛИКОВАНО (msg_id={ch_msg.message_id})")
        if len(new_caption) > 1024:
            new_caption = new_caption[:1023] + "…"
        await cb.message.edit_caption(new_caption, reply_markup=None)
    except Exception:
        pass

    await cb.answer("Опубликовано")
    logger.info("Draft approved and published: id=%d by admin=%d", draft_id, cb.from_user.id)


@admin_router.callback_query(F.data.startswith("adm:reject:"))
async def admin_reject_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    try:
        draft_id = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    await state.set_state(AdminReject.waiting_reason)
    await state.update_data(reject_draft_id=draft_id, reject_admin_msg_id=cb.message.message_id)
    await cb.message.answer(f"Пришли причину отклонения для анонса #{draft_id} (одним сообщением).")
    await cb.answer()


@admin_router.message(AdminReject.waiting_reason)
async def admin_reject_reason(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return

    reason = (message.text or "").strip()
    if len(reason) < 2:
        await message.answer("Причина слишком короткая. Напиши нормально.")
        return

    data = await state.get_data()
    try:
        draft_id = int(data["reject_draft_id"])
    except (KeyError, TypeError, ValueError):
        await message.answer("Ошибка: не найден draft_id.")
        await state.clear()
        return

    draft = await get_draft(draft_id)
    if not draft:
        await message.answer("Черновик не найден.")
        await state.clear()
        return

    await set_draft_rejected(draft_id, reason)

    await bot.send_message(
        chat_id=draft["creator_user_id"],
        text=(
            f"Твой анонс (id={draft_id}) отклонён ❌\n"
            f"Причина: {reason}\n\n"
            f"Нажми кнопку ниже, чтобы отредактировать и отправить заново."
        ),
        reply_markup=kb_edit_rejected(draft_id)
    )

    try:
        updated_draft = await get_draft(draft_id)
        new_caption = format_preview_safe(updated_draft) + f"\n\n❌ ОТКЛОНЕНО: {reason}"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1023] + "…"
        await bot.edit_message_caption(
            chat_id=ADMIN_CHAT_ID,
            message_id=int(data.get("reject_admin_msg_id")),
            caption=new_caption,
            reply_markup=None,
        )
    except Exception:
        pass

    await message.answer("Ок, отправил пользователю причину.")
    await state.clear()
    logger.info("Draft rejected: id=%d by admin=%d reason=%r", draft_id, message.from_user.id, reason)


# ---- Drop from queue (admin) ----

@admin_router.callback_query(F.data.startswith("adm:drop:"))
async def admin_drop_request(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    try:
        draft_id = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Черновик не найден.", show_alert=True)
        return

    title = draft.get("title") or f"#{draft_id}"
    await cb.message.answer(
        f"Удалить анонс #{draft_id} «{title}» из очереди?\n"
        f"Автор будет уведомлён. Это нельзя отменить.",
        reply_markup=kb_admin_confirm_delete(draft_id),
    )
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:drop_ok:"))
async def admin_drop_confirm(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Недостаточно прав.", show_alert=True)
        return

    try:
        draft_id = int(cb.data.split(":")[2])
    except (IndexError, ValueError):
        await cb.answer("Некорректный запрос.", show_alert=True)
        return

    draft = await get_draft(draft_id)
    if not draft:
        await cb.answer("Черновик не найден.", show_alert=True)
        return

    await delete_draft(draft_id)

    # Notify the author
    try:
        await bot.send_message(
            chat_id=draft["creator_user_id"],
            text=f"Твой анонс #{draft_id} был удалён администратором.",
            reply_markup=kb_start(),
        )
    except Exception:
        pass

    # Strike the admin message
    try:
        new_caption = ((cb.message.caption or "") + "\n\n🗑 УДАЛЕНО АДМИНИСТРАТОРОМ")
        if len(new_caption) > 1024:
            new_caption = new_caption[:1023] + "…"
        await bot.edit_message_caption(
            chat_id=ADMIN_CHAT_ID,
            message_id=draft.get("admin_message_id"),
            caption=new_caption,
            reply_markup=None,
        )
    except Exception:
        pass

    await cb.message.edit_text(f"Анонс #{draft_id} удалён.")
    await cb.answer("Удалено")
    logger.info("Draft deleted by admin: id=%d admin=%d", draft_id, cb.from_user.id)
