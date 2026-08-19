"""
هندلر گشت، رزمایش، ترور و رهگیری محموله (v1.10.6).

این چهار قابلیت جریان‌های سبک‌تری نسبت به حمله‌ی اصلی دارند:
- گشت و رزمایش: بدون تأیید مالک (در سقف عملیات هم شمرده نمی‌شوند)
- ترور و رهگیری: نیازمند تأیید مالک، چون اثر سنگین دارند
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    DRILL_BUDGET_COST,
    DRILL_DURATION_HOURS,
    DRILL_FUEL_COST,
    DRILL_READINESS_MAX,
    PATROL_DURATION_HOURS,
    PATROL_FUEL_BY_TYPE,
)
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import drills as drill_repo
from ..database.repositories import patrols as patrol_repo
from ..enums import (
    PATROL_EMOJI,
    PATROL_FA,
    DrillType,
    PatrolType,
)
from ..keyboards.command_center import (
    asset_picker_kb,
    drill_types_kb,
    operations_menu_kb,
    patrol_types_kb,
)
from ..keyboards.common import back_kb, confirm_cancel_kb, countries_kb
from ..loader import bot
from ..services import drill_service, patrol_service
from ..services.news_service import send_log
from ..states import DrillForm, PatrolForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="patrol_drill")


def _patrol_label(patrol_type: str) -> str:
    try:
        ptype = PatrolType(patrol_type)
        return f"{PATROL_EMOJI[ptype]} {PATROL_FA[ptype]}"
    except (ValueError, KeyError):
        return patrol_type


def _selected_summary(selected: dict[str, int]) -> str:
    """خلاصه‌ی تجهیزات انتخاب‌شده."""
    if not selected:
        return "هنوز تجهیزاتی انتخاب نشده است."
    lines = [f"  ✅ {name} — {fa_number(count)}" for name, count in selected.items()]
    lines.append(f"\n📦 مجموع: <b>{fa_number(sum(selected.values()))}</b> واحد")
    return "\n".join(lines)


# ============================================================
#  🛩 گشت دفاعی
# ============================================================
@router.callback_query(F.data == "op:patrol")
async def cb_patrol_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی گشت دفاعی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military.patrol"):
        return

    active = await patrol_repo.count_active(session, country.id)
    text = (
        header("گشت دفاعی", "🛩") + "\n\n"
        f"🔵 گشت‌های فعال: <b>{fa_number(active)}</b>\n"
        f"⏱ مدت هر گشت: {fa_number(PATROL_DURATION_HOURS)} ساعت\n"
        f"{DIVIDER}\n"
        "<b>گشت فعال چه سودی دارد؟</b>\n"
        "🛡 بونوس رهگیری پدافند در برابر حمله\n"
        "🕵️ شانس کشف خرابکاری و خنثی‌سازی ترور\n"
        "⚓ بونوس رهگیری محموله‌های عبوری\n\n"
        "<i>گشت در سقف عملیات شمرده نمی‌شود.</i>"
    )
    await safe_edit(call, text, reply_markup=patrol_types_kb())


@router.callback_query(F.data == "patrol:list")
async def cb_patrol_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست گشت‌های فعال."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    patrols = await patrol_repo.list_active(session, country.id)
    lines = [header("گشت‌های فعال", "🛩"), ""]

    if not patrols:
        lines.append("هیچ گشت فعالی ندارید.")
    else:
        for patrol in patrols:
            assets = patrol_service.parse_assets(patrol)
            assets_text = "، ".join(
                f"{a.get('name')} ({fa_number(a.get('count', 0))})" for a in assets[:3]
            )
            lines.append(
                f"{_patrol_label(patrol.patrol_type)}\n"
                f"   📍 منطقه: {patrol.area or '—'}\n"
                f"   🪖 نیرو: {assets_text or '—'}\n"
                f"   🔍 کشف‌شده: {fa_number(patrol.detections)} مورد"
            )

    await safe_edit(call, "\n".join(lines), reply_markup=patrol_types_kb())


@router.callback_query(F.data.startswith("patrol_type:"))
async def cb_patrol_type(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب نوع گشت و درخواست منطقه."""
    await call.answer()
    try:
        ptype = PatrolType(call.data.split(":")[1])
    except ValueError:
        await call.answer("نوع گشت نامعتبر است.", show_alert=True)
        return

    await state.clear()
    await state.update_data(patrol_type=ptype.value, selected={}, page=0)
    await state.set_state(PatrolForm.entering_area)

    fuel = PATROL_FUEL_BY_TYPE.get(ptype, 0.8)
    await safe_edit(
        call,
        f"{PATROL_EMOJI[ptype]} <b>{PATROL_FA[ptype]}</b>\n"
        f"⛽️ هزینه: {fa_number(fuel, 1)} میلیون بشکه نفت\n"
        f"{DIVIDER}\n"
        "📍 <b>منطقه‌ی گشت‌زنی را بنویسید:</b>\n"
        "<i>مثال: «مرز شرقی»، «تنگه هرمز»، «آسمان پایتخت»</i>",
    )


