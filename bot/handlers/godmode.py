"""
پنل گاد مود ادمین (v1.8):
ابزار کامل مدیریت برای مالک/مدیران بازی.

- مدیریت بازیکنان: آزادسازی (اخراج) کشور، بن/رفع بن کاربر
- ویرایش هر شاخص اقتصادی، ذخایر و تجهیزات نظامی هر کشور
- رساندن فوری محموله‌های در راه (تجاری/نظامی)
- رساندن فوری پرواز دیپلماتیک و آغاز نشست

دسترسی فقط برای مالک/مدیر (settings.is_admin).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
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
from ..constants import (
    DEFAULT_BASE_PRICES,
    DEPLOY_BRANCHES,
    INVESTMENT_CATEGORIES,
    MARKET_REASON_TEMPLATES,
    MIL_FACTORY_YIELD,
)
from ..database.models import (
    Country,
    Facility,
    GroupMeeting,
    Investment,
    Meeting,
    MilitaryAsset,
    MilitaryFactory,
    MilitarySale,
    ProfanityWord,
    ResourceSale,
    Sanction,
    UNAssemblyParticipant,
    UNAssemblySession,
    User,
)
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as diplomacy_repo
from ..database.repositories import facilities as fac_repo
from ..database.repositories import investments as inv_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_factory as milfac_repo
from ..database.repositories import profanity as profanity_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import tech_transfer as tech_repo
from ..database.repositories import united_nations as un_repo
from ..database.repositories import users as users_repo
from ..enums import (
    FACILITY_FA,
    MIL_FACTORY_CATEGORY,
    MIL_FACTORY_FA,
    RESOURCE_EMOJI,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    SANCTION_FA,
    AdminGroupType,
    DiplomacyStatus,
    FacilityType,
    MilitaryFactoryType,
    NewsCategory,
    ResourceType,
    SanctionType,
    TradeStatus,
)
from ..loader import bot
from ..services import profanity_service
from ..services.economy_service import facility_yield_for
from ..services.news_service import publish_news, send_log, send_to_admin_group
from ..utils.formatting import render_economy_panel, render_military_panel, render_reserves_panel
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header
from ..services.tech_service import get_equipment_origin
from ..states import GodForm, ProfanityAdminForm

logger = logging.getLogger(__name__)

router = Router(name="godmode")
settings = get_settings()

# تعداد تأسیسات در هر صفحه‌ی فهرست پنل گاد (v1.11.1)
GOD_FACILITY_PAGE_SIZE = 10

# تعداد سرمایه‌گذاری در هر صفحه‌ی فهرست پنل گاد (v1.11.1)
GOD_INVEST_PAGE_SIZE = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# شاخص‌های عددی قابل‌ویرایش اقتصاد/کشور (نام فیلد → نام فارسی)
_NUMERIC_FIELDS: dict[str, str] = {
    "budget": "بودجه",
    "economic_power": "قدرت اقتصادی",
    "inflation": "تورم",
    "unemployment": "بیکاری",
    "public_satisfaction": "رضایت عمومی",
    "stability": "ثبات داخلی",
    "govt_debt": "بدهی دولت",
    "population": "جمعیت",
    "international_duties": "عوارض بین‌المللی",
}

# فیلدهای متنی (enum) و مقادیر مجاز آن‌ها
_ENUM_FIELDS: dict[str, tuple[str, dict[str, str]]] = {
    "growth": ("رشد اقتصادی", {"up": "صعودی", "flat": "ثابت", "down": "نزولی"}),
    "energy_status": ("وضعیت انرژی", {"weak": "ضعیف", "medium": "متوسط", "good": "خوب", "excellent": "عالی"}),
    "foreign_trade": ("تجارت خارجی", {"negative": "منفی", "balanced": "متعادل", "positive": "مثبت"}),
}


async def _guard(event: CallbackQuery | Message) -> bool:
    """بررسی دسترسی ادمین؛ در صورت نبود دسترسی پیام مناسب می‌دهد."""
    uid = event.from_user.id
    if settings.is_admin(uid):
        return True
    if isinstance(event, CallbackQuery):
        await event.answer("⛔️ فقط مالک/مدیر بازی به این بخش دسترسی دارد.", show_alert=True)
    return False


# ============================================================
#  پنل اصلی گاد مود
# ============================================================
def _home_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏳 مدیریت کشورها", callback_data="god:countries", style=STYLE_MAIN)
    builder.button(text="🚚 محموله‌های در راه", callback_data="god:ship", style=STYLE_MAIN)
    builder.button(text="✈️ پروازهای دیپلماتیک", callback_data="god:flights", style=STYLE_MAIN)
    builder.button(text="🇺🇳 مجمع عمومی سازمان ملل", callback_data="god:unasmb", style=STYLE_MAIN)
    builder.button(text="🚫 تحریم‌ها", callback_data="god:sanctions", style=STYLE_MAIN)
    builder.button(text="📈 سرمایه‌گذاری‌ها", callback_data="god:invest", style=STYLE_MAIN)
    builder.button(text="📊 نرخ بازار جهانی", callback_data="god:market", style=STYLE_MAIN)
    builder.button(text="🏗 پروژه‌های اقتصادی", callback_data="god:projects", style=STYLE_MAIN)
    builder.button(text="☢️ برنامه‌های هسته‌ای", callback_data="god:nuclear", style=STYLE_MAIN)
    builder.button(text="🔬 لایسنس‌های تکنولوژی", callback_data="god:tech", style=STYLE_MAIN)
    builder.button(text="💥 سیستم تلفات", callback_data="god:casualty", style=STYLE_NO)
    builder.button(text="🤬 فیلتر فحش و کلمات رکیک", callback_data="god:profanity", style=STYLE_MAIN)
    builder.button(text="📢 جوین اجباری کانال", callback_data="god:force_join", style=STYLE_MAIN)
    builder.button(text="📁 تنظیم لینک فولدر", callback_data="god:set_folder", style=STYLE_MAIN)
    builder.button(text="📢 ارسال پیام همگانی", callback_data="god:broadcast", style=STYLE_MAIN)
    builder.button(text="🔒 غیرفعال‌کردن آپشن", callback_data="god:locks", style=STYLE_NO)
    builder.button(text="⛔️ مدیریت بن کاربران", callback_data="god:ban_list", style=STYLE_NO)
    builder.button(text="🔴 پایان و ریست کامل فصل", callback_data="god:endseason", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


_HOME_TEXT = (
    header("پنل گاد مود ادمین", "🛠")
    + "\n\nاز اینجا می‌توانید کشورها را ویرایش، محموله‌ها را فوری برسانید و "
    "پروازهای دیپلماتیک را درجا فعال کنید."
)


@router.message(Command("god"))
async def cmd_god(message: Message, state: FSMContext) -> None:
    """ورود به پنل گاد مود (فقط مالک/مدیر)."""
    if not await _guard(message):
        return
    await state.clear()
    await message.answer(_HOME_TEXT, reply_markup=_home_kb())


@router.callback_query(F.data == "god:home")
async def cb_home(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    await call.message.edit_text(_HOME_TEXT, reply_markup=_home_kb())


@router.callback_query(F.data == "god:endseason")
async def cb_god_endseason(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست ریست فصل از درون پنل گاد مود."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 بله، فصل را ریست کن", callback_data="season_reset_confirm",
                    style=STYLE_NO,
                )
            ],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="god:home", style=STYLE_MAIN)],
        ]
    )
    await call.message.edit_text(
        "⚠️ <b>پایان فصل و ریست کامل بازی</b>\n\n"
        "با این کار تمام تغییرات فصل به حالت اولیه برمی‌گردد:\n"
        "• اقتصاد، ذخایر و رضایت همه‌ی کشورها بازنشانی می‌شود\n"
        "• تجهیزات نظامی (تلفات‌ها) به تعداد اولیه برمی‌گردد\n"
        "• تأسیسات، کارخانه‌های نظامی، قراردادها، حملات، تماس‌ها، دیدارها و فروش‌ها پاک می‌شوند\n"
        "• <b>مالکیت همه‌ی کشورها آزاد می‌شود</b> و بازیکن‌ها باید دوباره کشورگیری کنند\n\n"
        "❗️ این عملیات <b>غیرقابل‌بازگشت</b> است. مطمئن هستید؟",
        reply_markup=kb,
    )


# ============================================================
#  جوین اجباری، لینک فولدر و پیام همگانی از پنل گاد
# ============================================================
@router.callback_query(F.data == "god:force_join")
async def cb_god_force_join(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    from ..database.repositories import bot_state as bot_state_repo
    bstate = await bot_state_repo.get_state(session)
    status_text = "🟢 فعال" if bstate.force_join_enabled else "🔴 غیرفعال"
    chat_id_text = bstate.force_join_chat_id or "تنظیم نشده"
    link_text = bstate.force_join_invite_link or "تنظیم نشده"

    toggle_text = "🔴 غیرفعال‌سازی جوین اجباری" if bstate.force_join_enabled else "🟢 فعال‌سازی جوین اجباری"
    toggle_style = STYLE_NO if bstate.force_join_enabled else STYLE_OK
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="god:force_join_toggle", style=toggle_style)],
            [
                InlineKeyboardButton(text="✏️ تغییر آیدی/یوزرنیم کانال", callback_data="setchan:chat_id", style=STYLE_MAIN),
                InlineKeyboardButton(text="🔗 تغییر لینک دعوت", callback_data="setchan:link", style=STYLE_MAIN),
            ],
            [InlineKeyboardButton(text="🔙 بازگشت به منوی گاد", callback_data="god:home", style=STYLE_MAIN)],
        ]
    )
    text = (
        header("مدیریت سیستم عضویت اجباری کانال", "📢")
        + f"\n\n<b>وضعیت فعلی:</b> {status_text}\n"
        f"<b>شناسه یا @یوزرنیم کانال:</b> <code>{chat_id_text}</code>\n"
        f"<b>لینک ورود به کانال:</b> {link_text}\n\n"
        "جهت تغییر تنظیمات از کلیدهای زیر استفاده کنید:"
    )
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "god:force_join_toggle")
async def cb_god_force_join_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    from ..database.repositories import bot_state as bot_state_repo
    bstate = await bot_state_repo.get_state(session)
    new_status = not bstate.force_join_enabled
    await bot_state_repo.update_state(session, force_join_enabled=new_status)
    await session.commit()
    await call.answer("وضعیت تغییر کرد")
    await cb_god_force_join(call, session)


@router.callback_query(F.data == "god:set_folder")
async def cb_god_set_folder(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    from ..database.repositories import bot_state as bot_state_repo
    from ..states import SetFolderForm
    await state.clear()
    await state.set_state(SetFolderForm.waiting_for_link)
    bstate = await bot_state_repo.get_state(session)
    curr = bstate.game_folder_link or "تنظیم نشده"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="god:home", style=STYLE_NO)]
        ]
    )
    await call.message.edit_text(
        f"📁 <b>تنظیم لینک فولدر رسمی بازی</b>\n\n"
        f"لینک فعلی: <code>{curr}</code>\n\n"
        "لطفاً لینک جدید فولدر تلگرام (مانند <code>https://t.me/addlist/...</code>) را ارسال کنید:",
        reply_markup=kb,
    )


@router.callback_query(F.data == "god:broadcast")
async def cb_god_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    from ..states import BroadcastForm
    await state.clear()
    await state.set_state(BroadcastForm.waiting_for_content)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data="god:home", style=STYLE_NO)]
        ]
    )
    await call.message.edit_text(
        "📢 <b>ارسال پیام همگانی به کل کاربران ربات</b>\n\n"
        "لطفاً پیام خود را ارسال کنید. می‌توانید <b>فقط متن</b> بفرستید و یا "
        "<b>یک عکس به همراه کپشن (متن زیر عکس)</b> ارسال کنید:",
        reply_markup=cancel_kb,
    )


# ============================================================
#  فهرست و پنل کشور
# ============================================================
@router.callback_query(F.data == "god:countries")
async def cb_countries(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    countries = await countries_repo.list_countries(session)
    builder = InlineKeyboardBuilder()
    for c in countries:
        mark = "🟢" if c.is_claimed else "⚪️"
        builder.button(text=f"{mark} {c.flag} {c.name_fa}", callback_data=f"godc:{c.id}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("🏳 یک کشور را برای مدیریت انتخاب کنید:", reply_markup=builder.as_markup())


async def _country_panel_kb(country: Country) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ ویرایش اقتصاد", callback_data=f"godeco:{country.id}", style=STYLE_MAIN)
    builder.button(text="📦 ویرایش ذخایر", callback_data=f"godres:{country.id}", style=STYLE_MAIN)
    builder.button(text="⚔️ ویرایش تجهیزات", callback_data=f"godmil:{country.id}", style=STYLE_MAIN)
    builder.button(text="🏭 تأسیسات و کارخانه‌ها", callback_data=f"godfac:{country.id}", style=STYLE_MAIN)
    builder.button(text="🔬 لایسنس‌های تکنولوژی", callback_data=f"godtech:{country.id}", style=STYLE_MAIN)
    builder.button(text="🏗 پروژه‌ها", callback_data=f"godproj:{country.id}", style=STYLE_MAIN)
    econ_sat_btn = (
        "🛰 ماهواره اقتصادی: فعال ✅"
        if getattr(country, "econ_sat_unlocked", False)
        else "🛰 ماهواره اقتصادی: غیرفعال ❌"
    )
    builder.button(
        text=econ_sat_btn,
        callback_data=f"godeconsat:{country.id}",
        style=STYLE_OK if getattr(country, "econ_sat_unlocked", False) else STYLE_NO,
    )
    if country.is_claimed:
        builder.button(text="🚪 آزادسازی (اخراج)", callback_data=f"godrelease:{country.id}", style=STYLE_NO)
        builder.button(text="⛔️ بن مالک", callback_data=f"godban:{country.id}", style=STYLE_NO)
        builder.button(text="✅ رفع بن مالک", callback_data=f"godunban:{country.id}", style=STYLE_OK)
        builder.button(text="⏸ تعلیق", callback_data=f"godsuspend:{country.id}", style=STYLE_NO)
        builder.button(text="▶️ رفع تعلیق", callback_data=f"godunsuspend:{country.id}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="god:countries", style=STYLE_MAIN)
    if country.is_claimed:
        builder.adjust(2, 2, 2, 1, 3, 2, 1)
    else:
        builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


async def _show_country_panel(call: CallbackQuery, session: AsyncSession, country_id: int) -> None:
    country = await countries_repo.get_country(session, country_id)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return
    owner_txt = "—"
    if country.owner_user_id:
        u = await users_repo.get_user(session, country.owner_user_id)
        uname = (f"@{u.username}" if u and u.username else (u.first_name if u else None)) or "—"
        banned = " (بن‌شده ⛔️)" if u and u.is_banned else ""
        suspended = " (معلق ⏸)" if u and getattr(u, "is_suspended", False) else ""
        owner_txt = f"{uname} (<code>{country.owner_user_id}</code>){banned}{suspended}"
    text = (
        header(f"مدیریت {country.flag} {country.name_fa}", "🛠")
        + f"\n\n👤 مالک: {owner_txt}\n"
        f"💸 بودجه: {fa_money(country.budget)}\n"
        f"💰 قدرت اقتصاد: {fa_number(country.economic_power)} | 😊 رضایت: {fa_number(country.public_satisfaction)} | 🏛 ثبات: {fa_number(country.stability)}"
    )
    await call.message.edit_text(text, reply_markup=await _country_panel_kb(country))


@router.callback_query(F.data.startswith("godc:"))
async def cb_country_panel(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await _show_country_panel(call, session, int(call.data.split(":")[1]))


@router.callback_query(F.data.startswith("godeconsat:"))
async def cb_god_econ_sat_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    """تغییر وضعیت فعالسازی ماهواره اقتصادی توسط مالک (v2.8)."""
    if not await _guard(call):
        return
    country_id = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, country_id)
    if country is None:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    country.econ_sat_unlocked = not getattr(country, "econ_sat_unlocked", False)
    await session.commit()

    st_txt = "فعال شد ✅" if country.econ_sat_unlocked else "غیرفعال شد ❌"
    await call.answer(f"ماهواره اقتصادی برای {country.name_fa} {st_txt}")
    await send_log(
        bot,
        f"🛠 <b>تغییر وضعیت ماهواره اقتصادی در پنل گاد</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"وضعیت جدید: {st_txt}",
    )
    await _show_country_panel(call, session, country_id)


@router.callback_query(F.data.startswith("godfac:"))
async def cb_god_facilities(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش فهرست تأسیسات و کارخانه‌های نظامی یک کشور در پنل گاد (v1.9)."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_facilities(call, session, int(call.data.split(":")[1]))


async def _render_god_facilities(
    call: CallbackQuery, session: AsyncSession, cid: int, page: int = 0
) -> None:
    """
    بدنه‌ی رندر فهرست تأسیسات/کارخانه‌ها (بدون call.answer تا قابل‌استفاده‌ی مجدد باشد).

    (v1.11.1) صفحه‌بندی‌شده و به‌تفکیک نوع؛ پیش‌تر با زیادشدن تأسیسات هم متن پیام
    و هم تعداد دکمه‌ها از حد تلگرام رد می‌شد.
    """
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return

    facilities = await fac_repo.list_facilities(session, cid)
    factories = await milfac_repo.list_factories(session, cid)

    # شمارش به‌تفکیک نوع (برای دید سریع مدیر)
    per_type: dict[str, int] = {}
    for f in facilities:
        per_type[f.type] = per_type.get(f.type, 0) + 1

    lines = [header(f"تأسیسات و کارخانه‌های {country.flag} {country.name_fa}", "🏭"), ""]

    lines.append("📊 <b>خلاصه به‌تفکیک نوع:</b>")
    if per_type:
        for tval, n in per_type.items():
            try:
                label = FACILITY_FA[FacilityType(tval)]
            except (ValueError, KeyError):
                label = tval
            lines.append(f"• {label}: {fa_number(n)} عدد")
    else:
        lines.append("—")

    total_pages = max(1, (len(facilities) + GOD_FACILITY_PAGE_SIZE - 1) // GOD_FACILITY_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = facilities[page * GOD_FACILITY_PAGE_SIZE : (page + 1) * GOD_FACILITY_PAGE_SIZE]

    lines.append("")
    lines.append(
        f"🏗 <b>تأسیسات</b> ({fa_number(len(facilities))}) — "
        f"صفحه {fa_number(page + 1)} از {fa_number(total_pages)}:"
    )
    if chunk:
        for idx, f in enumerate(chunk, start=page * GOD_FACILITY_PAGE_SIZE + 1):
            try:
                label = FACILITY_FA[FacilityType(f.type)]
            except (ValueError, KeyError):
                label = f.type
            if f.resource:
                try:
                    label += f" {RESOURCE_FA[ResourceType(f.resource)]}"
                except (ValueError, KeyError):
                    pass
            lines.append(f"{fa_number(idx)}. {label} — 📍 {f.location or '—'}")
    else:
        lines.append("—")

    lines.append("")
    lines.append(f"🏭 <b>کارخانه‌های نظامی</b> ({fa_number(len(factories))}):")
    if factories:
        for f in factories:
            try:
                label = MIL_FACTORY_FA[MilitaryFactoryType(f.factory_type)]
            except (ValueError, KeyError):
                label = f.factory_type
            lines.append(f"• {label} — بازتولید {f.asset_name} (📍 {f.location or '—'})")
    else:
        lines.append("—")

    # دکمه‌ی حذف فقط برای تأسیسات همین صفحه + ناوبری + دکمه‌های افزودن
    builder = InlineKeyboardBuilder()
    for f in chunk:
        try:
            label = FACILITY_FA[FacilityType(f.type)]
        except (ValueError, KeyError):
            label = f.type
        loc = (f.location or "—")[:18]
        builder.button(
            text=f"🗑 {label} — {loc}",
            callback_data=f"godfacdel:{cid}:{f.id}",
            style=STYLE_NO,
        )
    for f in factories:
        try:
            label = MIL_FACTORY_FA[MilitaryFactoryType(f.factory_type)]
        except (ValueError, KeyError):
            label = f.factory_type
        builder.button(text=f"🗑 {label}", callback_data=f"godmfdel:{cid}:{f.id}", style=STYLE_NO)
    builder.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ صفحه قبلی", callback_data=f"godfacpg:{cid}:{page - 1}", style=STYLE_MAIN
        ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            text="صفحه بعدی ▶️", callback_data=f"godfacpg:{cid}:{page + 1}", style=STYLE_MAIN
        ))
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(
            text="➕ افزودن تأسیسات", callback_data=f"godfacadd:{cid}", style=STYLE_OK
        ),
        InlineKeyboardButton(
            text="➕ افزودن کارخانه", callback_data=f"godmfadd:{cid}", style=STYLE_OK
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    )
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godfacpg:"))
async def cb_god_facilities_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ناوبری صفحه‌های فهرست تأسیسات در پنل گاد (v1.11.1)."""
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, page_s = call.data.split(":", 2)
    await _render_god_facilities(call, session, int(cid_s), int(page_s))


