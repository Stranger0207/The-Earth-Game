"""
روتر هندلرهای مدیریت تنگه‌ها، مسدودسازی، اخطار عبور و پنل اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import STRAIT_TOLL_MAX
from ..database.models import Country, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import straits as straits_repo
from ..database.repositories import trade as trade_repo
from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType, StraitBlockScope
from ..keyboards.straits import (
    blocked_cargo_actions_kb,
    blocked_cargo_confirm_kb,
    blocked_cargos_kb,
    strait_confiscate_choice_kb,
    strait_country_rule_kb,
    strait_custom_countries_kb,
    strait_detail_kb,
    strait_intercept_alert_kb,
    strait_intercept_attack_kb,
    strait_standoff_ctrl_kb,
    strait_standoff_owner_kb,
    straits_menu_kb,
)
from ..loader import bot
from ..services import geo_service as geo
from ..services import strait_service
from ..services.news_service import publish_news, send_log
from ..config import get_settings
from ..states.forms import StraitForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
settings = get_settings()

router = Router(name="straits")


# ============================================================
#  منوی اصلی مدیریت تنگه‌ها
# ============================================================

@router.callback_query(F.data == "menu:straits")
async def cb_menu_straits(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ورود به منوی مدیریت تنگه‌ها."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if not country:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "straits_management"):
        return

    # بررسی اینکه آیا این کشور هیچ تنگه‌ای را کنترل می‌کند یا خیر
    straits = await straits_repo.list_straits_by_controller(session, country.name_en)
    if not straits:
        await safe_edit(
            call,
            "🌊 <b>مدیریت آبراه‌ها و تنگه‌ها</b>\n\n"
            f"کشور {country.flag} {country.name_fa} کنترل‌کننده هیچ‌یک از تنگه‌ها یا آبراه‌های استراتژیک جهان نیست.\n\n"
            "<i>(فقط کشورهایی که بر تنگه‌ها حاکمیت دارند می‌توانند عوارض عبور وضع کرده یا آبراه را مسدود نمایند.)</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔒 اموال بلوکه‌شده", callback_data="strait:blocked_cargos", style=STYLE_MAIN),
                InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN),
            ]]),
        )
        return

    text = (
        f"🌊 <b>مرکز مدیریت تنگه‌ها و آبراه‌های استراتژیک</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n\n"
        "در این بخش می‌توانید وضعیت تردد کشتی‌ها، عوارض عبور و مسدودسازی تنگه‌های تحت کنترل کشورتان را مدیریت کنید:\n"
    )
    await show_menu(call, text, reply_markup=straits_menu_kb(straits), image_key="straits")


# ============================================================
#  مشاهده جزئیات و مدیریت یک تنگه خاص
# ============================================================

@router.callback_query(F.data.startswith("strait_detail:"))
async def cb_strait_detail(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده جزئیات، عوارض و وضعیت مسدودسازی تنگه."""
    await call.answer()
    strait_id = call.data.split(":")[1]
    country = await get_player_country(session, db_user)
    if not country:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not cfg or cfg.controller_country_name != country.name_en:
        await safe_edit(call, "شما کنترل‌کننده این تنگه نیستید.")
        return

    s_def = geo.get_strait_def(strait_id)
    desc = s_def.get("description", "") if s_def else ""

    if cfg.is_blocked:
        if cfg.block_scope == StraitBlockScope.ALL.value:
            status_text = "🔴 <b>مسدود کامل به روی تمام کشورها</b>"
        else:
            status_text = "🟡 <b>مسدود گزینشی (برای برخی کشورها)</b>"
    else:
        status_text = "🟢 <b>کاملاً باز برای عبور و مرور بین‌المللی</b>"

    text = (
        f"🌊 <b>مدیریت {cfg.name_fa} ({cfg.name_en})</b>\n\n"
        f"📝 <b>موقعیت:</b> {desc}\n"
        f"🚦 <b>وضعیت کنونی:</b> {status_text}\n"
        f"💵 <b>عوارض عبور عمومی:</b> {fa_money(cfg.default_toll)}\n\n"
        "<i>از گزینه‌های زیر برای تنظیم عوارض یا کنترل تردد کشتی‌ها استفاده کنید:</i>"
    )
    await safe_edit(call, text, reply_markup=strait_detail_kb(cfg))


