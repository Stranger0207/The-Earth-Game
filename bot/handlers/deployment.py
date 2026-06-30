"""
هندلر استقرار نیرو (v1.11) — فقط کشورهای VIP.

جریان «استقرار نیروی جدید»: انتخاب نوع کلان (زمینی/دریایی/هوایی) → انتخاب قلم تجهیزات از آن
دسته → تعداد → منطقه‌ی هدف → تأیید (هزینه‌ی تقریبی نفت). با تأیید، نفت کسر و خبر فوری با عکس
مخصوص در کانال نظامی منتشر می‌شود. تجهیزات از موجودی کشور کم نمی‌شوند.

«نیروهای مستقر»: آپدیت مکان یک گروه یا حذف گروه.
"""

from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    DEPLOY_BRANCHES,
    DEPLOY_OIL_COST_MAX,
    DEPLOY_OIL_COST_MIN,
    DEPLOY_OIL_PER_UNIT_MAX,
    DEPLOY_OIL_PER_UNIT_MIN,
)
from ..database.models import Deployment, User
from ..database.repositories import deployments as dep_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import ResourceType
from ..keyboards.common import confirm_cancel_kb
from ..keyboards.military import deploy_branch_kb, deploy_menu_kb, deployed_actions_kb, military_menu_kb
from ..loader import bot
from ..services.media import send_specific_photo
from ..services.news_service import send_log
from ..states import DeploymentForm
from ..utils.numbers import fa_number, parse_amount
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="deployment")
settings = get_settings()

_NOT_VIP_TEXT = "⛔️ فقط کشورهای VIP می‌توانند نیرو مستقر کنند."


def _back_deploy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="mil:deploy", style=STYLE_MAIN)
    ]])


def _compute_oil_cost(count: int) -> float:
    """هزینه‌ی تقریبی نفت (میلیون بشکه): وابسته به حجم نیرو، محدود به بازه‌ی ۱ تا ۱۰."""
    per_unit = random.uniform(DEPLOY_OIL_PER_UNIT_MIN, DEPLOY_OIL_PER_UNIT_MAX)
    raw = count * per_unit
    return round(min(DEPLOY_OIL_COST_MAX, max(DEPLOY_OIL_COST_MIN, raw)), 1)


# ============================================================
#  منوی استقرار
# ============================================================
@router.callback_query(F.data == "mil:deploy")
async def cb_deploy_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if not country.is_vip:
        await call.message.edit_text(
            header("استقرار نیرو", "🪖") + "\n\n" + _NOT_VIP_TEXT,
            reply_markup=military_menu_kb(),
        )
        return
    await call.message.edit_text(
        header("استقرار نیرو", "🪖")
        + "\n\nمی‌توانید نیرو به یک منطقه اعزام کنید یا نیروهای مستقر خود را مدیریت کنید.",
        reply_markup=deploy_menu_kb(),
    )