# ============================================================
#  حذف/افزودن تأسیسات و کارخانه‌های نظامی (v1.11)
# ============================================================
@router.callback_query(F.data.startswith("godfacdel:"))
async def cb_god_fac_delete(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, cid_s, fid_s = call.data.split(":", 2)
    cid, fid = int(cid_s), int(fid_s)
    facility = await session.get(Facility, fid)
    if facility is None or facility.country_id != cid:
        await call.answer("تأسیسات یافت نشد.", show_alert=True)
        return
    await session.delete(facility)
    await call.answer("تأسیسات حذف شد 🗑")
    await _render_god_facilities(call, session, cid)


@router.callback_query(F.data.startswith("godmfdel:"))
async def cb_god_mf_delete(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, cid_s, fid_s = call.data.split(":", 2)
    cid, fid = int(cid_s), int(fid_s)
    factory = await session.get(MilitaryFactory, fid)
    if factory is None or factory.country_id != cid:
        await call.answer("کارخانه یافت نشد.", show_alert=True)
        return
    await session.delete(factory)
    await call.answer("کارخانه حذف شد 🗑")
    await _render_god_facilities(call, session, cid)


# ----- افزودن تأسیسات -----
@router.callback_query(F.data.startswith("godfacadd:"))
async def cb_god_fac_add(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    builder = InlineKeyboardBuilder()
    for ft in FacilityType:
        builder.button(text=FACILITY_FA[ft], callback_data=f"godfact:{cid}:{ft.value}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("🏗 نوع تأسیسات جدید را انتخاب کنید:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godfact:"))
async def cb_god_fac_type(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, ftype = call.data.split(":", 2)
    cid = int(cid_s)
    if FacilityType(ftype) == FacilityType.MINE:
        builder = InlineKeyboardBuilder()
        for r in (ResourceType.COAL, ResourceType.ALUMINUM, ResourceType.IRON, ResourceType.GOLD):
            builder.button(text=RESOURCE_FA[r], callback_data=f"godfacr:{cid}:{ftype}:{r.value}", style=STYLE_OK)
        builder.button(text="🔙 بازگشت", callback_data=f"godfacadd:{cid}", style=STYLE_MAIN)
        builder.adjust(2)
        await call.message.edit_text("⛏ منبع معدن را انتخاب کنید:", reply_markup=builder.as_markup())
        return
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="facadd_loc", god_country=cid, god_ftype=ftype, god_resource=None)
    await call.message.edit_text(
        "📍 محل احداث تأسیسات را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
        ]]),
    )


@router.callback_query(F.data.startswith("godfacr:"))
async def cb_god_fac_resource(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, ftype, resource = call.data.split(":", 3)
    cid = int(cid_s)
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="facadd_loc", god_country=cid, god_ftype=ftype, god_resource=resource)
    await call.message.edit_text(
        "📍 محل احداث معدن را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ----- افزودن کارخانه نظامی -----
@router.callback_query(F.data.startswith("godmfadd:"))
async def cb_god_mf_add(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    builder = InlineKeyboardBuilder()
    for ft in MilitaryFactoryType:
        builder.button(text=MIL_FACTORY_FA[ft], callback_data=f"godmft:{cid}:{ft.value}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("🏭 نوع کارخانه‌ی جدید را انتخاب کنید:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godmft:"))
async def cb_god_mf_type(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, ftype = call.data.split(":", 2)
    cid = int(cid_s)
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="mfadd_name", god_country=cid, god_ftype=ftype)
    await call.message.edit_text(
        "📦 نام قلم تجهیزاتی که این کارخانه بازتولید می‌کند را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  لایسنس‌های تکنولوژی تسلیحاتی — v2.9
# ============================================================
async def _render_god_tech(call: CallbackQuery, session: AsyncSession, cid: int) -> None:
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return

    licenses = await tech_repo.list_licenses_for_country(session, cid)
    lines = [
        header(f"لایسنس‌های تکنولوژی {country.flag} {country.name_fa}", "🔬"),
        "",
        f"تعداد لایسنس‌های فعال: <b>{fa_number(len(licenses))}</b> مورد",
        DIVIDER,
    ]
    builder = InlineKeyboardBuilder()
    if not licenses:
        lines.append("<i>هیچ لایسنس فعالی برای این کشور ثبت نشده است.</i>")
    else:
        for lic in licenses:
            origin_c = await countries_repo.get_country(session, lic.origin_country_id)
            origin_name = f"{origin_c.flag} {origin_c.name_fa}" if origin_c else str(lic.origin_country_id)
            lines.append(f"• <b>{lic.equipment_name}</b> (سازنده: {origin_name})")
            builder.button(
                text=f"🗑 حذف: {lic.equipment_name[:18]}",
                callback_data=f"godtechdel:{cid}:{lic.id}",
                style=STYLE_NO,
            )

    builder.button(text="➕ اعطای لایسنس دستی", callback_data=f"godtechadd:{cid}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت به مدیریت کشور", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "god:tech")
async def cb_god_tech_countries(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    countries = await countries_repo.list_countries(session)
    builder = InlineKeyboardBuilder()
    for c in countries:
        mark = "🟢" if c.is_claimed else "⚪️"
        builder.button(text=f"{mark} {c.flag} {c.name_fa}", callback_data=f"godtech:{c.id}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text(
        header("مدیریت لایسنس‌های تکنولوژی تسلیحاتی", "🔬") + "\n\nکشور مورد نظر را انتخاب کنید:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("godtech:"))
async def cb_god_tech_detail(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    await _render_god_tech(call, session, cid)


@router.callback_query(F.data.startswith("godtechdel:"))
async def cb_god_tech_del(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, cid_s, lic_id_s = call.data.split(":")
    cid = int(cid_s)
    lic_id = int(lic_id_s)
    ok = await tech_repo.revoke_license(session, lic_id)
    await session.commit()
    if ok:
        await call.answer("لایسنس با موفقیت لغو و حذف شد.", show_alert=True)
        await send_log(bot, f"🔬 <b>لغو لایسنس در پنل گاد</b>\nکشور: {cid} | شناسه لایسنس: {lic_id}")
    else:
        await call.answer("لایسنس یافت نشد.", show_alert=True)
    await _render_god_tech(call, session, cid)


@router.callback_query(F.data.startswith("godtechadd:"))
async def cb_god_tech_add(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="techadd_name", god_country=cid)
    await call.message.edit_text(
        "🔬 نام تجهیزاتی که می‌خواهید لایسنس آن به این کشور اعطا شود را وارد کنید (دقیقاً مشابه نام در سیستم):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godtech:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  تحریم‌ها (مشاهده/لغو/افزودن) — v1.11
# ============================================================
@router.callback_query(F.data == "god:sanctions")
async def cb_god_sanctions(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_sanctions(call, session)


async def _render_god_sanctions(call: CallbackQuery, session: AsyncSession) -> None:
    sanctions = (await session.execute(
        select(Sanction).where(Sanction.active.is_(True)).order_by(Sanction.id.desc())
    )).scalars().all()
    lines = [header("تحریم‌های فعال", "🚫"), ""]
    builder = InlineKeyboardBuilder()
    if sanctions:
        for s in sanctions:
            frm = await countries_repo.get_country(session, s.from_country)
            to = await countries_repo.get_country(session, s.to_country)
            try:
                stype = SANCTION_FA[SanctionType(s.sanction_type)]
            except (ValueError, KeyError):
                stype = s.sanction_type or "—"
            frm_n = frm.name_fa if frm else "?"
            to_n = to.name_fa if to else "?"
            lines.append(f"• {frm_n} → {to_n}: {stype}")
            builder.button(text=f"🗑 {frm_n}→{to_n} ({stype})", callback_data=f"godsancdel:{s.id}", style=STYLE_NO)
    else:
        lines.append("—")
    builder.button(text="➕ افزودن تحریم", callback_data="godsancadd", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godsancdel:"))
async def cb_god_sanction_delete(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    sid = int(call.data.split(":")[1])
    s = await diplomacy_repo.get_sanction(session, sid)
    if s is None:
        await call.answer("تحریم یافت نشد.", show_alert=True)
        return
    await diplomacy_repo.deactivate_sanction(session, sid)
    await call.answer("تحریم لغو شد 🗑")
    await send_to_admin_group(bot, AdminGroupType.SANCTION_BILL, "🚫 <b>لغو تحریم توسط مدیریت</b>")
    await _render_god_sanctions(call, session)


def _god_countries_kb(countries, prefix: str, back: str) -> InlineKeyboardMarkup:
    """کیبورد انتخاب کشور با callback به شکل '{prefix}:{cid}'."""
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(text=f"{c.flag} {c.name_fa}", callback_data=f"{prefix}:{c.id}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data=back, style=STYLE_MAIN)
    builder.adjust(2)
    return builder.as_markup()


@router.callback_query(F.data == "godsancadd")
async def cb_god_sanction_add(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    countries = await countries_repo.list_countries(session)
    await call.message.edit_text(
        "🚫 کشور وضع‌کننده‌ی تحریم را انتخاب کنید:",
        reply_markup=_god_countries_kb(countries, "godsancf", "god:sanctions"),
    )


@router.callback_query(F.data.startswith("godsancf:"))
async def cb_god_sanction_from(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    frm = int(call.data.split(":")[1])
    countries = [c for c in await countries_repo.list_countries(session) if c.id != frm]
    await call.message.edit_text(
        "🎯 کشور هدف تحریم را انتخاب کنید:",
        reply_markup=_god_countries_kb(countries, f"godsanct:{frm}", "godsancadd"),
    )


@router.callback_query(F.data.startswith("godsanct:"))
async def cb_god_sanction_to(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, frm_s, to_s = call.data.split(":", 2)
    frm, to = int(frm_s), int(to_s)
    builder = InlineKeyboardBuilder()
    for st in SanctionType:
        builder.button(text=SANCTION_FA[st], callback_data=f"godsancok:{frm}:{to}:{st.value}", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="godsancadd", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("🚫 نوع تحریم را انتخاب کنید:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godsancok:"))
async def cb_god_sanction_create(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, frm_s, to_s, stype = call.data.split(":", 3)
    frm, to = int(frm_s), int(to_s)
    sanction = Sanction(from_country=frm, to_country=to, sanction_type=stype, active=True)
    await diplomacy_repo.add_sanction(session, sanction)
    await call.answer("تحریم اعمال شد ✅")
    frm_c = await countries_repo.get_country(session, frm)
    to_c = await countries_repo.get_country(session, to)
    await send_to_admin_group(
        bot,
        AdminGroupType.SANCTION_BILL,
        "🚫 <b>وضع تحریم توسط مدیریت</b>\n"
        f"{frm_c.name_fa if frm_c else '?'} → {to_c.name_fa if to_c else '?'}: "
        f"{SANCTION_FA.get(SanctionType(stype), stype)}",
    )
    await _render_god_sanctions(call, session)


# ============================================================
#  سرمایه‌گذاری‌ها (مشاهده/حذف/افزودن) — v1.11
# ============================================================
@router.callback_query(F.data == "god:invest")
async def cb_god_invest(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_invest(call, session)


async def _render_god_invest(
    call: CallbackQuery, session: AsyncSession, page: int = 0
) -> None:
    """
    فهرست سرمایه‌گذاری‌های فعال در پنل گاد.

    (v1.11.1) صفحه‌بندی‌شده؛ با زیادشدن سرمایه‌گذاری‌ها پیام و تعداد دکمه‌ها
    از حد تلگرام رد می‌شد.
    """
    items = (await session.execute(
        select(Investment).where(Investment.active.is_(True)).order_by(Investment.id.desc())
    )).scalars().all()

    total_pages = max(1, (len(items) + GOD_INVEST_PAGE_SIZE - 1) // GOD_INVEST_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * GOD_INVEST_PAGE_SIZE : (page + 1) * GOD_INVEST_PAGE_SIZE]

    lines = [header("سرمایه‌گذاری‌های فعال", "📈"), ""]
    lines.append(
        f"📊 مجموع: <b>{fa_number(len(items))}</b> | "
        f"صفحه {fa_number(page + 1)} از {fa_number(total_pages)}"
    )
    lines.append("")

    builder = InlineKeyboardBuilder()
    if chunk:
        for idx, inv in enumerate(chunk, start=page * GOD_INVEST_PAGE_SIZE + 1):
            investor = await countries_repo.get_country(session, inv.investor_country)
            target = await countries_repo.get_country(session, inv.target_country)
            fa, _pct = INVESTMENT_CATEGORIES.get(inv.category, (inv.category, 0.0))
            inv_n = investor.name_fa if investor else "?"
            tgt_n = "داخلی" if inv.investor_country == inv.target_country else (target.name_fa if target else "?")
            lines.append(f"{fa_number(idx)}. {inv_n} → {tgt_n} | {fa}: {fa_money(inv.amount)}")
            builder.button(
                text=f"🗑 {inv_n}→{tgt_n} ({fa})",
                callback_data=f"godinvdel:{inv.id}",
                style=STYLE_NO,
            )
    else:
        lines.append("—")
    builder.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ صفحه قبلی", callback_data=f"godinvpg:{page - 1}", style=STYLE_MAIN
        ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            text="صفحه بعدی ▶️", callback_data=f"godinvpg:{page + 1}", style=STYLE_MAIN
        ))
    if nav:
        builder.row(*nav)

    builder.row(InlineKeyboardButton(
        text="➕ افزودن سرمایه‌گذاری", callback_data="godinvadd", style=STYLE_OK
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN
    ))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godinvpg:"))
async def cb_god_invest_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ناوبری صفحه‌های فهرست سرمایه‌گذاری در پنل گاد (v1.11.1)."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_invest(call, session, int(call.data.split(":")[1]))


@router.callback_query(F.data.startswith("godinvdel:"))
async def cb_god_invest_delete(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    inv_id = int(call.data.split(":")[1])
    inv = await session.get(Investment, inv_id)
    if inv is None:
        await call.answer("سرمایه‌گذاری یافت نشد.", show_alert=True)
        return
    inv.active = False
    await call.answer("حذف شد 🗑")
    await send_log(bot, "📈 <b>حذف سرمایه‌گذاری توسط مدیریت</b>")
    await _render_god_invest(call, session)


@router.callback_query(F.data == "godinvadd")
async def cb_god_invest_add(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    countries = await countries_repo.list_countries(session)
    await call.message.edit_text(
        "📈 کشور سرمایه‌گذار را انتخاب کنید:",
        reply_markup=_god_countries_kb(countries, "godinvf", "god:invest"),
    )


@router.callback_query(F.data.startswith("godinvf:"))
async def cb_god_invest_from(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    frm = int(call.data.split(":")[1])
    countries = await countries_repo.list_countries(session)
    await call.message.edit_text(
        "🎯 کشور هدف سرمایه‌گذاری را انتخاب کنید (می‌تواند خودش باشد = داخلی):",
        reply_markup=_god_countries_kb(countries, f"godinvt:{frm}", "godinvadd"),
    )


@router.callback_query(F.data.startswith("godinvt:"))
async def cb_god_invest_to(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, frm_s, to_s = call.data.split(":", 2)
    frm, to = int(frm_s), int(to_s)
    builder = InlineKeyboardBuilder()
    for key, (fa, pct) in INVESTMENT_CATEGORIES.items():
        builder.button(text=f"{fa} ({int(pct)}٪)", callback_data=f"godinvc:{frm}:{to}:{key}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="godinvadd", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("📊 دسته‌ی سرمایه‌گذاری را انتخاب کنید:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godinvc:"))
async def cb_god_invest_category(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, frm_s, to_s, key = call.data.split(":", 3)
    await state.set_state(GodForm.entering_value)
    await state.update_data(
        god_kind="invadd_amount", god_inv_from=int(frm_s), god_inv_to=int(to_s), god_inv_cat=key
    )
    await call.message.edit_text(
        "💵 مبلغ سرمایه‌گذاری را وارد کنید (مثلاً 1b):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data="god:invest", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  سیستم تلفات دستی (v1.11)
# ============================================================
@router.callback_query(F.data == "god:casualty")
async def cb_god_casualty(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    countries = await countries_repo.list_countries(session)
    await call.message.edit_text(
        header("سیستم تلفات", "💥") + "\n\nکشور موردنظر را انتخاب کنید:",
        reply_markup=_god_countries_kb(countries, "godcasc", "god:home"),
    )


@router.callback_query(F.data.startswith("godcasc:"))
async def cb_god_casualty_country(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    builder = InlineKeyboardBuilder()
    icons = {"ground": "🪖", "navy": "🚢", "air": "✈️"}
    for key, (fa, _stem, _branches) in DEPLOY_BRANCHES.items():
        builder.button(text=f"{icons.get(key,'')} {fa}", callback_data=f"godcasb:{cid}:{key}", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="god:casualty", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("💥 نوع نیرو را انتخاب کنید:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godcasb:"))
async def cb_god_casualty_branch(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, key = call.data.split(":", 2)
    cid = int(cid_s)
    if key not in DEPLOY_BRANCHES:
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    _fa, _stem, branches = DEPLOY_BRANCHES[key]
    assets = await mil_repo.list_assets(session, cid)
    matching = [a for a in assets if a.branch in branches and a.count > 0]
    if not matching:
        await call.message.edit_text(
            "⚠️ این کشور در این نیرو تجهیزاتی ندارد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"godcasc:{cid}", style=STYLE_MAIN)
            ]]),
        )
        return
    await state.update_data(god_cas_assets=[a.name for a in matching])
    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(matching):
        builder.button(text=f"{a.name} ({fa_number(a.count)})", callback_data=f"godcasa:{cid}:{idx}", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data=f"godcasc:{cid}", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("💥 کدام قلم تلفات داشته است؟", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godcasa:"))
async def cb_god_casualty_asset(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, idx_s = call.data.split(":", 2)
    cid, idx = int(cid_s), int(idx_s)
    data = await state.get_data()
    assets = data.get("god_cas_assets", [])
    if idx >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    name = assets[idx]
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="casualty", god_country=cid, god_asset=name)
    await call.message.edit_text(
        f"🔢 تعداد تلفات «{name}» را وارد کنید (از موجودی کسر می‌شود):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godcasc:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  ویرایش اقتصاد
# ============================================================
@router.callback_query(F.data.startswith("godeco:"))
async def cb_eco_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return
    builder = InlineKeyboardBuilder()
    for field, fa in _NUMERIC_FIELDS.items():
        builder.button(text=fa, callback_data=f"gset:{cid}:{field}", style=STYLE_OK)
    for field, (fa, _vals) in _ENUM_FIELDS.items():
        builder.button(text=fa, callback_data=f"gset:{cid}:{field}", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text(
        f"✏️ کدام شاخص {country.flag} {country.name_fa} را ویرایش می‌کنید؟\n"
        + render_economy_panel(country),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("gset:"))
async def cb_eco_field(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, field = call.data.split(":", 2)
    cid = int(cid_s)

    # فیلد متنی (enum): نمایش دکمه‌های مقدار
    if field in _ENUM_FIELDS:
        fa, vals = _ENUM_FIELDS[field]
        builder = InlineKeyboardBuilder()
        for val, val_fa in vals.items():
            builder.button(text=val_fa, callback_data=f"gsetv:{cid}:{field}:{val}", style=STYLE_OK)
        builder.button(text="🔙 بازگشت", callback_data=f"godeco:{cid}", style=STYLE_MAIN)
        builder.adjust(2)
        await call.message.edit_text(f"مقدار جدید «{fa}» را انتخاب کنید:", reply_markup=builder.as_markup())
        return

    # فیلد عددی: درخواست مقدار
    fa = _NUMERIC_FIELDS.get(field, field)
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="eco", god_country=cid, god_field=field)
    await call.message.edit_text(
        f"🔢 مقدار جدید «{fa}» را وارد کنید (می‌توانید از k/m/b استفاده کنید):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godeco:{cid}", style=STYLE_MAIN)
        ]]),
    )


@router.callback_query(F.data.startswith("gsetv:"))
async def cb_eco_set_enum(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer("ثبت شد ✅")
    _, cid_s, field, value = call.data.split(":", 3)
    cid = int(cid_s)
    country = await countries_repo.get_country(session, cid)
    if country is None or field not in _ENUM_FIELDS:
        await call.message.edit_text("خطا.", reply_markup=_home_kb())
        return
    setattr(country, field, value)
    await _show_country_panel(call, session, cid)


# ============================================================
#  ویرایش ذخایر
# ============================================================
@router.callback_query(F.data.startswith("godres:"))
async def cb_res_menu(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return
    reserves = await reserves_repo.list_reserves(session, cid)
    builder = InlineKeyboardBuilder()
    for r in ResourceType:
        builder.button(text=RESOURCE_FA[r], callback_data=f"gres:{cid}:{r.value}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text(
        render_reserves_panel(country, reserves) + "\n\n📦 کدام ذخیره را ویرایش می‌کنید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("gres:"))
async def cb_res_field(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, resource = call.data.split(":", 2)
    cid = int(cid_s)
    try:
        unit = RESOURCE_UNIT_FA[ResourceType(resource)]
        rname = RESOURCE_FA[ResourceType(resource)]
    except (ValueError, KeyError):
        unit, rname = "", resource
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="res", god_country=cid, god_resource=resource)
    await call.message.edit_text(
        f"🔢 مقدار جدید «{rname}» را وارد کنید (به {unit}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godres:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  ویرایش تجهیزات نظامی
# ============================================================
@router.callback_query(F.data.startswith("godmil:"))
async def cb_mil_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return
    assets = await mil_repo.list_assets(session, cid)
    if not assets:
        await call.message.edit_text(
            "⚠️ این کشور تجهیزاتی ندارد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
            ]]),
        )
        return
    # ذخیره‌ی نام تجهیزات برای انتخاب با ایندکس
    await state.update_data(god_assets=[a.name for a in assets])
    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(assets):
        builder.button(
            text=f"{a.name} ({fa_number(a.count)})",
            callback_data=f"gmil:{cid}:{idx}",
            style=STYLE_OK,
        )
    builder.button(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("⚔️ کدام قلم تجهیزات را ویرایش می‌کنید؟", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gmil:"))
async def cb_mil_field(call: CallbackQuery, state: FSMContext) -> None:
    if not await _guard(call):
        return
    await call.answer()
    _, cid_s, idx_s = call.data.split(":", 2)
    cid, idx = int(cid_s), int(idx_s)
    data = await state.get_data()
    assets = data.get("god_assets", [])
    if idx >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    name = assets[idx]
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="mil", god_country=cid, god_asset=name)
    await call.message.edit_text(
        f"🔢 تعداد جدید «{name}» را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godmil:{cid}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  دریافت مقدار جدید (مشترک برای اقتصاد عددی/ذخیره/تجهیزات)
# ============================================================
def _god_back_country_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت به کشور", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    ]])


@router.message(GodForm.entering_value, F.text)
async def msg_god_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    kind = data.get("god_kind")

    # --- kindهای با ورودی متنی (نه عددی) ---
    if kind == "facadd_loc":
        await state.clear()
        cid = data.get("god_country")
        ftype = FacilityType(data.get("god_ftype"))
        resource = data.get("god_resource")
        location = message.text.strip()
        yield_amount, output_resource, intake = facility_yield_for(ftype, resource)
        facility = Facility(
            country_id=cid, type=ftype.value, resource=output_resource, location=location,
            budget=0.0, yield_amount=yield_amount, yield_interval_h=24, intake_amount=intake,
            active=True, last_yield_at=_utcnow(),
        )
        session.add(facility)
        country = await countries_repo.get_country(session, cid)
        await message.answer(
            f"✅ تأسیسات «{FACILITY_FA[ftype]}» در «{location}» برای {country.name_fa if country else cid} افزوده شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 تأسیسات", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
            ]]),
        )
        await send_log(bot, f"🏗 <b>افزودن تأسیسات توسط مدیریت</b>\n{FACILITY_FA[ftype]} برای کشور {cid}")
        return

    if kind == "mfadd_name":
        await state.set_state(GodForm.entering_value)
        await state.update_data(god_kind="mfadd_loc", god_mf_name=message.text.strip())
        cid = data.get("god_country")
        await message.answer(
            "📍 محل احداث کارخانه را وارد کنید:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 لغو", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
            ]]),
        )
        return

    if kind == "mfadd_loc":
        await state.clear()
        cid = data.get("god_country")
        ftype = MilitaryFactoryType(data.get("god_ftype"))
        name = data.get("god_mf_name", "")
        location = message.text.strip()
        yield_amount, interval_h = MIL_FACTORY_YIELD[ftype]
        factory = MilitaryFactory(
            country_id=cid, factory_type=ftype.value, asset_name=name,
            category=MIL_FACTORY_CATEGORY[ftype], unit="عدد", location=location,
            cost=0.0, yield_amount=yield_amount, yield_interval_h=interval_h,
            active=True, last_yield_at=_utcnow(),
        )
        await milfac_repo.add_factory(session, factory)
        await message.answer(
            f"✅ کارخانه‌ی «{MIL_FACTORY_FA[ftype]}» برای بازتولید «{name}» در «{location}» افزوده شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 تأسیسات", callback_data=f"godfac:{cid}", style=STYLE_MAIN)
            ]]),
        )
        await send_log(bot, f"🏭 <b>افزودن کارخانه نظامی توسط مدیریت</b>\n{MIL_FACTORY_FA[ftype]} برای کشور {cid}")
        return

    if kind == "techadd_name":
        await state.clear()
        cid = data.get("god_country")
        name = message.text.strip()
        country = await countries_repo.get_country(session, cid)
        origin_code = get_equipment_origin(name)
        origin_country = None
        if origin_code:
            origin_country = await countries_repo.get_country_by_name(session, origin_code)
        origin_id = origin_country.id if origin_country else cid

        await tech_repo.grant_license(
            session,
            holder_country_id=cid,
            origin_country_id=origin_id,
            equipment_name=name,
            price_paid=0.0,
        )
        await session.commit()
        origin_label = f"{origin_country.flag} {origin_country.name_fa}" if origin_country else "سیستم"
        await message.answer(
            f"✅ لایسنس بازتولید «{name}» (سازنده: {origin_label}) با موفقیت به {country.name_fa if country else cid} اعطا شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 لایسنس‌ها", callback_data=f"godtech:{cid}", style=STYLE_MAIN)
            ]]),
        )
        await send_log(
            bot,
            f"🔬 <b>اعطای دستی لایسنس توسط مدیریت</b>\n"
            f"کشور: {country.name_fa if country else cid}\n"
            f"تجهیز: {name}\n"
            f"سازنده: {origin_label}",
        )
        return

    if kind == "market_custom_reason":
        await state.clear()
        res_key = data.get("god_res")
        new_price = data.get("god_new_price")
        delta_pct = data.get("god_delta_pct")
        reason_text = message.text.strip()
        from ..services import market_service
        updated_mp = await market_service.update_price(
            session=session,
            resource=res_key,
            delta_pct=delta_pct,
            absolute_price=new_price,
            reason_code="ADMIN_MANUAL",
            custom_reason_text=reason_text,
        )
        await session.commit()
        await message.answer(
            f"✅ نرخ ذخیره <b>{res_key}</b> با موفقیت به <b>{fa_money(updated_mp.current_price)}</b> تغییر یافت.\n"
            f"📌 دلیل ثبت‌شده: {reason_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به بازار", callback_data="god:market", style=STYLE_MAIN)
            ]]),
        )
        await send_log(
            bot,
            f"📈 <b>تغییر دستی نرخ بازار توسط مدیریت</b>\n"
            f"ذخیره: {res_key}\n"
            f"نرخ جدید: {fa_money(updated_mp.current_price)}\n"
            f"روند: {updated_mp.trend} ({updated_mp.change_pct:+.1f}٪)\n"
            f"دلیل: {reason_text}",
        )
        return

    # --- kindهای با ورودی عددی ---
    value = parse_amount(message.text)
    if value is None:
        await message.answer("عدد نامعتبر است. لطفاً دوباره وارد کنید.")
        return

    if kind == "market_price_abs":
        res_key = data.get("god_res")
        await state.update_data(god_new_price=float(value))
        await _show_god_market_reason_picker(message, state, res_key, new_price=float(value))
        return

    if kind == "invadd_amount":
        await state.clear()
        frm = data.get("god_inv_from")
        to = data.get("god_inv_to")
        cat = data.get("god_inv_cat")
        fa, pct = INVESTMENT_CATEGORIES.get(cat, (cat, 0.0))
        inv = Investment(
            investor_country=frm, target_country=to, category=cat,
            amount=float(value), profit_pct=pct,
        )
        await inv_repo.add_investment(session, inv)
        await message.answer(
            f"✅ سرمایه‌گذاری «{fa}» به مبلغ {fa_money(float(value))} افزوده شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 سرمایه‌گذاری‌ها", callback_data="god:invest", style=STYLE_MAIN)
            ]]),
        )
        await send_log(bot, f"📈 <b>افزودن سرمایه‌گذاری توسط مدیریت</b>\n{fa}: {fa_money(float(value))}")
        return

    cid = data.get("god_country")
    await state.clear()
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await message.answer("کشور یافت نشد.")
        return

    if kind == "casualty":
        name = data.get("god_asset")
        await mil_repo.reduce_count(session, cid, name, int(value))
        asset = await mil_repo.get_asset_by_name(session, cid, name)
        remaining = asset.count if asset else 0
        await message.answer(
            f"💥 {fa_number(value)} فروند/دستگاه از «{name}» {country.name_fa} به‌عنوان تلفات کسر شد. "
            f"(باقی‌مانده: {fa_number(remaining)})",
            reply_markup=_god_back_country_kb(cid),
        )
        await send_log(
            bot,
            "💥 <b>اعمال تلفات توسط مدیریت</b>\n"
            f"کشور: {country.flag} {country.name_fa}\n"
            f"قلم: {name} | تلفات: {fa_number(value)}",
        )
        return

    if kind == "eco":
        field = data.get("god_field")
        if field == "population":
            setattr(country, field, int(value))
        elif field in _NUMERIC_FIELDS:
            setattr(country, field, float(value))
        await message.answer(
            f"✅ «{_NUMERIC_FIELDS.get(field, field)}» {country.name_fa} به {fa_number(value, 2)} تغییر کرد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به کشور", callback_data=f"godc:{cid}", style=STYLE_MAIN)
            ]]),
        )
    elif kind == "res":
        resource = data.get("god_resource")
        reserve = await reserves_repo.ensure_reserve(session, cid, resource)
        reserve.amount = max(0.0, float(value))
        await message.answer(
            f"✅ ذخیره‌ی «{RESOURCE_FA.get(ResourceType(resource), resource)}» {country.name_fa} به {fa_number(value)} تغییر کرد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به کشور", callback_data=f"godc:{cid}", style=STYLE_MAIN)
            ]]),
        )
    elif kind == "mil":
        name = data.get("god_asset")
        asset = await mil_repo.get_asset_by_name(session, cid, name)
        if asset is not None:
            asset.count = max(0, int(value))
        await message.answer(
            f"✅ تعداد «{name}» {country.name_fa} به {fa_number(value)} تغییر کرد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به کشور", callback_data=f"godc:{cid}", style=STYLE_MAIN)
            ]]),
        )