# ============================================================
#  بستن / باز کردن سراسری تنگه
# ============================================================

@router.callback_query(F.data.startswith("strait_block_all:"))
async def cb_strait_block_all(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """درخواست بستن کامل تنگه به روی تمام کشتی‌ها (نیازمند تأیید ادمین در گروه رول نظامی)."""
    strait_id = call.data.split(":")[1]
    country = await get_player_country(session, db_user)
    if not country:
        await call.answer()
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not cfg or cfg.controller_country_name != country.name_en:
        await call.answer("دسترسی غیرمجاز است.", show_alert=True)
        return

    if cfg.is_blocked and cfg.block_scope == StraitBlockScope.ALL.value:
        await call.answer("این آبراه هم‌اکنون به طور کامل مسدود است.", show_alert=True)
        return

    await strait_service.submit_strait_block_request(
        bot, session, strait_id, country, db_user, target_country=None
    )

    await call.answer(
        "⏳ درخواست مسدودسازی کامل تنگه به گروه رول نظامی ارسال شد و پس از بررسی و تأیید ادمین اعمال خواهد شد.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("strait_unblock:"))
async def cb_strait_unblock(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """باز کردن کامل تنگه و لغو مسدودسازی."""
    await call.answer()
    strait_id = call.data.split(":")[1]
    country = await get_player_country(session, db_user)
    if not country:
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not cfg or cfg.controller_country_name != country.name_en:
        await call.answer("دسترسی غیرمجاز است.", show_alert=True)
        return

    await straits_repo.update_strait_config(
        session, strait_id, is_blocked=False, block_scope=StraitBlockScope.NONE.value
    )

    # واکنش تخلیه حباب انرژی به بازگشایی تنگه (آپدیت شماره ۴)
    try:
        from ..services import market_service
        await market_service.on_strait_status_changed(session, strait_id, is_closed=False)
    except Exception:
        pass

    news_text = (
        f"🟢 <b>آزادسازی و بازگشایی آبراه {cfg.name_fa}</b>\n\n"
        f"دولت {country.flag} {country.name_fa} اعلام کرد که انسداد تنگه <b>{cfg.name_fa}</b> "
        "لغو شده و تردد کشتی‌ها در این آبراه بین‌المللی به حالت عادی بازگشت."
    )
    await publish_news(bot, "diplomacy", news_text)
    await send_log(
        bot,
        f"🟢 <b>بازگشایی تنگه</b>\nتنگه: {cfg.name_fa}\nکشور: {country.flag} {country.name_fa}",
    )

    await call.answer("تنگه با موفقیت باز شد 🟢", show_alert=True)
    await cb_strait_detail(call, session, db_user)


# ============================================================
#  تنظیم عوارض عبور عمومی
# ============================================================

@router.callback_query(F.data.startswith("strait_toll:"))
async def cb_strait_toll_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع فرم تعیین عوارض عبور عمومی تنگه."""
    await call.answer()
    strait_id = call.data.split(":")[1]
    country = await get_player_country(session, db_user)
    if not country:
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not cfg or cfg.controller_country_name != country.name_en:
        return

    await state.set_state(StraitForm.entering_default_toll)
    await state.update_data(strait_id=strait_id)

    await safe_edit(
        call,
        f"💵 <b>تنظیم عوارض عبور عمومی از {cfg.name_fa}</b>\n\n"
        f"عوارض فعلی: {fa_money(cfg.default_toll)}\n"
        f"سقف مجاز: {fa_money(STRAIT_TOLL_MAX)}\n\n"
        "مبلغ عوارض جدید را به دلار وارد کنید (مثلاً 2m برای ۲ میلیون دلار، یا 0 برای رایگان):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 انصراف", callback_data=f"strait_detail:{strait_id}", style=STYLE_MAIN)
        ]]),
    )


@router.message(StraitForm.entering_default_toll, F.text)
async def msg_strait_default_toll(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """دریافت و ذخیره مبلغ عوارض جدید."""
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("لطفاً یک مبلغ معتبر (۰ یا بیشتر) وارد کنید.")
        return

    if amount > STRAIT_TOLL_MAX:
        await message.answer(
            f"حداکثر سقف مجاز عوارض هر تنگه {fa_money(STRAIT_TOLL_MAX)} است. لطفاً مبلغ کمتری وارد کنید."
        )
        return

    data = await state.get_data()
    strait_id = data["strait_id"]
    country = await get_player_country(session, db_user)
    if not country:
        await state.clear()
        return

    cfg = await straits_repo.update_strait_config(session, strait_id, default_toll=amount)
    await state.clear()

    await message.answer(
        f"✅ عوارض عبور عمومی از <b>{cfg.name_fa if cfg else strait_id}</b> با موفقیت بر روی <b>{fa_money(amount)}</b> تنظیم شد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت به تنگه", callback_data=f"strait_detail:{strait_id}", style=STYLE_MAIN)
        ]]),
    )
    await send_log(
        bot,
        f"💵 <b>تغییر عوارض تنگه</b>\nتنگه: {cfg.name_fa if cfg else strait_id}\nعوارض جدید: {fa_money(amount)}\nکشور: {country.flag} {country.name_fa}",
    )


# ============================================================
#  قوانین اختصاصی و مسدودسازی کشورها
# ============================================================

@router.callback_query(F.data.startswith("strait_custom:"))
async def cb_strait_custom_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """فهرست کشورها برای اعمال قوانین خاص."""
    await call.answer()
    parts = call.data.split(":")
    strait_id = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    country = await get_player_country(session, db_user)
    if not country:
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not cfg or cfg.controller_country_name != country.name_en:
        return

    all_countries = await countries_repo.list_countries(session)
    others = [c for c in all_countries if c.id != country.id]

    rules = await straits_repo.list_block_rules(session, strait_id)
    rules_map = {r.target_country_id: r for r in rules}

    text = (
        f"🎯 <b>قوانین و عوارض اختصاصی برای {cfg.name_fa}</b>\n\n"
        "می‌توانید برای هر کشور وضعیت عبور (مجاز/مسدود) یا عوارض متفاوتی تعیین کنید:\n"
        "روی هر کشور کلیک کنید تا تنظیمات آن باز شود."
    )
    await safe_edit(call, text, reply_markup=strait_custom_countries_kb(strait_id, others, rules_map, page))


@router.callback_query(F.data.startswith("strait_crule:"))
async def cb_strait_country_rule(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده و ویرایش تنظیمات یک کشور خاص روی تنگه."""
    await call.answer()
    parts = call.data.split(":")
    strait_id = parts[1]
    target_cid = int(parts[2])

    country = await get_player_country(session, db_user)
    target_c = await countries_repo.get_country(session, target_cid)
    if not country or not target_c:
        return

    cfg = await straits_repo.get_strait_config(session, strait_id)
    rule = await straits_repo.get_block_rule(session, strait_id, target_cid)

    status_tag = "🔴 مسدود" if (rule and rule.is_blocked) else "🟢 مجاز"
    toll_tag = fa_money(rule.custom_toll) if (rule and rule.custom_toll is not None) else f"پیش‌فرض ({fa_money(cfg.default_toll)})"

    text = (
        f"⚙️ <b>تنظیمات عبور {target_c.flag} {target_c.name_fa} از {cfg.name_fa}</b>\n\n"
        f"• وضعیت تردد: {status_tag}\n"
        f"• عوارض عبور: {toll_tag}\n\n"
        "دستور خود را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=strait_country_rule_kb(strait_id, target_c, rule))


@router.callback_query(F.data.startswith("strait_toggle_block:"))
async def cb_strait_toggle_block(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تاگل کردن مسدودسازی یک کشور خاص (بستن نیازمند تأیید ادمین در گروه رول نظامی)."""
    parts = call.data.split(":")
    strait_id = parts[1]
    target_cid = int(parts[2])
    blocked = bool(int(parts[3]))

    country = await get_player_country(session, db_user)
    target_c = await countries_repo.get_country(session, target_cid)
    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not country or not target_c or not cfg:
        await call.answer()
        return

    if cfg.controller_country_name != country.name_en:
        await call.answer("دسترسی غیرمجاز است.", show_alert=True)
        return

    # در صورت رفع مسدودیت (unblock): بلافاصله انجام می‌شود
    if not blocked:
        await straits_repo.set_block_rule(session, strait_id, target_cid, is_blocked=False)
        await call.answer(f"تردد {target_c.name_fa} مجاز شد 🟢", show_alert=True)
        await send_log(
            bot,
            f"🟢 <b>رفع مسدودسازی کشور در تنگه</b>\n"
            f"تنگه: {cfg.name_fa}\n"
            f"کشور هدف: {target_c.flag} {target_c.name_fa}\n"
            f"توسط: {country.flag} {country.name_fa}",
        )
        call.data = f"strait_crule:{strait_id}:{target_cid}"
        await cb_strait_country_rule(call, session, db_user)
        return

    # در صورت مسدود کردن: ارسال به گروه رول نظامی جهت تأیید ادمین
    await strait_service.submit_strait_block_request(
        bot, session, strait_id, country, db_user, target_country=target_c
    )
    await call.answer(
        f"⏳ درخواست مسدودسازی تردد {target_c.name_fa} به گروه رول نظامی ارسال شد و پس از بررسی و تأیید ادمین اعمال خواهد شد.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("adm_strait_blk:"))
async def cb_admin_strait_block_decision(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """رسیدگی ادمین به درخواست مسدودسازی تنگه در گروه رول نظامی."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔ دسترسی غیرمجاز! فقط مدیران بازی می‌توانند این عملیات را تأیید یا رد کنند.", show_alert=True)
        return

    parts = call.data.split(":")
    # adm_strait_blk:action:strait_id:target_spec:requester_id
    action = parts[1]        # approve / reject
    strait_id = parts[2]
    target_spec = parts[3]  # "all" or country_id (int)
    requester_id = int(parts[4])

    target_cid = None if target_spec == "all" else int(target_spec)
    admin_mention = f"@{call.from_user.username}" if call.from_user.username else (call.from_user.first_name or str(call.from_user.id))

    if action == "reject":
        await strait_service.reject_strait_block_request(
            bot, session, strait_id, target_cid, db_user, requester_id
        )
        await call.answer("درخواست مسدودسازی رد شد.", show_alert=True)
        if call.message:
            try:
                await call.message.edit_text(
                    call.message.html_text + f"\n\n❌ <b>رد شد</b> توسط ادمین {admin_mention}",
                    reply_markup=None,
                )
            except Exception:
                pass
        return

    # approve
    await strait_service.approve_strait_block_request(
        bot, session, strait_id, target_cid, db_user, requester_id
    )
    await call.answer("مسدودسازی تنگه با موفقیت تأیید و اعمال شد 🔴", show_alert=True)
    if call.message:
        try:
            await call.message.edit_text(
                call.message.html_text + f"\n\n✅ <b>تأیید و مسدود شد</b> توسط ادمین {admin_mention}",
                reply_markup=None,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("strait_set_ctoll:"))
async def cb_strait_set_ctoll_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع فرم تعیین عوارض اختصاصی برای یک کشور."""
    await call.answer()
    parts = call.data.split(":")
    strait_id = parts[1]
    target_cid = int(parts[2])

    target_c = await countries_repo.get_country(session, target_cid)
    cfg = await straits_repo.get_strait_config(session, strait_id)
    if not target_c or not cfg:
        return

    await state.set_state(StraitForm.entering_custom_toll)
    await state.update_data(strait_id=strait_id, target_cid=target_cid)

    await safe_edit(
        call,
        f"💵 <b>تنظیم عوارض اختصاصی برای {target_c.flag} {target_c.name_fa} در {cfg.name_fa}</b>\n\n"
        f"سقف مجاز: {fa_money(STRAIT_TOLL_MAX)}\n\n"
        "مبلغ عوارض دلاری را وارد کنید (مثلاً 0 برای رایگان، یا 500k):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 انصراف", callback_data=f"strait_crule:{strait_id}:{target_cid}", style=STYLE_MAIN)
        ]]),
    )


@router.message(StraitForm.entering_custom_toll, F.text)
async def msg_strait_custom_toll(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ذخیره عوارض اختصاصی کشور."""
    amount = parse_amount(message.text)
    if amount is None or amount < 0 or amount > STRAIT_TOLL_MAX:
        await message.answer(f"لطفاً مبلغ معتبری بین ۰ تا {fa_money(STRAIT_TOLL_MAX)} وارد کنید.")
        return

    data = await state.get_data()
    strait_id = data["strait_id"]
    target_cid = data["target_cid"]
    await state.clear()

    rule = await straits_repo.get_block_rule(session, strait_id, target_cid)
    blocked = rule.is_blocked if rule else False
    await straits_repo.set_block_rule(session, strait_id, target_cid, is_blocked=blocked, custom_toll=amount)

    target_c = await countries_repo.get_country(session, target_cid)
    s_def = geo.get_strait_def(strait_id)
    strait_name = s_def["name_fa"] if s_def else strait_id

    await message.answer(
        f"✅ عوارض عبور <b>{target_c.flag} {target_c.name_fa if target_c else '?'}</b> از <b>{strait_name}</b> بر روی <b>{fa_money(amount)}</b> تنظیم شد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت به تنظیمات کشور", callback_data=f"strait_crule:{strait_id}:{target_cid}", style=STYLE_MAIN)
        ]]),
    )


