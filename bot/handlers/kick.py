"""هندلر پنل و دستور /kick برای آزادسازی درجا کشور توسط ادمین."""

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
from ..loader import bot
from ..services.news_service import send_log
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK

logger = logging.getLogger(__name__)
router = Router(name="kick")
settings = get_settings()

PAGE_SIZE = 8


async def find_country_by_query(session: AsyncSession, query: str) -> Country | None:
    """جستجوی کشور بر اساس شناسه، نام انگلیسی یا نام فارسی."""
    q = query.strip()
    if not q:
        return None
    if q.isdigit():
        c = await session.get(Country, int(q))
        if c:
            return c
    res = await session.execute(select(Country).where(Country.name_en.ilike(q)))
    c = res.scalar_one_or_none()
    if c:
        return c
    res = await session.execute(select(Country).where(Country.name_fa == q))
    c = res.scalar_one_or_none()
    if c:
        return c
    res = await session.execute(select(Country).where(Country.name_fa.ilike(f"%{q}%")))
    c = res.scalars().first()
    if c:
        return c
    res = await session.execute(select(Country).where(Country.name_en.ilike(f"%{q}%")))
    return res.scalars().first()


async def _get_claimed_countries(session: AsyncSession) -> list[Country]:
    """دریافت فهرست تمام کشورهای دارای بازیکن."""
    stmt = (
        select(Country)
        .where(Country.is_claimed.is_(True), Country.owner_user_id.is_not(None))
        .order_by(Country.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_kick_kb(countries: list[Country], page: int) -> InlineKeyboardMarkup:
    """ساخت کیبورد شیشه‌ای صفحه‌بندی‌شده برای آزادسازی کشورها."""
    total_items = len(countries)
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * PAGE_SIZE
    chunk = countries[start_idx : start_idx + PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for c in chunk:
        builder.button(
            text=f"🚪 {c.flag} {c.name_fa}",
            callback_data=f"kick_pick:{c.id}:{page}",
            style=STYLE_NO,
        )
    builder.adjust(2)

    nav_btns: list[InlineKeyboardButton] = []
    if page > 0:
        nav_btns.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"kick_p:{page - 1}", style=STYLE_MAIN)
        )
    if total_pages > 1:
        nav_btns.append(
            InlineKeyboardButton(text=f"📄 {fa_number(page + 1)}/{fa_number(total_pages)}", callback_data="kick_noop")
        )
    if start_idx + PAGE_SIZE < total_items:
        nav_btns.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"kick_p:{page + 1}", style=STYLE_MAIN)
        )
    if nav_btns:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="❌ بستن پنل", callback_data="kick_close", style=STYLE_MAIN))
    return builder.as_markup()


