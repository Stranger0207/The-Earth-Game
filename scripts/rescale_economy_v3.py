"""
اسکریپت کمکی مهاجرت و همگام‌سازی اقتصاد و ذخایر به مقیاس جدید (v3.0).

این اسکریپت بودجه‌ها، بدهی‌ها، دسترسی به استخراج (can_extract) و ذخایر آلومینیوم، آهن و فولاد
را از روی `data/countries.json` در دیتابیس فعلی به‌روزرسانی می‌کند بدون نیاز به ریست کامل فصل.

اجرا:
    python -m scripts.rescale_economy_v3
    یا با حالت پیش‌نمایش:
    python -m scripts.rescale_economy_v3 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select  # noqa: E402

from bot.constants import DEFAULT_BASE_YIELD  # noqa: E402
from bot.database.base import async_session_factory, init_db  # noqa: E402
from bot.database.models import Country, Reserve  # noqa: E402
from bot.database.repositories import countries as countries_repo  # noqa: E402

DATA_FILE = ROOT / "data" / "countries.json"


def _load_json() -> dict:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"فایل داده در مسیر {DATA_FILE} یافت نشد.")
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


async def rescale_database(dry_run: bool = False, force_reserves: bool = False) -> None:
    data = _load_json()
    countries_map = {c["name_en"]: c for c in data.get("countries", [])}

    print(f"🔄 بارگذاری داده‌های {len(countries_map)} کشور از countries.json...")
    if dry_run:
        print("🔍 حالت پیش‌نمایش (Dry Run) فعال است. هیچ تغییری در دیتابیس ذخیره نخواهد شد.\n")

    async with async_session_factory() as session:
        db_countries = await countries_repo.list_countries(session)
        if not db_countries:
            print("⚠️ هیچ کشوری در دیتابیس یافت نشد.")
            return

        updated_countries_count = 0
        updated_reserves_count = 0

        for country in db_countries:
            entry = countries_map.get(country.name_en)
            if not entry:
                continue

            econ = entry.get("economy", {})
            new_budget = econ.get("budget", country.budget)
            new_debt = econ.get("govt_debt", country.govt_debt)

            budget_changed = abs((country.budget or 0.0) - new_budget) > 1.0
            debt_changed = abs((country.govt_debt or 0.0) - new_debt) > 1.0

            if budget_changed or debt_changed:
                print(
                    f"🏳️ {country.name_fa} ({country.name_en}): "
                    f"بودجه {country.budget:,.0f} -> {new_budget:,.0f} | "
                    f"بدهی {country.govt_debt:,.0f} -> {new_debt:,.0f}"
                )
                if not dry_run:
                    country.budget = new_budget
                    country.govt_debt = new_debt
                updated_countries_count += 1

            # بررسی و به‌روزرسانی ذخایر کشور
            res_result = await session.execute(
                select(Reserve).where(Reserve.country_id == country.id)
            )
            existing_reserves = {r.resource: r for r in res_result.scalars().all()}

            for res_key, res_data in entry.get("reserves", {}).items():
                target_amount = float(res_data.get("amount", 0.0))
                can_extract = bool(res_data.get("can_extract", False))
                target_base_yield = DEFAULT_BASE_YIELD.get(res_key, 0.0) if can_extract else 0.0

                reserve = existing_reserves.get(res_key)
                if reserve:
                    amount_to_set = target_amount if force_reserves else max(reserve.amount or 0.0, target_amount)
                    diff = (
                        abs((reserve.amount or 0.0) - amount_to_set) > 1.0
                        or reserve.can_extract != can_extract
                        or abs((reserve.base_yield or 0.0) - target_base_yield) > 0.1
                    )
                    if diff:
                        if not dry_run:
                            reserve.amount = amount_to_set
                            reserve.can_extract = can_extract
                            reserve.base_yield = target_base_yield
                        updated_reserves_count += 1
                else:
                    if not dry_run:
                        session.add(
                            Reserve(
                                country_id=country.id,
                                resource=res_key,
                                amount=target_amount,
                                can_extract=can_extract,
                                base_yield=target_base_yield,
                            )
                        )
                    updated_reserves_count += 1

        if not dry_run:
            await session.commit()
            print("\n💾 تغییرات با موفقیت در دیتابیس ثبت شدند.")
        else:
            print("\n🔎 پایان شبیه‌سازی پیش‌نمایش.")

        print(
            f"📊 خلاصه: {updated_countries_count} کشور به‌روز شدند | "
            f"{updated_reserves_count} ردیف ذخایر همگام‌سازی شدند."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="همگام‌سازی اقتصاد و ذخایر دیتابیس با countries.json")
    parser.add_argument("--dry-run", action="store_true", help="فقط تغییرات را نمایش بده بدون ذخیره")
    parser.add_argument("--force-reserves", action="store_true", help="تنظیم اجباری مقادیر ذخایر دقیقا مطابق فایل JSON")
    args = parser.parse_args()

    await init_db()
    await rescale_database(dry_run=args.dry_run, force_reserves=args.force_reserves)


if __name__ == "__main__":
    asyncio.run(main())
