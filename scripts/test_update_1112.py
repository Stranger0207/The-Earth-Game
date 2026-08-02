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

from bot.constants import (
    INTERCEPTOR_DEPLETED_BRANCHES,
    INTERCEPTOR_MAX_UNITS,
)
from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, MilitaryAsset, ResourceSale
from bot.database.repositories import military as mil_repo
from bot.enums import ResourceType, TradeStatus
from bot.services import interception_service
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


# ── ۱) مخفی‌بودن محتویات محموله ──────────────────────────────
def _test_hidden_cargo() -> None:
    from bot.keyboards.covert import shipments_kb

    shipments = [{
        "sale_id": 7,
        "seller": "🇮🇷 ایران",
        "buyer": "🇨🇳 چین",
        "resource_fa": "نفت",
        "amount": 1234.0,
        "unit": "میلیون بشکه",
        "escort_power": 0.0,
        "escort_label": "🟢 بدون اسکورت",
    }]
    kb = shipments_kb(shipments, "cc:operations")
    labels = " | ".join(b.text for row in kb.inline_keyboard for b in row)

    check("مبدأ/مقصد در دکمه هست", "ایران" in labels and "چین" in labels, labels)
    check("نام منبع فاش نمی‌شود", "نفت" not in labels, labels)
    check("مقدار محموله فاش نمی‌شود", "۱٬۲۳۴" not in labels and "1234" not in labels, labels)
    check("وضعیت اسکورت نمایش داده می‌شود", "اسکورت" in labels, labels)

    # متن مرحله‌ی انتخاب محموله هم بارنامه را فاش نمی‌کند
    src = inspect.getsource(
        __import__("bot.handlers.interception", fromlist=["x"]).cb_intercept_pick
    )
    check(
        "متن انتخاب محموله محتوا را نامعلوم می‌گوید",
        "نامعلوم" in src and "fa_number(sale.amount)" not in src,
        "",
    )


# ── ۲) سقف رهگیر و تخلیه‌ی پدافند ────────────────────────────
def _test_interceptor_limits() -> None:
    check("سقف نیروی رهگیر ۴۰ است", INTERCEPTOR_MAX_UNITS == 40, str(INTERCEPTOR_MAX_UNITS))
    check(
        "شاخه‌ی پدافند تخلیه‌شونده است",
        "سامانه‌های دفاعی" in INTERCEPTOR_DEPLETED_BRANCHES,
        str(set(INTERCEPTOR_DEPLETED_BRANCHES)),
    )

    # هندلر سقف را چک می‌کند و هشدار تخلیه را نشان می‌دهد
    mod = __import__("bot.handlers.interception", fromlist=["x"])
    src_count = inspect.getsource(mod.msg_intercept_count)
    check("سقف در ثبت تعداد اعمال می‌شود", "INTERCEPTOR_MAX_UNITS" in src_count)

    src_pick = inspect.getsource(mod.cb_intercept_pick)
    check(
        "هشدار تخلیه‌ی پدافند به بازیکن داده می‌شود",
        "تخلیه" in src_pick and "حذف" in src_pick,
    )

    src_done = inspect.getsource(mod.cb_intercept_done)
    check("پیش از تأیید فهرست تخلیه‌شونده نشان داده می‌شود", "split_depleted" in src_done)

    # تفکیک تخلیه‌شونده از بازگشتی
    committed = [
        CommittedAsset(name="S-300", count=6, branch="سامانه‌های دفاعی",
                       category="سامانه ضدموشکی", unit="سامانه"),
        CommittedAsset(name="F-16", count=8, branch="نیروی هوایی",
                       category="جنگنده", unit="فروند"),
    ]
    depleted, reusable = interception_service.split_depleted(committed)
    check("پدافند در گروه تخلیه است", [a.name for a in depleted] == ["S-300"])
    check("جنگنده در گروه بازگشتی است", [a.name for a in reusable] == ["F-16"])


