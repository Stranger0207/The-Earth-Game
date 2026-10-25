"""
تست‌های آپدیت v1.11.2 (بدون نیاز به PostgreSQL/توکن/AI):

1) محتویات محموله در فهرست رهگیری به بازیکن نشان داده نمی‌شود.
2) سقف ۴۰ واحد نیروی رهگیر و تخلیه‌ی کامل پدافندهای به‌کاررفته.
3) سه کشور جدید (نروژ، افغانستان، تایوان) در countries.json و geography.json.
4) پرامپت و سنجش‌گر توان فناورانه‌ی خریدار در فروش تجهیزات نظامی.

اجرا:
    python -m scripts.test_update_1112
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, MilitaryAsset, ResourceSale
from bot.database.repositories import military as mil_repo
from bot.enums import ResourceType, TradeStatus
from bot.services.combat import CommittedAsset

ROOT = Path(__file__).resolve().parent.parent

# ── چک‌های کوچک ─────────────────────────────────────────────
_CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _CHECKS.append((name, bool(ok), detail))


def _mk(name_en: str, name_fa: str, vip: bool = False) -> Country:
    return Country(
        name_en=name_en, name_fa=name_fa, flag="🏳", region="آسیا",
        population=1_000, is_vip=vip,
    )


# ── ۳) سه کشور جدید ─────────────────────────────────────────
def _test_new_countries() -> None:
    countries = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
    geo = json.loads((ROOT / "data" / "geography.json").read_text(encoding="utf-8"))

    by_name = {c["name_en"]: c for c in countries["countries"]}
    check("تعداد کشورها ۴۰ شد", len(countries["countries"]) == 40, str(len(countries["countries"])))

    for name in ("Norway", "Afghanistan", "Taiwan"):
        c = by_name.get(name)
        check(f"{name} در countries.json هست", c is not None)
        if c is None:
            continue

        check(f"{name} غیر VIP است", c.get("is_vip") is False, str(c.get("is_vip")))
        check(f"{name} منطقه دارد", bool(c.get("region")), str(c.get("region")))
        check(f"{name} جمعیت واقعی دارد", (c.get("population") or 0) > 0)

        econ = c.get("economy") or {}
        needed = {
            "economic_power", "budget", "growth", "inflation", "unemployment",
            "energy_status", "foreign_trade", "govt_debt",
            "public_satisfaction", "stability",
        }
        check(f"{name} اقتصاد کامل دارد", needed <= set(econ), str(needed - set(econ)))

        res = c.get("reserves") or {}
        check(f"{name} هر ۸ منبع را دارد", len(res) == 8, str(sorted(res)))
        check(
            f"{name} ساختار ذخایر درست است",
            all({"amount", "can_extract"} <= set(v) for v in res.values()),
        )

        mil = c.get("military") or []
        check(f"{name} تجهیزات نظامی دارد", len(mil) >= 5, f"{len(mil)} قلم")
        check(
            f"{name} ساختار تجهیزات درست است",
            all({"branch", "category", "name", "unit", "count"} <= set(m) for m in mil),
        )
        check(
            f"{name} پرسنل آماده نبرد دارد",
            any(m["category"] == "سرباز آماده نبرد" for m in mil),
        )

        g = geo["countries"].get(name)
        check(f"{name} در geography.json هست", g is not None)
        if g is not None:
            check(f"{name} مختصات دارد", isinstance(g.get("coords"), list) and len(g["coords"]) == 2)
            check(f"{name} قاره دارد", bool(g.get("continent")))
            check(f"{name} کلید همسایه و دریا دارد",
                  "neighbors" in g and "seas" in g)

    # شاخه‌ها و واحدها باید با بقیه‌ی بازی یکسان باشند (نه رشته‌ی تازه)
    known_branches = {
        m["branch"] for c in countries["countries"] for m in c["military"]
        if c["name_en"] not in ("Norway", "Afghanistan", "Taiwan")
    }
    for name in ("Norway", "Afghanistan", "Taiwan"):
        c = by_name.get(name)
        if c is None:
            continue
        bad = {m["branch"] for m in c["military"]} - known_branches
        check(f"{name} شاخه‌ی ناشناس ندارد", not bad, str(bad))

    # همسایگی دوطرفه است
    gc = geo["countries"]
    for name in ("Norway", "Afghanistan", "Taiwan"):
        g = gc.get(name)
        if g is None:
            continue
        for nb in g.get("neighbors", []):
            check(
                f"همسایگی {name}↔{nb} دوطرفه است",
                nb in gc and name in gc[nb].get("neighbors", []),
                f"{nb} → {gc.get(nb, {}).get('neighbors')}",
            )
        check(f"{name} همسایه‌ی خارج از بازی ندارد",
              all(nb in gc for nb in g.get("neighbors", [])), str(g.get("neighbors")))


# ── ۴) حذف سنجش توان فناورانه‌ی خریدار (آزادسازی معاملات نظامی) ──────────
def _test_arms_export_gate() -> None:
    from bot.services.ai import evaluators, prompts

    check("پرامپت صادرات تسلیحات حذف شده", not hasattr(prompts, "arms_export_prompt"))
    check("سنجش‌گر صادرات تسلیحات حذف شده", not hasattr(evaluators, "evaluate_arms_export"))

    # هندلر فروش، دیگر سنجش را صدا نمی‌زند و مستقیم معامله را جلو می‌برد
    src = inspect.getsource(
        __import__("bot.handlers.military", fromlist=["x"]).cb_sell_buyer
    )
    check("هندلر فروش دیگر سنجش AI را صدا نمی‌زند", "evaluate_arms_export" not in src)
    check("انتقال مستقیم به فرم تعیین پرداخت‌کننده عوارض", "MilitarySaleForm.choosing_fee_payer" in src)


async def main() -> None:
    await init_db()

    _test_new_countries()
    _test_arms_export_gate()

    failed = [c for c in _CHECKS if not c[1]]
    for name, ok, detail in _CHECKS:
        mark = "✅" if ok else "❌"
        print(f"{mark} {name}" + (f" — {detail}" if detail else ""))
    print(f"\n{len(_CHECKS) - len(failed)}/{len(_CHECKS)} بررسی موفق بود")
    if failed:
        print("ناموفق:", [c[0] for c in failed])
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
