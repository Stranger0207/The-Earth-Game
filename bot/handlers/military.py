"""هندلر بخش نظامی: گزارش تجهیزات و ۴ نوع حمله."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Attack, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import ATTACK_FA, AttackStatus, AttackType, ResourceType
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.military import attack_types_kb, military_menu_kb
from ..loader import bot
from ..services.ai import evaluators
from ..services.military_service import apply_losses, format_casualties_log
from ..services.news_service import send_log
from ..states import AttackForm
from ..utils.formatting import render_military_panel
from ..utils.numbers import fa_number
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="military")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        "مثال: «حمله با ۲۰ جنگنده F-16 به پایگاه هوایی دشمن»"
    )


@router.message(AttackForm.describing, F.text)
async def msg_attack_describe(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شرح حمله؛ خرابکاری به مالک ارسال می‌شود، بقیه توسط AI سنجیده می‌شوند."""
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["target_id"])
    if country is None or target is None:
        await message.answer("خطا در ثبت حمله.")
        await state.clear()
        return

    atype = AttackType(data["attack_type"])

    # --- حمله خرابکاری (v1.5): بدون محدودیت، درخواست به مالک برای تأیید ---
    if atype == AttackType.SABOTAGE:
        attack = Attack(
            attacker_country=country.id,
            defender_country=target.id,
            type=atype.value,
            payload=message.text,
            fuel_cost=0.0,
            status=AttackStatus.PENDING,  # در انتظار تأیید مالک
        )
        session.add(attack)
        await session.flush()
        await state.clear()

        await message.answer(
            "🕵️ درخواست حمله‌ی خرابکارانه‌ی شما برای بررسی به مدیریت بازی ارسال شد.\n"
            "پس از تأیید، نتیجه به شما اعلام خواهد شد.",
            reply_markup=military_menu_kb(),
        )
        # ارسال درخواست به گروه لاگ با دکمه‌ی تأیید/رد
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تأیید", callback_data=f"sabotage_ok:{attack.id}"),
            InlineKeyboardButton(text="❌ رد", callback_data=f"sabotage_no:{attack.id}"),
        ]])
        await send_log(
            bot,
            f"🕵️ <b>درخواست حمله‌ی خرابکارانه</b>\n\n"
            f"🔴 مهاجم: {country.flag} {country.name_fa}\n"
            f"🔵 هدف: {target.flag} {target.name_fa}\n\n"
            f"📝 شرح بازیکن:\n{message.text}",
            reply_markup=kb,
        )
        return

    # --- حملات هوایی/زمینی/دریایی: سنجش توسط AI ---
    await message.answer("⏳ در حال سنجش حمله توسط فرماندهی...")
    result = await evaluators.evaluate_attack(
        session, country.id, target.id, ATTACK_FA[atype], message.text
    )

    # بررسی امکان‌پذیری/منطقی‌بودن حمله توسط AI (مثلاً حمله هوایی سوریه به آمریکا)
    if result.get("feasible") is False:
        reason = result.get("reject_reason") or "این حمله از نظر نظامی غیرقابل‌انجام است."
        await state.clear()
        await message.answer(
            f"⛔️ <b>حمله انجام نخواهد شد</b>\n\n"
            f"دلیل: {reason}",
            reply_markup=military_menu_kb(),
        )
        return

    fuel = float(result.get("fuel_cost_million_barrels", 0) or 0)
    await state.update_data(
        payload=message.text,
        eval_result=json.dumps(result, ensure_ascii=False),
        fuel=fuel,
    )
    await state.set_state(AttackForm.confirming_fuel)
    await message.answer(
        f"⛽ سوخت لازم برای این حمله: <b>{fa_number(fuel, 2)} میلیون بشکه نفت</b>\n\n"
        "آیا حمله تأیید می‌شود؟",
        reply_markup=confirm_cancel_kb("atk_confirm"),
    )


