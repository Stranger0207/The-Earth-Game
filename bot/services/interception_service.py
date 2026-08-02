"""
سرویس رهگیری محموله (v1.10.7) — با مکانیک اسکورت.

کشور می‌تواند محموله‌هایی را که از خاک یا آب قلمروش عبور می‌کنند رهگیری کند.
مسیر عبور با لایه‌ی جغرافیا (`geo_service.route_crosses`) تعیین می‌شود.

**مکانیک اسکورت (v1.10.7):**
- محموله‌ی بدون اسکورت: رهگیری با شانس بالا (۷۵٪) و بدون تلفات
- محموله‌ی اسکورت‌دار: باید نیروی رهگیر **۳۵٪ قوی‌تر** از اسکورت باشد،
  وگرنه اسکورت آن را دفع می‌کند و رهگیر تلفات سنگین می‌دهد.

**تخلیه‌ی پدافند (v1.11.2):** سامانه‌های شاخه‌ی «سامانه‌های دفاعی» که برای
رهگیری اعزام می‌شوند یک‌بارمصرف‌اند — کل تعداد اعزامی از موجودی حذف می‌شود،
چه رهگیری موفق شود و چه دفع. جنگنده و ناوچه فقط تلفات معمول می‌دهند.

نتیجه‌ی موفق: مصادره یا نابودی محموله + بحران دیپلماتیک با هر دو طرف.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ESCORT_BREAK_RATIO,
    ESCORT_LOSS_PCT,
    INTERCEPTION_DIPLOMATIC_HIT,
    INTERCEPTION_FAIL_SATISFACTION_HIT,
    INTERCEPTION_SEIZE_PCT,
    INTERCEPTION_UNESCORTED_SUCCESS_PCT,
    INTERCEPTOR_DEPLETED_BRANCHES,
    INTERCEPTOR_LOSS_PCT,
    INTERCEPTOR_REPULSED_LOSS_PCT,
)
from ..database.models import Country, ResourceSale
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import trade as trade_repo
from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType, TradeStatus
from . import geo_service as geo
from . import patrol_service
from .combat.power import CommittedAsset, strike_power

logger = logging.getLogger(__name__)


class InterceptionError(Exception):
    """خطای قابل‌نمایش به بازیکن."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_escort(sale: ResourceSale) -> list[dict]:
    """تجهیزات اسکورت یک محموله را از JSON بازمی‌خواند."""
    try:
        return json.loads(getattr(sale, "escort_json", "") or "[]")
    except (ValueError, TypeError):
        return []


def escort_label(escort_power: float) -> str:
    """برچسب فارسی قدرت اسکورت (برای نمایش به بازیکن)."""
    if escort_power <= 0:
        return "🟢 بدون اسکورت"
    if escort_power < 60:
        return "🟡 اسکورت سبک"
    if escort_power < 200:
        return "🟠 اسکورت متوسط"
    return "🔴 اسکورت سنگین"


def required_power(escort_power: float) -> float:
    """حداقل قدرتی که برای شکستن اسکورت لازم است."""
    if escort_power <= 0:
        return 0.0
    return escort_power * ESCORT_BREAK_RATIO