# ============================================================
#  آزادسازی (اخراج) و بن/رفع‌بن
# ============================================================
@router.callback_query(F.data.startswith("godrelease:"))
async def cb_release_confirm(call: CallbackQuery) -> None:
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔴 بله، آزاد کن", callback_data=f"godrelease2:{cid}", style=STYLE_NO),
        InlineKeyboardButton(text="❌ انصراف", callback_data=f"godc:{cid}", style=STYLE_MAIN),
    ]])
    await call.message.edit_text(
        "⚠️ با آزادسازی، مالکیت این کشور حذف می‌شود و بازیکن از آن اخراج می‌گردد. مطمئنید؟",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("godrelease2:"))
async def cb_release_do(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer("آزاد شد")
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return
    former_owner = country.owner_user_id
    await countries_repo.release_country(session, cid)
    if former_owner:
        # رفع تعلیق کاربر برکنارشده تا بتواند مجدداً کشورگیری کند
        await users_repo.set_suspended(session, former_owner, False)
        try:
            await bot.send_message(
                former_owner,
                f"🚪 مدیریت بازی شما را از رهبری {country.flag} {country.name_fa} برکنار کرد. "
                "می‌توانید کشور دیگری بگیرید. /claim",
            )
        except Exception:  # noqa: BLE001
            pass
    await _show_country_panel(call, session, cid)


@router.callback_query(F.data.startswith("godban:"))
async def cb_ban(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None or country.owner_user_id is None:
        await call.answer("این کشور مالک ندارد.", show_alert=True)
        return
    if settings.is_admin(country.owner_user_id):
        await call.answer("⛔️ امکان مسدودسازی ادمین یا مالک بازی وجود ندارد.", show_alert=True)
        return
    await users_repo.set_banned(session, country.owner_user_id, True)
    await call.answer("کاربر بن شد ⛔️")
    try:
        await bot.send_message(country.owner_user_id, "⛔️ دسترسی شما به بازی توسط مدیریت مسدود شد.")
    except Exception:  # noqa: BLE001
        pass
    await _show_country_panel(call, session, cid)


@router.callback_query(F.data.startswith("godunban:"))
async def cb_unban(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None or country.owner_user_id is None:
        await call.answer("این کشور مالک ندارد.", show_alert=True)
        return
    await users_repo.set_banned(session, country.owner_user_id, False)
    await call.answer("بن کاربر برداشته شد ✅")
    try:
        await bot.send_message(country.owner_user_id, "✅ دسترسی شما به بازی دوباره فعال شد.")
    except Exception:  # noqa: BLE001
        pass
    await _show_country_panel(call, session, cid)


@router.callback_query(F.data == "god:ban_list")
async def cb_ban_list(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش لیست کاربران بن‌شده و امکان رفع بن آن‌ها."""
    if not await _guard(call):
        return
    await call.answer()
    banned_users = await users_repo.list_banned_users(session)
    builder = InlineKeyboardBuilder()

    lines = [
        header("مدیریت بن کاربران", "⛔️"),
        f"\nتعداد کاربران مسدودشده: <b>{fa_number(len(banned_users))}</b> نفر\n",
        "💡 <i>جهت بن یا رفع بن سریع می‌توانید از دستورات زیر نیز استفاده کنید:</i>",
        "• <code>/ban 123456789</code> یا <code>/ban @username</code>",
        "• <code>/unban 123456789</code> یا <code>/unban @username</code>\n",
    ]

    if not banned_users:
        lines.append("🟢 هیچ کاربری در حال حاضر در کل ربات بن نشده است.")
    else:
        lines.append("فهرست کاربران مسدود:")
        for u in banned_users[:15]:
            uname = f"@{u.username}" if u.username else (u.first_name or "بدون نام")
            lines.append(f"• {uname} (<code>{u.telegram_id}</code>)")
            builder.button(
                text=f"✅ رفع بن {uname}",
                callback_data=f"god_unban_uid:{u.telegram_id}",
                style=STYLE_OK,
            )

    builder.button(text="🔙 بازگشت به گاد مود", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("god_unban_uid:"))
async def cb_god_unban_uid(call: CallbackQuery, session: AsyncSession) -> None:
    """رفع بن کاربر با آیدی از طریق پنل گاد."""
    if not await _guard(call):
        return
    uid = int(call.data.split(":")[1])
    await users_repo.set_banned(session, uid, False)
    await call.answer("بن کاربر برداشته شد ✅", show_alert=True)
    try:
        await bot.send_message(uid, "🟢 دسترسی شما به ربات توسط مدیریت آزاد شد. /start")
    except Exception:
        pass
    await send_log(
        bot,
        f"🟢 <b>رفع بن کاربر از پنل گاد</b>\nکاربر: <code>{uid}</code>\nتوسط: {call.from_user.id}",
    )
    await cb_ban_list(call, session)


@router.callback_query(F.data.startswith("godsuspend:"))
async def cb_suspend(call: CallbackQuery, session: AsyncSession) -> None:
    """تعلیق مالک کشور (v1.10.5) — متمایز از بن کامل."""
    if not await _guard(call):
        return
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None or country.owner_user_id is None:
        await call.answer("این کشور مالک ندارد.", show_alert=True)
        return
    if settings.is_admin(country.owner_user_id):
        await call.answer("⛔️ امکان تعلیق ادمین یا مالک بازی وجود ندارد.", show_alert=True)
        return
    await users_repo.set_suspended(session, country.owner_user_id, True)
    await call.answer("مالک معلق شد ⏸")
    try:
        await bot.send_message(
            country.owner_user_id,
            "⏸ کشور شما توسط مدیریت بازی معلق شد و فعلاً نمی‌توانید اقدامی انجام دهید.",
        )
    except Exception:  # noqa: BLE001
        pass
    await _show_country_panel(call, session, cid)


@router.callback_query(F.data.startswith("godunsuspend:"))
async def cb_unsuspend(call: CallbackQuery, session: AsyncSession) -> None:
    """رفع تعلیق مالک کشور (v1.10.5)."""
    if not await _guard(call):
        return
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None or country.owner_user_id is None:
        await call.answer("این کشور مالک ندارد.", show_alert=True)
        return
    await users_repo.set_suspended(session, country.owner_user_id, False)
    await call.answer("تعلیق مالک برداشته شد ▶️")
    try:
        await bot.send_message(
            country.owner_user_id,
            "▶️ تعلیق کشور شما برداشته شد؛ اکنون می‌توانید دوباره فعالیت کنید.",
        )
    except Exception:  # noqa: BLE001
        pass
    await _show_country_panel(call, session, cid)


# ============================================================
#  محموله‌های در راه: رساندن فوری
# ============================================================
@router.callback_query(F.data == "god:ship")
async def cb_ship_list(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await _render_ship_list(call, session)


async def _render_ship_list(call: CallbackQuery, session: AsyncSession) -> None:
    builder = InlineKeyboardBuilder()
    # محموله‌های تجاری در راه
    res_sales = (await session.execute(
        select(ResourceSale).where(ResourceSale.status == TradeStatus.IN_TRANSIT)
    )).scalars().all()
    for s in res_sales:
        seller = await countries_repo.get_country(session, s.seller_country)
        buyer = await countries_repo.get_country(session, s.buyer_country)
        try:
            rname = RESOURCE_FA[ResourceType(s.resource)]
        except (ValueError, KeyError):
            rname = s.resource
        label = f"📦 {seller.name_fa if seller else '?'}→{buyer.name_fa if buyer else '?'} ({rname})"
        builder.button(text=label, callback_data=f"gdeliver:res:{s.id}", style=STYLE_OK)
    # محموله‌های نظامی در راه
    mil_sales = (await session.execute(
        select(MilitarySale).where(MilitarySale.status == TradeStatus.IN_TRANSIT)
    )).scalars().all()
    for s in mil_sales:
        seller = await countries_repo.get_country(session, s.seller_country)
        buyer = await countries_repo.get_country(session, s.buyer_country)
        label = f"🪖 {seller.name_fa if seller else '?'}→{buyer.name_fa if buyer else '?'} ({s.name})"
        builder.button(text=label, callback_data=f"gdeliver:mil:{s.id}", style=STYLE_OK)

    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1)
    if not res_sales and not mil_sales:
        await call.message.edit_text("🚚 هیچ محموله‌ی در راهی وجود ندارد.", reply_markup=builder.as_markup())
        return
    await call.message.edit_text(
        "🚚 یک محموله را برای رساندن فوری انتخاب کنید:", reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gdeliver:"))
async def cb_deliver_now(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, kind, sid_s = call.data.split(":", 2)
    sid = int(sid_s)
    if kind == "res":
        sale = await session.get(ResourceSale, sid)
    else:
        sale = await session.get(MilitarySale, sid)
    if sale is None or sale.status != TradeStatus.IN_TRANSIT:
        await call.answer("این محموله دیگر در راه نیست.", show_alert=True)
        return
    # زمان رسیدن را به گذشته می‌بریم و زمان‌بند را همان‌جا اجرا می‌کنیم
    sale.ship_eta = _utcnow() - timedelta(seconds=1)
    await session.commit()
    await call.answer("در حال تحویل فوری...")

    from ..scheduler.jobs import process_military_shipments, process_shipments

    if kind == "res":
        await process_shipments(bot)
    else:
        await process_military_shipments(bot)
    await _render_ship_list(call, session)


# ============================================================
#  پروازهای دیپلماتیک: رساندن فوری و آغاز نشست
# ============================================================
@router.callback_query(F.data == "god:flights")
async def cb_flights_list(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    await call.answer()
    await _render_flights_list(call, session)


async def _render_flights_list(call: CallbackQuery, session: AsyncSession) -> None:
    builder = InlineKeyboardBuilder()
    # دیدارهای دوجانبه‌ی در حال سفر (پذیرفته‌شده اما هنوز نرسیده)
    meetings = (await session.execute(
        select(Meeting).where(Meeting.status == DiplomacyStatus.ACTIVE)
    )).scalars().all()
    now = _utcnow()
    shown = 0
    for m in meetings:
        eta = m.travel_eta
        if eta is not None and eta.tzinfo is None:
            eta = eta.replace(tzinfo=timezone.utc)
        if eta is None or eta <= now:
            continue  # رسیده است
        traveler = await countries_repo.get_country(session, m.traveler_country)
        host = await countries_repo.get_country(session, m.host_country)
        builder.button(
            text=f"✈️ {traveler.name_fa if traveler else '?'}→{host.name_fa if host else '?'}",
            callback_data=f"garrive:meet:{m.id}",
            style=STYLE_OK,
        )
        shown += 1
    # نشست‌های چندجانبه‌ی در انتظار (هنوز فعال نشده)
    groups = (await session.execute(
        select(GroupMeeting).where(GroupMeeting.status == DiplomacyStatus.PENDING)
    )).scalars().all()
    for g in groups:
        host = await countries_repo.get_country(session, g.host_country)
        builder.button(
            text=f"👥 {g.title} (میزبان {host.name_fa if host else '?'})",
            callback_data=f"garrive:gmeet:{g.id}",
            style=STYLE_OK,
        )
        shown += 1

    # پروازهای هیئت‌های دیپلماتیک به مجمع عمومی سازمان ملل متحد (نیویورک)
    un_participants = (await session.execute(
        select(UNAssemblyParticipant).where(UNAssemblyParticipant.status == "in_flight")
    )).scalars().all()
    for part in un_participants:
        country = await countries_repo.get_country(session, part.country_id)
        cname = f"{country.flag} {country.name_fa}" if country else f"کشور #{part.country_id}"
        builder.button(
            text=f"🇺🇳 {cname} → نیویورک",
            callback_data=f"garrive:unasmb:{part.id}",
            style=STYLE_OK,
        )
        shown += 1

    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1)
    if shown == 0:
        await call.message.edit_text("✈️ هیچ پرواز/نشست در انتظاری وجود ندارد.", reply_markup=builder.as_markup())
        return
    await call.message.edit_text(
        "✈️ یک مورد را برای رساندن فوری/آغاز نشست انتخاب کنید:", reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("garrive:"))
async def cb_arrive_now(call: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard(call):
        return
    _, kind, mid_s = call.data.split(":", 2)
    mid = int(mid_s)
    now = _utcnow()
    if kind == "meet":
        meeting = await session.get(Meeting, mid)
        if meeting is None or meeting.status != DiplomacyStatus.ACTIVE:
            await call.answer("این دیدار دیگر معتبر نیست.", show_alert=True)
            return
        meeting.travel_eta = now - timedelta(seconds=1)
        await session.commit()
        await call.answer("در حال آغاز نشست...")
        from ..scheduler.jobs import process_meetings

        await process_meetings(bot)
    elif kind == "unasmb":
        part = await session.get(UNAssemblyParticipant, mid)
        if part is None or part.status != "in_flight":
            await call.answer("این پرواز دیگر معتبر نیست یا فرود آمده است.", show_alert=True)
            return
        part.travel_eta = now - timedelta(seconds=1)
        await session.commit()
        await call.answer("پرواز به نیویورک فرود آمد!", show_alert=True)
        from ..scheduler.jobs import process_un_assembly

        await process_un_assembly(bot)
    else:
        group = await session.get(GroupMeeting, mid)
        if group is None or group.status != DiplomacyStatus.PENDING:
            await call.answer("این نشست دیگر معتبر نیست.", show_alert=True)
            return
        # زمان شروع را همین حالا قرار می‌دهیم تا زمان‌بند نشست را فعال کند
        group.start_at = now - timedelta(seconds=1)
        await session.commit()
        await call.answer("در حال آغاز نشست...")
        from ..scheduler.jobs import process_group_meetings

        await process_group_meetings(bot)
    await _render_flights_list(call, session)


# ============================================================
#  🇺🇳 مدیریت مجمع عمومی سازمان ملل (God Mode)
# ============================================================
@router.callback_query(F.data == "god:unasmb")
async def cb_god_unasmb(call: CallbackQuery, session: AsyncSession) -> None:
    """پنل مدیریت و پایش مجمع عمومی سازمان ملل متحد."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_unasmb(call, session)


async def _render_god_unasmb(call: CallbackQuery, session: AsyncSession) -> None:
    active_s = await un_repo.get_active_session(session)
    builder = InlineKeyboardBuilder()

    if not active_s:
        txt = (
            "🇺🇳 <b>مدیریت مجمع عمومی سازمان ملل متحد (God Mode):</b>\n\n"
            "⚠️ در حال حاضر هیچ اجلاسی در جریان نیست (یا بسته شده است)."
        )
        builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
        builder.adjust(1)
        await call.message.edit_text(txt, reply_markup=builder.as_markup())
        return

    # دریافت آمار حاضران
    parts = await un_repo.list_participants(session, active_s.id)
    in_flight = [p for p in parts if p.status == "in_flight"]
    in_ny = [p for p in parts if p.status == "in_new_york"]
    in_hall = [p for p in parts if p.status == "inside_hall"]

    status_fa = {
        "pending": "در انتظار ورود رهبران و پروازها (قبل از افتتاح)",
        "active": "🟢 صحن علنی فعال و در حال برگزاری",
        "closed": "پایان‌یافته",
    }.get(active_s.status, active_s.status)

    speaker_info = "—"
    if active_s.current_speaker_country_id:
        spk_c = await countries_repo.get_country(session, active_s.current_speaker_country_id)
        if spk_c:
            ends = _aware(active_s.speech_ends_at)
            rem = ""
            if ends:
                diff = int((ends - _utcnow()).total_seconds())
                if diff > 0:
                    rem = f" ({diff // 60}:{diff % 60:02d} باقی‌مانده)"
            speaker_info = f"{spk_c.flag} {spk_c.name_fa}{rem}"

    txt = (
        f"🇺🇳 <b>پنل نظارت مجمع عمومی سازمان ملل (God Mode):</b>\n\n"
        f"• <b>اجلاس:</b> دوره‌ی #{fa_number(active_s.id)}\n"
        f"• <b>عنوان:</b> {active_s.title}\n"
        f"• <b>وضعیت صحن:</b> {status_fa}\n"
        f"• <b>تریبون سخنران فعلی:</b> {speaker_info}\n\n"
        f"👥 <b>آمار مشارکت‌کنندگان:</b>\n"
        f"• ✈️ در حال پرواز به نیویورک: <b>{fa_number(len(in_flight))}</b>\n"
        f"• 🗽 در لابی/شهر نیویورک: <b>{fa_number(len(in_ny))}</b>\n"
        f"• 🏛 داخل تالار مجمع عمومی: <b>{fa_number(len(in_hall))}</b>\n"
        f"• 🌐 مجموع هیئت‌ها: <b>{fa_number(len(parts))}</b>\n"
    )

    if in_flight:
        builder.button(
            text="🛬 فرود فوری تمام پروازها به نیویورک",
            callback_data=f"god:unasmb_land_all:{active_s.id}",
            style=STYLE_OK,
        )
    if active_s.status == "pending":
        builder.button(
            text="🏛 آغاز و افتتاح فوری صحن علنی",
            callback_data=f"god:unasmb_force_act:{active_s.id}",
            style=STYLE_MAIN,
        )
    if active_s.status in ["pending", "active"]:
        builder.button(
            text="🚪 پایان دادن فوری به این اجلاس",
            callback_data=f"god:unasmb_force_close:{active_s.id}",
            style=STYLE_NO,
        )

    builder.button(text="🔄 بروزرسانی وضعیت", callback_data="god:unasmb", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به پنل اصلی", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text(txt, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("god:unasmb_land_all:"))
async def cb_god_unasmb_land_all(call: CallbackQuery, session: AsyncSession) -> None:
    """فرود فوری تمام پروازهای هیئت‌های دیپلماتیک به نیویورک."""
    if not await _guard(call):
        return
    sid = int(call.data.split(":")[2])
    now = _utcnow()
    res = await session.execute(
        select(UNAssemblyParticipant).where(
            UNAssemblyParticipant.session_id == sid,
            UNAssemblyParticipant.status == "in_flight",
        )
    )
    count = 0
    for part in res.scalars().all():
        part.travel_eta = now - timedelta(seconds=1)
        count += 1
    await session.commit()

    if count > 0:
        from ..scheduler.jobs import process_un_assembly
        await process_un_assembly(bot)
        await call.answer(f"✅ {fa_number(count)} پرواز با موفقیت در نیویورک فرود آمدند!", show_alert=True)
    else:
        await call.answer("هیچ پروازی در حال حاضر در هوا نبود.")
    await _render_god_unasmb(call, session)


@router.callback_query(F.data.startswith("god:unasmb_force_act:"))
async def cb_god_unasmb_force_act(call: CallbackQuery, session: AsyncSession) -> None:
    """افتتاح و فعال‌سازی اجباری صحن علنی توسط گاد مود."""
    if not await _guard(call):
        return
    sid = int(call.data.split(":")[2])
    asmb = await un_repo.get_session(session, sid)
    if asmb and asmb.status == "pending":
        asmb.status = "active"
        asmb.activated_at = _utcnow()
        await session.commit()
        await call.answer("🏛 صحن علنی مجمع عمومی رسماً افتتاح شد!", show_alert=True)
        await publish_news(
            bot,
            NewsCategory.DIPLOMACY,
            "🇺🇳 <b>آغاز صحن علنی مجمع عمومی سازمان ملل متحد در نیویورک:</b>\n"
            "با حضور گسترده هیئت‌های دیپلماتیک و سران کشورها، چکش افتتاح اجلاس مجمع عمومی به صدا درآمد.",
        )
    else:
        await call.answer("اجلاس یافت نشد یا از قبل فعال است.")
    await _render_god_unasmb(call, session)


@router.callback_query(F.data.startswith("god:unasmb_force_close:"))
async def cb_god_unasmb_force_close(call: CallbackQuery, session: AsyncSession) -> None:
    """پایان دادن اجباری به اجلاس توسط گاد مود."""
    if not await _guard(call):
        return
    sid = int(call.data.split(":")[2])
    await un_repo.close_session(session, sid)
    await session.commit()
    await call.answer("🚪 اجلاس مجمع عمومی خاتمه یافت.", show_alert=True)
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        "🇺🇳 <b>پایان رسمی اجلاس سالانه مجمع عمومی سازمان ملل متحد:</b>\n"
        "دبیرکل سازمان ملل متحد پایان کار این دوره از نشست سالانه مجمع عمومی را رسماً اعلام نمود.",
    )
    await _render_god_unasmb(call, session)


# ============================================================
#  ☢️ مدیریت برنامه‌های هسته‌ای (v1.10.4)
# ============================================================
@router.callback_query(F.data == "god:nuclear")
async def cb_god_nuclear(call: CallbackQuery, session: AsyncSession) -> None:
    """فهرست کشورهای دارای برنامه‌ی هسته‌ای."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_god_nuclear_list(call, session)


async def _render_god_nuclear_list(call: CallbackQuery, session: AsyncSession) -> None:
    """رندر فهرست برنامه‌های هسته‌ای فعال."""
    from ..database.repositories import nuclear as nuc_repo

    programs = await nuc_repo.list_active_programs(session)
    lines = [header("برنامه‌های هسته‌ای فعال", "☢️"), ""]
    builder = InlineKeyboardBuilder()

    if programs:
        for p in programs:
            c = await countries_repo.get_country(session, p.country_id)
            if c is None:
                continue
            mark = "🚨" if p.is_discovered else "🕵️"
            warheads = await nuc_repo.count_ready_warheads(session, p.country_id)
            lines.append(
                f"{mark} {c.flag} {c.name_fa} — فاز {fa_number(p.phase)} | "
                f"افشا {fa_number(p.exposure)}٪ | کلاهک: {fa_number(warheads)}"
            )
            builder.button(
                text=f"{c.flag} {c.name_fa}",
                callback_data=f"godnuc:{p.country_id}",
                style=STYLE_MAIN,
            )
    else:
        lines.append("— هیچ کشوری برنامه‌ی هسته‌ای فعالی ندارد.")

    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(2)
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godnuc:"))
async def cb_god_nuclear_country(call: CallbackQuery, session: AsyncSession) -> None:
    """پنل مدیریت برنامه‌ی هسته‌ای یک کشور."""
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    await _render_god_nuclear_country(call, session, cid)


async def _render_god_nuclear_country(
    call: CallbackQuery, session: AsyncSession, cid: int
) -> None:
    """رندر جزئیات برنامه‌ی هسته‌ای همراه ابزارهای مدیریتی."""
    from ..database.repositories import nuclear as nuc_repo
    from ..enums import NUCLEAR_FACILITY_STATUS_FA, NuclearFacilityStatus

    country = await countries_repo.get_country(session, cid)
    program = await nuc_repo.get_program(session, cid)
    if country is None or program is None:
        await call.answer("برنامه یافت نشد.", show_alert=True)
        return

    facilities = await nuc_repo.list_facilities(session, cid)
    warheads = await nuc_repo.count_ready_warheads(session, cid)
    discovered_fa = "🚨 کشف‌شده" if program.is_discovered else "مخفی"
    cover_fa = "فعال" if program.civilian_cover else "غیرفعال"
    npt_fa = "عضو" if program.npt_member else "خارج‌شده"

    lines = [
        header(f"برنامه‌ی هسته‌ای {country.flag} {country.name_fa}", "☢️"),
        "",
        f"🚩 فاز: {fa_number(program.phase)} از ۵",
        f"🕵️ شاخص افشا: {fa_number(program.exposure)}٪ ({discovered_fa})",
        f"🎭 پوشش صلح‌آمیز: {cover_fa} | 📜 NPT: {npt_fa}",
        "",
        f"🟡 کیک زرد: {fa_number(program.yellowcake_tons, 1)} تن | "
        f"💨 UF6: {fa_number(program.uf6_tons, 1)} تن",
        f"⚛️ ۳.۵٪: {fa_number(program.leu_35_kg, 1)}kg | ۲۰٪: {fa_number(program.leu_20_kg, 1)}kg",
        f"⚛️ ۶۰٪: {fa_number(program.heu_60_kg, 1)}kg | ۹۰٪: {fa_number(program.heu_90_kg, 1)}kg",
        f"⚙️ سانتریفیوژ: {fa_number(program.centrifuges)} | ☢️ کلاهک آماده: {fa_number(warheads)}",
        "",
        "🏗 <b>تأسیسات:</b>",
    ]
    if facilities:
        for f in facilities:
            status = NUCLEAR_FACILITY_STATUS_FA.get(
                NuclearFacilityStatus(f.status), f.status
            )
            ug = " 🕳" if f.is_underground else ""
            lines.append(f"• {f.name}{ug} — {f.location or '—'} ({status})")
    else:
        lines.append("—")

    builder = InlineKeyboardBuilder()
    if program.is_discovered:
        builder.button(text="🕵️ مخفی‌سازی مجدد", callback_data=f"godnuchide:{cid}", style=STYLE_OK)
    else:
        builder.button(text="🚨 افشای فوری برنامه", callback_data=f"godnucreveal:{cid}", style=STYLE_NO)
    builder.button(text="♻️ صفرکردن شاخص افشا", callback_data=f"godnuczero:{cid}", style=STYLE_OK)
    builder.button(text="⏸ توقف غنی‌سازی", callback_data=f"godnucstop:{cid}", style=STYLE_NO)
    builder.button(text="🗑 حذف کامل برنامه", callback_data=f"godnucwipe:{cid}", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="god:nuclear", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godnucreveal:"))
async def cb_god_nuclear_reveal(call: CallbackQuery, session: AsyncSession) -> None:
    """افشای فوری برنامه‌ی هسته‌ای توسط مدیریت."""
    if not await _guard(call):
        return
    from ..database.repositories import nuclear as nuc_repo

    cid = int(call.data.split(":")[1])
    program = await nuc_repo.get_program(session, cid)
    if program is None:
        await call.answer("برنامه یافت نشد.", show_alert=True)
        return
    program.is_discovered = True
    program.discovered_at = _utcnow()
    program.exposure = 100.0
    await session.commit()
    country = await countries_repo.get_country(session, cid)
    await call.answer("برنامه افشا شد 🚨")
    if country is not None:
        await send_log(
            bot,
            "🚨 <b>افشای برنامه‌ی هسته‌ای توسط مدیریت</b>\n"
            f"کشور: {country.flag} {country.name_fa}",
        )
    await _render_god_nuclear_country(call, session, cid)


@router.callback_query(F.data.startswith("godnuchide:"))
async def cb_god_nuclear_hide(call: CallbackQuery, session: AsyncSession) -> None:
    """بازگرداندن برنامه به حالت مخفی."""
    if not await _guard(call):
        return
    from ..database.repositories import nuclear as nuc_repo

    cid = int(call.data.split(":")[1])
    program = await nuc_repo.get_program(session, cid)
    if program is None:
        await call.answer("برنامه یافت نشد.", show_alert=True)
        return
    program.is_discovered = False
    program.discovered_at = None
    program.exposure = 0.0
    await session.commit()
    await call.answer("برنامه دوباره مخفی شد 🕵️")
    await _render_god_nuclear_country(call, session, cid)


@router.callback_query(F.data.startswith("godnuczero:"))
async def cb_god_nuclear_zero(call: CallbackQuery, session: AsyncSession) -> None:
    """صفرکردن شاخص افشا."""
    if not await _guard(call):
        return
    from ..database.repositories import nuclear as nuc_repo

    cid = int(call.data.split(":")[1])
    program = await nuc_repo.get_program(session, cid)
    if program is None:
        await call.answer("برنامه یافت نشد.", show_alert=True)
        return
    program.exposure = 0.0
    await session.commit()
    await call.answer("شاخص افشا صفر شد ♻️")
    await _render_god_nuclear_country(call, session, cid)


@router.callback_query(F.data.startswith("godnucstop:"))
async def cb_god_nuclear_stop(call: CallbackQuery, session: AsyncSession) -> None:
    """توقف اضطراری غنی‌سازی یک کشور."""
    if not await _guard(call):
        return
    from ..database.repositories import nuclear as nuc_repo

    cid = int(call.data.split(":")[1])
    program = await nuc_repo.get_program(session, cid)
    if program is None:
        await call.answer("برنامه یافت نشد.", show_alert=True)
        return
    program.enrich_tier = None
    program.enrich_centrifuges = 0
    program.swu_accumulated = 0.0
    program.enrich_started_at = None
    program.last_enrich_tick_at = None
    await session.commit()
    await call.answer("غنی‌سازی متوقف شد ⏸")
    await _render_god_nuclear_country(call, session, cid)


@router.callback_query(F.data.startswith("godnucwipe:"))
async def cb_god_nuclear_wipe_ask(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید دومرحله‌ای برای حذف کامل برنامه (عملیات مخرب)."""
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ بله، همه‌چیز حذف شود", callback_data=f"godnucwipeok:{cid}", style=STYLE_NO)
    builder.button(text="❌ انصراف", callback_data=f"godnuc:{cid}", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text(
        header("حذف کامل برنامه‌ی هسته‌ای", "⚠️") + "\n\n"
        f"کشور: {country.flag} <b>{country.name_fa}</b>\n\n"
        "🚨 این عملیات <b>غیرقابل‌بازگشت</b> است: تمام تأسیسات، تحقیقات، سانتریفیوژها، "
        "ذخایر غنی‌شده و کلاهک‌های این کشور برای همیشه حذف می‌شوند.\n\n"
        "آیا کاملاً مطمئنید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("godnucwipeok:"))
async def cb_god_nuclear_wipe(call: CallbackQuery, session: AsyncSession) -> None:
    """اجرای حذف کامل برنامه‌ی هسته‌ای یک کشور."""
    if not await _guard(call):
        return
    from sqlalchemy import delete as _delete

    from ..database.models import (
        NuclearFacility,
        NuclearProgram,
        NuclearTech,
        NuclearTest,
        NuclearWarhead,
    )

    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    for model in (NuclearWarhead, NuclearTest, NuclearFacility, NuclearTech, NuclearProgram):
        await session.execute(_delete(model).where(model.country_id == cid))
    await session.commit()
    await call.answer("برنامه‌ی هسته‌ای حذف شد 🗑", show_alert=True)
    if country is not None:
        await send_log(
            bot,
            "🗑 <b>حذف کامل برنامه‌ی هسته‌ای توسط مدیریت</b>\n"
            f"کشور: {country.flag} {country.name_fa}",
        )
    await _render_god_nuclear_list(call, session)


# ============================================================
#  🏗 مدیریت پروژه‌های اقتصادی در گاد مود (آپدیت شماره ۹)
# ============================================================

@router.callback_query(F.data == "god:projects")
async def cb_god_projects_all(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده تمام پروژه‌های فعال در پنل گاد مود."""
    if not await _guard(call):
        return
    await call.answer()
    from ..database.repositories import economic_projects as proj_repo
    from ..enums import ECONOMIC_PROJECT_STATUS_FA, EconomicProjectStatus

    projects = await proj_repo.list_all_active(session)
    builder = InlineKeyboardBuilder()

    text_lines = [header("مدیریت پروژه‌های اقتصادی (گاد مود)", "🏗"), ""]
    if not projects:
        text_lines.append("در حال حاضر هیچ پروژه فعالی در بازی وجود ندارد.")
    else:
        text_lines.append(f"تعداد پروژه‌های فعال: {fa_number(len(projects))}\n")
        for p in projects:
            c = await countries_repo.get_country(session, p.country_id)
            c_name = f"{c.flag} {c.name_fa}" if c else "—"
            text_lines.append(
                f"• <b>{p.title}</b> ({c_name})\n"
                f"   سود ۷۲ساعته: {fa_money(p.yield_cash_72h)} | شناسه: #{p.id}"
            )
            builder.button(text=f"🗑 حذف #{p.id} ({p.title[:12]})", callback_data=f"godproj_del:{p.id}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(text_lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godproj:"))
async def cb_god_country_projects(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده پروژه‌های یک کشور در پنل گاد مود."""
    if not await _guard(call):
        return
    await call.answer()
    from ..database.repositories import economic_projects as proj_repo
    from ..enums import ECONOMIC_PROJECT_STATUS_FA, EconomicProjectStatus

    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if not country:
        await safe_edit(call, "❌ کشور یافت نشد.")
        return

    projects = await proj_repo.list_all_by_country(session, cid)
    builder = InlineKeyboardBuilder()

    text_lines = [
        header(f"پروژه‌های اقتصادی {country.name_fa}", "🏗"),
        f"کشور: {country.flag} <b>{country.name_fa}</b>\n",
    ]
    if not projects:
        text_lines.append("این کشور هیچ پروژه‌ای ندارد.")
    else:
        for p in projects:
            st_fa = ECONOMIC_PROJECT_STATUS_FA.get(EconomicProjectStatus(p.status), p.status)
            text_lines.append(
                f"• <b>{p.title}</b> [{st_fa}]\n"
                f"   بودجه پیشنهادی: {fa_money(p.proposed_budget)} | سود: {fa_money(p.yield_cash_72h)}"
            )
            builder.button(text=f"🗑 حذف #{p.id} ({p.title[:12]})", callback_data=f"godproj_del:{p.id}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به کشور", callback_data=f"godcountry:{cid}", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(text_lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godproj_del:"))
async def cb_god_project_delete(call: CallbackQuery, session: AsyncSession) -> None:
    """حذف یک پروژه توسط ادمین در پنل گاد مود."""
    if not await _guard(call):
        return
    from ..database.repositories import economic_projects as proj_repo

    pid = int(call.data.split(":")[1])
    proj = await proj_repo.get_project(session, pid)
    if proj:
        cid = proj.country_id
        await proj_repo.delete_project(session, proj)
        await session.commit()
        await call.answer("پروژه با موفقیت حذف گردید 🗑", show_alert=True)
        # بازگشت به لیست پروژه‌های همان کشور
        call.data = f"godproj:{cid}"
        await cb_god_country_projects(call, session)
    else:
        await call.answer("پروژه یافت نشد.", show_alert=True)


# ============================================================
#  📊 مدیریت نرخ لحظه‌ای بازار جهانی (آپدیت شماره ۴)
# ============================================================

async def _show_god_market_panel(target: Message | CallbackQuery, session: AsyncSession) -> None:
    from ..database.repositories import bot_state as bstate_repo
    from ..services import market_service

    bstate = await bstate_repo.get_state(session)
    news_enabled = getattr(bstate, "market_news_enabled", True)
    status_tag = "🟢 فعال (روشن)" if news_enabled else "🔴 غیرفعال (خاموش)"

    prices = await market_service.get_all_prices(session)

    text_lines = [
        "📊 <b>مدیریت نرخ‌های لحظه‌ای بازار جهانی (WTO)</b>",
        f"🔔 وضعیت پخش اخبار ۱۲ ساعته در کانال اقتصاد: <b>{status_tag}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "برای تغییر قیمت یا مشاهده جزئیات روی هر ذخیره کلیک کنید:\n",
    ]

    builder = InlineKeyboardBuilder()

    for p in prices:
        try:
            rtype = ResourceType(p.resource)
            emoji = RESOURCE_EMOJI.get(rtype, "📦")
            name = RESOURCE_FA.get(rtype, p.resource)
            unit = RESOURCE_UNIT_FA.get(rtype, "واحد")
        except Exception:
            emoji, name, unit = "📦", p.resource, "واحد"

        trend_icon = "⚪️"
        sign = ""
        if p.trend == "UP" or p.change_pct > 0.05:
            trend_icon = "🟢"
            sign = "+"
        elif p.trend == "DOWN" or p.change_pct < -0.05:
            trend_icon = "🔴"

        btn_text = f"{emoji} {name}: {fa_money(p.current_price)} ({trend_icon} {sign}{fa_number(p.change_pct, 1)}٪)"
        builder.button(text=btn_text, callback_data=f"godm:res:{p.resource}", style=STYLE_MAIN)

    builder.adjust(1)

    # دکمه‌های کنترل سراسری
    builder.row(
        InlineKeyboardButton(
            text=f"🔔 {'خاموش‌کردن' if news_enabled else 'روشن‌کردن'} اخبار ۱۲ ساعته",
            callback_data="godm:toggle_news",
            style=STYLE_NO if news_enabled else STYLE_OK,
        ),
        InlineKeyboardButton(
            text="📢 انتشار فوری در کانال اقتصاد",
            callback_data="godm:broadcast_now",
            style=STYLE_OK,
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به گاد مود", callback_data="god:home", style=STYLE_MAIN)
    )

    full_text = "\n".join(text_lines)
    if isinstance(target, CallbackQuery):
        await safe_edit(target, full_text, reply_markup=builder.as_markup())
    else:
        await target.answer(full_text, reply_markup=builder.as_markup())


@router.message(Command("market"))
async def cmd_market(message: Message, session: AsyncSession) -> None:
    """دستور مستقیم ورود به پنل مدیریت نرخ بازار جهانی (فقط ادمین)."""
    if not await _guard(message):
        return
    await _show_god_market_panel(message, session)


@router.message(Command("marketnews"))
async def cmd_marketnews(message: Message, session: AsyncSession) -> None:
    """دستور روشن/خاموش کردن ارسال اخبار ۱۲ ساعته بازار به کانال اقتصاد."""
    if not await _guard(message):
        return
    from ..database.repositories import bot_state as bstate_repo

    bstate = await bstate_repo.get_state(session)
    cur = getattr(bstate, "market_news_enabled", True)
    new_val = not cur
    await bstate_repo.update_state(session, market_news_enabled=new_val)
    await session.commit()

    action_fa = "فعال شد 🟢" if new_val else "غیرفعال شد 🔴"
    await message.answer(f"📢 ارسال اخبار ۱۲ ساعته نرخ ذخایر به کانال اقتصاد {action_fa}")
    await send_log(
        bot,
        f"⚙️ <b>تغییر وضعیت اخبار بازار توسط مدیریت</b>\n"
        f"وضعیت جدید: {'فعال 🟢' if new_val else 'غیرفعال 🔴'}\n"
        f"توسط: @{message.from_user.username or message.from_user.id}",
    )


@router.callback_query(F.data == "god:market")
async def cb_god_market(call: CallbackQuery, session: AsyncSession) -> None:
    """ورود به پنل بازار جهانی از طریق منوی گاد مود."""
    if not await _guard(call):
        return
    await call.answer()
    await _show_god_market_panel(call, session)


@router.callback_query(F.data == "godm:toggle_news")
async def cb_god_market_toggle_news(call: CallbackQuery, session: AsyncSession) -> None:
    """تاگل پخش اخبار ۱۲ ساعته بازار در کانال اقتصاد."""
    if not await _guard(call):
        return
    from ..database.repositories import bot_state as bstate_repo

    bstate = await bstate_repo.get_state(session)
    cur = getattr(bstate, "market_news_enabled", True)
    new_val = not cur
    await bstate_repo.update_state(session, market_news_enabled=new_val)
    await session.commit()

    action_fa = "فعال شد 🟢" if new_val else "غیرفعال شد 🔴"
    await call.answer(f"اخبار ۱۲ ساعته {action_fa}", show_alert=True)
    await _show_god_market_panel(call, session)


@router.callback_query(F.data == "godm:broadcast_now")
async def cb_god_market_broadcast_now(call: CallbackQuery, session: AsyncSession) -> None:
    """انتشار فوری و دستی گزارش نرخ‌ها در کانال اقتصاد."""
    if not await _guard(call):
        return
    from ..scheduler.jobs import broadcast_market_rates

    ok = await broadcast_market_rates(bot, force=True)
    if ok:
        await call.answer("تابلوی نرخ‌ها با موفقیت در کانال اقتصاد منتشر شد 📢", show_alert=True)
        await send_log(bot, "📢 <b>انتشار فوری تابلوی بورس در کانال اقتصاد توسط مدیریت</b>")
    else:
        await call.answer("خطا در انتشار اخبار یا عدم وجود نرخ‌ها.", show_alert=True)


@router.callback_query(F.data.startswith("godm:res:"))
async def cb_god_market_resource(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده مشخصات یک ذخیره و گزینه‌های تغییر قیمت."""
    if not await _guard(call):
        return
    await call.answer()
    res_key = call.data.split(":")[2]

    from ..services import market_service
    mp = await market_service.get_current_price(session, res_key)
    all_p = await market_service.get_all_prices(session)
    record = next((p for p in all_p if p.resource == res_key), None)

    try:
        rtype = ResourceType(res_key)
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, res_key)
        unit = RESOURCE_UNIT_FA.get(rtype, "واحد")
        base_p = DEFAULT_BASE_PRICES.get(rtype, 100.0)
    except Exception:
        emoji, name, unit = "📦", res_key, "واحد"
        base_p = 100.0

    trend_icon = "⚪️"
    change_pct = record.change_pct if record else 0.0
    if record and (record.trend == "UP" or change_pct > 0.05):
        trend_icon = "🟢"
    elif record and (record.trend == "DOWN" or change_pct < -0.05):
        trend_icon = "🔴"

    last_reason = record.last_reason_text if record else "تعیین اولیه"

    text = (
        f"{emoji} <b>مدیریت نرخ ذخیره «{name}»</b>\n\n"
        f"💵 <b>قیمت لحظه‌ای فعلی:</b> {fa_money(mp)} / {unit}\n"
        f"📊 <b>قیمت پایه استاندارد:</b> {fa_money(base_p)}\n"
        f"📉 <b>کف مجاز نوسان (۳۰٪):</b> {fa_money(base_p * 0.3)}\n"
        f"📈 <b>سقف مجاز نوسان (۴۰۰٪):</b> {fa_money(base_p * 4.0)}\n"
        f"📈 <b>آخرین روند:</b> {trend_icon} {fa_number(change_pct, 1)}٪\n"
        f"📌 <b>دلیل آخرین تغییر:</b> {last_reason}\n\n"
        "دستور مورد نظر را انتخاب کنید:"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ تعیین قیمت مستقیم", callback_data=f"godm:set_abs:{res_key}", style=STYLE_OK),
            ],
            [
                InlineKeyboardButton(text="📈 +۱۰٪", callback_data=f"godm:set_rel:{res_key}:10", style=STYLE_OK),
                InlineKeyboardButton(text="📈 +۲۵٪", callback_data=f"godm:set_rel:{res_key}:25", style=STYLE_OK),
                InlineKeyboardButton(text="📈 +۵۰٪", callback_data=f"godm:set_rel:{res_key}:50", style=STYLE_OK),
            ],
            [
                InlineKeyboardButton(text="📉 -۱۰٪", callback_data=f"godm:set_rel:{res_key}:-10", style=STYLE_NO),
                InlineKeyboardButton(text="📉 -۲۵٪", callback_data=f"godm:set_rel:{res_key}:-25", style=STYLE_NO),
                InlineKeyboardButton(text="📉 -۵۰٪", callback_data=f"godm:set_rel:{res_key}:-50", style=STYLE_NO),
            ],
            [
                InlineKeyboardButton(text="♻️ بازگرداندن به قیمت پایه اولیه", callback_data=f"godm:reset:{res_key}", style=STYLE_MAIN),
            ],
            [
                InlineKeyboardButton(text="🔙 بازگشت به فهرست ذخایر", callback_data="god:market", style=STYLE_MAIN),
            ],
        ]
    )
    await safe_edit(call, text, reply_markup=kb)


@router.callback_query(F.data.startswith("godm:set_abs:"))
async def cb_god_market_set_abs(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست وارد کردن قیمت جدید به صورت مستقیم."""
    if not await _guard(call):
        return
    await call.answer()
    res_key = call.data.split(":")[2]
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="market_price_abs", god_res=res_key)

    await safe_edit(
        call,
        f"✏️ لطفاً قیمت جدید هر واحد از <b>{res_key}</b> را به دلار وارد کنید (مثلاً 500k یا 12m):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godm:res:{res_key}", style=STYLE_MAIN)
        ]]),
    )


@router.callback_query(F.data.startswith("godm:set_rel:"))
async def cb_god_market_set_rel(call: CallbackQuery, state: FSMContext) -> None:
    """تغییر درصدی قیمت و انتقال به مرحله انتخاب دلیل."""
    if not await _guard(call):
        return
    await call.answer()
    parts = call.data.split(":")
    res_key = parts[2]
    delta_pct = float(parts[3])

    await state.update_data(god_res=res_key, god_delta_pct=delta_pct, god_new_price=None)
    await _show_god_market_reason_picker(call, state, res_key, delta_pct=delta_pct)


@router.callback_query(F.data.startswith("godm:reset:"))
async def cb_god_market_reset(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """بازنشانی قیمت به نرخ پایه اولیه و انتقال به مرحله دلیل."""
    if not await _guard(call):
        return
    await call.answer()
    res_key = call.data.split(":")[2]
    try:
        rtype = ResourceType(res_key)
        base_p = DEFAULT_BASE_PRICES.get(rtype, 100.0)
    except Exception:
        base_p = 100.0

    await state.update_data(god_res=res_key, god_new_price=base_p, god_delta_pct=None)
    await _show_god_market_reason_picker(call, state, res_key, new_price=base_p)


async def _show_god_market_reason_picker(
    target: Message | CallbackQuery,
    state: FSMContext,
    res_key: str,
    new_price: float | None = None,
    delta_pct: float | None = None,
) -> None:
    """نمایش منوی انتخاب دلیل آماده یا تایپ دلیل دلخواه."""
    prompt = ""
    if new_price is not None:
        prompt = f"قیمت جدید هدف: <b>{fa_money(new_price)}</b>\n"
    elif delta_pct is not None:
        prompt = f"تغییر درصدی: <b>{delta_pct:+.1f}٪</b>\n"

    text = (
        f"📌 <b>ثبت دلیل تغییر نرخ برای {res_key}</b>\n\n"
        f"{prompt}"
        "یکی از دلایل آماده زیر را انتخاب کنید یا دلیل دلخواه خود را تایپ نمایید:"
    )

    builder = InlineKeyboardBuilder()

    reasons_list = [
        ("HIGH_DEMAND", "🟢 افزایش تقاضا"),
        ("AUCTION_FEVER", "🟢 رقابت مزایده"),
        ("STRAIT_CLOSURE", "🟢 مسدود شدن تنگه"),
        ("STRAIT_INTERCEPTION", "🟢 توقیف/حمله به کشتی"),
        ("GLOBAL_SHORTAGE", "🟢 کمبود عرضه جهانی"),
        ("WAR_CONSUMPTION", "🟢 مصارف جنگی"),
        ("OVERSUPPLY", "🔴 مازاد عرضه"),
        ("LOW_DEMAND", "🔴 رکود تقاضا"),
        ("STRAIT_REOPENED", "🔴 بازگشایی تنگه‌ها"),
        ("MASS_SELLING", "🔴 فروش انبوه"),
        ("ADMIN_MANUAL", "⚙️ مداخله مدیریت"),
    ]

    for code, label in reasons_list:
        builder.button(text=label, callback_data=f"godm:apply_reason:{code}")

    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="✍️ تایپ دلیل دلخواه", callback_data="godm:custom_reason", style=STYLE_OK)
    )
    builder.row(
        InlineKeyboardButton(text="🔙 لغو", callback_data=f"godm:res:{res_key}", style=STYLE_MAIN)
    )

    if isinstance(target, CallbackQuery):
        await safe_edit(target, text, reply_markup=builder.as_markup())
    else:
        await target.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("godm:apply_reason:"))
async def cb_god_market_apply_reason(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """اعمال دلیل آماده انتخاب‌شده و ثبت نهایی تغییر نرخ."""
    if not await _guard(call):
        return
    await call.answer()
    reason_code = call.data.split(":")[2]

    data = await state.get_data()
    await state.clear()

    res_key = data.get("god_res")
    new_price = data.get("god_new_price")
    delta_pct = data.get("god_delta_pct")

    if not res_key:
        await call.answer("اطلاعات ذخیره منقضی شده است.", show_alert=True)
        await _show_god_market_panel(call, session)
        return

    from ..services import market_service
    updated_mp = await market_service.update_price(
        session=session,
        resource=res_key,
        delta_pct=delta_pct,
        absolute_price=new_price,
        reason_code=reason_code,
    )
    await session.commit()

    reason_desc = MARKET_REASON_TEMPLATES.get(reason_code, reason_code)

    await call.answer("نرخ جدید با موفقیت اعمال گردید ✅", show_alert=True)
    await send_log(
        bot,
        f"📈 <b>تغییر نرخ بازار جهانی توسط مدیریت</b>\n"
        f"ذخیره: {res_key}\n"
        f"نرخ جدید: {fa_money(updated_mp.current_price)}\n"
        f"روند: {updated_mp.trend} ({updated_mp.change_pct:+.1f}٪)\n"
        f"دلیل: {reason_desc}",
    )
    await _show_god_market_panel(call, session)


@router.callback_query(F.data == "godm:custom_reason")
async def cb_god_market_custom_reason_ask(call: CallbackQuery, state: FSMContext) -> None:
    """ورود به حالت تایپ دلیل دلخواه برای تغییر نرخ."""
    if not await _guard(call):
        return
    await call.answer()
    await state.set_state(GodForm.entering_value)
    await state.update_data(god_kind="market_custom_reason")

    data = await state.get_data()
    res_key = data.get("god_res", "")

    await safe_edit(
        call,
        f"✍️ لطفاً متن دلیل تغییر نرخ برای <b>{res_key}</b> را تایپ کرده و ارسال کنید:\n"
        "<i>(این متن دقیقاً در تابلوی بورس به همه بازیکنان نمایش داده خواهد شد)</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 لغو", callback_data=f"godm:res:{res_key}", style=STYLE_MAIN)
        ]]),
    )


# ============================================================
#  🤬 پنل و دستورات مدیریت فیلتر کلمات رکیک (/badwords)
# ============================================================

def _profanity_panel_kb(is_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_enabled:
        builder.button(text="🔴 خاموش کردن فیلتر فحش", callback_data="prof:toggle", style=STYLE_NO)
    else:
        builder.button(text="🟢 روشن کردن فیلتر فحش", callback_data="prof:toggle", style=STYLE_OK)
    builder.button(text="➕ افزودن کلمه جدید", callback_data="prof:add", style=STYLE_MAIN)
    builder.button(text="➖ حذف کلمه", callback_data="prof:del", style=STYLE_MAIN)
    builder.button(text="📋 فهرست کلمات فیلترشده", callback_data="prof:list:0", style=STYLE_MAIN)
    builder.button(text="🔍 آزمایش یک متن", callback_data="prof:test", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به گاد مود", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()


async def _render_profanity_screen(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    await profanity_service.ensure_seeded(session)
    from ..database.repositories import profanity as profanity_repo

    words_count = await profanity_repo.count_words(session)
    enabled = profanity_service.is_filter_enabled()
    status_str = "🟢 <b>روشن و فعال</b>" if enabled else "🔴 <b>خاموش و غیرفعال</b>"

    text = (
        header("مدیریت فیلتر فحش و کلمات رکیک", "🤬")
        + f"\n\nوضعیت فعلی سیستم: {status_str}\n"
        f"📊 تعداد کل کلمات در بلک‌لیست: <b>{fa_number(words_count)}</b> کلمه\n\n"
        "💡 <b>دستورات سریع مدیریتی:</b>\n"
        "• <code>/badwords toggle</code> — سوئیچ سریع خاموش/روشن\n"
        "• <code>/addword کلمه</code> — افزودن کلمه به بلک‌لیست\n"
        "• <code>/addword کلمه۱، کلمه۲، کلمه۳</code> — افزودن دسته‌ای کلمات\n"
        "• <code>/delword کلمه</code> — حذف کلمه از بلک‌لیست\n\n"
        "از دکمه‌های زیر برای مدیریت استفاده کنید:"
    )
    return text, _profanity_panel_kb(enabled)


@router.message(Command("badwords", "profanity"))
async def cmd_badwords(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """دستور ورود به پنل فیلتر فحش یا تاگل وضعیت."""
    if not await _guard(message):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip().lower() == "toggle":
        new_val = await profanity_service.toggle_filter(session)
        st = "🟢 روشن و فعال" if new_val else "🔴 خاموش و غیرفعال"
        await message.answer(f"✅ وضعیت فیلتر فحش تغییر یافت: {st}")
        await send_log(bot, f"🤬 <b>تغییر وضعیت فیلتر فحش توسط مدیریت</b>\nوضعیت جدید: {st}")
        return

    await state.clear()
    msg, kb = await _render_profanity_screen(session)
    await message.answer(msg, reply_markup=kb)


@router.callback_query(F.data == "god:profanity")
async def cb_god_profanity(call: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """باز کردن پنل فیلتر فحش از درون منوی گاد مود."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    msg, kb = await _render_profanity_screen(session)
    await safe_edit(call, msg, reply_markup=kb)


@router.callback_query(F.data == "prof:toggle")
async def cb_prof_toggle(call: CallbackQuery, session: AsyncSession) -> None:
    """تغییر وضعیت فعال/غیرفعال بودن فیلتر فحش."""
    if not await _guard(call):
        return
    new_val = await profanity_service.toggle_filter(session)
    st = "روشن" if new_val else "خاموش"
    await call.answer(f"فیلتر فحش {st} شد ✅", show_alert=True)
    await send_log(
        bot,
        f"🤬 <b>تغییر وضعیت فیلتر فحش توسط مدیریت</b>\n"
        f"وضعیت جدید: {'🟢 فعال' if new_val else '🔴 غیرفعال'}",
    )
    msg, kb = await _render_profanity_screen(session)
    await safe_edit(call, msg, reply_markup=kb)


@router.message(Command("addword"))
async def cmd_addword(message: Message, session: AsyncSession) -> None:
    """افزودن مستقیم کلمه یا چند کلمه به بلک‌لیست."""
    if not await _guard(message):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("⚠️ لطفاً کلمه یا کلمات مورد نظر را وارد کنید:\nمثال: <code>/addword کلمه</code> یا <code>/addword کلمه۱، کلمه۲</code>")
        return

    raw_input = parts[1].strip()
    raw_words = [w.strip() for w in re.split(r"[,،\n]+", raw_input) if w.strip()]
    if not raw_words:
        await message.answer("❌ کلمه معتبری یافت نشد.")
        return

    added = await profanity_service.add_words_bulk(session, raw_words, admin_id=message.from_user.id)
    await message.answer(f"✅ {fa_number(added)} کلمه جدید با موفقیت به بلک‌لیست افزوده شد.")
    await send_log(
        bot,
        f"🤬 <b>افزودن کلمات جدید به فیلتر فحش</b>\n"
        f"تعداد اضافه شده: {added}\n"
        f"کلمات: <code>{', '.join(raw_words[:10])}</code>",
    )


@router.message(Command("delword"))
async def cmd_delword(message: Message, session: AsyncSession) -> None:
    """حذف مستقیم کلمه از بلک‌لیست."""
    if not await _guard(message):
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("⚠️ لطفاً کلمه مورد نظر برای حذف را وارد کنید:\nمثال: <code>/delword کلمه</code>")
        return

    word_to_del = parts[1].strip()
    ok = await profanity_service.remove_word(session, word_to_del)
    if ok:
        await message.answer(f"✅ کلمه «{word_to_del}» با موفقیت از بلک‌لیست حذف شد.")
        await send_log(bot, f"🤬 <b>حذف کلمه از فیلتر فحش توسط مدیریت</b>\nکلمه: <code>{word_to_del}</code>")
    else:
        await message.answer(f"ℹ️ کلمه «{word_to_del}» در بلک‌لیست یافت نشد.")


@router.callback_query(F.data == "prof:add")
async def cb_prof_add(call: CallbackQuery, state: FSMContext) -> None:
    """ورود به فرم دریافت کلمه جدید برای افزودن."""
    if not await _guard(call):
        return
    await call.answer()
    await state.set_state(ProfanityAdminForm.waiting_for_add_word)
    text = (
        "➕ <b>افزودن کلمه یا کلمات رکیک به بلک‌لیست:</b>\n\n"
        "لطفاً کلمه یا کلمات مورد نظر را ارسال کنید.\n"
        "💡 می‌توانید چند کلمه را با کاما (،) یا فاصله یا در خطوط جداگانه ارسال کنید."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="god:profanity", style=STYLE_MAIN)
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(ProfanityAdminForm.waiting_for_add_word, F.text)
async def msg_prof_add_word(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """پردازش متن کلمات ارسالی برای افزودن."""
    if not await _guard(message):
        await state.clear()
        return

    raw_input = message.text.strip()
    raw_words = [w.strip() for w in re.split(r"[,،\n]+", raw_input) if w.strip()]
    if not raw_words:
        await message.answer("❌ کلمه معتبری یافت نشد.")
        return

    await state.clear()
    added = await profanity_service.add_words_bulk(session, raw_words, admin_id=message.from_user.id)
    await message.answer(
        f"✅ <b>{fa_number(added)}</b> کلمه با موفقیت ثبت و در کش فیلتر فعال شد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت به فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN)
        ]]),
    )
    await send_log(
        bot,
        f"🤬 <b>افزودن کلمات جدید به فیلتر فحش</b>\n"
        f"تعداد اضافه شده: {added}\n"
        f"کلمات: <code>{', '.join(raw_words[:10])}</code>",
    )


@router.callback_query(F.data == "prof:del")
async def cb_prof_del(call: CallbackQuery, state: FSMContext) -> None:
    """ورود به فرم دریافت کلمه برای حذف."""
    if not await _guard(call):
        return
    await call.answer()
    await state.set_state(ProfanityAdminForm.waiting_for_del_word)
    text = (
        "➖ <b>حذف کلمه از بلک‌لیست فیلتر فحش:</b>\n\n"
        "لطفاً کلمه‌ای را که مایل به حذف آن از فیلتر هستید ارسال فرمایید:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="god:profanity", style=STYLE_MAIN)
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(ProfanityAdminForm.waiting_for_del_word, F.text)
async def msg_prof_del_word(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """پردازش کلمه حذفی."""
    if not await _guard(message):
        await state.clear()
        return

    word_to_del = message.text.strip()
    await state.clear()
    ok = await profanity_service.remove_word(session, word_to_del)
    if ok:
        await message.answer(
            f"✅ کلمه «{word_to_del}» با موفقیت از فیلتر فحش حذف شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN)
            ]]),
        )
        await send_log(bot, f"🤬 <b>حذف کلمه از فیلتر فحش توسط مدیریت</b>\nکلمه: <code>{word_to_del}</code>")
    else:
        await message.answer(
            f"ℹ️ کلمه «{word_to_del}» در بلک‌لیست فیلتر یافت نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN)
            ]]),
        )


@router.callback_query(F.data.startswith("prof:list:"))
async def cb_prof_list(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش صفحه‌بندی‌شده کلمات موجود در بلک‌لیست."""
    if not await _guard(call):
        return
    await call.answer()

    from ..database.repositories import profanity as profanity_repo

    page = int(call.data.split(":")[2])
    limit = 15
    offset = page * limit

    words, total = await profanity_repo.get_words_paginated(session, offset=offset, limit=limit)
    total_pages = max(1, (total + limit - 1) // limit)

    builder = InlineKeyboardBuilder()

    lines = [
        header("فهرست کلمات فیلترشده", "📋"),
        f"\nتعداد کل کلمات: <b>{fa_number(total)}</b> | صفحه: <b>{fa_number(page + 1)} از {fa_number(total_pages)}</b>\n",
    ]

    if not words:
        lines.append("<i>هیچ کلمه‌ای در بلک‌لیست ثبت نشده است.</i>")
    else:
        for idx, w in enumerate(words, start=offset + 1):
            lines.append(f"{fa_number(idx)}. <code>{w.word}</code>")
            builder.button(text=f"🗑 {w.word}", callback_data=f"prof:del_w:{w.id}:{page}", style=STYLE_NO)

    builder.adjust(3)

    # دکمه‌های ناوبری صفحه
    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"prof:list:{page - 1}", style=STYLE_MAIN))
    if page + 1 < total_pages:
        nav_btns.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"prof:list:{page + 1}", style=STYLE_MAIN))
    if nav_btns:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN))

    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("prof:del_w:"))