async def _test_depletion_applied(s) -> None:
    """پدافند اعزامی کامل از موجودی حذف می‌شود؛ جنگنده فقط تلفات می‌دهد."""
    # از کشورهای واقعی استفاده می‌کنیم تا مسیر عبور (is_on_route) برقرار باشد.
    # مسیر روسیه ← هند از ایران می‌گذرد (طبق geography.json).
    seller = _mk("Russia", "روسیه")
    buyer = _mk("India", "هند")
    interceptor = _mk("Iran", "ایران")
    s.add_all([seller, buyer, interceptor])
    await s.flush()

    s.add_all([
        MilitaryAsset(country_id=interceptor.id, branch="سامانه‌های دفاعی",
                      category="سامانه ضدموشکی", name="S-300", count=10, unit="سامانه"),
        MilitaryAsset(country_id=interceptor.id, branch="نیروی هوایی",
                      category="جنگنده", name="F-16", count=40, unit="فروند"),
    ])
    sale = ResourceSale(
        seller_country=seller.id, buyer_country=buyer.id,
        resource=ResourceType.OIL.value, amount=500.0, price=1.0,
        status=TradeStatus.IN_TRANSIT,
    )
    s.add(sale)
    await s.flush()

    committed = [
        CommittedAsset(name="S-300", count=6, branch="سامانه‌های دفاعی",
                       category="سامانه ضدموشکی", unit="سامانه"),
        CommittedAsset(name="F-16", count=20, branch="نیروی هوایی",
                       category="جنگنده", unit="فروند"),
    ]

    # مسیر بی‌اسکورت با seed ثابت (بازتولیدپذیر)
    result = await interception_service.resolve_interception(
        s, interceptor, sale, committed=committed, seed=1,
    )

    depleted_names = {i["name"] for i in result["depleted"]}
    check("پدافند در نتیجه تخلیه‌شده ثبت می‌شود", depleted_names == {"S-300"}, str(depleted_names))

    s300 = await mil_repo.get_asset_by_name(s, interceptor.id, "S-300")
    check("کل پدافند اعزامی از موجودی حذف شد", s300 is not None and s300.count == 4,
          f"count={getattr(s300, 'count', None)}")

    f16 = await mil_repo.get_asset_by_name(s, interceptor.id, "F-16")
    check("جنگنده کامل حذف نشد", f16 is not None and f16.count > 20,
          f"count={getattr(f16, 'count', None)}")

    check("متن نتیجه تخلیه را اعلام می‌کند", "تخلیه" in result["effect_note"],
          result["effect_note"])

    # ---------- مسیر اسکورت‌دار: تخلیه حتی هنگام دفع شدن ----------
    escorted = ResourceSale(
        seller_country=seller.id, buyer_country=buyer.id,
        resource=ResourceType.OIL.value, amount=300.0, price=1.0,
        status=TradeStatus.IN_TRANSIT,
        escort_power=99_000.0,  # اسکورت بسیار سنگین → رهگیری قطعاً دفع می‌شود
        escort_json=json.dumps(
            [{"name": "F-35", "count": 30, "branch": "نیروی هوایی",
              "category": "جنگنده", "unit": "فروند"}],
            ensure_ascii=False,
        ),
    )
    s.add(escorted)
    await s.flush()

    before = (await mil_repo.get_asset_by_name(s, interceptor.id, "S-300")).count
    repulsed = await interception_service.resolve_interception(
        s, interceptor, escorted,
        committed=[CommittedAsset(name="S-300", count=3, branch="سامانه‌های دفاعی",
                                  category="سامانه ضدموشکی", unit="سامانه")],
        seed=2,
    )
    after = (await mil_repo.get_asset_by_name(s, interceptor.id, "S-300")).count

    check("رهگیری ناکافی دفع می‌شود", repulsed["repulsed"] is True, str(repulsed["repulsed"]))
    check("پدافند حتی هنگام دفع شدن تخلیه می‌شود", after == before - 3,
          f"{before} → {after}")
    check("متن دفع‌شدن هم تخلیه را اعلام می‌کند", "تخلیه" in repulsed["effect_note"],
          repulsed["effect_note"])


# ── ۳) سه کشور جدید ─────────────────────────────────────────
def _test_new_countries() -> None:
    countries = json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))
    geo = json.loads((ROOT / "data" / "geography.json").read_text(encoding="utf-8"))

    by_name = {c["name_en"]: c for c in countries["countries"]}
    check("تعداد کشورها ۳۹ شد", len(countries["countries"]) == 39, str(len(countries["countries"])))

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


# ── ۴) سنجش توان فناورانه‌ی خریدار ──────────────────────────
def _test_arms_export_gate() -> None:
    from bot.services.ai import evaluators, prompts

    p = prompts.arms_export_prompt()
    check("پرامپت صادرات تسلیحات وجود دارد", bool(p))
    check("F-22 در پرامپت نمونه شده", "F-22" in p)
    check("B-2 در پرامپت نمونه شده", "B-2" in p)
    check("نسل ۵ در پرامپت آمده", "نسل ۵" in p)
    check("خروجی allowed دارد", '"allowed"' in p)
    check("خروجی severity دارد", '"severity"' in p)

    check("سنجش‌گر صادرات تسلیحات هست", hasattr(evaluators, "evaluate_arms_export"))
    sig = inspect.signature(evaluators.evaluate_arms_export)
    for param in ("item_name", "category_fa", "branch_fa", "count"):
        check(f"پارامتر {param} در سنجش‌گر هست", param in sig.parameters)

    # هندلر فروش، سنجش را صدا می‌زند و در صورت رد معامله را ثبت نمی‌کند
    src = inspect.getsource(
        __import__("bot.handlers.military", fromlist=["x"]).cb_sell_buyer
    )
    check("هندلر فروش سنجش را صدا می‌زند", "evaluate_arms_export" in src)
    check("رد شدن معامله را متوقف می‌کند",
          'verdict.get("allowed") is False' in src and "return" in src)
    check("رد شدن در گروه لاگ ثبت می‌شود", "send_log" in src)
    # fallback: خطای AI (دیکشنری خالی) معامله را رد نمی‌کند
    check("خطای AI معامله را رد نمی‌کند", "if verdict and" in src)


async def main() -> None:
    await init_db()

    _test_hidden_cargo()
    _test_interceptor_limits()
    _test_new_countries()
    _test_arms_export_gate()

    async with async_session_factory() as s:
        await _test_depletion_applied(s)
        await s.rollback()

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
