"""هندلر پنل و دستور /switch برای ورود مستقیم ادمین به عنوان پلیر هر کشور."""

from __future__ import annotations

import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import Country
from ..database.repositories import countries as countries_repo
from ..database.repositories import users as users_repo
from ..keyboards.menu import main_menu_kb
from ..loader import bot
from ..services.news_service import send_log
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .kick import find_country_by_query

logger = logging.getLogger(__name__)
router = Router(name="switch")
settings = get_settings()

PAGE_SIZE = 8


def _build_switch_kb(countries: list[Country], page: int) -> InlineKeyboardMarkup:
    """ساخت کیبورد شیشه‌ای کشورها برای سوییچ ادمین."""
    total_items = len(countries)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * PAGE_SIZE
    chunk = countries[start_idx : start_idx + PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for c in chunk:
        # نمایش وضعیت: 👤 دارای بازیکن | ⚪️ کشور آزاد
        icon = "👤" if c.owner_user_id else "⚪️"
        style = STYLE_NO if c.owner_user_id else STYLE_MAIN
        builder.button(
            text=f"{icon} {c.flag} {c.name_fa}",
            callback_data=f"switch_do:{c.id}:{page}",
            style=style,
        )
    builder.adjust(2)

    nav_btns: list[InlineKeyboardButton] = []
    if page > 0:
        nav_btns.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"switch_p:{page - 1}", style=STYLE_MAIN)
        )
    if total_pages > 1:
        nav_btns.append(
            InlineKeyboardButton(text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}", callback_data="switch_noop")
        )
    if start_idx + PAGE_SIZE < total_items:
        nav_btns.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"switch_p:{page + 1}", style=STYLE_MAIN)
        )
    if nav_btns:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="❌ بستن پنل", callback_data="switch_close", style=STYLE_MAIN))
    return builder.as_markup()


async def _execute_admin_switch(
    session: AsyncSession,
    admin_id: int,
    admin_name: str,
    target_country: Country,
) -> tuple[int | None, Country | None]:
    """انتقال مالکیت کشور به ادمین، اطلاع‌رسانی به پلیر قبلی و آزادسازی کشور قبلی ادمین."""
    # ۱. اگر ادمین قبلاً روی کشور دیگری بود، کشور قبلی را آزاد می‌کنیم
    prev_country = await countries_repo.get_country_by_owner(session, admin_id)
    if prev_country and prev_country.id != target_country.id:
        prev_country.owner_user_id = None
        prev_country.is_claimed = False

    former_owner_id = target_country.owner_user_id

    # ۲. اگر کشور قبلاً پلیر دیگری داشت، به او اطلاع می‌دهیم
    if former_owner_id and former_owner_id != admin_id:
        try:
            await bot.send_message(
                former_owner_id,
                f"⚠️ مدیریت بازی وارد مدیریت کشور شما ({target_country.flag} {target_country.name_fa}) شد.",
            )
        except Exception as exc:
            logger.debug("Could not notify former owner %s: %s", former_owner_id, exc)

    # ۳. واگذاری مستقیم کشور به ادمین
    target_country.owner_user_id = admin_id
    target_country.is_claimed = True
    await session.commit()

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"🔄 <b>سوییچ ادمین روی کشور (/switch)</b>\n"
        f"کشور: {target_country.flag} {target_country.name_fa}\n"
        f"ادمین: {admin_name} (<code>{admin_id}</code>)\n"
        f"مالک قبلی: {('<code>' + str(former_owner_id) + '</code>') if former_owner_id else 'نداشت (آزاد)'}",
    )
    return former_owner_id, prev_country


@router.message(Command("switch"))
async def cmd_switch(message: Message, session: AsyncSession) -> None:
    """دستور و پنل سوییچ مستقیم ادمین روی کشورها (/switch)."""
    if not settings.is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) > 1:
        # سوییچ مستقیم با نام یا شناسه کشور
        query = parts[1].strip()
        country = await find_country_by_query(session, query)
        if not country:
            await message.answer(f"❌ کشوری با مشخصات «{query}» یافت نشد.")
            return

        former_owner_id, _ = await _execute_admin_switch(
            session,
            admin_id=message.from_user.id,
            admin_name=message.from_user.full_name,
            target_country=country,
        )

        owner_note = (
            "\n⚠️ <i>به پلیر قبلی این کشور اطلاع‌رسانی شد.</i>"
            if former_owner_id and former_owner_id != message.from_user.id
            else ""
        )
        await message.answer(
            f"✅ <b>سوییچ با موفقیت انجام شد:</b>\n\n"
            f"شما اکنون به عنوان رهبر کشور {country.flag} <b>{country.name_fa}</b> قرار گرفتید.{owner_note}",
            reply_markup=main_menu_kb(),
        )
        return

    # حالت بدون آرگومان -> نمایش پنل کشورها
    countries = await countries_repo.list_countries(session)
    if not countries:
        await message.answer("❌ هیچ کشوری در دیتابیس یافت نشد.")
        return

    kb = _build_switch_kb(countries, page=0)
    await message.answer(
        "🔄 <b>پنل سوییچ ادمین روی کشورها (/switch)</b>\n\n"
        "💡 <i>راهنما:</i>\n"
        "• 👤 : کشورهای دارای بازیکن فعال (با ورود شما، پیام آگاهی‌بخش به پلیر ارسال می‌شود)\n"
        "• ⚪️ : کشورهای آزاد\n\n"
        "کشور مورد نظر خود را جهت تحویل فوری رهبری انتخاب کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("switch_p:"))
async def cb_switch_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ورق زدن صفحات پنل switch."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    page = int(call.data.split(":")[1])
    countries = await countries_repo.list_countries(session)
    kb = _build_switch_kb(countries, page=page)
    await safe_edit(
        call,
        "🔄 <b>پنل سوییچ ادمین روی کشورها (/switch)</b>\n\n"
        "💡 <i>راهنما:</i>\n"
        "• 👤 : کشورهای دارای بازیکن فعال (با ورود شما، پیام آگاهی‌بخش به پلیر ارسال می‌شود)\n"
        "• ⚪️ : کشورهای آزاد\n\n"
        "کشور مورد نظر خود را جهت تحویل فوری رهبری انتخاب کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("switch_do:"))
async def cb_switch_do(call: CallbackQuery, session: AsyncSession) -> None:
    """اجرای سوییچ از طریق کلیک روی دکمه کشور در پنل."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    parts = call.data.split(":")
    cid = int(parts[1])
    country = await countries_repo.get_country(session, cid)
    if not country:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    former_owner_id, _ = await _execute_admin_switch(
        session,
        admin_id=call.from_user.id,
        admin_name=call.from_user.full_name,
        target_country=country,
    )

    await call.answer(f"به کشور {country.name_fa} سوییچ شدید ✅", show_alert=True)

    owner_note = (
        "\n⚠️ <i>به پلیر قبلی این کشور اطلاع‌رسانی شد.</i>"
        if former_owner_id and former_owner_id != call.from_user.id
        else ""
    )
    await safe_edit(
        call,
        f"✅ <b>سوییچ با موفقیت انجام شد:</b>\n\n"
        f"شما اکنون به عنوان رهبر کشور {country.flag} <b>{country.name_fa}</b> قرار گرفتید.{owner_note}",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "switch_noop")
async def cb_switch_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "switch_close")
async def cb_switch_close(call: CallbackQuery) -> None:
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return
    await call.answer("پنل بسته شد.")
    try:
        await call.message.delete()
    except Exception:
        await safe_edit(call, "🔒 پنل سوییچ بسته شد.", reply_markup=None)
