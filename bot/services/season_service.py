"""
سرویس مدیریت فصل بازی: ریست کامل به حالت اولیه برای شروع فصل جدید.

با ریست فصل:
- شاخص‌های اقتصادی، رضایت و ثبات هر کشور به مقدار اولیه‌ی countries.json برمی‌گردد.
- ذخایر به مقدار اولیه و بازدهی طبیعی ۷۲ ساعته بازنشانی می‌شود.
- تجهیزات نظامی (که با تلفات کم شده) به تعداد اولیه برمی‌گردد.
- همه‌ی تأسیسات، قراردادها، تماس‌ها، دیدارها، تحریم‌ها، حملات، فروش‌ها و کول‌داون‌ها پاک می‌شوند.
- مالکیت همه‌ی کشورها آزاد می‌شود و درخواست‌های کشورگیری پاک می‌گردد.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import DEFAULT_RESERVE_YIELD_HOURS
from ..database.models import (
    Attack,
    ClaimRequest,
    Contract,
    Cooldown,
    Country,
    Facility,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    MilitaryAsset,
    PhoneCall,
    PhoneCallMessage,
    Reserve,
    ResourceSale,
    Sanction,
)
from ..database.repositories import countries as countries_repo

# مسیر فایل داده‌ی اولیه‌ی کشورها
DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "countries.json"

# بازدهی طبیعی پیش‌فرض هر منبع (هماهنگ با scripts/seed.py)
_DEFAULT_BASE_YIELD: dict[str, float] = {
    "coal": 10_000,
    "aluminum": 5_000,
    "iron": 8_000,
    "steel": 0,
    "oil": 0.3,
    "gas": 6,
    "gold": 50,
}


def _load_seed() -> dict[str, dict]:
    """داده‌ی اولیه‌ی کشورها را از countries.json می‌خواند و بر اساس نام انگلیسی نگاشت می‌کند."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {entry["name_en"]: entry for entry in data["countries"]}


async def reset_season(session: AsyncSession) -> dict[str, int]:
    """
    ریست کامل فصل. تعداد موارد بازنشانی‌شده را برمی‌گرداند (برای گزارش به مالک).
    """
    seed = _load_seed()
    now = datetime.now(timezone.utc)
    yield_until = now + timedelta(hours=DEFAULT_RESERVE_YIELD_HOURS)

    # --- ۱) پاک کردن همه‌ی جدول‌های وضعیت/تراکنش فصل ---
    # (ترتیب مهم است: جدول‌های وابسته اول)
    await session.execute(delete(PhoneCallMessage))
    await session.execute(delete(PhoneCall))
    await session.execute(delete(GroupMeetingParticipant))
    await session.execute(delete(GroupMeeting))
    await session.execute(delete(Meeting))
    await session.execute(delete(Contract))
    await session.execute(delete(Sanction))
    await session.execute(delete(ResourceSale))
    await session.execute(delete(Attack))
    await session.execute(delete(Facility))
    await session.execute(delete(Cooldown))
    await session.execute(delete(ClaimRequest))

    # --- ۲) آزادسازی مالکیت همه‌ی کشورها ---
    await session.execute(
        update(Country).values(owner_user_id=None, is_claimed=False)
    )

    # --- ۳) بازگرداندن داده‌ی هر کشور به حالت اولیه ---
    countries = await countries_repo.list_countries(session)
    reset_count = 0
    for country in countries:
        entry = seed.get(country.name_en)
        if entry is None:
            continue
        econ = entry.get("economy", {})

        # شاخص‌های اقتصادی و سیاست داخلی
        country.economic_power = econ.get("economic_power", 50.0)
        country.budget = econ.get("budget", 0.0)
        country.growth = econ.get("growth", "flat")
        country.inflation = econ.get("inflation", 0.0)
        country.unemployment = econ.get("unemployment", 0.0)
        country.energy_status = econ.get("energy_status", "medium")
        country.foreign_trade = econ.get("foreign_trade", "balanced")
        country.govt_debt = econ.get("govt_debt", 0.0)
        country.public_satisfaction = econ.get("public_satisfaction", 60.0)
        country.stability = econ.get("stability", 60.0)

        # بازنشانی ذخایر این کشور (حذف و درج دوباره از روی داده‌ی اولیه)
        await session.execute(
            delete(Reserve).where(Reserve.country_id == country.id)
        )
        for res_key, res_val in entry.get("reserves", {}).items():
            can_extract = res_val.get("can_extract", False)
            session.add(
                Reserve(
                    country_id=country.id,
                    resource=res_key,
                    amount=res_val.get("amount", 0.0),
                    can_extract=can_extract,
                    base_yield=_DEFAULT_BASE_YIELD.get(res_key, 0.0) if can_extract else 0.0,
                    yield_until=yield_until if can_extract else None,
                )
            )

        # بازنشانی تجهیزات نظامی این کشور (جبران تلفات فصل)
        await session.execute(
            delete(MilitaryAsset).where(MilitaryAsset.country_id == country.id)
        )
        for asset in entry.get("military", []):
            session.add(
                MilitaryAsset(
                    country_id=country.id,
                    branch=asset.get("branch", ""),
                    category=asset.get("category", ""),
                    name=asset["name"],
                    unit=asset.get("unit", "عدد"),
                    count=asset.get("count", 0),
                )
            )

        reset_count += 1

    await session.commit()
    return {"countries_reset": reset_count}
