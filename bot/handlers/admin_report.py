"""هندلرهای دستورات و کیبورد شیشه‌ای گزارش تراز جهانی و داشبورد آماری ادمین."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.base import async_session_factory
from ..keyboards.admin_report import global_report_back_kb, global_report_dashboard_kb
from ..services.global_report_service import (
    generate_csv_reports,
    generate_global_report,
    render_full_report,
    render_market_trades_report,
    render_short_report,
    render_top_holders_report,
)
from ..utils.numbers import to_fa_digits
from ..utils.screens import safe_edit

logger = logging.getLogger(__name__)
settings = get_settings()

router = Router(name="admin_report")


async def _guard(event: CallbackQuery | Message) -> bool:
    """بررسی دسترسی ادمین یا مالک برای استفاده از داشبورد گزارش جهانی."""
    uid = event.from_user.id if event.from_user else 0
    if settings.is_admin(uid):
        return True
    if isinstance(event, CallbackQuery):
        await event.answer("⛔️ دسترسی غیرمجاز. فقط مدیران ارشد بازی مجاز هستند.", show_alert=True)
    return False


@router.message(Command("admin_global_report"))
async def cmd_admin_global_report(message: Message) -> None:
    """
    نمایش داشبورد گزارش تراز کلان جهانی.
    پشتیبانی از آرگومان‌های اختیاری مانند:
    /admin_global_report 24h
    /admin_global_report 72h full
    /admin_global_report csv
    """
    if not await _guard(message):
        return

    text = message.text or ""
    parts = text.split()
    hours = 8
    mode = "short"

    for p in parts[1:]:
        p_lower = p.lower()
        m_h = re.search(r"(\d+)", p_lower)
        if m_h:
            hours = int(m_h.group(1))
        if "full" in p_lower:
            mode = "full"
        elif "top" in p_lower:
            mode = "top"
        elif "market" in p_lower:
            mode = "market"
        elif "csv" in p_lower:
            mode = "csv"

    if hours not in (8, 24, 72):
        hours = 8

    async with async_session_factory() as session:
        report, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    if mode == "full":
        full_parts = render_full_report(data)
        if len(full_parts) == 1:
            await message.answer(full_parts[0], reply_markup=global_report_back_kb(hours))
        else:
            await message.answer(full_parts[0])
            await message.answer(full_parts[1], reply_markup=global_report_back_kb(hours))
    elif mode == "top":
        top_text = render_top_holders_report(data)
        await message.answer(top_text, reply_markup=global_report_back_kb(hours))
    elif mode == "market":
        m_text = render_market_trades_report(data)
        await message.answer(m_text, reply_markup=global_report_back_kb(hours))
    elif mode == "csv":
        csv_files = generate_csv_reports(data)
        for fname, fbytes in csv_files.items():
            doc = BufferedInputFile(fbytes, filename=fname)
            await message.answer_document(
                doc, caption=f"📊 خروجی {fname} ({to_fa_digits(hours)} ساعته)"
            )
    else:
        # حالت پیش‌فرض: نمایش خلاصه همراه با کیبورد داشبورد ۵ ردیفه
        short_text = report.short_text or render_short_report(data)
        await message.answer(short_text, reply_markup=global_report_dashboard_kb(hours))


@router.callback_query(F.data.startswith("rep:short:"))
async def cb_rep_short(call: CallbackQuery) -> None:
    """تغییر بازه زمانی گزارش خلاصه (۸، ۲۴ یا ۷۲ ساعته)."""
    if not await _guard(call):
        return
    await call.answer()
    hours = 8
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        pass

    async with async_session_factory() as session:
        report, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    text = report.short_text or render_short_report(data)
    await safe_edit(call, text, reply_markup=global_report_dashboard_kb(hours))


@router.callback_query(F.data.startswith("rep:full:"))
async def cb_rep_full(call: CallbackQuery) -> None:
    """نمایش گزارش کامل و تحلیلی ادمین به صورت تفکیک‌شده."""
    if not await _guard(call):
        return
    await call.answer()
    hours = 8
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        pass

    async with async_session_factory() as session:
        _, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    parts = render_full_report(data)
    if len(parts) == 1:
        await safe_edit(call, parts[0], reply_markup=global_report_back_kb(hours))
    else:
        await safe_edit(call, parts[0])
        if call.message:
            await call.message.answer(parts[1], reply_markup=global_report_back_kb(hours))


@router.callback_query(F.data.startswith("rep:top:"))
async def cb_rep_top(call: CallbackQuery) -> None:
    """نمایش گزارش تمرکز منابع و ۳ دارنده برتر جهان."""
    if not await _guard(call):
        return
    await call.answer()
    hours = 8
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        pass

    async with async_session_factory() as session:
        _, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    text = render_top_holders_report(data)
    await safe_edit(call, text, reply_markup=global_report_back_kb(hours))


@router.callback_query(F.data.startswith("rep:market:"))
async def cb_rep_market(call: CallbackQuery) -> None:
    """نمایش وضعیت بازار و ۱۰ معامله اخیر WTO."""
    if not await _guard(call):
        return
    await call.answer()
    hours = 8
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        pass

    async with async_session_factory() as session:
        _, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    text = render_market_trades_report(data)
    await safe_edit(call, text, reply_markup=global_report_back_kb(hours))


@router.callback_query(F.data.startswith("rep:csv:"))
async def cb_rep_csv(call: CallbackQuery) -> None:
    """تولید و ارسال فایل‌های سه‌گانه CSV در رم برای ادمین."""
    if not await _guard(call):
        return
    await call.answer("⏳ در حال پردازش و استخراج فایل‌های CSV...")
    hours = 8
    try:
        hours = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        pass

    async with async_session_factory() as session:
        _, data = await generate_global_report(session, period_hours=hours)
        await session.commit()

    csv_files = generate_csv_reports(data)
    if call.message:
        for fname, fbytes in csv_files.items():
            doc = BufferedInputFile(fbytes, filename=fname)
            await call.message.answer_document(
                doc, caption=f"📊 خروجی {fname} ({to_fa_digits(hours)} ساعته)"
            )


@router.callback_query(F.data == "god:global_report")
async def cb_god_global_report(call: CallbackQuery) -> None:
    """ورود مستقیم به داشبورد گزارش تراز جهانی از طریق دکمه پنل /god."""
    if not await _guard(call):
        return
    await call.answer()
    async with async_session_factory() as session:
        report, data = await generate_global_report(session, period_hours=8)
        await session.commit()

    text = report.short_text or render_short_report(data)
    await safe_edit(call, text, reply_markup=global_report_dashboard_kb(8))
