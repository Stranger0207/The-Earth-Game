"""منطق کسب‌وکار نبردهای نظامی، اعلان جنگ و فازهای خبری (v2.0)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import Battle, Country, WarDeclaration
from ..database.repositories import battles as battle_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import AttackType, NewsCategory, ResourceType
from ..loader import bot
from ..services.ai import evaluators
from ..services.media import send_photo_news
from ..services.news_service import publish_news, send_log
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_NO, STYLE_OK

logger = logging.getLogger(__name__)
settings = get_settings()


class BattleServiceError(Exception):
    """خطای سرویس نبرد."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def declare_war(
    session: AsyncSession, declarer: Country, target: Country
) -> WarDeclaration:
    """اعلام جنگ رسمی علیه یک کشور."""
    if declarer.id == target.id:
        raise BattleServiceError("نمی‌توانید علیه کشور خودتان اعلام جنگ کنید.")

    already_war = await battle_repo.has_active_war_declaration(session, declarer.id, target.id)
    if already_war:
        raise BattleServiceError(f"کشور شما قبلاً علیه {target.name_fa} اعلام جنگ کرده است.")

    decl = await battle_repo.declare_war(session, declarer.id, target.id)

    # انتشار خبر اعلام جنگ در کانال دیپلماسی
    news_text = (
        f"🚨 **اعلام رسمی وضعیت جنگ!!**\n\n"
        f"دولت و شورای عالی امنیت ملی کشور {declarer.flag} {declarer.name_fa} رسماً علیه کشور "
        f"{target.flag} {target.name_fa} **اعلام جنگ** کرد!\n"
        "فرماندهی نیروهای مسلح وضعیت آماده‌باش کامل اعلام نموده است."
    )
    await publish_news(bot, NewsCategory.DIPLOMACY, news_text)
    await send_log(
        bot,
        "🚨 **اعلام جنگ رسمی**\n"
        f"مهاجم: {declarer.flag} {declarer.name_fa}\n"
        f"مدافع: {target.flag} {target.name_fa}",
    )
    return decl


async def create_battle_request(
    session: AsyncSession,
    attacker: Country,
    defender: Country,
    attack_type: str,
    target_type: str,
    payload_text: str,
    claim_responsibility: bool = True,
) -> Battle:
    """
    ثبت درخواست نبرد نظامی.
    - بررسی محدودیت ۲۴ ساعته (حداکثر ۱ حمله در ۲۴ ساعت).
    - بررسی اعلان جنگ (مگر آنکه حمله خرابکاری باشد).
    - ثبت نبرد با وضعیت pending_owner و ارسال به مالک برای تأیید اولیه.
    """
    if attacker.id == defender.id:
        raise BattleServiceError("نمی‌توانید به کشور خودتان حمله کنید.")

    # ۱. محدودیت ۱ حمله در ۲۴ ساعت
    count_24h = await battle_repo.count_attacks_in_last_24h(session, attacker.id)
    if count_24h >= 1:
        raise BattleServiceError("هر کشور در هر ۲۴ ساعت حداکثر ۱ حمله نظامی می‌تواند انجام دهد.")

    is_sabotage = attack_type == AttackType.SABOTAGE.value

    # ۲. بررسی اعلان جنگ (اگر خرابکاری نباشد)
    if not is_sabotage:
        has_war = await battle_repo.has_active_war_declaration(session, attacker.id, defender.id)
        if not has_war:
            raise BattleServiceError(
                f"برای این حمله، ابتدا باید از بخش دیپلماسی علیه کشور {defender.name_fa} **اعلام جنگ** کنید!"
            )

    battle = Battle(
        attacker_country_id=attacker.id,
        defender_country_id=defender.id,
        attack_type=attack_type,
        target_type=target_type,
        payload=payload_text,
        claim_responsibility=claim_responsibility,
        status="pending_owner",
        created_at=_utcnow(),
    )
    battle = await battle_repo.create_battle(session, battle)

    # ارسال پیام درخواست به گروه لاگ مدیریت برای تأیید مالک بازی
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ تأیید و شروع نبرد", callback_data=f"gapprove_btl:{battle.id}", style=STYLE_OK),
            InlineKeyboardButton(text="❌ رد حمله", callback_data=f"greject_btl:{battle.id}", style=STYLE_NO),
        ]]
    )

    attack_type_fa = {
        "ground": "حمله زمینی",
        "air": "حمله هوایی",
        "naval": "حمله دریایی",
        "sabotage": "خرابکاری مخفیانه",
        "wto_interception": "حمله به محموله WTO",
    }.get(attack_type, attack_type)

    await send_log(
        bot,
        "⚔️ **درخواست حمله نظامی جدید (نیازمند تأیید مالک)**\n\n"
        f"🔴 **مهاجم:** {attacker.flag} {attacker.name_fa}\n"
        f"🔵 **مدافع:** {defender.flag} {defender.name_fa}\n"
        f"🏷 **نوع:** {attack_type_fa}\n"
        f"🎯 **هدف:** {target_type}\n\n"
        f"📝 **نقشه و توضیحات بازیکن:**\n{payload_text}",
        reply_markup=kb,
    )

    return battle