# ============================================================
#  استقرار نیروی جدید
# ============================================================
@router.callback_query(F.data == "dep:new")
async def cb_deploy_new(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if not country.is_vip:
        await call.message.edit_text(_NOT_VIP_TEXT, reply_markup=military_menu_kb())
        return
    await state.set_state(DeploymentForm.choosing_branch)
    await call.message.edit_text(
        "🪖 چه نوع نیرویی را به جنگ می‌برید؟", reply_markup=deploy_branch_kb()
    )


@router.callback_query(DeploymentForm.choosing_branch, F.data.startswith("dep_branch:"))
async def cb_deploy_branch(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    key = call.data.split(":")[1]
    if key not in DEPLOY_BRANCHES:
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    branch_fa, _stem, branches = DEPLOY_BRANCHES[key]
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    assets = await mil_repo.list_assets(session, country.id)
    matching = [a for a in assets if a.branch in branches and a.count > 0]
    if not matching:
        await call.message.edit_text(
            f"⚠️ کشور شما در نیروی «{branch_fa}» تجهیزات قابل‌اعزامی ندارد.",
            reply_markup=_back_deploy_kb(),
        )
        return
    # ذخیره‌ی لیست برای انتخاب با ایندکس
    await state.update_data(
        branch_key=key,
        branch_fa=branch_fa,
        assets=[{"name": a.name, "unit": a.unit, "count": a.count} for a in matching],
    )
    await state.set_state(DeploymentForm.choosing_asset)
    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(matching):
        builder.button(
            text=f"{a.name} ({fa_number(a.count)})", callback_data=f"dep_asset:{idx}", style=STYLE_OK
        )
    builder.button(text="🔙 بازگشت", callback_data="dep:new", style=STYLE_MAIN)
    builder.adjust(1)
    await call.message.edit_text(
        f"کدام تجهیزات نیروی «{branch_fa}» را اعزام می‌کنید؟", reply_markup=builder.as_markup()
    )


@router.callback_query(DeploymentForm.choosing_asset, F.data.startswith("dep_asset:"))
async def cb_deploy_asset(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    idx = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets", [])
    if idx >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return
    pick = assets[idx]
    await state.update_data(asset_name=pick["name"], asset_unit=pick["unit"], asset_count=pick["count"])
    await state.set_state(DeploymentForm.entering_count)
    await call.message.edit_text(
        f"🔢 چه تعداد «{pick['name']}» اعزام می‌کنید؟ (موجودی: {fa_number(pick['count'])} {pick['unit']})",
        reply_markup=_back_deploy_kb(),
    )


@router.message(DeploymentForm.entering_count, F.text)
async def msg_deploy_count(message: Message, state: FSMContext) -> None:
    count = parse_amount(message.text)
    data = await state.get_data()
    available = int(data.get("asset_count", 0))
    if count is None or count <= 0 or int(count) > available:
        await message.answer(f"عدد نامعتبر. موجودی شما {fa_number(available)} است.")
        return
    count = int(count)
    oil_cost = _compute_oil_cost(count)
    await state.update_data(deploy_count=count, oil_cost=oil_cost)
    await state.set_state(DeploymentForm.entering_region)
    await message.answer("📍 منطقه‌ی هدف اعزام را وارد کنید:")


@router.message(DeploymentForm.entering_region, F.text)
async def msg_deploy_region(message: Message, state: FSMContext) -> None:
    region = message.text.strip()
    data = await state.get_data()
    await state.update_data(region=region)
    await state.set_state(DeploymentForm.confirming)
    await message.answer(
        "❓ <b>آیا مطمئن هستید؟</b>\n\n"
        f"🪖 نیرو: {data.get('branch_fa')}\n"
        f"📦 تجهیزات: {fa_number(data.get('deploy_count'))} {data.get('asset_unit')} {data.get('asset_name')}\n"
        f"📍 منطقه: {region}\n"
        f"🛢 هزینه‌ی تقریبی: {fa_number(data.get('oil_cost'))} میلیون بشکه نفت\n\n"
        "با تأیید، این مقدار نفت از ذخایر شما کسر می‌شود.",
        reply_markup=confirm_cancel_kb("dep:confirm", cancel_data="mil:deploy"),
    )


@router.callback_query(DeploymentForm.confirming, F.data == "dep:confirm")
async def cb_deploy_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if not country.is_vip:
        await call.message.edit_text(_NOT_VIP_TEXT, reply_markup=military_menu_kb())
        return

    branch_key = data.get("branch_key")
    branch_fa = data.get("branch_fa", "")
    asset_name = data.get("asset_name", "")
    count = int(data.get("deploy_count", 0))
    region = data.get("region", "")
    oil_cost = float(data.get("oil_cost", 0))

    # کفایت نفت
    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, oil_cost):
        await call.message.edit_text(
            f"⛔️ نفت کافی ندارید. این استقرار {fa_number(oil_cost)} میلیون بشکه نفت نیاز دارد.",
            reply_markup=deploy_menu_kb(),
        )
        return

    # کسر نفت و ثبت استقرار (تجهیزات از موجودی کم نمی‌شوند)
    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -oil_cost)
    dep = Deployment(
        country_id=country.id,
        branch_key=branch_key,
        branch_fa=branch_fa,
        asset_name=asset_name,
        count=count,
        region=region,
        oil_cost=oil_cost,
    )
    await dep_repo.add_deployment(session, dep)

    await call.message.edit_text(
        f"✅ استقرار ثبت شد.\n"
        f"🪖 {fa_number(count)} {data.get('asset_unit','')} {asset_name} به منطقه‌ی «{region}» اعزام شد.\n"
        f"🛢 {fa_number(oil_cost)} میلیون بشکه نفت کسر شد.",
        reply_markup=deploy_menu_kb(),
    )

    # خبر فوری در کانال نظامی با عکس مخصوص (ground/navy/air)
    _fa, stem, _branches = DEPLOY_BRANCHES.get(branch_key, (branch_fa, "ground", frozenset()))
    news = (
        "🔴 فووووری!!\n\n"
        f"در خبری فوری مقامات کشور {country.flag} {country.name_fa} اعلام کرده اند چندین نیروی "
        f"{branch_fa} به منطقه {region} درحال حرکت هستند و نیروها اعلام آماده باش کرده اند!!\n\n"
        "🔰اطلاعات بیشتر راجب این موضوع به زودی اعلام خواهد شد!!"
    )
    if settings.news_military_channel_id is not None:
        await send_specific_photo(
            bot, settings.news_military_channel_id,
            cache_key=f"military_{stem}", category="military", stem=stem, caption=news,
        )

    # لاگ ممیزی به گروه لاگ
    await send_log(
        bot,
        "🪖 <b>استقرار نیرو</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"نوع: {branch_fa}\n"
        f"تجهیزات: {fa_number(count)} {data.get('asset_unit','')} {asset_name}\n"
        f"منطقه: {region}\n"
        f"هزینه: {fa_number(oil_cost)} میلیون بشکه نفت",
    )


# ============================================================
#  نیروهای مستقر: آپدیت مکان / حذف
# ============================================================
@router.callback_query(F.data == "dep:list")
async def cb_deploy_list(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    if not country.is_vip:
        await call.message.edit_text(_NOT_VIP_TEXT, reply_markup=military_menu_kb())
        return
    deployments = await dep_repo.list_active(session, country.id)
    if not deployments:
        await call.message.edit_text("📋 هنوز هیچ نیرویی مستقر نکرده‌اید.", reply_markup=_back_deploy_kb())
        return
    lines = [header("نیروهای مستقر", "📋"), ""]
    for d in deployments:
        lines.append(f"• {d.branch_fa} — {fa_number(d.count)} {d.asset_name} 📍 {d.region}")
    await call.message.edit_text("\n".join(lines), reply_markup=deployed_actions_kb())


async def _list_deployments_for(call: CallbackQuery, session: AsyncSession, db_user: User, action: str) -> None:
    """فهرست نیروهای مستقر با دکمه‌ی action (upd/rm) برای هر گروه."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.message.edit_text(NO_COUNTRY_TEXT)
        return
    deployments = await dep_repo.list_active(session, country.id)
    if not deployments:
        await call.message.edit_text("📋 هیچ نیروی مستقری ندارید.", reply_markup=_back_deploy_kb())
        return
    prefix = "dep_upd" if action == "upd" else "dep_rm"
    style = STYLE_MAIN if action == "upd" else STYLE_NO
    builder = InlineKeyboardBuilder()
    for d in deployments:
        builder.button(
            text=f"{d.branch_fa} — {d.asset_name} 📍 {d.region}",
            callback_data=f"{prefix}:{d.id}",
            style=style,
        )
    builder.button(text="🔙 بازگشت", callback_data="dep:list", style=STYLE_MAIN)
    builder.adjust(1)
    title = "📍 کدام گروه را جابه‌جا می‌کنید؟" if action == "upd" else "🗑 کدام گروه را حذف می‌کنید؟"
    await call.message.edit_text(title, reply_markup=builder.as_markup())


@router.callback_query(F.data == "dep:upd")
async def cb_deploy_upd_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await _list_deployments_for(call, session, db_user, "upd")


@router.callback_query(F.data == "dep:rm")
async def cb_deploy_rm_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    await _list_deployments_for(call, session, db_user, "rm")


@router.callback_query(F.data.startswith("dep_upd:"))
async def cb_deploy_upd_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    dep_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    dep = await dep_repo.get(session, dep_id)
    if country is None or dep is None or dep.country_id != country.id or not dep.active:
        await call.answer("این گروه دیگر معتبر نیست.", show_alert=True)
        return
    await state.set_state(DeploymentForm.updating_region)
    await state.update_data(upd_dep_id=dep_id)
    await call.message.edit_text(
        f"📍 منطقه‌ی جدید برای «{dep.asset_name}» ({dep.branch_fa}) را وارد کنید:",
        reply_markup=_back_deploy_kb(),
    )


@router.message(DeploymentForm.updating_region, F.text)
async def msg_deploy_update_region(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    region = message.text.strip()
    data = await state.get_data()
    await state.clear()
    dep_id = data.get("upd_dep_id")
    country = await get_player_country(session, db_user)
    dep = await dep_repo.get(session, dep_id) if dep_id else None
    if country is None or dep is None or dep.country_id != country.id or not dep.active:
        await message.answer("⛔️ این گروه دیگر معتبر نیست.", reply_markup=deploy_menu_kb())
        return
    old_region = dep.region
    dep.region = region
    await message.answer(
        f"✅ مکان نیروی «{dep.asset_name}» از «{old_region}» به «{region}» تغییر کرد.",
        reply_markup=deploy_menu_kb(),
    )
    await send_log(
        bot,
        "📍 <b>جابه‌جایی نیروی مستقر</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"تجهیزات: {fa_number(dep.count)} {dep.asset_name} ({dep.branch_fa})\n"
        f"از «{old_region}» به «{region}»",
    )


@router.callback_query(F.data.startswith("dep_rm:"))
async def cb_deploy_rm(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    dep_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    dep = await dep_repo.get(session, dep_id)
    if country is None or dep is None or dep.country_id != country.id or not dep.active:
        await call.answer("این گروه دیگر معتبر نیست.", show_alert=True)
        return
    label = f"{fa_number(dep.count)} {dep.asset_name} ({dep.branch_fa}) 📍 {dep.region}"
    await dep_repo.remove(session, dep_id)
    await call.message.edit_text(
        f"🗑 گروه نیروی «{label}» حذف شد.", reply_markup=deploy_menu_kb()
    )
    await send_log(
        bot,
        "🗑 <b>حذف گروه نیروی مستقر</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"گروه: {label}",
    )