@router.callback_query(AttackForm.confirming_fuel, F.data == "atk_confirm")
async def cb_attack_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """تأیید حمله: کسر سوخت، اعمال تلفات و زمان‌بندی اعلام نتیجه."""
    await call.answer()
    data = await state.get_data()
    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, data["target_id"])
    await state.clear()
    if country is None or target is None:
        await call.message.edit_text("خطا.")
        return

    result = json.loads(data.get("eval_result", "{}"))
    fuel = float(data.get("fuel", 0) or 0)
    atype = AttackType(data["attack_type"])

    # بررسی و کسر سوخت (نفت)
    if not await reserves_repo.has_enough(session, country.id, ResourceType.OIL, fuel):
        await call.message.edit_text(
            "⛔️ سوخت (نفت) کافی برای این حمله ندارید.", reply_markup=military_menu_kb()
        )
        return
    await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -fuel)

    # اعمال تلفات روی تجهیزات دو طرف
    await apply_losses(session, country.id, target.id, result)

    # ساخت رکورد حمله با زمان اعلام نتیجه؛ گزارش دقیق برای لاگ مدیران ذخیره می‌شود
    delay = int(result.get("delay_minutes", 15) or 15)
    delay = max(5, min(delay, 180))
    player_report = result.get("player_report", "نتیجه‌ی حمله ثبت شد.")
    log_report = format_casualties_log(
        f"{country.flag} {country.name_fa}",
        f"{target.flag} {target.name_fa}",
        ATTACK_FA[atype],
        result,
    )

    attack = Attack(
        attacker_country=country.id,
        defender_country=target.id,
        type=atype.value,
        payload=data.get("payload", ""),
        fuel_cost=fuel,
        result=log_report,  # گزارش دقیق تلفات (به لاگ مدیران می‌رود، نه کانال نظامی)
        status=AttackStatus.IN_PROGRESS,
        resolve_eta=_utcnow() + timedelta(minutes=delay),
    )
    session.add(attack)

    await call.message.edit_text(
        f"✅ {ATTACK_FA[atype]} آغاز شد.\n"
        f"⛽ سوخت مصرف‌شده: {fa_number(fuel, 2)} میلیون بشکه\n\n"
        f"📋 گزارش اولیه:\n{player_report}\n\n"
        f"⏳ نتیجه‌ی نهایی تا حدود {fa_number(delay)} دقیقه‌ی دیگر آماده و به مدیریت بازی اعلام می‌شود.",
        reply_markup=military_menu_kb(),
    )

    # اطلاع فوری به مدافع
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"🚨 کشور شما هدف {ATTACK_FA[atype]} از سوی {country.flag} {country.name_fa} قرار گرفت!",
            )
        except Exception:  # noqa: BLE001
            pass


# ============================================================
#  تأیید/رد حمله‌ی خرابکارانه توسط مالک (v1.5)
# ============================================================
@router.callback_query(F.data.startswith("sabotage_ok:"))
async def cb_sabotage_ok(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید حمله‌ی خرابکارانه: AI نتیجه را می‌سنجد و به مهاجم/مدافع/لاگ اعلام می‌شود."""
    from ..config import get_settings

    if not get_settings().is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی مجاز است.", show_alert=True)
        return

    attack_id = int(call.data.split(":")[1])
    attack = await session.get(Attack, attack_id)
    if attack is None or attack.status != AttackStatus.PENDING:
        await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
        return

    await call.answer("در حال سنجش...")
    attacker = await countries_repo.get_country(session, attack.attacker_country)
    defender = await countries_repo.get_country(session, attack.defender_country)

    result = await evaluators.evaluate_attack(
        session, attack.attacker_country, attack.defender_country,
        ATTACK_FA[AttackType.SABOTAGE], attack.payload,
    )
    await apply_losses(session, attack.attacker_country, attack.defender_country, result)

    log_report = format_casualties_log(
        f"{attacker.flag} {attacker.name_fa}" if attacker else "?",
        f"{defender.flag} {defender.name_fa}" if defender else "?",
        ATTACK_FA[AttackType.SABOTAGE],
        result,
    )
    attack.result = log_report
    attack.status = AttackStatus.RESOLVED

    await call.message.edit_text(call.message.html_text + "\n\n✅ <b>تأیید و اجرا شد</b>")
    # اعلام نتیجه به لاگ مدیران
    await send_log(bot, log_report)
    # اعلام به مهاجم و مدافع در ربات
    player_report = result.get("player_report", "نتیجه‌ی عملیات خرابکارانه ثبت شد.")
    for c in (attacker, defender):
        if c and c.owner_user_id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"🕵️ <b>نتیجه‌ی عملیات خرابکارانه</b>\n\n{player_report}",
                )
            except Exception:  # noqa: BLE001
                pass


@router.callback_query(F.data.startswith("sabotage_no:"))
async def cb_sabotage_no(call: CallbackQuery, session: AsyncSession) -> None:
    """رد حمله‌ی خرابکارانه توسط مالک."""
    from ..config import get_settings

    if not get_settings().is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی مجاز است.", show_alert=True)
        return

    attack_id = int(call.data.split(":")[1])
    attack = await session.get(Attack, attack_id)
    if attack is None or attack.status != AttackStatus.PENDING:
        await call.answer("این درخواست دیگر معتبر نیست.", show_alert=True)
        return
    attack.status = AttackStatus.CANCELLED
    await call.answer("رد شد")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")

    attacker = await countries_repo.get_country(session, attack.attacker_country)
    if attacker and attacker.owner_user_id:
        try:
            await bot.send_message(
                attacker.owner_user_id,
                "❌ درخواست حمله‌ی خرابکارانه‌ی شما توسط مدیریت رد شد.",
            )
        except Exception:  # noqa: BLE001
            pass
