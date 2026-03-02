from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

CATEGORIES = [
    "ТРИЛИСТНИК",
    "D&D",
    "КИНО",
    "ЛЕКЦИЯ",
    "ИГРЫ",
    "ДРУГОЕ",
]

# Statuses that the user can delete
USER_DELETABLE = {"draft", "pending", "rejected"}
# Statuses that the admin can drop from queue
ADMIN_DELETABLE = {"pending"}


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
        [
            InlineKeyboardButton(text="✏️ Создать анонс", callback_data="new"),
            InlineKeyboardButton(text="📋 Мои анонсы", callback_data="my_drafts"),
        ]
    ])


def kb_send_to_moderation() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Отправить на модерацию", callback_data="send_to_mod")],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
    ])


def kb_admin_moderation(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm:approve:{draft_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:reject:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить из очереди", callback_data=f"adm:drop:{draft_id}"),
        ],
    ])


def kb_edit_rejected(draft_id: int) -> InlineKeyboardMarkup:
    """Shown to user in rejection notification."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_draft:{draft_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"draft_drop:{draft_id}")],
    ])


def kb_my_drafts(drafts: list[dict]) -> InlineKeyboardMarkup | None:
    """
    One row per actionable draft.
    Rejected: [✏️ #N title]  [🗑 #N]
    Draft / pending: [🗑 Удалить #N title]
    Published / approved: no row
    """
    rows = []
    for d in drafts:
        status = d["status"]
        draft_id = d["id"]
        short = (d.get("title") or f"#{draft_id}")[:22]

        if status == "rejected":
            rows.append([
                InlineKeyboardButton(text=f"✏️ #{draft_id} {short}", callback_data=f"edit_draft:{draft_id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"draft_drop:{draft_id}"),
            ])
        elif status in ("draft", "pending"):
            rows.append([
                InlineKeyboardButton(text=f"🗑 #{draft_id} {short}", callback_data=f"draft_drop:{draft_id}"),
            ])

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def kb_confirm_delete(draft_id: int) -> InlineKeyboardMarkup:
    """User-side delete confirmation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"draft_drop_ok:{draft_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
        ]
    ])


def kb_admin_confirm_delete(draft_id: int) -> InlineKeyboardMarkup:
    """Admin-side delete confirmation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm:drop_ok:{draft_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
        ]
    ])
