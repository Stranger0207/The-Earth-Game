"""
پنل مدیریت عملیات نظامی برای مالک بازی (v1.10.6).

بخش «⚔️ عملیات نظامی» در پنل /god:
- تأیید/رد عملیات‌های در انتظار
- بستن فوری عملیات گیرکرده
- مدیریت گشت‌ها و رزمایش‌ها
- ترور/احیای دستی فرماندهان

این فایل جدا از godmode.py است تا آن فایل بیش از حد بزرگ نشود.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.repositories import countries as countries_repo
from ..enums import (
    COMMANDER_ROLE_FA,
    OPERATION_FA,
    PATROL_FA,
    TARGET_FA,
    CommanderRole,
    OperationStatus,
    OperationType,
    PatrolType,
    TargetType,
)
from ..loader import bot
from ..services.news_service import send_log
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header

logger = logging.getLogger(__name__)
router = Router(name="god_operations")
settings = get_settings()


async def _guard(call: CallbackQuery) -> bool:
    """فقط مالک/مدیر بازی دسترسی دارد."""
    if settings.is_admin(call.from_user.id):
        return True
    await call.answer("⛔️ فقط مالک/مدیر بازی به این بخش دسترسی دارد.", show_alert=True)
    return False


def _ops_menu_kb() -> InlineKeyboardMarkup:
    """منوی مدیریت عملیات نظامی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ در انتظار تأیید", callback_data="god:ops_pending", style=STYLE_NO)
    builder.button(text="🔴 در حال اجرا", callback_data="god:ops_live", style=STYLE_MAIN)
    builder.button(text="🛩 گشت‌های فعال", callback_data="god:ops_patrols", style=STYLE_MAIN)
    builder.button(text="🎪 رزمایش‌های جاری", callback_data="god:ops_drills", style=STYLE_MAIN)
    builder.button(text="🎖 فرماندهان", callback_data="god:ops_commanders", style=STYLE_MAIN)
    builder.button(text="👤 بحران رهبری", callback_data="god:ops_crisis", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def _op_fa(value: str) -> str:
    try:
        return OPERATION_FA[OperationType(value)]
    except (ValueError, KeyError):
        return value


def _target_fa(value: str) -> str:
    try:
        return TARGET_FA[TargetType(value)]
    except (ValueError, KeyError):
        return value


# ============================================================
#  منوی اصلی
# ============================================================
@router.callback_query(F.data == "god:ops")
async def cb_ops_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """منوی اصلی مدیریت عملیات نظامی."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()

    from ..database.repositories import operations as op_repo

    pending = len(await op_repo.list_pending_owner(session))
    live = len(await op_repo.list_by_status(session, OperationStatus.IN_PROGRESS.value))

    text = (
        header("مدیریت عملیات نظامی", "⚔️") + "\n\n"
        f"⏳ در انتظار تأیید: <b>{fa_number(pending)}</b>\n"
        f"🔴 در حال اجرا: <b>{fa_number(live)}</b>\n\n"
        "<i>از این بخش عملیات‌ها را تأیید/رد کنید، عملیات گیرکرده را ببندید و "
        "وضعیت گشت‌ها، رزمایش‌ها و فرماندهان را مدیریت کنید.</i>"
    )
    await call.message.edit_text(text, reply_markup=_ops_menu_kb())


# ============================================================
#  فهرست عملیات‌ها
# ============================================================
async def _render_ops_list(
    call: CallbackQuery, session: AsyncSession, status: str, title: str, emoji: str
) -> None:
    """رندر فهرست عملیات یک وضعیت با دکمه‌های مدیریتی."""
    from ..database.repositories import operations as op_repo

    if status == OperationStatus.PENDING_OWNER.value:
        rows = await op_repo.list_pending_owner(session)
    else:
        rows = await op_repo.list_by_status(session, status)

    builder = InlineKeyboardBuilder()
    lines = [header(title, emoji), ""]

    if not rows:
        lines.append("موردی وجود ندارد.")
    else:
        for op in rows[:10]:
            attacker = await countries_repo.get_country(session, op.attacker_country_id)
            defender = await countries_repo.get_country(session, op.defender_country_id)
            a_name = f"{attacker.flag} {attacker.name_fa}" if attacker else "؟"
            d_name = f"{defender.flag} {defender.name_fa}" if defender else "؟"

            lines.append(
                f"<b>#{op.id}</b> {_op_fa(op.operation_type)}\n"
                f"   {a_name} ← {d_name}\n"
                f"   🎯 {_target_fa(op.target_type)} | شدت {fa_number(op.intensity)}/۱۰ | "
                f"فاز {fa_number(op.current_phase)}/{fa_number(op.total_phases)}"
            )

            if status == OperationStatus.PENDING_OWNER.value:
                builder.button(
                    text=f"✅ تأیید #{op.id}", callback_data=f"op_approve:{op.id}", style=STYLE_OK
                )
                builder.button(
                    text=f"❌ رد #{op.id}", callback_data=f"op_reject:{op.id}", style=STYLE_NO
                )
            else:
                builder.button(
                    text=f"🏁 بستن #{op.id}", callback_data=f"god_op_end:{op.id}", style=STYLE_NO
                )

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops", style=STYLE_MAIN))

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await call.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "god:ops_pending")
async def cb_ops_pending(call: CallbackQuery, session: AsyncSession) -> None:
    """عملیات‌های در انتظار تأیید."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_ops_list(
        call, session, OperationStatus.PENDING_OWNER.value, "در انتظار تأیید", "⏳"
    )


