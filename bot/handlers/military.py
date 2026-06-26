"""هندلر بخش نظامی: گزارش تجهیزات و ۴ نوع حمله."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    MIL_FACTORY_BUILD_RESOURCES,
    MIL_FACTORY_COST_USD,
    MIL_FACTORY_INTAKE,
    MIL_FACTORY_YIELD,
)
from ..database.models import Attack, MilitaryFactory, MilitarySale, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_factory as milfac_repo
from ..database.repositories import military_sale as milsale_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import (
    ATTACK_FA,
    MIL_FACTORY_CATEGORY,
    MIL_FACTORY_FA,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    AttackStatus,
    AttackType,
    MilitaryFactoryType,
    ResourceType,
    TradeStatus,
)
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.military import (
    attack_types_kb,
    military_factory_menu_kb,
    military_factory_types_kb,
    military_menu_kb,
)
from ..loader import bot
from ..services.ai import evaluators
from ..services.media import send_photo_news
from ..services.military_service import apply_losses, format_casualties_log
from ..services.news_service import send_log
from ..states import AttackForm, MilitaryFactoryForm, MilitarySaleForm
from ..utils.formatting import render_military_panel
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.ui import STYLE_NO, STYLE_OK, header
from aiogram.utils.keyboard import InlineKeyboardBuilder
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="military")
settings = get_settings()


def _fmt_resources(resources: dict[str, float]) -> str:
    """نمایش یک دیکشنری منابع به‌صورت چندخطی فارسی (با واحد هر منبع)."""
    lines = []
    for key, amount in resources.items():
        try:
            rtype = ResourceType(key)
            name = RESOURCE_FA[rtype]
            unit = RESOURCE_UNIT_FA[rtype]
        except (ValueError, KeyError):
            name, unit = key, ""
        lines.append(f"• {name}: {fa_number(amount)} {unit}")
    return "\n".join(lines)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _back_kb(callback_data: str) -> InlineKeyboardMarkup:
    """کیبورد تک‌دکمه‌ای بازگشت به مرحله‌ی قبل (v1.8)."""
    from ..utils.ui import STYLE_MAIN

    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data, style=STYLE_MAIN)
    ]])


@router.callback_query(F.data == "mil:report")
async def cb_report(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """⚔️ پنل گزارش تجهیزات نظامی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    assets = await mil_repo.list_assets(session, country.id)
    text = render_military_panel(country, assets)
    # تلگرام محدودیت طول پیام دارد؛ در صورت نیاز کوتاه می‌شود
    if len(text) > 3900:
        text = text[:3900] + "\n..."
    await call.message.edit_text(text, reply_markup=military_menu_kb())


