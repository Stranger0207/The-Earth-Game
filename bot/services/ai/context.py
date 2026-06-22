"""
ساخت context برای هوش مصنوعی.
داده‌ی کشور از دیتابیس خوانده شده و به JSON/متن تبدیل می‌شود تا به‌عنوان زمینه به Groq داده شود.
(این همان مرحله‌ی «تبدیل دیتای کاربر به json/txt و ارسال به مدل» است.)
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from ...database.repositories import countries as countries_repo
from ...enums import RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType


async def build_country_context(
    session: AsyncSession, country_id: int
) -> dict:
    """
    داده‌ی کامل یک کشور را به‌صورت یک دیکشنری ساختاریافته برمی‌گرداند.
    شامل اقتصاد، ذخایر، تأسیسات، تجهیزات نظامی و سیاست داخلی.
    """
    country = await countries_repo.get_country_with_relations(session, country_id)
    if country is None:
        return {}

    president = country.owner.president_name if country.owner else None

    # --- ذخایر ---
    reserves = []
    for res in country.reserves:
        try:
            unit = RESOURCE_UNIT_FA[ResourceType(res.resource)]
            name_fa = RESOURCE_FA[ResourceType(res.resource)]
        except (ValueError, KeyError):
            unit, name_fa = "", res.resource
        reserves.append(
            {
                "resource": res.resource,
                "name_fa": name_fa,
                "amount": res.amount,
                "unit": unit,
                "can_extract": res.can_extract,
            }
        )

    # --- تأسیسات ---
    facilities = [
        {
            "type": f.type,
            "resource": f.resource,
            "location": f.location,
            "yield_amount": f.yield_amount,
            "yield_interval_h": f.yield_interval_h,
        }
        for f in country.facilities
    ]

    # --- تجهیزات نظامی ---
    military = [
        {
            "branch": a.branch,
            "category": a.category,
            "name": a.name,
            "count": a.count,
            "unit": a.unit,
        }
        for a in country.military_assets
    ]

    return {
        "country": {
            "name_fa": country.name_fa,
            "name_en": country.name_en,
            "region": country.region,
            "is_vip": country.is_vip,
            "population": country.population,
            "president_name": president,
        },
        "economy": {
            "economic_power": country.economic_power,
            "budget_usd": country.budget,
            "growth": country.growth,
            "inflation_pct": country.inflation,
            "unemployment_pct": country.unemployment,
            "energy_status": country.energy_status,
            "foreign_trade": country.foreign_trade,
            "govt_debt_usd": country.govt_debt,
        },
        "internal_politics": {
            "public_satisfaction": country.public_satisfaction,
            "stability": country.stability,
        },
        "reserves": reserves,
        "facilities": facilities,
        "military": military,
    }


async def build_country_context_text(
    session: AsyncSession, country_id: int
) -> str:
    """
    همان context ولی به‌صورت متن JSON قابل‌خواندن (برای پاس‌دادن مستقیم به مدل).
    """
    data = await build_country_context(session, country_id)
    return json.dumps(data, ensure_ascii=False, indent=2)