async def interceptable_shipments(
    session: AsyncSession, country: Country
) -> list[dict]:
    """
    محموله‌های در حال حرکتی که مسیرشان از قلمرو این کشور می‌گذرد.

    خروجی هر آیتم شامل وضعیت اسکورت است تا بازیکن پیش از اقدام بداند
    چه نیرویی لازم دارد.
    """
    sales = await trade_repo.list_in_transit(session)
    result: list[dict] = []

    for sale in sales:
        # محموله‌ی خودِ کشور (فروشنده یا خریدار) قابل رهگیری نیست
        if country.id in (sale.seller_country, sale.buyer_country):
            continue

        seller = await countries_repo.get_country(session, sale.seller_country)
        buyer = await countries_repo.get_country(session, sale.buyer_country)
        if seller is None or buyer is None:
            continue

        # شرط کلیدی: مسیر باید از قلمرو ما بگذرد
        if not geo.is_on_route(country.name_en, seller.name_en, buyer.name_en):
            continue

        try:
            rtype = ResourceType(sale.resource)
            resource_fa = RESOURCE_FA[rtype]
            unit = RESOURCE_UNIT_FA[rtype]
        except (ValueError, KeyError):
            resource_fa, unit = sale.resource, ""

        escort_power = float(getattr(sale, "escort_power", 0.0) or 0.0)
        escort_items = parse_escort(sale)

        result.append({
            "sale_id": sale.id,
            "seller": f"{seller.flag} {seller.name_fa}",
            "buyer": f"{buyer.flag} {buyer.name_fa}",
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "resource_fa": resource_fa,
            "resource": sale.resource,
            "amount": sale.amount,
            "unit": unit,
            "escort_power": escort_power,
            "escort_label": escort_label(escort_power),
            "escort_items": escort_items,
            "required_power": required_power(escort_power),
        })

    return result


def _distribute(
    assets: list[CommittedAsset], loss_ratio: float, rng: random.Random
) -> list[dict]:
    """
    پخش تلفات میان اقلام درگیر با نوسان تصادفی مستقل برای هر قلم.
    (همان الگوی موتور نبرد، تا نتیجه یکنواخت به‌نظر نرسد.)
    """
    losses: list[dict] = []
    if loss_ratio <= 0:
        return losses

    for asset in assets:
        if asset.count <= 0:
            continue
        lost = asset.count * loss_ratio * rng.uniform(0.85, 1.15)
        whole = int(lost)
        if rng.random() < (lost - whole):
            whole += 1
        whole = min(whole, asset.count)
        if whole > 0:
            losses.append({
                "name": asset.name,
                "count": whole,
                "unit": asset.unit,
                "category": asset.category,
            })
    return losses


async def _apply_losses(
    session: AsyncSession, country_id: int, losses: list[dict]
) -> None:
    """کسر تلفات از موجودی واقعی یک کشور."""
    for item in losses:
        try:
            await mil_repo.reduce_count(
                session, country_id, item.get("name", ""), int(item.get("count", 0))
            )
        except Exception as exc:  # noqa: BLE001 — یک قلم خراب نباید کل عملیات را بشکند
            logger.warning("Failed to apply interception loss: %s", exc)


def split_depleted(
    committed: list[CommittedAsset],
) -> tuple[list[CommittedAsset], list[CommittedAsset]]:
    """
    نیروی رهگیر را به دو گروه می‌شکند (v1.11.2):

    - **تخلیه‌شونده:** سامانه‌های پدافندی که پس از شلیک از بین می‌روند و کل
      تعداد اعزامی‌شان از موجودی حذف می‌شود.
    - **بازگشتی:** جنگنده و شناور که فقط سهم تلفات را می‌دهند.
    """
    depleted = [a for a in committed if a.branch in INTERCEPTOR_DEPLETED_BRANCHES]
    reusable = [a for a in committed if a.branch not in INTERCEPTOR_DEPLETED_BRANCHES]
    return depleted, reusable


def _as_items(assets: list[CommittedAsset]) -> list[dict]:
    """تبدیل تجهیزات اعزامی به فهرست خوانا (برای گزارش و کسر موجودی)."""
    return [
        {
            "name": a.name,
            "count": a.count,
            "unit": a.unit,
            "category": a.category,
        }
        for a in assets
        if a.count > 0
    ]


def _depletion_note(result: dict) -> str:
    """جملات هشدار تخلیه‌ی پدافند برای متن نتیجه (v1.11.2)."""
    if not result.get("depleted"):
        return ""
    return (
        "\n🎯 سامانه‌های پدافندی به‌کاررفته تخلیه شدند و از موجودی خارج گردیدند."
    )