@router.message(PatrolForm.entering_area, F.text)
async def msg_patrol_area(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت منطقه و نمایش فهرست تجهیزات."""
    area = message.text.strip()
    if not area:
        await message.answer("لطفاً نام منطقه را بنویسید.")
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    ptype = PatrolType(data["patrol_type"])
    assets = await patrol_service.available_assets(session, country.id, ptype)

    if not assets:
        await state.clear()
        await message.answer(
            f"⚠️ کشور شما تجهیزات مناسبی برای {PATROL_FA[ptype]} ندارد.",
            reply_markup=patrol_types_kb(),
        )
        return

    await state.update_data(area=area, assets=assets)
    await state.set_state(PatrolForm.selecting_assets)
    await message.answer(
        header("انتخاب نیروی گشت", "🪖") + f"\n\n"
        f"{PATROL_EMOJI[ptype]} {PATROL_FA[ptype]} — 📍 {area}\n\n"
        "تجهیزاتی که به این گشت اختصاص می‌دهید را انتخاب کنید:",
        reply_markup=asset_picker_kb(assets, {}, page=0),
    )


@router.callback_query(PatrolForm.selecting_assets, F.data.startswith("op_page:"))
async def cb_patrol_page(call: CallbackQuery, state: FSMContext) -> None:
    """ناوبری صفحه‌های تجهیزات گشت."""
    await call.answer()
    page = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)
    await safe_edit(
        call,
        header("انتخاب نیروی گشت", "🪖") + "\n\n" + _selected_summary(dict(data.get("selected") or {})),
        reply_markup=asset_picker_kb(data.get("assets") or [], dict(data.get("selected") or {}), page=page),
    )


@router.callback_query(PatrolForm.selecting_assets, F.data == "op_assets_clear")
async def cb_patrol_clear(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌کردن انتخاب تجهیزات گشت."""
    await call.answer("انتخاب‌ها پاک شد")
    data = await state.get_data()
    await state.update_data(selected={})
    await safe_edit(
        call,
        header("انتخاب نیروی گشت", "🪖") + "\n\nهنوز تجهیزاتی انتخاب نشده است.",
        reply_markup=asset_picker_kb(data.get("assets") or [], {}, page=data.get("page", 0)),
    )


@router.callback_query(PatrolForm.selecting_assets, F.data.startswith("op_asset:"))
async def cb_patrol_pick(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب یک قلم برای گشت."""
    await call.answer()
    index = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets") or []
    if index >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = assets[index]
    await state.update_data(pending_index=index)
    await state.set_state(PatrolForm.entering_asset_count)
    await safe_edit(
        call,
        f"🪖 <b>{asset['name']}</b>\n"
        f"📦 موجودی: {fa_number(asset['count'])} {asset['unit']}\n\n"
        "چه تعداد به این گشت اختصاص می‌دهید؟\n"
        "<i>برای حذف، صفر بفرستید.</i>",
    )


@router.message(PatrolForm.entering_asset_count, F.text)
async def msg_patrol_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد و بازگشت به فهرست."""
    data = await state.get_data()
    assets = data.get("assets") or []
    index = data.get("pending_index")

    if index is None or index >= len(assets):
        await state.set_state(PatrolForm.selecting_assets)
        await message.answer("خطا در انتخاب. دوباره تلاش کنید.")
        return

    asset = assets[index]
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("⚠️ عدد معتبر وارد کنید.")
        return

    count = int(amount)
    if count > asset["count"]:
        await message.answer(f"⚠️ حداکثر {fa_number(asset['count'])} {asset['unit']} دارید.")
        return

    selected = dict(data.get("selected") or {})
    if count == 0:
        selected.pop(asset["name"], None)
    else:
        selected[asset["name"]] = count

    await state.update_data(selected=selected, pending_index=None)
    await state.set_state(PatrolForm.selecting_assets)
    await message.answer(
        header("انتخاب نیروی گشت", "🪖") + "\n\n" + _selected_summary(selected),
        reply_markup=asset_picker_kb(assets, selected, page=data.get("page", 0)),
    )


@router.callback_query(PatrolForm.selecting_assets, F.data == "op_assets_done")
async def cb_patrol_done(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت نهایی گشت."""
    await call.answer()
    data = await state.get_data()
    selected = dict(data.get("selected") or {})
    if not selected:
        await call.answer("ابتدا تجهیزات انتخاب کنید.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    assets_meta = {a["name"]: a for a in (data.get("assets") or [])}
    payload = [
        {"name": name, "count": count, "unit": assets_meta.get(name, {}).get("unit", "عدد")}
        for name, count in selected.items()
    ]
    ptype = PatrolType(data["patrol_type"])
    area = data.get("area", "")

    await state.clear()
    try:
        patrol = await patrol_service.start_patrol(session, country, ptype, area, payload)
    except patrol_service.PatrolError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=patrol_types_kb())
        return

    await safe_edit(
        call,
        "✅ <b>گشت آغاز شد</b>\n\n"
        f"{PATROL_EMOJI[ptype]} {PATROL_FA[ptype]}\n"
        f"📍 منطقه: {area}\n"
        f"🪖 نیرو: {fa_number(patrol.total_units)} واحد\n"
        f"⛽️ سوخت مصرفی: {fa_number(patrol.fuel_cost, 1)} میلیون بشکه\n"
        f"⏱ مدت: {fa_number(PATROL_DURATION_HOURS)} ساعت\n\n"
        "<i>این گشت پدافند شما را تقویت می‌کند و شانس کشف عملیات مخفیانه را بالا می‌برد.</i>",
        reply_markup=patrol_types_kb(),
    )

    await send_log(
        bot,
        f"🛩 <b>آغاز گشت دفاعی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نوع: {PATROL_FA[ptype]}\n"
        f"منطقه: {area}\n"
        f"نیرو: {fa_number(patrol.total_units)} واحد",
    )


# ============================================================
#  🎪 رزمایش
# ============================================================
@router.callback_query(F.data == "op:drill")
async def cb_drill_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی رزمایش."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military.drill"):
        return

    readiness = float(getattr(country, "readiness", 0.0) or 0.0)
    text = (
        header("رزمایش نظامی", "🎪") + "\n\n"
        f"🎯 آمادگی رزمی فعلی: <b>{fa_number(readiness, 1)}</b> از {fa_number(DRILL_READINESS_MAX)}\n"
        f"{DIVIDER}\n"
        "<b>رزمایش چه سودی دارد؟</b>\n"
        "آمادگی رزمی مستقیماً قدرت نیروهای شما را در نبرد افزایش می‌دهد.\n\n"
        f"⏱ مدت: {fa_number(DRILL_DURATION_HOURS)} ساعت\n"
        f"⛽️ سوخت: {fa_number(DRILL_FUEL_COST, 1)} میلیون بشکه\n"
        f"💰 هزینه: {fa_money(DRILL_BUDGET_COST)}\n\n"
        "<i>آمادگی رزمی به‌مرور افت می‌کند، پس رزمایش را تکرار کنید.</i>"
    )
    await safe_edit(call, text, reply_markup=drill_types_kb())


@router.callback_query(F.data == "drill:list")
async def cb_drill_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست رزمایش‌های جاری."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    drills = await drill_repo.list_active(session, country.id)
    lines = [header("رزمایش‌های جاری", "🎪"), ""]

    if not drills:
        lines.append("رزمایش در حال اجرایی ندارید.")
    else:
        for drill in drills:
            partner_text = ""
            if drill.partner_country_id:
                partner = await countries_repo.get_country(session, drill.partner_country_id)
                if partner:
                    status = "✅ پذیرفته" if drill.partner_accepted else "⏳ در انتظار پاسخ"
                    partner_text = f"\n   🤝 شریک: {partner.flag} {partner.name_fa} ({status})"
            lines.append(
                f"🎪 <b>{drill.title or 'رزمایش'}</b>\n"
                f"   📍 {drill.area or '—'}\n"
                f"   🎯 آمادگی: +{fa_number(drill.readiness_gain, 1)}"
                + partner_text
            )

    await safe_edit(call, "\n".join(lines), reply_markup=drill_types_kb())


@router.callback_query(F.data.startswith("drill_type:"))
async def cb_drill_type(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب نوع رزمایش و درخواست عنوان."""
    await call.answer()
    try:
        dtype = DrillType(call.data.split(":")[1])
    except ValueError:
        await call.answer("نوع رزمایش نامعتبر است.", show_alert=True)
        return

    await state.clear()
    await state.update_data(drill_type=dtype.value, selected={}, page=0)
    await state.set_state(DrillForm.entering_title)

    await safe_edit(
        call,
        f"🎪 <b>{'رزمایش مشترک' if dtype is DrillType.JOINT else 'رزمایش تکی'}</b>\n\n"
        "📝 <b>نام رزمایش را بنویسید:</b>\n"
        "<i>مثال: «اقتدار ۱۴۰۵»، «سپر آسمان»، «ذوالفقار»</i>",
    )


@router.message(DrillForm.entering_title, F.text)
async def msg_drill_title(message: Message, state: FSMContext) -> None:
    """ثبت عنوان و درخواست منطقه."""
    title = message.text.strip()
    if not title:
        await message.answer("لطفاً نام رزمایش را بنویسید.")
        return

    await state.update_data(title=title)
    await state.set_state(DrillForm.entering_area)
    await message.answer(
        f"🎪 <b>{title}</b>\n\n"
        "📍 <b>منطقه‌ی برگزاری را بنویسید:</b>\n"
        "<i>مثال: «سواحل مکران»، «شمال غرب کشور»</i>"
    )


@router.message(DrillForm.entering_area, F.text)
async def msg_drill_area(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت منطقه و نمایش تجهیزات."""
    area = message.text.strip()
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    assets = await drill_service.available_assets(session, country.id)
    if not assets:
        await state.clear()
        await message.answer("⚠️ کشور شما تجهیزاتی برای رزمایش ندارد.", reply_markup=drill_types_kb())
        return

    await state.update_data(area=area, assets=assets)
    await state.set_state(DrillForm.selecting_assets)
    data = await state.get_data()
    await message.answer(
        header("نیروی شرکت‌کننده", "🪖") + f"\n\n🎪 {data.get('title')} — 📍 {area}\n\n"
        "تجهیزات شرکت‌کننده در رزمایش را انتخاب کنید:",
        reply_markup=asset_picker_kb(assets, {}, page=0),
    )


@router.callback_query(DrillForm.selecting_assets, F.data.startswith("op_page:"))
async def cb_drill_page(call: CallbackQuery, state: FSMContext) -> None:
    """ناوبری صفحه‌های تجهیزات رزمایش."""
    await call.answer()
    page = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)
    await safe_edit(
        call,
        header("نیروی شرکت‌کننده", "🪖") + "\n\n" + _selected_summary(dict(data.get("selected") or {})),
        reply_markup=asset_picker_kb(data.get("assets") or [], dict(data.get("selected") or {}), page=page),
    )


@router.callback_query(DrillForm.selecting_assets, F.data == "op_assets_clear")
async def cb_drill_clear(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌کردن انتخاب تجهیزات رزمایش."""
    await call.answer("انتخاب‌ها پاک شد")
    data = await state.get_data()
    await state.update_data(selected={})
    await safe_edit(
        call,
        header("نیروی شرکت‌کننده", "🪖") + "\n\nهنوز تجهیزاتی انتخاب نشده است.",
        reply_markup=asset_picker_kb(data.get("assets") or [], {}, page=data.get("page", 0)),
    )


@router.callback_query(DrillForm.selecting_assets, F.data.startswith("op_asset:"))
async def cb_drill_pick(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب یک قلم برای رزمایش."""
    await call.answer()
    index = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets") or []
    if index >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = assets[index]
    await state.update_data(pending_index=index)
    await state.set_state(DrillForm.entering_asset_count)
    await safe_edit(
        call,
        f"🪖 <b>{asset['name']}</b>\n"
        f"📦 موجودی: {fa_number(asset['count'])} {asset['unit']}\n\n"
        "چه تعداد در رزمایش شرکت می‌کنند؟\n"
        "<i>برای حذف، صفر بفرستید.</i>",
    )


@router.message(DrillForm.entering_asset_count, F.text)
async def msg_drill_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد تجهیزات رزمایش."""
    data = await state.get_data()
    assets = data.get("assets") or []
    index = data.get("pending_index")

    if index is None or index >= len(assets):
        await state.set_state(DrillForm.selecting_assets)
        await message.answer("خطا در انتخاب. دوباره تلاش کنید.")
        return

    asset = assets[index]
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("⚠️ عدد معتبر وارد کنید.")
        return

    count = int(amount)
    if count > asset["count"]:
        await message.answer(f"⚠️ حداکثر {fa_number(asset['count'])} {asset['unit']} دارید.")
        return

    selected = dict(data.get("selected") or {})
    if count == 0:
        selected.pop(asset["name"], None)
    else:
        selected[asset["name"]] = count

    await state.update_data(selected=selected, pending_index=None)
    await state.set_state(DrillForm.selecting_assets)
    await message.answer(
        header("نیروی شرکت‌کننده", "🪖") + "\n\n" + _selected_summary(selected),
        reply_markup=asset_picker_kb(assets, selected, page=data.get("page", 0)),
    )


@router.callback_query(DrillForm.selecting_assets, F.data == "op_assets_done")
async def cb_drill_assets_done(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """پایان انتخاب تجهیزات: رزمایش تکی ثبت می‌شود، مشترک شریک می‌خواهد."""
    await call.answer()
    data = await state.get_data()
    selected = dict(data.get("selected") or {})
    if not selected:
        await call.answer("ابتدا تجهیزات انتخاب کنید.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    dtype = DrillType(data["drill_type"])

    if dtype is DrillType.JOINT:
        await state.set_state(DrillForm.choosing_partner)
        countries = await countries_repo.list_countries(session)
        others = [c for c in countries if c.id != country.id and c.is_claimed]
        if not others:
            await state.clear()
            await safe_edit(
                call,
                "⚠️ کشور دیگری برای رزمایش مشترک در دسترس نیست.",
                reply_markup=drill_types_kb(),
            )
            return
        await safe_edit(
            call,
            "🤝 <b>کشور شریک رزمایش را انتخاب کنید:</b>",
            reply_markup=countries_kb(others, prefix="drill_partner", columns=2, back_data="op:drill"),
        )
        return

    await _finalize_drill(call, state, session, country, partner=None)


@router.callback_query(DrillForm.choosing_partner, F.data.startswith("drill_partner:"))
async def cb_drill_partner(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """انتخاب شریک رزمایش مشترک."""
    await call.answer()
    partner_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    partner = await countries_repo.get_country(session, partner_id)

    if country is None or partner is None:
        await state.clear()
        await safe_edit(call, "کشور شریک یافت نشد.", reply_markup=drill_types_kb())
        return

    await _finalize_drill(call, state, session, country, partner=partner)


async def _finalize_drill(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    country,
    *,
    partner,
) -> None:
    """ثبت نهایی رزمایش (تکی یا مشترک)."""
    data = await state.get_data()
    selected = dict(data.get("selected") or {})
    assets_meta = {a["name"]: a for a in (data.get("assets") or [])}
    payload = [
        {"name": name, "count": count, "unit": assets_meta.get(name, {}).get("unit", "عدد")}
        for name, count in selected.items()
    ]
    dtype = DrillType(data["drill_type"])
    title = data.get("title", "رزمایش")
    area = data.get("area", "")

    await state.clear()
    try:
        drill = await drill_service.start_drill(
            session, country, dtype, title, area, payload, partner=partner
        )
    except drill_service.DrillError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=drill_types_kb())
        return

    if partner is not None:
        await safe_edit(
            call,
            "📨 <b>دعوت رزمایش مشترک ارسال شد</b>\n\n"
            f"🎪 {title}\n"
            f"🤝 شریک: {partner.flag} {partner.name_fa}\n\n"
            "پس از پذیرش شریک، رزمایش آغاز می‌شود.",
            reply_markup=drill_types_kb(),
        )
        if partner.owner_user_id:
            try:
                await bot.send_message(
                    partner.owner_user_id,
                    f"🤝 <b>دعوت به رزمایش مشترک</b>\n\n"
                    f"کشور {country.flag} {country.name_fa} شما را به رزمایش "
                    f"«{title}» در منطقه‌ی {area} دعوت کرده است.\n\n"
                    f"🎯 آمادگی رزمی هر دو کشور: +{fa_number(drill.readiness_gain, 1)}",
                    reply_markup=confirm_cancel_kb(f"drill_ok:{drill.id}", f"drill_no:{drill.id}"),
                )
            except Exception:  # noqa: BLE001
                pass
    else:
        await safe_edit(
            call,
            "✅ <b>رزمایش آغاز شد</b>\n\n"
            f"🎪 {title}\n"
            f"📍 منطقه: {area}\n"
            f"⏱ مدت: {fa_number(DRILL_DURATION_HOURS)} ساعت\n"
            f"🎯 آمادگی رزمی پس از پایان: +{fa_number(drill.readiness_gain, 1)}",
            reply_markup=drill_types_kb(),
        )

    await send_log(
        bot,
        f"🎪 <b>برگزاری رزمایش</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نام: {title}\n"
        f"نوع: {'مشترک' if partner else 'تکی'}"
        + (f"\nشریک: {partner.flag} {partner.name_fa}" if partner else ""),
    )


@router.callback_query(F.data.startswith("drill_ok:"))
async def cb_drill_accept(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پذیرش دعوت رزمایش مشترک."""
    drill_id = int(call.data.split(":")[1])
    drill = await drill_repo.get_drill(session, drill_id)
    if drill is None:
        await call.answer("این رزمایش دیگر معتبر نیست.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None or drill.partner_country_id != country.id:
        await call.answer("شما مجاز به پاسخ به این دعوت نیستید.", show_alert=True)
        return

    try:
        await drill_service.accept_joint_drill(session, drill)
    except drill_service.DrillError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("دعوت پذیرفته شد ✅")
    await safe_edit(
        call,
        f"✅ <b>رزمایش مشترک آغاز شد</b>\n\n"
        f"🎪 {drill.title}\n"
        f"⏱ مدت: {fa_number(DRILL_DURATION_HOURS)} ساعت\n"
        f"🎯 آمادگی رزمی: +{fa_number(drill.readiness_gain, 1)}",
    )

    host = await countries_repo.get_country(session, drill.country_id)
    if host and host.owner_user_id:
        try:
            await bot.send_message(
                host.owner_user_id,
                f"✅ {country.flag} {country.name_fa} دعوت رزمایش «{drill.title}» را پذیرفت.",
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("drill_no:"))
async def cb_drill_reject(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """رد دعوت رزمایش مشترک."""
    drill_id = int(call.data.split(":")[1])
    drill = await drill_repo.get_drill(session, drill_id)
    if drill is None:
        await call.answer("این رزمایش دیگر معتبر نیست.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None or drill.partner_country_id != country.id:
        await call.answer("شما مجاز به پاسخ به این دعوت نیستید.", show_alert=True)
        return

    await drill_service.reject_joint_drill(session, drill)
    await call.answer("دعوت رد شد")
    await safe_edit(call, "❌ دعوت رزمایش مشترک رد شد.")

    host = await countries_repo.get_country(session, drill.country_id)
    if host and host.owner_user_id:
        try:
            await bot.send_message(
                host.owner_user_id,
                f"❌ {country.flag} {country.name_fa} دعوت رزمایش «{drill.title}» را رد کرد.",
            )
        except Exception:  # noqa: BLE001
            pass
