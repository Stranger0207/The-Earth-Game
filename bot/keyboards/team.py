"""کیبوردهای اینلاین مدیریت تیم و مالکان ربات (/team)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import User
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def team_main_kb(is_owner: bool = False) -> InlineKeyboardMarkup:
    """کیبورد اصلی پنل مدیریت تیم."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ افزودن ادمین جدید", callback_data="team:add_admin", style=STYLE_OK)
    builder.button(text="➖ حذف ادمین", callback_data="team:remove_admin", style=STYLE_NO)
    builder.adjust(2)

    if is_owner:
        builder.row(
            InlineKeyboardButton(text="👑 مدیریت مالکان", callback_data="team:manage_owners", style=STYLE_MAIN)
        )

    builder.row(
        InlineKeyboardButton(text="🔄 بازگشت به منوی اصلی", callback_data="menu:main", style=STYLE_MAIN)
    )
    return builder.as_markup()


def team_remove_admin_kb(admins: list[User]) -> InlineKeyboardMarkup:
    """کیبورد حذف ادمین با انتخاب از لیست یا ورودی متنی."""
    builder = InlineKeyboardBuilder()
    for user in admins:
        name = user.first_name or f"User {user.telegram_id}"
        if user.username:
            display = f"❌ {name} (@{user.username})"
        else:
            display = f"❌ {name} ({user.telegram_id})"
        builder.button(text=display, callback_data=f"team:del_admin:{user.telegram_id}", style=STYLE_NO)
    builder.adjust(1)

    builder.row(
        InlineKeyboardButton(text="✏️ ارسال متنی آیدی / یوزرنیم", callback_data="team:manual_del_admin", style=STYLE_MAIN)
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به منوی تیم", callback_data="team:main", style=STYLE_MAIN)
    )
    return builder.as_markup()


def team_owners_kb() -> InlineKeyboardMarkup:
    """کیبورد زیرمنوی مدیریت مالکان."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ افزودن مالک جدید", callback_data="team:add_owner", style=STYLE_OK)
    builder.button(text="➖ خلع مالک (پویا)", callback_data="team:remove_owner", style=STYLE_NO)
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به منوی تیم", callback_data="team:main", style=STYLE_MAIN)
    )
    return builder.as_markup()


def team_remove_owner_kb(dynamic_owners: list[User]) -> InlineKeyboardMarkup:
    """کیبورد خلع مالک پویا."""
    builder = InlineKeyboardBuilder()
    for user in dynamic_owners:
        name = user.first_name or f"User {user.telegram_id}"
        if user.username:
            display = f"❌ {name} (@{user.username})"
        else:
            display = f"❌ {name} ({user.telegram_id})"
        builder.button(text=display, callback_data=f"team:del_owner:{user.telegram_id}", style=STYLE_NO)
    builder.adjust(1)

    builder.row(
        InlineKeyboardButton(text="✏️ ارسال متنی آیدی / یوزرنیم", callback_data="team:manual_del_owner", style=STYLE_MAIN)
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به مدیریت مالکان", callback_data="team:manage_owners", style=STYLE_MAIN)
    )
    return builder.as_markup()


def team_cancel_kb() -> InlineKeyboardMarkup:
    """دکمه انصراف و بازگشت به منوی تیم."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data="team:main", style=STYLE_NO)]
        ]
    )
