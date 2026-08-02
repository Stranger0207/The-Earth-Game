"""
سرویس اسکورت محموله (v1.10.7).

فروشنده می‌تواند همراه محموله نیروی محافظ بفرستد. محموله‌ی اسکورت‌دار
فقط با نیروی به‌مراتب قوی‌تر قابل رهگیری است.

معامله‌ی راهبردی برای بازیکن: اسکورت سوخت و ریسک تلفات دارد، ولی محموله‌ی
گران‌قیمت را از دست‌درازی کشورهای مسیر حفظ می‌کند.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ESCORT_ALLOWED_BRANCHES,
    ESCORT_FUEL_PER_UNIT,
    ESCORT_MAX_UNITS,
)
from ..database.models import Country
from ..database.repositories import military as mil_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import ResourceType
from .combat.power import CommittedAsset, strike_power

logger = logging.getLogger(__name__)


class EscortError(Exception):
    """خطای قابل‌نمایش به بازیکن هنگام تخصیص اسکورت."""


async def available_escort_assets(
    session: AsyncSession, country_id: int
) -> list[dict]:
    """تجهیزاتی که می‌توانند نقش اسکورت بگیرند (دریایی/هوایی/پدافندی)."""
    assets = await mil_repo.list_assets(session, country_id)
    return [
        {
            "name": a.name,
            "count": a.count,
            "unit": a.unit,
            "category": a.category,
            "branch": a.branch,
        }
        for a in assets
        if a.count > 0 and a.branch in ESCORT_ALLOWED_BRANCHES
    ]


def compute_escort_power(assets: list[dict]) -> float:
    """
    قدرت اسکورت را از تجهیزات محاسبه می‌کند.

    از همان موتور قدرت نبرد استفاده می‌شود تا اعداد با بقیه‌ی بازی سازگار باشد.
    """
    committed = [
        CommittedAsset(
            name=a.get("name", ""),
            count=int(a.get("count", 0) or 0),
            branch=a.get("branch", ""),
            category=a.get("category", ""),
            unit=a.get("unit", "عدد"),
        )
        for a in assets
    ]
    return round(strike_power(committed).total, 2)


def escort_fuel_cost(assets: list[dict]) -> float:
    """سوخت لازم برای همراهی اسکورت (میلیون بشکه)."""
    units = sum(int(a.get("count", 0) or 0) for a in assets)
    return round(units * ESCORT_FUEL_PER_UNIT, 2)


async def validate_escort(
    session: AsyncSession, country: Country, assets: list[dict]
) -> tuple[float, float]:
    """
    بررسی اعتبار اسکورت انتخابی و برگرداندن (قدرت، سوخت لازم).

    در صورت مشکل، EscortError با پیام فارسی پرتاب می‌شود.
    """
    if not assets:
        return 0.0, 0.0

    total_units = sum(int(a.get("count", 0) or 0) for a in assets)
    if total_units > ESCORT_MAX_UNITS:
        raise EscortError(
            f"⚠️ حداکثر {ESCORT_MAX_UNITS} واحد می‌توانید به‌عنوان اسکورت اختصاص دهید "
            f"(انتخاب فعلی: {total_units})."
        )

    # بررسی موجودی واقعی
    for item in assets:
        asset = await mil_repo.get_asset_by_name(session, country.id, item.get("name", ""))
        needed = int(item.get("count", 0) or 0)
        if asset is None or asset.count < needed:
            available = asset.count if asset else 0
            raise EscortError(
                f"موجودی «{item.get('name')}» کافی نیست (موجودی: {available})."
            )

    fuel = escort_fuel_cost(assets)
    if fuel > 0 and not await reserves_repo.has_enough(
        session, country.id, ResourceType.OIL, fuel
    ):
        raise EscortError(
            f"⛽️ سوخت کافی برای اسکورت ندارید. نیاز: {fuel} میلیون بشکه."
        )

    return compute_escort_power(assets), fuel


async def attach_escort(
    session: AsyncSession, country: Country, sale, assets: list[dict]
) -> float:
    """
    اسکورت را به یک محموله می‌چسباند و سوخت را کسر می‌کند.

    `sale` می‌تواند `ResourceSale` یا `MilitarySale` باشد (هر دو ستون‌های
    `escort_power` و `escort_json` دارند).

    خروجی: قدرت اسکورت.
    """
    if not assets:
        sale.escort_power = 0.0
        sale.escort_json = "[]"
        return 0.0

    power, fuel = await validate_escort(session, country, assets)

    if fuel > 0:
        await reserves_repo.add_amount(session, country.id, ResourceType.OIL, -fuel)

    sale.escort_power = power
    sale.escort_json = json.dumps(assets, ensure_ascii=False)
    await session.flush()
    return power


def describe_escort(sale) -> str:
    """توصیف فارسی اسکورت یک محموله (برای نمایش در پنل و خبر)."""
    power = float(getattr(sale, "escort_power", 0.0) or 0.0)
    if power <= 0:
        return "بدون اسکورت"

    try:
        items = json.loads(getattr(sale, "escort_json", "") or "[]")
    except (ValueError, TypeError):
        items = []

    names = "، ".join(
        f"{i.get('name')} ({i.get('count')})" for i in items[:3]
    )
    return f"{names} — قدرت {power:,.0f}" if names else f"قدرت {power:,.0f}"
