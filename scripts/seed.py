"""
اسکریپت آماده‌سازی دیتابیس:
1) ساخت همه‌ی جدول‌ها
2) ریختن داده‌ی ۳۶ کشور از data/countries.json به دیتابیس

اجرا:
    python -m scripts.seed
یا:
    python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# اطمینان از خروجی UTF-8 در کنسول ویندوز (در غیر این صورت ایموجی‌ها خطا می‌دهند)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# اطمینان از در دسترس بودن پکیج bot هنگام اجرای مستقیم
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constants import DEFAULT_RESERVE_YIELD_HOURS  # noqa: E402
from bot.database.base import async_session_factory, init_db  # noqa: E402
from bot.database.models import Country, MilitaryAsset, Reserve  # noqa: E402
from bot.database.repositories import countries as countries_repo  # noqa: E402
from bot.enums import ResourceType  # noqa: E402

DATA_DIR = ROOT / "data"

# بازدهی طبیعی پیش‌فرض هر منبع در هر ۲۴ ساعت (پیش از ساخت معدن/سکو)
DEFAULT_BASE_YIELD: dict[str, float] = {
    ResourceType.COAL.value: 10_000,
    ResourceType.ALUMINUM.value: 5_000,
    ResourceType.IRON.value: 8_000,
    ResourceType.STEEL.value: 0,       # فولاد بازدهی طبیعی ندارد (نیازمند کارخانه)
    ResourceType.OIL.value: 0.3,       # میلیون بشکه
    ResourceType.GAS.value: 6,         # میلیون متر مکعب
    ResourceType.GOLD.value: 50,       # کیلوگرم
}


def _load_json(name: str) -> dict:
    """خواندن یک فایل JSON از پوشه‌ی data."""
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


async def seed_countries() -> None:
    """ریختن داده‌ی کشورها در دیتابیس (اگر از قبل وجود نداشته باشند)."""
    data = _load_json("countries.json")
    now = datetime.now(timezone.utc)
    yield_until = now + timedelta(hours=DEFAULT_RESERVE_YIELD_HOURS)

    async with async_session_factory() as session:
        created = 0
        for entry in data["countries"]:
            # رد کردن کشورهایی که قبلاً ساخته شده‌اند
            existing = await countries_repo.get_country_by_name(
                session, entry["name_en"]
            )
            if existing is not None:
                continue

            econ = entry.get("economy", {})
            country = Country(
                name_en=entry["name_en"],
                name_fa=entry["name_fa"],
                flag=entry.get("flag", ""),
                region=entry["region"],
                is_vip=entry.get("is_vip", False),
                population=entry.get("population", 0),
                economic_power=econ.get("economic_power", 50.0),
                budget=econ.get("budget", 0.0),
                growth=econ.get("growth", "flat"),
                inflation=econ.get("inflation", 0.0),
                unemployment=econ.get("unemployment", 0.0),
                energy_status=econ.get("energy_status", "medium"),
                foreign_trade=econ.get("foreign_trade", "balanced"),
                govt_debt=econ.get("govt_debt", 0.0),
                public_satisfaction=econ.get("public_satisfaction", 60.0),
                stability=econ.get("stability", 60.0),
            )
            session.add(country)
            await session.flush()  # برای گرفتن country.id

            # --- ذخایر ---
            for res_key, res_val in entry.get("reserves", {}).items():
                can_extract = res_val.get("can_extract", False)
                reserve = Reserve(
                    country_id=country.id,
                    resource=res_key,
                    amount=res_val.get("amount", 0.0),
                    can_extract=can_extract,
                    base_yield=DEFAULT_BASE_YIELD.get(res_key, 0.0) if can_extract else 0.0,
                    yield_until=yield_until if can_extract else None,
                )
                session.add(reserve)

            # --- تجهیزات نظامی ---
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

            created += 1

        await session.commit()
        print(f"✅ {created} کشور جدید ساخته شد (از مجموع {len(data['countries'])}).")


async def main() -> None:
    print("⏳ در حال ساخت جدول‌ها...")
    await init_db()
    print("✅ جدول‌ها ساخته شدند.")
    print("⏳ در حال ریختن داده‌ی کشورها...")
    await seed_countries()
    print("🎉 آماده‌سازی دیتابیس کامل شد.")


if __name__ == "__main__":
    asyncio.run(main())