@router.callback_query(F.data == "god:ops_live")
async def cb_ops_live(call: CallbackQuery, session: AsyncSession) -> None:
    """عملیات‌های در حال اجرا."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_ops_list(
        call, session, OperationStatus.IN_PROGRESS.value, "عملیات در حال اجرا", "🔴"
    )


@router.callback_query(F.data.startswith("god_op_end:"))
async def cb_op_end(call: CallbackQuery, session: AsyncSession) -> None:
    """بستن فوری یک عملیات گیرکرده (اعمال نتایج و پایان فازها)."""
    if not await _guard(call):
        return

    op_id = int(call.data.split(":")[1])
    from ..database.repositories import operations as op_repo
    from ..services import operation_service

    operation = await op_repo.get_operation(session, op_id)
    if operation is None:
        await call.answer("عملیات یافت نشد.", show_alert=True)
        return

    try:
        await operation_service.apply_outcome(session, operation)
        operation.current_phase = operation.total_phases
        operation.next_phase_at = None
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("god_op_end failed: %s", exc)
        await call.answer("خطا در بستن عملیات.", show_alert=True)
        return

    await call.answer("عملیات بسته شد 🏁", show_alert=True)
    await send_log(bot, f"🏁 <b>بستن فوری عملیات #{op_id} توسط مدیریت</b>")
    await _render_ops_list(
        call, session, OperationStatus.IN_PROGRESS.value, "عملیات در حال اجرا", "🔴"
    )


# ============================================================
#  گشت‌ها
# ============================================================
@router.callback_query(F.data == "god:ops_patrols")
async def cb_patrols(call: CallbackQuery, session: AsyncSession) -> None:
    """فهرست گشت‌های فعال همه‌ی کشورها."""
    if not await _guard(call):
        return
    await call.answer()

    from ..database.models import Patrol

    result = await session.execute(
        select(Patrol)
        .where(Patrol.is_active == True)  # noqa: E712
        .order_by(Patrol.started_at.desc())
    )
    patrols = list(result.scalars().all())

    builder = InlineKeyboardBuilder()
    lines = [header("گشت‌های فعال", "🛩"), ""]

    if not patrols:
        lines.append("گشت فعالی وجود ندارد.")
    else:
        for patrol in patrols[:12]:
            country = await countries_repo.get_country(session, patrol.country_id)
            try:
                ptype_fa = PATROL_FA[PatrolType(patrol.patrol_type)]
            except (ValueError, KeyError):
                ptype_fa = patrol.patrol_type
            name = f"{country.flag} {country.name_fa}" if country else "؟"
            lines.append(
                f"<b>#{patrol.id}</b> {name} — {ptype_fa}\n"
                f"   📍 {patrol.area or '—'} | 🪖 {fa_number(patrol.total_units)} واحد "
                f"| 🔍 {fa_number(patrol.detections)}"
            )
            builder.button(
                text=f"🛑 پایان #{patrol.id}",
                callback_data=f"god_patrol_end:{patrol.id}",
                style=STYLE_NO,
            )

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops", style=STYLE_MAIN))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("god_patrol_end:"))
async def cb_patrol_end(call: CallbackQuery, session: AsyncSession) -> None:
    """پایان دادن به یک گشت توسط مدیریت."""
    if not await _guard(call):
        return

    patrol_id = int(call.data.split(":")[1])
    from ..database.repositories import patrols as patrol_repo

    patrol = await patrol_repo.get_patrol(session, patrol_id)
    if patrol is None:
        await call.answer("گشت یافت نشد.", show_alert=True)
        return

    patrol.is_active = False
    await session.commit()
    await call.answer("گشت پایان یافت 🛑")
    await cb_patrols(call, session)


# ============================================================
#  رزمایش‌ها
# ============================================================
@router.callback_query(F.data == "god:ops_drills")
async def cb_drills(call: CallbackQuery, session: AsyncSession) -> None:
    """فهرست رزمایش‌های جاری."""
    if not await _guard(call):
        return
    await call.answer()

    from ..database.models import Drill

    result = await session.execute(
        select(Drill)
        .where(Drill.is_completed == False)  # noqa: E712
        .order_by(Drill.started_at.desc())
    )
    drills = list(result.scalars().all())

    builder = InlineKeyboardBuilder()
    lines = [header("رزمایش‌های جاری", "🎪"), ""]

    if not drills:
        lines.append("رزمایشی در جریان نیست.")
    else:
        for drill in drills[:12]:
            country = await countries_repo.get_country(session, drill.country_id)
            name = f"{country.flag} {country.name_fa}" if country else "؟"
            partner_text = ""
            if drill.partner_country_id:
                partner = await countries_repo.get_country(session, drill.partner_country_id)
                if partner:
                    mark = "✅" if drill.partner_accepted else "⏳"
                    partner_text = f" {mark} با {partner.flag} {partner.name_fa}"
            lines.append(
                f"<b>#{drill.id}</b> {name} — {drill.title or 'رزمایش'}{partner_text}\n"
                f"   🎯 آمادگی: +{fa_number(drill.readiness_gain, 1)}"
            )
            builder.button(
                text=f"⚡️ اتمام #{drill.id}",
                callback_data=f"god_drill_end:{drill.id}",
                style=STYLE_OK,
            )

    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops", style=STYLE_MAIN))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("god_drill_end:"))
async def cb_drill_end(call: CallbackQuery, session: AsyncSession) -> None:
    """اتمام فوری یک رزمایش و اعمال آمادگی رزمی."""
    if not await _guard(call):
        return

    drill_id = int(call.data.split(":")[1])
    from ..database.repositories import drills as drill_repo
    from ..services import drill_service

    drill = await drill_repo.get_drill(session, drill_id)
    if drill is None:
        await call.answer("رزمایش یافت نشد.", show_alert=True)
        return

    try:
        result = await drill_service.complete_drill(session, drill)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("god_drill_end failed: %s", exc)
        await call.answer("خطا در اتمام رزمایش.", show_alert=True)
        return

    gain = result.get("country_gain", 0.0)
    await call.answer(f"رزمایش تمام شد (+{gain:.1f} آمادگی) ⚡️", show_alert=True)
    await cb_drills(call, session)


# ============================================================
#  فرماندهان
# ============================================================
@router.callback_query(F.data == "god:ops_commanders")
async def cb_commanders_countries(
    call: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """انتخاب کشور برای مشاهده‌ی فرماندهان."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()

    countries = await countries_repo.list_countries(session)
    builder = InlineKeyboardBuilder()
    for country in countries:
        builder.button(
            text=f"{country.flag} {country.name_fa}",
            callback_data=f"god_cmd_list:{country.id}",
            style=STYLE_MAIN,
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops", style=STYLE_MAIN))
    await call.message.edit_text(
        header("فرماندهان — انتخاب کشور", "🎖"), reply_markup=builder.as_markup()
    )


async def _render_commanders(call: CallbackQuery, session: AsyncSession, country_id: int) -> None:
    """فهرست فرماندهان یک کشور با امکان ترور/احیای دستی."""
    from ..database.repositories import commanders as cmd_repo

    country = await countries_repo.get_country(session, country_id)
    commanders = await cmd_repo.list_commanders(session, country_id)

    builder = InlineKeyboardBuilder()
    lines = [header("فرماندهان", "🎖"), ""]
    if country:
        lines.append(f"کشور: {country.flag} <b>{country.name_fa}</b>")
        lines.append("")

    if not commanders:
        lines.append("فرماندهی ثبت نشده است.")
        lines.append("\n<i>برای ساخت: python -m scripts.seed_commanders</i>")
    else:
        for cmd in commanders:
            try:
                role_fa = COMMANDER_ROLE_FA[CommanderRole(cmd.role)]
            except (ValueError, KeyError):
                role_fa = cmd.role
            state_text = "🟢 فعال" if cmd.is_alive else "🔴 ترورشده"
            lines.append(
                f"<b>#{cmd.id}</b> {cmd.rank_title} {cmd.name}\n"
                f"   {role_fa} | {state_text} | +{fa_number(cmd.bonus_pct)}٪"
            )
            if cmd.is_alive:
                builder.button(
                    text=f"💀 ترور #{cmd.id}",
                    callback_data=f"god_cmd_kill:{cmd.id}",
                    style=STYLE_NO,
                )
            else:
                builder.button(
                    text=f"♻️ احیا #{cmd.id}",
                    callback_data=f"god_cmd_revive:{cmd.id}",
                    style=STYLE_OK,
                )

    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops_commanders", style=STYLE_MAIN)
    )
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("god_cmd_list:"))
async def cb_cmd_list(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش فرماندهان یک کشور."""
    if not await _guard(call):
        return
    await call.answer()
    await _render_commanders(call, session, int(call.data.split(":")[1]))


@router.callback_query(F.data.startswith("god_cmd_kill:"))
async def cb_cmd_kill(call: CallbackQuery, session: AsyncSession) -> None:
    """ترور دستی یک فرمانده توسط مدیریت."""
    if not await _guard(call):
        return

    cmd_id = int(call.data.split(":")[1])
    from ..constants import COMMANDER_REPLACEMENT_HOURS
    from ..database.repositories import commanders as cmd_repo

    commander = await cmd_repo.get_commander(session, cmd_id)
    if commander is None:
        await call.answer("فرمانده یافت نشد.", show_alert=True)
        return

    replacement_at = datetime.now(timezone.utc) + timedelta(hours=COMMANDER_REPLACEMENT_HOURS)
    await cmd_repo.kill_commander(session, commander, replacement_at)
    await session.commit()

    await call.answer("فرمانده ترور شد 💀", show_alert=True)
    await send_log(
        bot,
        f"💀 <b>ترور دستی فرمانده توسط مدیریت</b>\n{commander.rank_title} {commander.name}",
    )
    await _render_commanders(call, session, commander.country_id)


@router.callback_query(F.data.startswith("god_cmd_revive:"))
async def cb_cmd_revive(call: CallbackQuery, session: AsyncSession) -> None:
    """احیای دستی یک فرمانده."""
    if not await _guard(call):
        return

    cmd_id = int(call.data.split(":")[1])
    from ..database.repositories import commanders as cmd_repo

    commander = await cmd_repo.get_commander(session, cmd_id)
    if commander is None:
        await call.answer("فرمانده یافت نشد.", show_alert=True)
        return

    commander.is_alive = True
    commander.killed_at = None
    commander.replacement_at = None
    await session.commit()

    await call.answer("فرمانده احیا شد ♻️", show_alert=True)
    await _render_commanders(call, session, commander.country_id)


# ============================================================
#  بحران رهبری: احیای رئیس‌جمهور (v2.1)
# ============================================================
#
# پس از ترور موفق رئیس‌جمهور، کشور هدف تا LEADERSHIP_CRISIS_HOURS ساعت
# نمی‌تواند عملیات نظامی ثبت کند (`operation_service.assert_can_operate`).
# پیش از v2.1 هیچ راه دستی برای رفع این قفل نبود و مالک باید صبر می‌کرد.

def _crisis_remaining_min(country) -> int:
    """چند دقیقه از بحران رهبری این کشور باقی مانده است؟ (صفر = بحرانی نیست)"""
    until = getattr(country, "leadership_crisis_until", None)
    if until is None:
        return 0
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    remaining = (until - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(remaining // 60))


async def _render_crisis_list(call: CallbackQuery, session: AsyncSession) -> None:
    """فهرست کشورهای در «بحران رهبری» با دکمه‌ی احیای رئیس‌جمهور."""
    countries = await countries_repo.list_countries(session)
    in_crisis = [(c, _crisis_remaining_min(c)) for c in countries]
    in_crisis = [(c, m) for c, m in in_crisis if m > 0]

    builder = InlineKeyboardBuilder()
    lines = [header("بحران رهبری", "👤"), ""]

    if not in_crisis:
        lines.append("🟢 هیچ کشوری در بحران رهبری نیست.")
        lines.append(
            "\n<i>بحران رهبری پس از ترور موفق رئیس‌جمهور رخ می‌دهد و تا چند ساعت "
            "کشور را از ثبت عملیات نظامی محروم می‌کند.</i>"
        )
    else:
        lines.append(
            "کشورهای زیر پس از ترور رئیس‌جمهور در بحران رهبری‌اند و نمی‌توانند "
            "عملیات نظامی ثبت کنند.\n"
        )
        for country, minutes in in_crisis:
            hours, mins = divmod(minutes, 60)
            remaining = (
                f"{fa_number(hours)} ساعت و {fa_number(mins)} دقیقه"
                if hours
                else f"{fa_number(mins)} دقیقه"
            )
            lines.append(
                f"🔴 {country.flag} <b>{country.name_fa}</b> — باقی‌مانده: {remaining}"
            )
            builder.button(
                text=f"♻️ احیای رئیس‌جمهور {country.name_fa}",
                callback_data=f"god_pres_revive:{country.id}",
                style=STYLE_OK,
            )
        builder.adjust(1)

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:ops", style=STYLE_MAIN)
    )
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "god:ops_crisis")
async def cb_crisis_list(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """پنل بحران رهبری."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    await _render_crisis_list(call, session)


@router.callback_query(F.data.startswith("god_pres_revive:"))
async def cb_pres_revive(call: CallbackQuery, session: AsyncSession) -> None:
    """
    احیای دستی رئیس‌جمهور: پایان‌دادن فوری به بحران رهبری.

    فقط قفل عملیات (`leadership_crisis_until`) برداشته می‌شود؛ افت ثبات و
    رضایت عمومی که اثر جداگانه‌ی ترور بودند دست‌نخورده می‌مانند تا نتیجه‌ی
    عملیات مهاجم بی‌اثر نشود.
    """
    if not await _guard(call):
        return

    cid = int(call.data.split(":")[1])
    country = await countries_repo.get_country(session, cid)
    if country is None:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    if _crisis_remaining_min(country) <= 0:
        await call.answer("این کشور در بحران رهبری نیست.", show_alert=True)
        await _render_crisis_list(call, session)
        return

    country.leadership_crisis_until = None
    await session.commit()

    await call.answer("رئیس‌جمهور احیا شد ♻️", show_alert=True)
    await send_log(
        bot,
        f"♻️ <b>احیای دستی رئیس‌جمهور</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        "بحران رهبری پایان یافت و محدودیت ثبت عملیات برداشته شد.\n"
        "👤 توسط مدیریت بازی",
    )

    if country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                "▶️ <b>بحران رهبری کشور شما پایان یافت.</b>\n\n"
                "رئیس‌جمهور جدید مستقر شد و اکنون می‌توانید دوباره عملیات "
                "نظامی ثبت کنید.",
            )
        except Exception:  # noqa: BLE001 — خطای ارسال نباید جریان را متوقف کند
            pass

    await _render_crisis_list(call, session)