async def _charge_interceptor(
    session: AsyncSession,
    interceptor_id: int,
    committed: list[CommittedAsset],
    loss_pct: float,
    rng: random.Random,
    result: dict,
) -> None:
    """
    هزینه‌ی نیروی رهگیر را اعمال می‌کند (v1.11.2).

    پدافندهای اعزامی کامل تخلیه می‌شوند و بقیه‌ی نیرو سهم تلفات را می‌دهد.
    هر دو گروه در نتیجه ثبت می‌شوند تا در گزارش بازیکن تفکیک شوند.
    """
    depleted, reusable = split_depleted(committed)

    losses = _distribute(reusable, loss_pct / 100.0, rng)
    depleted_items = _as_items(depleted)

    result["interceptor_losses"] = losses
    result["depleted"] = depleted_items

    await _apply_losses(session, interceptor_id, losses + depleted_items)


async def resolve_interception(
    session: AsyncSession,
    interceptor: Country,
    sale: ResourceSale,
    *,
    committed: list[CommittedAsset] | None = None,
    seed: int | None = None,
) -> dict:
    """
    اجرای رهگیری یک محموله و اعمال نتیجه.

    `committed`: نیروی رهگیر. برای محموله‌ی **اسکورت‌دار** الزامی است؛
    برای محموله‌ی بی‌محافظ اختیاری (گشت کفایت می‌کند).

    خروجی dict شامل:
        success, seized, repulsed, escort_power, attack_power,
        interceptor_losses, escort_losses, effect_note
    """
    rng = random.Random(seed)

    if sale.status != TradeStatus.IN_TRANSIT:
        raise InterceptionError("این محموله دیگر در مسیر نیست.")

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)
    if seller is None or buyer is None:
        raise InterceptionError("اطلاعات طرفین محموله یافت نشد.")

    if not geo.is_on_route(interceptor.name_en, seller.name_en, buyer.name_en):
        raise InterceptionError(
            "مسیر این محموله از قلمرو شما نمی‌گذرد؛ رهگیری آن ممکن نیست."
        )

    try:
        rtype = ResourceType(sale.resource)
        resource_fa = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
    except (ValueError, KeyError):
        rtype, resource_fa, unit = None, sale.resource, ""

    escort_power = float(getattr(sale, "escort_power", 0.0) or 0.0)
    committed = committed or []
    attack_power = strike_power(committed).total if committed else 0.0

    result = {
        "success": False,
        "seized": False,
        "repulsed": False,
        "resource_fa": resource_fa,
        "amount": sale.amount,
        "unit": unit,
        "seller": f"{seller.flag} {seller.name_fa}",
        "buyer": f"{buyer.flag} {buyer.name_fa}",
        "escort_power": escort_power,
        "attack_power": attack_power,
        "interceptor_losses": [],
        "escort_losses": [],
        "depleted": [],  # (v1.11.2) پدافندهای تخلیه‌شده
        "effect_note": "",
    }

    # ============================================================
    #  مسیر ۱: محموله‌ی بدون اسکورت — رهگیری آسان
    # ============================================================
    if escort_power <= 0:
        chance = INTERCEPTION_UNESCORTED_SUCCESS_PCT
        chance += await patrol_service.intercept_bonus(session, interceptor.id)
        # گشت دریایی خریدار کمی از محموله محافظت می‌کند
        chance -= await patrol_service.intercept_bonus(session, buyer.id)
        chance = max(15.0, min(95.0, chance))

        if rng.uniform(0.0, 100.0) > chance:
            interceptor.public_satisfaction = max(
                0.0,
                (interceptor.public_satisfaction or 0.0) + INTERCEPTION_FAIL_SATISFACTION_HIT,
            )
            # پدافندهای اعزامی حتی در صورت شکست هم تخلیه شده‌اند
            if committed:
                await _charge_interceptor(
                    session, interceptor.id, committed, 0.0, rng, result
                )
            result["effect_note"] = (
                "❌ محموله از چنگ نیروهای شما گریخت و مسیر خود را ادامه داد."
                + _depletion_note(result)
            )
            await session.flush()
            return result

        result["success"] = True
        if committed:
            await _charge_interceptor(
                session, interceptor.id, committed, 0.0, rng, result
            )

    # ============================================================
    #  مسیر ۲: محموله‌ی اسکورت‌دار — نبرد واقعی
    # ============================================================
    else:
        if not committed:
            raise InterceptionError(
                f"🛡 این محموله <b>{escort_label(escort_power)}</b> دارد "
                f"(قدرت {escort_power:,.0f}).\n\n"
                "برای رهگیری آن باید نیروی نظامی اعزام کنید — "
                f"حداقل قدرت لازم: <b>{required_power(escort_power):,.0f}</b>"
            )

        needed = required_power(escort_power)
        # بونوس گشت به‌صورت ضریب قدرت اعمال می‌شود
        patrol_boost = 1.0 + await patrol_service.intercept_bonus(session, interceptor.id) / 100.0
        effective_attack = attack_power * patrol_boost * rng.uniform(0.9, 1.1)
        result["attack_power"] = round(effective_attack, 1)

        if effective_attack < needed:
            # ---------- اسکورت حمله را دفع کرد ----------
            result["repulsed"] = True
            await _charge_interceptor(
                session, interceptor.id, committed, INTERCEPTOR_REPULSED_LOSS_PCT, rng, result
            )

            interceptor.public_satisfaction = max(
                0.0,
                (interceptor.public_satisfaction or 0.0) + INTERCEPTION_FAIL_SATISFACTION_HIT * 2,
            )
            interceptor.stability = max(0.0, (interceptor.stability or 0.0) - 2.0)
            result["effect_note"] = (
                f"🛡 اسکورت محموله (قدرت {escort_power:,.0f}) حمله را دفع کرد.\n"
                f"نیروی شما با قدرت {effective_attack:,.0f} برای شکستن آن کافی نبود "
                f"(حداقل لازم: {needed:,.0f}).\n"
                "نیروهای رهگیر تلفات سنگینی دادند."
                + _depletion_note(result)
            )
            await session.flush()
            return result

        # ---------- اسکورت شکسته شد ----------
        result["success"] = True
        await _charge_interceptor(
            session, interceptor.id, committed, INTERCEPTOR_LOSS_PCT, rng, result
        )

        escort_items = [CommittedAsset.from_dict(i) for i in parse_escort(sale)]
        result["escort_losses"] = _distribute(escort_items, ESCORT_LOSS_PCT / 100.0, rng)
        await _apply_losses(session, seller.id, result["escort_losses"])

    # ============================================================
    #  نتیجه‌ی موفقیت (هر دو مسیر)
    # ============================================================
    sale.status = TradeStatus.REJECTED  # محموله به مقصد نمی‌رسد

    seize = rng.uniform(0.0, 100.0) <= INTERCEPTION_SEIZE_PCT
    result["seized"] = seize

    if seize and rtype is not None:
        await reserves_repo.ensure_reserve(session, interceptor.id, sale.resource)
        await reserves_repo.add_amount(session, interceptor.id, rtype, sale.amount)
        result["effect_note"] = (
            f"📦 محموله مصادره شد و {sale.amount:,.0f} {unit} {resource_fa} "
            "به ذخایر کشور شما افزوده گردید."
        )
    else:
        result["effect_note"] = "💥 محموله در مسیر نابود شد و به دست هیچ‌کس نرسید."

    if result["escort_losses"]:
        result["effect_note"] += "\n🛡 اسکورت محموله در نبرد تلفات داد."

    result["effect_note"] += _depletion_note(result)

    # ---------- هزینه‌ی دیپلماتیک ----------
    interceptor.public_satisfaction = max(
        0.0, (interceptor.public_satisfaction or 0.0) + INTERCEPTION_DIPLOMATIC_HIT
    )
    for side in (seller, buyer):
        side.public_satisfaction = max(0.0, (side.public_satisfaction or 0.0) - 2.0)
        side.stability = max(0.0, (side.stability or 0.0) - 1.0)

    await session.flush()
    return result
