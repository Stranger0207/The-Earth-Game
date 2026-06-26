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
from ..database.models import (
    Country,
    GroupMeeting,
    Meeting,
    MilitaryAsset,
    MilitarySale,
    ResourceSale,
    User,
)
from ..database.repositories import countries as countries_repo
from ..database.repositories import facilities as fac_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_factory as milfac_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import users as users_repo
from ..enums import (
    FACILITY_FA,
    MIL_FACTORY_FA,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    DiplomacyStatus,
    FacilityType,
    MilitaryFactoryType,
    ResourceType,
    TradeStatus,
)
from ..loader import bot
from ..utils.formatting import render_economy_panel, render_military_panel, render_reserves_panel
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from ..states import GodForm

router = Router(name="godmode")
settings = get_settings()


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
    if country.is_claimed:
        builder.button(text="🚪 آزادسازی (اخراج)", callback_data=f"godrelease:{country.id}", style=STYLE_NO)
        builder.button(text="⛔️ بن مالک", callback_data=f"godban:{country.id}", style=STYLE_NO)
        builder.button(text="✅ رفع بن مالک", callback_data=f"godunban:{country.id}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="god:countries", style=STYLE_MAIN)
    builder.adjust(2, 2, 3, 1)
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
        owner_txt = f"{uname} (<code>{country.owner_user_id}</code>){banned}"
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


@router.callback_query(F.data.startswith("godfac:"))
async def cb_god_facilities(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش فهرست تأسیسات و کارخانه‌های نظامی یک کشور در پنل گاد (v1.9)."""
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.message.edit_text("کشور یافت نشد.", reply_markup=_home_kb())
        return

    facilities = await fac_repo.list_facilities(session, cid)
    factories = await milfac_repo.list_factories(session, cid)

    lines = [header(f"تأسیسات و کارخانه‌های {country.flag} {country.name_fa}", "🏭"), ""]

    lines.append("🏗 <b>تأسیسات:</b>")
    if facilities:
        for f in facilities:
            try:
                label = FACILITY_FA[FacilityType(f.type)]
            except (ValueError, KeyError):
                label = f.type
            if f.resource:
                try:
                    label += f" {RESOURCE_FA[ResourceType(f.resource)]}"
                except (ValueError, KeyError):
                    pass
            lines.append(f"• {label} — 📍 {f.location or '—'}")
    else:
        lines.append("—")

    lines.append("")
    lines.append("🏭 <b>کارخانه‌های نظامی:</b>")
    if factories:
        for f in factories:
            try:
                label = MIL_FACTORY_FA[MilitaryFactoryType(f.factory_type)]
            except (ValueError, KeyError):
                label = f.factory_type
            lines.append(f"• {label} — بازتولید {f.asset_name} (📍 {f.location or '—'})")
    else:
        lines.append("—")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"godc:{cid}", style=STYLE_MAIN)
    ]])
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


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
@router.message(GodForm.entering_value, F.text)
async def msg_god_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    value = parse_amount(message.text)
    if value is None:
        await message.answer("عدد نامعتبر است. لطفاً دوباره وارد کنید.")
        return
    data = await state.get_data()
    kind = data.get("god_kind")
    cid = data.get("god_country")
    await state.clear()
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await message.answer("کشور یافت نشد.")
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