async def cb_prof_del_item(call: CallbackQuery, session: AsyncSession) -> None:
    """حذف تک‌کلیکی کلمه از درون فهرست صفحه‌بندی‌شده."""
    if not await _guard(call):
        return
    parts = call.data.split(":")
    word_id = int(parts[2])
    page = int(parts[3])

    from sqlalchemy import select
    from ..database.models.profanity import ProfanityWord
    from ..database.repositories import profanity as profanity_repo

    stmt = select(ProfanityWord).where(ProfanityWord.id == word_id)
    pw = (await session.execute(stmt)).scalars().first()
    if pw:
        w_text = pw.word
        await profanity_service.remove_word(session, w_text)
        await call.answer(f"کلمه «{w_text}» حذف شد ✅")
        await send_log(bot, f"🤬 <b>حذف کلمه از فیلتر فحش</b>\nکلمه: <code>{w_text}</code>")
    else:
        await call.answer("کلمه یافت نشد.", show_alert=True)

    # به‌روزرسانی مجدد صفحه
    limit = 15
    offset = page * limit
    words, total = await profanity_repo.get_words_paginated(session, offset=offset, limit=limit)
    total_pages = max(1, (total + limit - 1) // limit)
    if page >= total_pages and page > 0:
        page -= 1
        offset = page * limit
        words, total = await profanity_repo.get_words_paginated(session, offset=offset, limit=limit)
        total_pages = max(1, (total + limit - 1) // limit)

    builder = InlineKeyboardBuilder()
    lines = [
        header("فهرست کلمات فیلترشده", "📋"),
        f"\nتعداد کل کلمات: <b>{fa_number(total)}</b> | صفحه: <b>{fa_number(page + 1)} از {fa_number(total_pages)}</b>\n",
    ]
    for idx, w in enumerate(words, start=offset + 1):
        lines.append(f"{fa_number(idx)}. <code>{w.word}</code>")
        builder.button(text=f"🗑 {w.word}", callback_data=f"prof:del_w:{w.id}:{page}", style=STYLE_NO)
    builder.adjust(3)

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"prof:list:{page - 1}", style=STYLE_MAIN))
    if page + 1 < total_pages:
        nav_btns.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"prof:list:{page + 1}", style=STYLE_MAIN))
    if nav_btns:
        builder.row(*nav_btns)

    builder.row(InlineKeyboardButton(text="🔙 بازگشت به فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN))
    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "prof:test")
async def cb_prof_test(call: CallbackQuery, state: FSMContext) -> None:
    """ورود به فرم تست یک متن دلخواه توسط ادمین."""
    if not await _guard(call):
        return
    await call.answer()
    await state.set_state(ProfanityAdminForm.waiting_for_test_text)
    text = (
        "🔍 <b>تست و راستی‌آزمایی متن در فیلتر فحش:</b>\n\n"
        "لطفاً یک جمله یا متن آزمایشی را بفرستید تا موتور فیلتر آن را تحلیل کرده و نتیجه را به شما گزارش دهد."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="god:profanity", style=STYLE_MAIN)
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(ProfanityAdminForm.waiting_for_test_text, F.text)
async def msg_prof_test_text(message: Message, state: FSMContext) -> None:
    """تحلیل متن آزمایشی و گزارش به ادمین."""
    if not await _guard(message):
        await state.clear()
        return

    test_input = message.text.strip()
    await state.clear()

    has_bad, bad_word = profanity_service.check_profanity(test_input)
    norm = profanity_service.normalize_text(test_input)

    if has_bad:
        res_text = (
            "🚨 <b>نتیجه تست: حاوی کلمات رکیک / مسدود می‌شود</b>\n\n"
            f"🚫 <b>کلمه شناسایی‌شده:</b> <code>{bad_word}</code>\n"
            f"🔤 <b>متن نرمال‌شده:</b> <code>{norm}</code>"
        )
    else:
        res_text = (
            "✅ <b>نتیجه تست: پاک و بدون کلمه ممنوعه</b>\n\n"
            "این متن مجاز است و فیلتر به آن اجازه عبور می‌دهد.\n"
            f"🔤 <b>متن نرمال‌شده:</b> <code>{norm}</code>"
        )

    await message.answer(
        res_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔍 تست متن دیگر", callback_data="prof:test", style=STYLE_MAIN),
            InlineKeyboardButton(text="🔙 فیلتر فحش", callback_data="god:profanity", style=STYLE_MAIN),
        ]]),
    )