async def approve_battle_by_owner(session: AsyncSession, battle_id: int) -> Battle:
    """
    تأیید نبرد توسط مالک بازی.
    با تأیید: سنجش AI انجام شده، سوخت کسر می‌شود، وضعیت به in_progress تغییر می‌یابد و فاز ۱ فوراً کلید می‌خورد.
    """
    battle = await battle_repo.get_battle(session, battle_id)
    if not battle or battle.status != "pending_owner":
        raise BattleServiceError("نبرد معتبری در انتظار تأیید یافت نشد.")

    attacker = await countries_repo.get_country(session, battle.attacker_country_id)
    defender = await countries_repo.get_country(session, battle.defender_country_id)

    if not attacker or not defender:
        raise BattleServiceError("اطلاعات طرفین نبرد یافت نشد.")

    attack_type_fa = {
        "ground": "حمله زمینی",
        "air": "حمله هوایی",
        "naval": "حمله دریایی",
        "sabotage": "خرابکاری مخفیانه",
        "wto_interception": "حمله به محموله WTO",
    }.get(battle.attack_type, battle.attack_type)

    # داوری هوش مصنوعی
    eval_res = await evaluators.evaluate_battle(
        session=session,
        attacker_id=attacker.id,
        defender_id=defender.id,
        attack_type_fa=attack_type_fa,
        target_info=battle.target_type,
        payload_text=battle.payload,
    )

    # بازدارندگی هسته‌ای (v1.10.4): زرادخانه‌ی مدافع تلفات مهاجم را بالا و خسارت مدافع را کم می‌کند.
    # مهاجم در برابر یک قدرت هسته‌ای محتاط‌تر عمل می‌کند و عمق عملیات کمتر می‌شود.
    try:
        from . import nuclear_service

        deterrence = await nuclear_service.deterrence_defense_pct(session, defender.id)
        if deterrence > 0:
            factor = deterrence / 100.0
            def_losses = eval_res.get("defender_losses", [])
            for item in def_losses:
                item["count"] = max(0, int(int(item.get("count", 0)) * (1.0 - factor)))
            econ = eval_res.get("economic_effects", {})
            for key in (
                "defender_satisfaction_delta",
                "defender_stability_delta",
                "defender_inflation_delta",
            ):
                if key in econ:
                    econ[key] = float(econ[key]) * (1.0 - factor)
            eval_res["economic_effects"] = econ
            logger.info(
                "Nuclear deterrence applied: defender=%s, reduction=%.1f%%",
                defender.name_en,
                deterrence,
            )
    except Exception as exc:  # noqa: BLE001 — بازدارندگی نباید جریان نبرد را متوقف کند
        logger.exception("Failed to apply nuclear deterrence: %s", exc)

    fuel_cost = float(eval_res.get("fuel_cost_oil_barrels", 1.0))
    battle.fuel_cost = fuel_cost
    battle.attacker_losses_json = json.dumps(eval_res.get("attacker_losses", []), ensure_ascii=False)
    battle.defender_losses_json = json.dumps(eval_res.get("defender_losses", []), ensure_ascii=False)
    battle.econ_effects_json = json.dumps(eval_res.get("economic_effects", {}), ensure_ascii=False)
    battle.outcome = eval_res.get("outcome", "برتری نامشخص")

    # ذخیره واقعیت‌های فازهای خبری
    phase_facts = eval_res.get("phase_facts", {})
    battle.payload += f"\n\n---PHASE_FACTS---\n{json.dumps(phase_facts, ensure_ascii=False)}"

    # کسر سوخت نفت از مهاجم
    if await reserves_repo.has_enough(session, attacker.id, ResourceType.OIL, fuel_cost):
        await reserves_repo.add_amount(session, attacker.id, ResourceType.OIL, -fuel_cost)

    battle.status = "in_progress"
    battle.current_phase = 1
    battle.next_phase_at = _utcnow()
    await session.flush()
    return battle


