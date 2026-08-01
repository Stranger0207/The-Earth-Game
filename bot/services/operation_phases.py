"""
پردازش فازهای خبری عملیات (v1.10.6).

اینجا همه‌ی قطعات به هم وصل می‌شوند:
موتور نبرد (اعداد) → خبرنویس ضدتکرار (متن) → لایه‌ی انتشار (کانال/عکس)

هر عملیات تأییدشده در چند فاز خبری منتشر می‌شود (۳ تا ۹ فاز بر اساس شدت).
در آخرین فاز، نتایج واقعی (تلفات و اثرات اقتصادی) روی بازی اعمال می‌شود.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Operation
from ..database.repositories import countries as countries_repo
from ..database.repositories import operations as op_repo
from ..enums import OperationStatus
from . import operation_service
from .news import facts as facts_mod
from .news import military_news, publisher

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _used_archetypes(operation: Operation) -> list[str]:
    """سبک‌های خبری استفاده‌شده در فازهای قبلی همین عملیات."""
    try:
        return list(json.loads(operation.used_archetypes_json or "[]"))
    except (ValueError, TypeError):
        return []


async def _owner_chat_ids(session: AsyncSession, operation: Operation) -> list[int]:
    """
    آی‌دی مالکان طرفین برای ارسال خبر به پیوی.

    در عملیات مخفیانه‌ی افشانشده، مدافع خبر را می‌گیرد ولی نمی‌داند مهاجم کیست
    (این در متن خبر رعایت می‌شود، نه در گیرندگان).
    """
    ids: list[int] = []
    for country_id in (operation.attacker_country_id, operation.defender_country_id):
        country = await countries_repo.get_country(session, country_id)
        if country and country.owner_user_id:
            ids.append(country.owner_user_id)
    return ids


def _anonymize_facts(facts: dict, operation: Operation) -> dict:
    """
    در عملیات مخفیانه‌ی بدون پذیرش مسئولیت، نام مهاجم از خبر عمومی حذف می‌شود
    تا خبرنویس آن را لو ندهد.
    """
    if operation.claim_responsibility or operation.is_exposed:
        return facts

    masked = dict(facts)
    masked["attacker"] = "عوامل ناشناس"
    masked["top_attack_assets"] = []
    masked["_covert"] = True
    return masked


async def process_due_phases(session: AsyncSession, bot: Bot) -> int:
    """
    عملیات‌هایی که فاز خبری بعدی‌شان سررسیده را پردازش می‌کند.

    خروجی: تعداد فازهای منتشرشده.

    هر عملیات مستقل در try/except اجرا می‌شود تا خطای یکی بقیه را متوقف نکند.
    """
    published = 0
    due = await op_repo.list_due_phases(session)

    for operation in due:
        try:
            published += await _advance_one(session, bot, operation)
        except Exception as exc:  # noqa: BLE001 — خطای یک عملیات نباید تیک را بشکند
            logger.exception("Operation phase failed (id=%s): %s", operation.id, exc)
            # جلوگیری از حلقه‌ی بی‌پایان: فاز را جلو ببر
            try:
                operation.current_phase += 1
                if operation.current_phase > operation.total_phases:
                    operation.status = OperationStatus.RESOLVED.value
                    operation.resolved_at = _utcnow()
                    operation.next_phase_at = None
                else:
                    operation.next_phase_at = _utcnow() + timedelta(
                        minutes=max(1, operation.phase_interval_min)
                    )
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()

    return published


async def _advance_one(session: AsyncSession, bot: Bot, operation: Operation) -> int:
    """یک فاز از یک عملیات را منتشر می‌کند. خروجی: ۱ اگر منتشر شد."""
    phase_index = max(1, operation.current_phase)
    plan = facts_mod.phase_plan(operation.total_phases)
    if phase_index > len(plan):
        # فازها تمام شده‌اند
        await _finalize(session, bot, operation)
        return 0

    phase_kind = plan[phase_index - 1]
    raw_facts = operation_service.parse_facts(operation)
    facts = _anonymize_facts(raw_facts, operation)

    attacker = await countries_repo.get_country(session, operation.attacker_country_id)
    defender = await countries_repo.get_country(session, operation.defender_country_id)

    # ---------- نوشتن خبر ----------
    text, archetype = await military_news.write_phase_news(
        session,
        facts,
        phase_kind,
        used_archetypes=_used_archetypes(operation),
        seed=operation.id * 100 + phase_index,
    )

    # ثبت سبک استفاده‌شده تا فاز بعدی تکرارش نکند
    used = _used_archetypes(operation)
    used.append(archetype)
    operation.used_archetypes_json = json.dumps(used, ensure_ascii=False)

    # ---------- انتشار ----------
    to_channel = await publisher.deliver_operation_news(
        bot,
        text=text,
        facts=facts,
        phase_kind=phase_kind,
        intensity=operation.intensity,
        attacker_is_vip=bool(attacker and attacker.is_vip),
        defender_is_vip=bool(defender and defender.is_vip),
        owner_chat_ids=await _owner_chat_ids(session, operation),
    )
    if to_channel:
        operation.published_to_channel = True

    # ---------- برنامه‌ریزی فاز بعدی ----------
    operation.current_phase = phase_index + 1
    if operation.current_phase > operation.total_phases:
        operation.next_phase_at = None
        await _finalize(session, bot, operation)
    else:
        operation.next_phase_at = _utcnow() + timedelta(
            minutes=max(1, operation.phase_interval_min)
        )

    await session.commit()
    return 1


async def _finalize(session: AsyncSession, bot: Bot, operation: Operation) -> None:
    """
    پایان عملیات: اعمال تلفات و اثرات اقتصادی + گزارش نهایی به طرفین و لاگ.
    """
    if operation.status == OperationStatus.RESOLVED.value:
        return

    await operation_service.apply_outcome(session, operation)

    attacker = await countries_repo.get_country(session, operation.attacker_country_id)
    defender = await countries_repo.get_country(session, operation.defender_country_id)

    from ..enums import OPERATION_FA, OperationType
    from ..services.news_service import send_log
    from ..utils.numbers import fa_number

    try:
        op_fa = OPERATION_FA[OperationType(operation.operation_type)]
    except (ValueError, KeyError):
        op_fa = operation.operation_type

    attacker_losses = json.loads(operation.attacker_losses_json or "[]")
    defender_losses = json.loads(operation.defender_losses_json or "[]")

    def _losses_text(items: list[dict]) -> str:
        if not items:
            return "بدون تلفات"
        return "، ".join(
            f"{fa_number(i.get('count', 0))} {i.get('unit', '')} {i.get('name', '')}".strip()
            for i in items[:5]
        )

    # ---------- گزارش دقیق به گروه لاگ (ممیزی کامل) ----------
    attacker_name = f"{attacker.flag} {attacker.name_fa}" if attacker else "نامشخص"
    defender_name = f"{defender.flag} {defender.name_fa}" if defender else "نامشخص"

    log_lines = [
        "🏁 <b>پایان عملیات — گزارش نهایی</b>",
        "",
        f"🔴 مهاجم: {attacker_name}",
        f"🔵 مدافع: {defender_name}",
        f"🏷 نوع: {op_fa}",
        f"🏆 نتیجه: {operation.outcome}",
        f"🛡 رهگیری: {fa_number(operation.intercept_pct, 1)}٪",
        f"💥 خسارت: {fa_number(operation.infra_damage_pct, 1)}٪",
    ]
    if operation.civilian_casualties:
        log_lines.append(f"⚠️ تلفات غیرنظامی: {fa_number(operation.civilian_casualties)}")
    log_lines += [
        f"💀 تلفات مهاجم: {_losses_text(attacker_losses)}",
        f"💀 تلفات مدافع: {_losses_text(defender_losses)}",
        f"📡 انتشار در کانال: {'بله' if operation.published_to_channel else 'خیر (شدت پایین)'}",
    ]
    await send_log(bot, "\n".join(log_lines))

    # ---------- پیام به طرفین ----------
    if attacker and attacker.owner_user_id:
        try:
            await bot.send_message(
                attacker.owner_user_id,
                f"🏁 <b>عملیات شما پایان یافت</b>\n\n"
                f"🏷 {op_fa}\n"
                f"🏆 نتیجه: {operation.outcome}\n"
                f"💥 خسارت واردشده: {fa_number(operation.infra_damage_pct, 1)}٪\n"
                f"💀 تلفات نیروی خودی: {_losses_text(attacker_losses)}",
            )
        except Exception:  # noqa: BLE001
            pass

    if defender and defender.owner_user_id:
        # در عملیات مخفیانه‌ی افشانشده، هویت مهاجم لو نمی‌رود
        if operation.claim_responsibility or operation.is_exposed:
            who = f"{attacker.flag} {attacker.name_fa}" if attacker else "نامشخص"
        else:
            who = "🕵️ عوامل ناشناس"
        try:
            await bot.send_message(
                defender.owner_user_id,
                f"🛡 <b>عملیات علیه کشور شما پایان یافت</b>\n\n"
                f"🏷 {op_fa} از سوی {who}\n"
                f"🛡 عملکرد پدافند: {fa_number(operation.intercept_pct, 1)}٪ رهگیری\n"
                f"💥 خسارت واردشده: {fa_number(operation.infra_damage_pct, 1)}٪\n"
                f"💀 تلفات شما: {_losses_text(defender_losses)}",
            )
        except Exception:  # noqa: BLE001
            pass