@router.callback_query(F.data == "mil:attack")
async def cb_attack(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    await state.set_state(AttackForm.choosing_type)
    await call.message.edit_text("💥 نوع حمله را انتخاب کنید:", reply_markup=attack_types_kb())


@router.callback_query(AttackForm.choosing_type, F.data.startswith("atk_type:"))
async def cb_attack_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    atype = AttackType(call.data.split(":")[1])
    await state.update_data(attack_type=atype.value)
    await state.set_state(AttackForm.choosing_target)
    country = await get_player_country(session, db_user)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await call.message.edit_text(
        f"🎯 هدف {ATTACK_FA[atype]} را انتخاب کنید:",
        reply_markup=countries_kb(others, prefix="atk_target", columns=2, back_data="menu:military"),
    )


@router.callback_query(AttackForm.choosing_target, F.data.startswith("atk_target:"))
async def cb_attack_target(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(target_id=int(call.data.split(":")[1]))
    await state.set_state(AttackForm.describing)
    await call.message.edit_text(
        "📝 تجهیزات و هدف حمله را شرح دهید (متن آزاد):\n"
        "مثال: «حمله با ۲۰ جنگنده F-16 به پایگاه هوایی دشمن»",
        reply_markup=_back_kb("atkback:target"),
    )


@router.callback_query(StateFilter(AttackForm), F.data == "atkback:target")
async def cb_attack_back_target(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """بازگشت به انتخاب هدف حمله."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    data = await state.get_data()
    atype = AttackType(data["attack_type"])
    await state.set_state(AttackForm.choosing_target)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await call.message.edit_text(
        f"🎯 هدف {ATTACK_FA[atype]} را انتخاب کنید:",
        reply_markup=countries_kb(others, prefix="atk_target", columns=2, back_data="menu:military"),
    )


@router.message(AttackForm.describing, F.text)
async def msg_attack_describe(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """
    شرح حمله (هر چهار نوع): فقط امکان‌سنجی توسط AI انجام می‌شود و در صورت تأیید،
    شرح بازیکن به گروه لاگ مدیریت ارسال می‌شود تا مالک دستی نتیجه و خبر را وارد کند.
    هیچ تلفات یا اثری به‌صورت خودکار اعمال نمی‌شود (v1.9).
    """
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["target_id"])
    await state.clear()
    if country is None or target is None:
        await message.answer("خطا در ثبت حمله.")
        return

    atype = AttackType(data["attack_type"])

    await message.answer("⏳ در حال امکان‌سنجی حمله توسط فرماندهی...")
    result = await evaluators.evaluate_attack(
        session, country.id, target.id, ATTACK_FA[atype], message.text
    )

    # امکان‌سنجی: اگر غیرمنطقی/غیرممکن بود رد می‌شود
    if result.get("feasible") is False:
        reason = result.get("reject_reason") or "این حمله از نظر نظامی غیرقابل‌انجام است."
        await message.answer(
            f"⛔️ <b>حمله انجام نخواهد شد</b>\n\nدلیل: {reason}",
            reply_markup=military_menu_kb(),
        )
        return

    # امکان‌پذیر است → فقط شرح بازیکن به گروه لاگ می‌رود (نتیجه را مالک دستی اعلام می‌کند)
    await send_log(
        bot,
        f"💥 <b>درخواست {ATTACK_FA[atype]}</b>\n\n"
        f"🔴 مهاجم: {country.flag} {country.name_fa}\n"
        f"🔵 هدف: {target.flag} {target.name_fa}\n\n"
        f"📝 شرح بازیکن:\n{message.text}",
    )
    await message.answer(
        "✅ حمله‌ی شما امکان‌پذیر تشخیص داده شد و برای بررسی و اعلام نتیجه به مدیریت بازی ارسال شد.",
        reply_markup=military_menu_kb(),
    )


# ============================================================
#  🏭 سیستم کارخانه‌ی نظامی (v1.7) — بازتولید تجهیزات
# ============================================================
@router.callback_query(F.data == "mil:factory")
async def cb_factory_menu(call: CallbackQuery, state: FSMContext) -> None:
    """منوی کارخانه‌ی نظامی."""
    await call.answer()
    await state.clear()
    await call.message.edit_text(
        header("کارخانه نظامی", "🏭") + "\n\nبا احداث کارخانه می‌توانید تجهیزات موجود کشورتان را بازتولید کنید.",
        reply_markup=military_factory_menu_kb(),
    )


@router.callback_query(F.data == "milfac:build")
async def cb_factory_build(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب نوع کارخانه برای احداث."""
    await call.answer()
    await state.set_state(MilitaryFactoryForm.choosing_type)
    await call.message.edit_text(
        "🏗 نوع کارخانه‌ای که می‌خواهید احداث کنید را انتخاب کنید:",
        reply_markup=military_factory_types_kb(),
    )


@router.callback_query(MilitaryFactoryForm.choosing_type, F.data.startswith("milfac_type:"))
async def cb_factory_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """نمایش تجهیزات کشور در این دسته برای انتخاب قلم بازتولیدی."""
    await call.answer()
    ftype = MilitaryFactoryType(call.data.split(":")[1])
    category = MIL_FACTORY_CATEGORY[ftype]
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    assets = await mil_repo.list_assets(session, country.id)
    matching = [a for a in assets if a.category == category]
    if not matching:
        await call.message.edit_text(
            f"⚠️ کشور شما در دسته‌ی «{category}» تجهیزاتی برای بازتولید ندارد.",
            reply_markup=military_factory_menu_kb(),
        )
        return

    # ذخیره‌ی لیست برای انتخاب با ایندکس (به‌جای نام طولانی در callback)
    await state.update_data(
        factory_type=ftype.value,
        assets=[{"name": a.name, "unit": a.unit} for a in matching],
    )
    await state.set_state(MilitaryFactoryForm.choosing_asset)
    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(matching):
        builder.button(text=a.name, callback_data=f"milfac_asset:{idx}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="milfac:build", style="primary")
    builder.adjust(1)
    await call.message.edit_text(
        f"کدام قلم از «{category}» را بازتولید می‌کنید؟",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(MilitaryFactoryForm.choosing_asset, F.data.startswith("milfac_asset:"))
async def cb_factory_asset(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب قلم تجهیزات و درخواست محل احداث."""
    await call.answer()
    idx = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets", [])
    if idx >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    await state.update_data(asset_name=assets[idx]["name"], asset_unit=assets[idx]["unit"])
    await state.set_state(MilitaryFactoryForm.entering_location)
    await call.message.edit_text(
        f"🏭 کارخانه‌ی بازتولید <b>{assets[idx]['name']}</b>\n\n📍 محل احداث را وارد کنید:",
        reply_markup=_back_kb("mfback:asset"),
    )


@router.callback_query(StateFilter(MilitaryFactoryForm), F.data == "mfback:asset")
async def cb_factory_back_asset(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب قلم تجهیزات کارخانه."""
    await call.answer()
    data = await state.get_data()
    assets = data.get("assets", [])
    category = ""
    try:
        category = MIL_FACTORY_CATEGORY[MilitaryFactoryType(data["factory_type"])]
    except (ValueError, KeyError):
        pass
    await state.set_state(MilitaryFactoryForm.choosing_asset)
    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(assets):
        builder.button(text=a["name"], callback_data=f"milfac_asset:{idx}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="milfac:build", style="primary")
    builder.adjust(1)
    await call.message.edit_text(
        f"کدام قلم از «{category}» را بازتولید می‌کنید؟",
        reply_markup=builder.as_markup(),
    )


@router.message(MilitaryFactoryForm.entering_location, F.text)
async def msg_factory_location(message: Message, state: FSMContext) -> None:
    """نمایش هزینه‌ها و درخواست تأیید نهایی."""
    data = await state.get_data()
    ftype = MilitaryFactoryType(data["factory_type"])
    location = message.text.strip()
    await state.update_data(location=location)
    await state.set_state(MilitaryFactoryForm.confirming)

    cost = MIL_FACTORY_COST_USD[ftype]
    build_res = MIL_FACTORY_BUILD_RESOURCES[ftype]
    intake = MIL_FACTORY_INTAKE[ftype]
    yield_amount, interval_h = MIL_FACTORY_YIELD[ftype]
    interval_fa = "۲۴ ساعت" if interval_h == 24 else f"{fa_number(interval_h // 24)} روز"

    await message.answer(
        f"🏭 <b>{MIL_FACTORY_FA[ftype]}</b>\n"
        f"📦 بازتولید: {data['asset_name']}\n"
        f"📍 محل: {location}\n\n"
        f"💰 هزینه‌ی ساخت: {fa_money(cost)}\n\n"
        f"🧱 <b>منابع لازم برای ساخت:</b>\n{_fmt_resources(build_res)}\n\n"
        f"🔄 <b>مصرف هر چرخه:</b>\n{_fmt_resources(intake)}\n\n"
        f"🏭 بازدهی: {fa_number(yield_amount)} {data['asset_unit']} در هر {interval_fa}\n\n"
        "آیا احداث این کارخانه را تأیید می‌کنید؟",
        reply_markup=confirm_cancel_kb("milfac_confirm"),
    )


@router.callback_query(MilitaryFactoryForm.confirming, F.data == "milfac_confirm")
async def cb_factory_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """بررسی بودجه و منابع، کسر آن‌ها و ساخت کارخانه."""
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return

    ftype = MilitaryFactoryType(data["factory_type"])
    cost = MIL_FACTORY_COST_USD[ftype]
    build_res = MIL_FACTORY_BUILD_RESOURCES[ftype]
    yield_amount, interval_h = MIL_FACTORY_YIELD[ftype]

    if country.budget < cost:
        await call.message.edit_text(
            f"⛔️ بودجه‌ی کافی ندارید. هزینه‌ی این کارخانه {fa_money(cost)} است.",
            reply_markup=military_factory_menu_kb(),
        )
        return

    # بررسی کافی‌بودن همه‌ی منابع لازم برای ساخت
    for key, amount in build_res.items():
        if not await reserves_repo.has_enough(session, country.id, key, amount):
            rname = RESOURCE_FA.get(ResourceType(key), key) if key in [r.value for r in ResourceType] else key
            await call.message.edit_text(
                f"⛔️ منابع کافی برای ساخت ندارید. کمبود در: {rname}.",
                reply_markup=military_factory_menu_kb(),
            )
            return

    # کسر بودجه و منابع
    country.budget -= cost
    for key, amount in build_res.items():
        await reserves_repo.add_amount(session, country.id, key, -amount)

    factory = MilitaryFactory(
        country_id=country.id,
        factory_type=ftype.value,
        asset_name=data["asset_name"],
        category=MIL_FACTORY_CATEGORY[ftype],
        unit=data.get("asset_unit", "عدد"),
        location=data.get("location", ""),
        cost=cost,
        yield_amount=yield_amount,
        yield_interval_h=interval_h,
        active=True,
        last_yield_at=_utcnow(),
    )
    await milfac_repo.add_factory(session, factory)

    interval_fa = "۲۴ ساعت" if interval_h == 24 else f"{fa_number(interval_h // 24)} روز"
    await call.message.edit_text(
        f"✅ {MIL_FACTORY_FA[ftype]} برای بازتولید «{data['asset_name']}» در «{data.get('location','')}» احداث شد.\n"
        f"🏭 بازدهی: {fa_number(yield_amount)} {factory.unit} در هر {interval_fa}\n"
        f"💰 بودجه‌ی باقی‌مانده: {fa_money(country.budget)}",
        reply_markup=military_factory_menu_kb(),
    )

    # لاگ احداث کارخانه به گروه لاگ (بدون خبر در کانال)
    await send_log(
        bot,
        "🏭 <b>احداث کارخانه نظامی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"کارخانه: {MIL_FACTORY_FA[ftype]}\n"
        f"بازتولید: {data['asset_name']}\n"
        f"محل: {data.get('location','')}\n"
        f"هزینه: {fa_money(cost)}",
    )


@router.callback_query(F.data == "milfac:mine")
async def cb_factory_mine(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست کارخانه‌های نظامی کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    factories = await milfac_repo.list_factories(session, country.id)
    if not factories:
        await call.message.edit_text(
            "🏭 هنوز کارخانه‌ی نظامی‌ای احداث نکرده‌اید.",
            reply_markup=military_factory_menu_kb(),
        )
        return
    lines = ["🏭 <b>کارخانه‌های نظامی شما</b>", ""]
    for f in factories:
        try:
            fa = MIL_FACTORY_FA[MilitaryFactoryType(f.factory_type)]
        except ValueError:
            fa = f.factory_type
        interval_fa = "۲۴ ساعت" if f.yield_interval_h == 24 else f"{fa_number(f.yield_interval_h // 24)} روز"
        lines.append(
            f"• {fa} — بازتولید {f.asset_name}\n"
            f"   📍 {f.location} | 🏭 {fa_number(f.yield_amount)} {f.unit}/{interval_fa} | 💰 {fa_money(f.cost)}"
        )
    await call.message.edit_text("\n".join(lines), reply_markup=military_factory_menu_kb())


# ============================================================
#  💰 فروش تجهیزات نظامی (v1.7)
# ============================================================
@router.callback_query(F.data == "mil:sell")
async def cb_sell(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب دسته‌ی تجهیزات برای فروش."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    assets = await mil_repo.list_assets(session, country.id)
    assets = [a for a in assets if a.count > 0]
    if not assets:
        await call.message.edit_text("⚠️ تجهیزاتی برای فروش ندارید.", reply_markup=military_menu_kb())
        return

    # دسته‌های موجود (یکتا، با حفظ ترتیب)
    categories: list[str] = []
    for a in assets:
        if a.category not in categories:
            categories.append(a.category)
    await state.update_data(sell_assets=[
        {"name": a.name, "unit": a.unit, "category": a.category, "branch": a.branch, "count": a.count}
        for a in assets
    ])
    await state.set_state(MilitarySaleForm.choosing_category)
    builder = InlineKeyboardBuilder()
    for idx, cat in enumerate(categories):
        builder.button(text=cat, callback_data=f"milsell_cat:{idx}", style="primary")
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style="primary")
    builder.adjust(2)
    await state.update_data(sell_categories=categories)
    await call.message.edit_text("💰 قصد فروش کدام دسته از تجهیزات را دارید؟", reply_markup=builder.as_markup())


@router.callback_query(MilitarySaleForm.choosing_category, F.data.startswith("milsell_cat:"))
async def cb_sell_category(call: CallbackQuery, state: FSMContext) -> None:
    """نمایش تجهیزات آن دسته."""
    await call.answer()
    idx = int(call.data.split(":")[1])
    data = await state.get_data()
    categories = data.get("sell_categories", [])
    if idx >= len(categories):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    category = categories[idx]
    assets = [a for a in data.get("sell_assets", []) if a["category"] == category]
    await state.update_data(sell_filtered=assets, sell_category_name=category)
    await _show_sell_assets(call, state)


async def _show_sell_assets(call: CallbackQuery, state: FSMContext) -> None:
    """نمایش فهرست تجهیزات یک دسته برای فروش (با دکمه‌ی بازگشت)."""
    data = await state.get_data()
    assets = data.get("sell_filtered", [])
    category = data.get("sell_category_name", "")
    await state.set_state(MilitarySaleForm.choosing_asset)
    builder = InlineKeyboardBuilder()
    for i, a in enumerate(assets):
        builder.button(text=f"{a['name']} ({fa_number(a['count'])})", callback_data=f"milsell_asset:{i}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="mil:sell", style="primary")
    builder.adjust(1)
    await call.message.edit_text(f"کدام قلم از «{category}» را می‌فروشید؟", reply_markup=builder.as_markup())


@router.callback_query(StateFilter(MilitarySaleForm), F.data == "msback:asset")
async def cb_milsell_back_asset(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به انتخاب قلم تجهیزات برای فروش."""
    await call.answer()
    await _show_sell_assets(call, state)


@router.callback_query(MilitarySaleForm.choosing_asset, F.data.startswith("milsell_asset:"))
async def cb_sell_asset(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب قلم و درخواست تعداد."""
    await call.answer()
    i = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("sell_filtered", [])
    if i >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    await state.update_data(sell_pick=assets[i])
    await state.set_state(MilitarySaleForm.entering_count)
    await call.message.edit_text(
        f"تعداد {assets[i]['name']} برای فروش را وارد کنید (موجودی: {fa_number(assets[i]['count'])} {assets[i]['unit']}):",
        reply_markup=_back_kb("msback:asset"),
    )


@router.message(MilitarySaleForm.entering_count, F.text)
async def msg_sell_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد و درخواست قیمت."""
    count = parse_amount(message.text)
    data = await state.get_data()
    pick = data.get("sell_pick")
    if pick is None:
        await message.answer("خطا در فروش.")
        await state.clear()
        return
    if count is None or count <= 0 or int(count) > pick["count"]:
        await message.answer(f"عدد نامعتبر. موجودی شما {fa_number(pick['count'])} است.")
        return
    await state.update_data(sell_count=int(count))
    await state.set_state(MilitarySaleForm.entering_price)
    await message.answer(
        "مبلغ فروش را به دلار وارد کنید (مثلاً 5b برای ۵ میلیارد):",
        reply_markup=_back_kb("msback:count"),
    )


@router.callback_query(StateFilter(MilitarySaleForm), F.data == "msback:count")
async def cb_milsell_back_count(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به وارد کردن تعداد تجهیزات."""
    await call.answer()
    data = await state.get_data()
    pick = data.get("sell_pick")
    if pick is None:
        await _show_sell_assets(call, state)
        return
    await state.set_state(MilitarySaleForm.entering_count)
    await call.message.edit_text(
        f"تعداد {pick['name']} برای فروش را وارد کنید (موجودی: {fa_number(pick['count'])} {pick['unit']}):",
        reply_markup=_back_kb("msback:asset"),
    )


@router.message(MilitarySaleForm.entering_price, F.text)
async def msg_sell_price(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت قیمت و انتخاب کشور خریدار."""
    price = parse_amount(message.text)
    if price is None or price <= 0:
        await message.answer("لطفاً مبلغ معتبر وارد کنید.")
        return
    await state.update_data(sell_price=price)
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return
    await state.set_state(MilitarySaleForm.choosing_buyer)
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await message.answer(
        "کشور خریدار را انتخاب کنید:",
        reply_markup=countries_kb(others, prefix="milsell_buyer", columns=2, back_data="msback:price"),
    )


@router.callback_query(StateFilter(MilitarySaleForm), F.data == "msback:price")
async def cb_milsell_back_price(call: CallbackQuery, state: FSMContext) -> None:
    """بازگشت به وارد کردن قیمت فروش تجهیزات."""
    await call.answer()
    await state.set_state(MilitarySaleForm.entering_price)
    await call.message.edit_text(
        "مبلغ فروش را به دلار وارد کنید (مثلاً 5b برای ۵ میلیارد):",
        reply_markup=_back_kb("msback:count"),
    )


@router.callback_query(MilitarySaleForm.choosing_buyer, F.data.startswith("milsell_buyer:"))
async def cb_sell_buyer(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ساخت پیشنهاد فروش و ارسال به خریدار."""
    await call.answer()
    buyer_id = int(call.data.split(":")[1])
    data = await state.get_data()
    pick = data.get("sell_pick")
    count = data.get("sell_count")
    price = data.get("sell_price")
    country = await get_player_country(session, db_user)
    await state.clear()
    if country is None or pick is None:
        await call.message.edit_text("خطا در فروش.")
        return
    buyer = await countries_repo.get_country(session, buyer_id)
    if buyer is None:
        await call.message.edit_text("کشور خریدار یافت نشد.")
        return

    # اطمینان از موجودی فعلی فروشنده
    asset = await mil_repo.get_asset_by_name(session, country.id, pick["name"])
    if asset is None or asset.count < count:
        await call.message.edit_text("موجودی شما برای این تعداد کافی نیست.", reply_markup=military_menu_kb())
        return

    sale = MilitarySale(
        seller_country=country.id,
        buyer_country=buyer_id,
        category=pick["category"],
        branch=pick.get("branch", ""),
        name=pick["name"],
        unit=pick["unit"],
        count=int(count),
        price=price,
        status=TradeStatus.PENDING,
    )
    await milsale_repo.add_sale(session, sale)
    await session.flush()

    await call.message.edit_text(
        f"📨 پیشنهاد فروش نظامی برای {buyer.flag} {buyer.name_fa} ارسال شد:\n"
        f"{fa_number(count)} {pick['unit']} {pick['name']} به مبلغ {fa_money(price)}\n\n"
        "پس از تأیید خریدار، محموله توسط WTO ارسال می‌شود."
    )
    if buyer.owner_user_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ خرید", callback_data=f"milsale_ok:{sale.id}", style=STYLE_OK),
            InlineKeyboardButton(text="❌ رد", callback_data=f"milsale_no:{sale.id}", style=STYLE_NO),
        ]])
        try:
            await bot.send_message(
                buyer.owner_user_id,
                f"🛒 <b>پیشنهاد خرید تجهیزات نظامی</b>\n\n"
                f"فروشنده: {country.flag} {country.name_fa}\n"
                f"تجهیزات: {fa_number(count)} {pick['unit']} {pick['name']}\n"
                f"قیمت: {fa_money(price)}",
                reply_markup=kb,
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("milsale_ok:"))
async def cb_milsale_ok(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأیید خرید تجهیزات: انتقال مالی و ارسال محموله‌ی نظامی توسط WTO."""
    sale_id = int(call.data.split(":")[1])
    sale = await milsale_repo.get_sale(session, sale_id)
    if sale is None or sale.status != TradeStatus.PENDING:
        await call.answer("این پیشنهاد دیگر معتبر نیست.", show_alert=True)
        return
    buyer = await countries_repo.get_country(session, sale.buyer_country)
    if buyer is None or buyer.owner_user_id != db_user.telegram_id:
        await call.answer("شما مجاز به تأیید این خرید نیستید.", show_alert=True)
        return
    seller = await countries_repo.get_country(session, sale.seller_country)
    if seller is None:
        await call.answer("فروشنده یافت نشد.", show_alert=True)
        return

    asset = await mil_repo.get_asset_by_name(session, sale.seller_country, sale.name)
    if asset is None or asset.count < sale.count:
        await call.answer("موجودی فروشنده کافی نیست.", show_alert=True)
        return
    if buyer.budget < sale.price:
        await call.answer("بودجه‌ی شما کافی نیست.", show_alert=True)
        return

    # انتقال مالی و کسر تجهیزات از فروشنده (افزودن به خریدار هنگام رسیدن محموله)
    buyer.budget -= sale.price
    seller.budget += sale.price
    asset.count -= sale.count

    # تخمین زمان رسیدن محموله توسط AI
    eta_data = await evaluators.estimate_shipping_time(
        seller.name_fa, buyer.name_fa, sale.name, sale.count
    )
    minutes = int(eta_data.get("shipping_minutes", 30) or 30)
    minutes = max(5, min(minutes, 120))
    sale.ship_eta = _utcnow() + timedelta(minutes=minutes)
    sale.status = TradeStatus.IN_TRANSIT

    await call.answer("خرید تأیید شد ✅")
    await call.message.edit_text(
        call.message.html_text + f"\n\n✅ <b>تأیید شد</b> — زمان رسیدن: حدود {fa_number(minutes)} دقیقه"
    )

    if seller.owner_user_id:
        try:
            await bot.send_message(
                seller.owner_user_id,
                f"✅ {buyer.flag} {buyer.name_fa} پیشنهاد فروش نظامی شما را پذیرفت. محموله در راه است.",
            )
        except Exception:  # noqa: BLE001
            pass

    # خبر محموله‌ی نظامی در کانال WTO (عکس + فرمت)
    if settings.wto_channel_id is not None:
        caption = (
            "🔵 | اطلاع رسانی سازمان نقل و انتقالات جهانی\n\n"
            f"✈ | یک محموله نظامی کشور {seller.flag} {seller.name_fa} را به مقصد کشور "
            f"{buyer.flag} {buyer.name_fa} ترک کرد.\n"
            f"⏳ | مدت زمان پرواز: {fa_number(minutes)} دقیقه"
        )
        await send_photo_news(bot, settings.wto_channel_id, "wto", caption)

    # لاگ فروش نظامی به گروه لاگ + دکمه‌ی «تحویل فوری» برای مدیران (v1.8)
    deliver_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚡️ تحویل فوری محموله", callback_data=f"gdeliver:mil:{sale.id}", style=STYLE_OK
        )
    ]])
    await send_log(
        bot,
        "🪖 <b>فروش تجهیزات نظامی</b>\n"
        f"فروشنده: {seller.flag} {seller.name_fa}\n"
        f"خریدار: {buyer.flag} {buyer.name_fa}\n"
        f"تجهیزات: {fa_number(sale.count)} {sale.unit} {sale.name}\n"
        f"قیمت: {fa_money(sale.price)}",
        reply_markup=deliver_kb,
    )


@router.callback_query(F.data.startswith("milsale_no:"))
async def cb_milsale_no(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """رد پیشنهاد خرید تجهیزات نظامی."""
    sale_id = int(call.data.split(":")[1])
    sale = await milsale_repo.get_sale(session, sale_id)
    if sale is None or sale.status != TradeStatus.PENDING:
        await call.answer("این پیشنهاد دیگر معتبر نیست.", show_alert=True)
        return
    sale.status = TradeStatus.REJECTED
    await call.answer("رد شد")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")
    seller = await countries_repo.get_country(session, sale.seller_country)
    if seller and seller.owner_user_id:
        try:
            await bot.send_message(seller.owner_user_id, "❌ پیشنهاد فروش نظامی شما رد شد.")
        except Exception:  # noqa: BLE001
            pass