@router.callback_query(F.data.startswith("strait_reset_rule:"))
async def cb_strait_reset_rule(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ریست کردن قانون اختصاصی یک کشور به پیش‌فرض."""
    await call.answer()
    parts = call.data.split(":")
    strait_id = parts[1]
    target_cid = int(parts[2])

    await straits_repo.remove_block_rule(session, strait_id, target_cid)
    await call.answer("قانون اختصاصی این کشور حذف شد و به حالت پیش‌فرض بازگشت ✅", show_alert=True)

    call.data = f"strait_crule:{strait_id}:{target_cid}"
    await cb_strait_country_rule(call, session, db_user)


# ============================================================
#  رسیدگی به اخطارهای توقیف شناور در تنگه (ارسالی به پیوی کنترل‌کننده)
# ============================================================

@router.callback_query(F.data.startswith("strait_act:allow:"))
async def cb_strait_act_allow(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """صدور اجازه عبور از تنگه توسط کشور کنترل‌کننده."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.allow_passage(bot, session, sale_id, strait_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await call.answer("اجازه عبور صادر شد ✅")
    await safe_edit(
        call,
        call.message.html_text + f"\n\n✅ <b>دستور شما:</b> صدور اجازه عبور از {res['strait_name_fa']}.",
    )


@router.callback_query(F.data.startswith("strait_act:warn:"))
async def cb_strait_act_warn(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """صدور اخطار رسمی به کشتی تجاری در تنگه (۱ تا ۳ اخطار)."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.issue_strait_warning(bot, session, sale_id, strait_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    w_count = res["warning_count"]
    await call.answer(f"اخطار شماره {fa_number(w_count)} با موفقیت به کشتی ابلاغ شد ⚠️", show_alert=False)

    await safe_edit(
        call,
        call.message.html_text + f"\n\n⚠️ <b>اخطار {fa_number(w_count)} صادر شد:</b> به کاپیتان کشتی هشدار داده شد.",
        reply_markup=strait_standoff_ctrl_kb(sale_id, strait_id, warning_count=w_count, is_running=False),
    )


@router.callback_query(F.data.startswith("strait_act:warn_max:"))
async def cb_strait_act_warn_max(call: CallbackQuery) -> None:
    """اخطار به کنترل‌کننده که سقف ۳ اخطار پر شده است."""
    await call.answer(
        "حداکثر ۳ اخطار رسمی به این شناور ابلاغ شده است. اکنون گزینه‌های شلیک به کشتی یا مصادره بار فعال گردیده‌اند.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("strait_act:fire_locked:"))
async def cb_strait_act_fire_locked(call: CallbackQuery) -> None:
    """اطلاع‌رسانی لزوم صدور ۳ اخطار پیش از شلیک."""
    await call.answer(
        "طبق قوانین بین‌المللی دریانوردی، فرمان شلیک به شناور تجاری تنها پس از صدور ۳ اخطار رسمی مجاز است!",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("strait_act:conf_locked:"))
async def cb_strait_act_conf_locked(call: CallbackQuery) -> None:
    """اطلاع‌رسانی لزوم صدور ۳ اخطار پیش از مصادره بار."""
    await call.answer(
        "طبق قوانین بین‌المللی دریانوردی، توقیف و مصادره بار تنها پس از صدور ۳ اخطار رسمی مجاز است!",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("strait_act:fire:"))
async def cb_strait_act_fire(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """دستور شلیک موشکی و انهدام کشتی متخلف در تنگه."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.fire_at_shipment(bot, session, sale_id, strait_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        try:
            await safe_edit(call, call.message.html_text + f"\n\n⚠️ {exc}", reply_markup=None)
        except Exception:
            pass
        return

    await call.answer("فرمان آتش صادر شد! شناور هدف قرار گرفت و غرق شد 💥", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n💥 <b>فرمان آتش:</b> شناور متخلف با موشک‌های ساحلی در {res['strait_name_fa']} منهدم و به قعر دریا فرستاده شد.",
    )


# ============================================================
#  تصمیمات مالک محموله در مواجهه با تنگه مسدود
# ============================================================

@router.callback_query(F.data.startswith("strait_owner:hold:"))
async def cb_strait_owner_hold(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """دستور لنگراندازی و توقف کشتی در دهانه تنگه توسط مالک بار."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.owner_hold_at_strait(bot, session, sale_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        try:
            await safe_edit(call, call.message.html_text + f"\n\n⚠️ {exc}", reply_markup=None)
        except Exception:
            pass
        return

    await call.answer("دستور توقف و لنگراندازی در مدخل تنگه صادر شد ⚓", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n⚓ <b>دستور شما:</b> توقف و لنگراندازی در دهانه {res['strait_name_fa']} تا تعیین تکلیف دیپلماتیک.",
        reply_markup=strait_standoff_owner_kb(sale_id, strait_id, current_action="HOLD"),
    )


@router.callback_query(F.data.startswith("strait_owner:retreat:"))
async def cb_strait_owner_retreat(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """دستور عقب‌نشینی و بازگرداندن محموله به کشور مبدأ توسط مالک بار."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.owner_retreat_from_strait(bot, session, sale_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        try:
            await safe_edit(call, call.message.html_text + f"\n\n⚠️ {exc}", reply_markup=None)
        except Exception:
            pass
        return

    await call.answer("کشتی دور زد و در حال بازگشت به مبدأ است 🔄", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n🔄 <b>دستور شما:</b> عقب‌نشینی از {res['strait_name_fa']} و بازگشت ایمن به کشور مبدأ.",
    )


@router.callback_query(F.data.startswith("strait_owner:run:"))
async def cb_strait_owner_run(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """دستور تلاش برای عبور با پذیرش ریسک شلیک توسط مالک بار."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    try:
        res = await strait_service.owner_run_blockade(bot, session, sale_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        try:
            await safe_edit(call, call.message.html_text + f"\n\n⚠️ {exc}", reply_markup=None)
        except Exception:
            pass
        return

    await call.answer("کشتی با تمام قوا به سمت تنگه پیشروی می‌کند 🚢⚠️", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n🚢 <b>دستور شما:</b> ورود به {res['strait_name_fa']} و شکستن محاصره با پذیرش خطر آتش ساحلی.",
    )


@router.callback_query(F.data.startswith("strait_owner:info_hold:"))
async def cb_strait_owner_info_hold(call: CallbackQuery) -> None:
    """توضیح وضعیت لنگراندازی."""
    await call.answer("شناور شما هم‌اکنون در آب‌های بین‌المللی دهانه تنگه لنگر انداخته است.", show_alert=True)


@router.callback_query(F.data.startswith("strait_act:attack_menu:"))
async def cb_strait_act_attack_menu(call: CallbackQuery) -> None:
    """نمایش گزینه‌های حمله به کشتی."""
    await call.answer()
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]
    await safe_edit(
        call,
        call.message.html_text + "\n\n⚔️ <b>عملیات حمله به شناور:</b>\nنوع اقدام را مشخص کنید:",
        reply_markup=strait_intercept_attack_kb(sale_id, strait_id),
    )


@router.callback_query(F.data.startswith("strait_act:back_alert:"))
async def cb_strait_act_back_alert(call: CallbackQuery) -> None:
    """بازگشت به دکمه‌های اولیه اخطار مرزبانی."""
    await call.answer()
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]
    await safe_edit(call, call.message.html_text, reply_markup=strait_intercept_alert_kb(sale_id, strait_id))


@router.callback_query(F.data.startswith("strait_act:destroy:"))
async def cb_strait_act_destroy(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """حمله و تخریب کامل کشتی در تنگه."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        return

    try:
        res = await strait_service.destroy_shipment(bot, session, sale_id, strait_id, country)
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await call.answer("کشتی و محموله با موفقیت منهدم شدند 💥", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n💥 <b>دستور شما:</b> حمله و غرق کردن کشتی در {res['strait_name_fa']}.",
    )


@router.callback_query(F.data.startswith("strait_act:confiscate_menu:"))
async def cb_strait_act_confiscate_menu(call: CallbackQuery) -> None:
    """نمایش انتخاب افزودن به ذخایر یا انتقال به اموال بلوکه‌شده."""
    await call.answer()
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    await safe_edit(
        call,
        call.message.html_text + "\n\n⚓ <b>مصادره بار:</b>\nبار کشتی ضبط شد. تمایل دارید با بار ضبط‌شده چه کنید؟",
        reply_markup=strait_confiscate_choice_kb(sale_id, strait_id),
    )


@router.callback_query(F.data.startswith("strait_act:conf_reserves:"))
async def cb_strait_conf_reserves(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مصادره و واریز فوری به ذخایر خودی."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        return

    try:
        res = await strait_service.confiscate_shipment(
            bot, session, sale_id, strait_id, country, to_blocked_assets=False
        )
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await call.answer("بار مصادره و به ذخایر کشورتان افزوده شد ✅", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n⚓ <b>دستور شما:</b> مصادره بار در {res['strait_name_fa']} و افزودن مستقیم به ذخایر خودی.",
    )


@router.callback_query(F.data.startswith("strait_act:conf_blocked:"))
async def cb_strait_conf_blocked(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مصادره و انتقال به پنل اموال بلوکه‌شده."""
    parts = call.data.split(":")
    sale_id = int(parts[2])
    strait_id = parts[3]

    country = await get_player_country(session, db_user)
    if not country:
        return

    try:
        res = await strait_service.confiscate_shipment(
            bot, session, sale_id, strait_id, country, to_blocked_assets=True
        )
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    await call.answer("بار مصادره و به اموال بلوکه‌شده منتقل شد 🔒", show_alert=True)
    await safe_edit(
        call,
        call.message.html_text + f"\n\n🔒 <b>دستور شما:</b> مصادره بار در {res['strait_name_fa']} و انتقال به اموال بلوکه‌شده.",
    )


# ============================================================
#  پنل اموال بلوکه‌شده (Blocked Assets Panel)
# ============================================================

@router.callback_query(F.data.startswith("strait:blocked_cargos") | F.data.startswith("strait:blocked_pg:"))
async def cb_blocked_cargos_list(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش فهرست محموله‌های بلوکه‌شده در دست کشور."""
    await call.answer()
    parts = call.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    country = await get_player_country(session, db_user)
    if not country:
        return

    cargos = await straits_repo.list_blocked_cargos_by_holding(session, country.id)
    if not cargos:
        await safe_edit(
            call,
            "🔒 <b>پنل اموال بلوکه‌شده</b>\n\n"
            "در حال حاضر هیچ محموله یا باری در توقیف یا بلوکه کشورتان قرار ندارد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔙 بازگشت به مدیریت تنگه‌ها", callback_data="menu:straits", style=STYLE_MAIN)
            ]]),
        )
        return

    all_c = await countries_repo.list_countries(session)
    cmap = {c.id: c for c in all_c}

    text = (
        f"🔒 <b>پنل اموال و محموله‌های بلوکه‌شده</b>\n"
        f"کشور ناظر: {country.flag} {country.name_fa}\n"
        f"تعداد کل اقلام توقیفی: {fa_number(len(cargos))}\n\n"
        "برای مشاهده جزئیات و تصمیم‌گیری درباره سرنوشت بار، روی هر محموله کلیک کنید:"
    )
    await safe_edit(call, text, reply_markup=blocked_cargos_kb(cargos, cmap, page))


@router.callback_query(F.data.startswith("blk_view:"))
async def cb_blocked_cargo_view(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده مشخصات کامل یک بار بلوکه‌شده و اقدامات سه‌گانه."""
    await call.answer()
    cargo_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    cargo = await straits_repo.get_blocked_cargo(session, cargo_id)
    if not cargo or cargo.holding_country_id != country.id:
        await safe_edit(call, "این محموله بلوکه‌شده یافت نشد.")
        return

    src = await countries_repo.get_country(session, cargo.source_country_id)
    dest = await countries_repo.get_country(session, cargo.dest_country_id)
    s_def = geo.get_strait_def(cargo.strait_id)
    strait_name = s_def["name_fa"] if s_def else cargo.strait_id

    try:
        rname = RESOURCE_FA[ResourceType(cargo.resource)]
        unit = RESOURCE_UNIT_FA[ResourceType(cargo.resource)]
    except (ValueError, KeyError):
        rname = cargo.resource
        unit = ""

    src_title = f"{src.flag} {src.name_fa}" if src else "?"
    dest_title = f"{dest.flag} {dest.name_fa}" if dest else "?"
    date_str = cargo.captured_at.strftime("%Y-%m-%d %H:%M UTC")

    text = (
        f"📦 <b>جزئیات محموله بلوکه‌شده #{cargo.id}</b>\n\n"
        f"• نوع بار: <b>{fa_number(cargo.amount)} {unit} {rname}</b>\n"
        f"• فرستنده اصلی (صاحب بار): {src_title}\n"
        f"• مقصد تجاری اولیه: {dest_title}\n"
        f"• محل توقیف: تنگه {strait_name}\n"
        f"• تاریخ توقیف: {date_str}\n\n"
        "دستور شما برای این محموله چیست؟"
    )
    await safe_edit(call, text, reply_markup=blocked_cargo_actions_kb(cargo.id))


@router.callback_query(F.data.startswith("blk_act:"))
async def cb_blocked_cargo_action_ask(call: CallbackQuery) -> None:
    """درخواست تأیید دومرحله‌ای برای هر یک از اقدامات سه‌گانه."""
    await call.answer()
    parts = call.data.split(":")
    action = parts[1]
    cargo_id = int(parts[2])

    action_prompts = {
        "destroy": "⚠️ <b>آیا مطمئنید می‌خواهید این محموله را کاملاً تخریب و نابود کنید؟</b>\n(این عمل غیرقابل بازگشت است و بار از بین می‌رود)",
        "claim": "📥 <b>آیا می‌خواهید این بار را ترخیص کرده و به ذخایر کشور خودتان اضافه کنید؟</b>",
        "return": "🚢 <b>آیا می‌خواهید این محموله را به کشور فرستنده اصلی بازگردانید؟</b>\n(بار به ذخایر فروشنده اصلی بازخواهد گشت)",
    }
    prompt = action_prompts.get(action, "آیا مطمئن هستید؟")
    await safe_edit(call, prompt, reply_markup=blocked_cargo_confirm_kb(action, cargo_id))


@router.callback_query(F.data.startswith("blk_cfm:"))
async def cb_blocked_cargo_action_confirm(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """اجرای نهایی اقدام تأییدشده روی محموله بلوکه‌شده."""
    await call.answer()
    parts = call.data.split(":")
    action = parts[1]
    cargo_id = int(parts[2])

    country = await get_player_country(session, db_user)
    if not country:
        return

    try:
        if action == "destroy":
            res = await strait_service.destroy_blocked_cargo(bot, session, cargo_id, country)
            await safe_edit(
                call,
                f"🗑 محموله <b>{fa_number(res['amount'])} {res['unit']} {res['resource_fa']}</b> با موفقیت تخریب و نابود شد.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔒 بازگشت به لیست اموال", callback_data="strait:blocked_cargos", style=STYLE_MAIN)
                ]]),
            )
        elif action == "claim":
            res = await strait_service.claim_blocked_cargo_to_reserves(bot, session, cargo_id, country)
            await safe_edit(
                call,
                f"📥 محموله <b>{fa_number(res['amount'])} {res['unit']} {res['resource_fa']}</b> به موجودی ذخایر کشورتان اضافه شد ✅",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔒 بازگشت به لیست اموال", callback_data="strait:blocked_cargos", style=STYLE_MAIN)
                ]]),
            )
        elif action == "return":
            res = await strait_service.return_blocked_cargo_to_source(bot, session, cargo_id, country)
            await safe_edit(
                call,
                f"🚢 محموله <b>{fa_number(res['amount'])} {res['unit']} {res['resource_fa']}</b> با موفقیت به کشور ارسال‌کننده بازگردانده شد.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔒 بازگشت به لیست اموال", callback_data="strait:blocked_cargos", style=STYLE_MAIN)
                ]]),
            )
    except strait_service.StraitError as exc:
        await call.answer(str(exc), show_alert=True)