async def process_battle_phases(session: AsyncSession, bot: Bot) -> None:
    """
    پردازش فازهای چندمرحله‌ای خبری برای نبردهای در حال اجرا (توسط زمان‌بند).
    هر دقیقه فقط ۱ پیام خبری ارسال می‌شود (۱ فاز در هر تیک).
    حداکثر ۵ فاز = ۵ دقیقه اخبار نبرد:
      فاز ۱: فلش فوری  |  فاز ۲: درگیری دفاعی  |  فاز ۳: گزارش خسارات
      فاز ۴: نتیجه نهایی  |  فاز ۵: جمع‌بندی کامل + اعمال تلفات
    اخبار با عکس‌های پویا به کانال اخبار نظامی ارسال می‌شوند.
    """
    battles = await battle_repo.list_in_progress_battles(session)
    now = _utcnow()

    for b in battles:
        if b.next_phase_at is None or b.next_phase_at > now:
            continue

        attacker = await countries_repo.get_country(session, b.attacker_country_id)
        defender = await countries_repo.get_country(session, b.defender_country_id)
        if not attacker or not defender:
            continue

        # استخراج واقعیت‌های فاز خبری
        phase_facts_dict = {}
        if "---PHASE_FACTS---" in b.payload:
            try:
                raw_json = b.payload.split("---PHASE_FACTS---")[1].strip()
                phase_facts_dict = json.loads(raw_json)
            except Exception:
                pass

        # هر فاز: فقط یک خبر تولید و ارسال شود، سپس شماره فاز بعدی ست شود
        phase = b.current_phase

        if phase == 1:
            facts = phase_facts_dict.get("phase1_flash") or f"حمله {b.attack_type} توسط {attacker.name_fa} به {defender.name_fa}"
            news_text = await evaluators.write_war_phase_news("فاز ۱: فلش فوری خبر", facts)

        elif phase == 2:
            facts = phase_facts_dict.get("phase2_clash") or f"درگیری سامانه‌های دفاعی در محور نبرد بین {attacker.name_fa} و {defender.name_fa}"
            news_text = await evaluators.write_war_phase_news("فاز ۲: درگیری دفاعی و هوایی", facts)

        elif phase == 3:
            facts = phase_facts_dict.get("phase3_damage") or "گزارش‌های خسارت به پایگاه‌ها و خطوط پشتیبانی"
            news_text = await evaluators.write_war_phase_news("فاز ۳: گزارش اولیه خسارات نبرد", facts)

        elif phase == 4:
            facts = phase_facts_dict.get("phase4_result") or f"پایان درگیری با {b.outcome}"
            news_text = await evaluators.write_war_phase_news("فاز ۴: خلاصه نهایی و جمع‌بندی نبرد", facts)

        elif phase == 5:
            # فاز ۵: بسته‌شدن نبرد + اعمال تلفات و اثرات اقتصادی
            outcome_text = b.outcome or "نتیجه نامشخص"
            news_text = (
                f"🏁 **پایان عملیات نظامی**\n\n"
                f"عملیات {b.attack_type} کشور {attacker.flag} {attacker.name_fa} علیه "
                f"{defender.flag} {defender.name_fa} به پایان رسید.\n\n"
                f"🏆 **نتیجه نهایی:** {outcome_text}"
            )

            # کسر خودکار تلفات تجهیزات
            try:
                atk_losses = json.loads(b.attacker_losses_json)
                def_losses = json.loads(b.defender_losses_json)
                for item in atk_losses:
                    await mil_repo.reduce_count(session, attacker.id, item.get("name", ""), int(item.get("count", 0)))
                for item in def_losses:
                    await mil_repo.reduce_count(session, defender.id, item.get("name", ""), int(item.get("count", 0)))
            except Exception as exc:
                logger.exception("Failed to apply losses: %s", exc)

            # اعمال اثرات اقتصادی روی کشور مدافع
            try:
                econ = json.loads(b.econ_effects_json)
                defender.public_satisfaction = max(0.0, min(100.0, defender.public_satisfaction + float(econ.get("defender_satisfaction_delta", -1.0))))
                defender.stability = max(0.0, min(100.0, defender.stability + float(econ.get("defender_stability_delta", -1.0))))
                defender.inflation = max(0.0, defender.inflation + float(econ.get("defender_inflation_delta", 0.5)))
            except Exception as exc:
                logger.exception("Failed to apply econ effects: %s", exc)

        else:
            # فاز نامعتبر: نبرد را ببند
            b.status = "resolved"
            b.resolved_at = now
            await session.commit()
            continue

        # ارسال یک خبر با عکس به کانال نظامی
        if settings.news_military_channel_id:
            await send_photo_news(bot, settings.news_military_channel_id, "military", news_text)
        else:
            await publish_news(bot, NewsCategory.MILITARY, news_text)

        # انتقال به فاز بعدی یا بسته‌شدن نبرد
        if phase < 5:
            b.current_phase = phase + 1
            b.next_phase_at = now + timedelta(minutes=1)
        else:
            # فاز ۵: نبرد تمام شد
            b.status = "resolved"
            b.resolved_at = now

            # اطلاع به طرفین نبرد
            for c in (attacker, defender):
                if c.owner_user_id:
                    try:
                        await bot.send_message(
                            c.owner_user_id,
                            f"🏁 **نتیجه نهایی نبرد بین {attacker.flag} {attacker.name_fa} و {defender.flag} {defender.name_fa}:**\n\n"
                            f"🏆 **نتیجه:** {b.outcome}\n"
                            "مشروح اخبار عکس‌دار نبرد در کانال رسمی اخبار نظامی منتشر شد.",
                        )
                    except Exception:
                        pass

        # commit بعد از هر فاز تا تغییرات ذخیره شود و دفعه بعد تکرار نشود
        await session.commit()

