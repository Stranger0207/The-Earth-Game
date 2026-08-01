"""
سرویس رهگیری محموله (v1.10.6).

کشور می‌تواند محموله‌هایی را که از خاک یا آب قلمروش عبور می‌کنند رهگیری کند.
مسیر عبور با لایه‌ی جغرافیا (`geo_service.route_crosses`) تعیین می‌شود — یعنی
نمی‌توان محموله‌ای را که هیچ ربطی به قلمرو ما ندارد رهگیری کرد.

نتیجه‌ی موفق: مصادره‌ی محموله (منابع به رهگیرنده می‌رسد) یا نابودی آن.
در هر دو حالت بحران دیپلماتیک با فروشنده و خریدار ایجاد می‌شود.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    INTERCEPTION_BASE_SUCCESS_PCT,
    INTERCEPTION_DIPLOMATIC_HIT,
    INTERCEPTION_FAIL_SATISFACTION_HIT,
    INTERCEPTION_SEIZE_PCT,
)
from ..database.models import Country, ResourceSale
from ..database.repositories import countries as countries_repo
from ..database.repositories import reserves as reserves_repo
from ..database.repositories import trade as trade_repo
from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType, TradeStatus
from . import geo_service as geo
from . import patrol_service

logger = logging.getLogger(__name__)


class InterceptionError(Exception):
    """خطای قابل‌نمایش به بازیکن."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def interceptable_shipments(
    session: AsyncSession, country: Country
) -> list[dict]:
    """
    محموله‌های در حال حرکتی که مسیرشان از قلمرو این کشور می‌گذرد.

    خروجی: [{"sale_id","seller","buyer","resource_fa","amount","unit"}]
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
        })

    return result


async def resolve_interception(
    session: AsyncSession,
    interceptor: Country,
    sale: ResourceSale,
    *,
    seed: int | None = None,
) -> dict:
    """
    اجرای رهگیری یک محموله و اعمال نتیجه.

    خروجی dict شامل:
        success, seized, resource_fa, amount, unit, seller, buyer, effect_note
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

    result = {
        "success": False,
        "seized": False,
        "resource_fa": resource_fa,
        "amount": sale.amount,
        "unit": unit,
        "seller": f"{seller.flag} {seller.name_fa}",
        "buyer": f"{buyer.flag} {buyer.name_fa}",
        "effect_note": "",
    }

    # ---------- شانس موفقیت ----------
    chance = INTERCEPTION_BASE_SUCCESS_PCT
    chance += await patrol_service.intercept_bonus(session, interceptor.id)
    # گشت دریایی خریدار می‌تواند از محموله محافظت کند
    guarded = await patrol_service.intercept_bonus(session, buyer.id)
    chance = max(5.0, min(90.0, chance - guarded))

    if rng.uniform(0.0, 100.0) > chance:
        # شکست: محموله سالم می‌رسد و رهگیرنده هزینه می‌دهد
        interceptor.public_satisfaction = max(
            0.0, (interceptor.public_satisfaction or 0.0) + INTERCEPTION_FAIL_SATISFACTION_HIT
        )
        result["effect_note"] = (
            "❌ عملیات رهگیری ناکام ماند و محموله مسیر خود را ادامه داد."
        )
        await session.flush()
        return result

    # ---------- موفقیت ----------
    result["success"] = True
    sale.status = TradeStatus.REJECTED  # محموله به مقصد نمی‌رسد

    seize = rng.uniform(0.0, 100.0) <= INTERCEPTION_SEIZE_PCT
    result["seized"] = seize

    if seize and rtype is not None:
        # مصادره: منابع به ذخایر رهگیرنده اضافه می‌شود
        await reserves_repo.ensure_reserve(session, interceptor.id, sale.resource)
        await reserves_repo.add_amount(session, interceptor.id, rtype, sale.amount)
        result["effect_note"] = (
            f"📦 محموله مصادره شد و {sale.amount:,.0f} {unit} {resource_fa} "
            "به ذخایر کشور شما افزوده گردید."
        )
    else:
        result["effect_note"] = "💥 محموله در مسیر نابود شد و به دست هیچ‌کس نرسید."

    # ---------- هزینه‌ی دیپلماتیک ----------
    interceptor.public_satisfaction = max(
        0.0, (interceptor.public_satisfaction or 0.0) + INTERCEPTION_DIPLOMATIC_HIT
    )
    for side in (seller, buyer):
        side.public_satisfaction = max(0.0, (side.public_satisfaction or 0.0) - 2.0)
        side.stability = max(0.0, (side.stability or 0.0) - 1.0)

    await session.flush()
    return result