@router.message(Command("kick"))
async def cmd_kick(message: Message, session: AsyncSession) -> None:
    """دستور و پنل آزادسازی درجا کشور توسط ادمین."""
    if not settings.is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) > 1:
        # ۱. آزادسازی مستقیم با نام یا آیدی کشور
        query = parts[1].strip()
        country = await find_country_by_query(session, query)
        if not country:
            await message.answer(f"❌ کشوری با مشخصات «{query}» یافت نشد.")
            return

        if not country.owner_user_id:
            await message.answer(f"ℹ️ کشور {country.flag} <b>{country.name_fa}</b> در حال حاضر مالکی ندارد و آزاد است.")
            return

        former_owner_id = country.owner_user_id
        await countries_repo.release_country(session, country.id)
        if former_owner_id:
            await users_repo.set_suspended(session, former_owner_id, False)
            try:
                await bot.send_message(
                    former_owner_id,
                    f"🚪 مدیریت بازی شما را از رهبری {country.flag} {country.name_fa} برکنار کرد.\n\n"
                    "کشور شما آزاد شد و اکنون می‌توانید کشور دیگری را انتخاب کنید: /claim",
                )
            except Exception as exc:
                logger.debug("Could not notify kicked player %s: %s", former_owner_id, exc)

        await session.commit()
        await message.answer(
            f"✅ کشور {country.flag} <b>{country.name_fa}</b> با موفقیت آزاد شد.\n"
            f"مالک قبلی (<code>{former_owner_id}</code>) برکنار و وضعیت تعلیق وی لغو گردید."
        )
        await send_log(
            bot,
            f"🚪 <b>آزادسازی کشور (/kick)</b>\n"
            f"کشور: {country.flag} {country.name_fa}\n"
            f"مالک برکنارشده: <code>{former_owner_id}</code>\n"
            f"ادمین: {message.from_user.full_name} (<code>{message.from_user.id}</code>)",
        )
        return

    # ۲. حالت بدون آرگومان -> نمایش پنل شیشه‌ای کشورها
    claimed = await _get_claimed_countries(session)
    if not claimed:
        await message.answer("ℹ️ در حال حاضر هیچ کشوری توسط بازیکنان اشغال نشده است.")
        return

    kb = _build_kick_kb(claimed, page=0)
    await message.answer(
        "🚪 <b>پنل آزادسازی درجا کشورها (/kick)</b>\n\n"
        f"تعداد کشورهای دارای بازیکن: <b>{fa_number(len(claimed))}</b>\n"
        "جهت آزادسازی فوری و برکناری بازیکن، کشور مورد نظر را انتخاب کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("kick_p:"))
async def cb_kick_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ورق زدن صفحات پنل kick."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    page = int(call.data.split(":")[1])
    claimed = await _get_claimed_countries(session)
    if not claimed:
        await safe_edit(call, "ℹ️ در حال حاضر هیچ کشوری اشغال نشده است.")
        return

    kb = _build_kick_kb(claimed, page=page)
    await safe_edit(
        call,
        "🚪 <b>پنل آزادسازی درجا کشورها (/kick)</b>\n\n"
        f"تعداد کشورهای دارای بازیکن: <b>{fa_number(len(claimed))}</b>\n"
        "جهت آزادسازی فوری و برکناری بازیکن، کشور مورد نظر را انتخاب کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("kick_pick:"))
async def cb_kick_pick(call: CallbackQuery, session: AsyncSession) -> None:
    """تأییدیه آزادسازی کشور انتخابی."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    await call.answer()
    parts = call.data.split(":")
    cid, page = int(parts[1]), int(parts[2])
    country = await countries_repo.get_country(session, cid)
    if not country:
        await safe_edit(call, "❌ کشور یافت نشد.")
        return

    former_user = None
    if country.owner_user_id:
        former_user = await users_repo.get_user(session, country.owner_user_id)

    owner_str = f"@{former_user.username}" if former_user and former_user.username else str(country.owner_user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، درجا آزاد کن", callback_data=f"kick_do:{country.id}:{page}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت به لیست", callback_data=f"kick_p:{page}", style=STYLE_MAIN)
    builder.adjust(1)

    await safe_edit(
        call,
        f"⚠️ <b>تأیید آزادسازی درجا:</b>\n\n"
        f"کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"مالک فعلی: <code>{owner_str}</code>\n\n"
        "با تأیید شما، کشور بلافاصله آزاد شده، مالک برکنار و تعلیق او لغو می‌شود.\n"
        "آیا اطمینان دارید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("kick_do:"))
async def cb_kick_do(call: CallbackQuery, session: AsyncSession) -> None:
    """اجرای نهایی آزادسازی کشور."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return

    parts = call.data.split(":")
    cid, page = int(parts[1]), int(parts[2])
    country = await countries_repo.get_country(session, cid)
    if not country:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    former_owner_id = country.owner_user_id
    await countries_repo.release_country(session, country.id)
    if former_owner_id:
        await users_repo.set_suspended(session, former_owner_id, False)
        try:
            await bot.send_message(
                former_owner_id,
                f"🚪 مدیریت بازی شما را از رهبری {country.flag} {country.name_fa} برکنار کرد.\n\n"
                "کشور شما آزاد شد و اکنون می‌توانید کشور دیگری را انتخاب کنید: /claim",
            )
        except Exception as exc:
            logger.debug("Could not notify kicked player %s: %s", former_owner_id, exc)

    await session.commit()
    await call.answer("کشور با موفقیت آزاد شد ✅", show_alert=True)

    await send_log(
        bot,
        f"🚪 <b>آزادسازی کشور (/kick)</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"مالک برکنارشده: <code>{former_owner_id}</code>\n"
        f"ادمین: {call.from_user.full_name} (<code>{call.from_user.id}</code>)",
    )

    claimed = await _get_claimed_countries(session)
    if not claimed:
        await safe_edit(call, "ℹ️ تمامی کشورها آزاد شدند. هیچ کشور اشغال‌شده‌ای وجود ندارد.")
        return

    kb = _build_kick_kb(claimed, page=page)
    await safe_edit(
        call,
        "🚪 <b>پنل آزادسازی درجا کشورها (/kick)</b>\n\n"
        f"تعداد کشورهای دارای بازیکن: <b>{fa_number(len(claimed))}</b>\n"
        "جهت آزادسازی فوری و برکناری بازیکن، کشور مورد نظر را انتخاب کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data == "kick_noop")
async def cb_kick_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "kick_close")
async def cb_kick_close(call: CallbackQuery) -> None:
    if not settings.is_admin(call.from_user.id):
        await call.answer("مجاز نیستید.", show_alert=True)
        return
    await call.answer("پنل بسته شد.")
    try:
        await call.message.delete()
    except Exception:
        await safe_edit(call, "🔒 پنل آزادسازی بسته شد.", reply_markup=None)
