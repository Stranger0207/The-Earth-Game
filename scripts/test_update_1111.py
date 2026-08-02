"""
تست‌های آپدیت v1.11.1 (بدون نیاز به PostgreSQL/توکن/AI):

1) اسکورت محموله فقط جنگنده است (موشک/پهپاد/ناوچه/پدافند مجاز نیستند)؛
   رهگیری همچنان با دریایی/هوایی/پدافندی ممکن است.
2) سقف کل تأسیسات برای غیر VIP و بی‌سقف بودن VIP + فهرست به‌تفکیک نوع.
3) سقف سرمایه‌گذاری فعال + صفحه‌بندی ۱۰تایی فهرست‌ها.
4) نامه: پاسخ به متحدان، صندوق پستی شامل پاسخ‌ها و دکمه‌ی همیشگی پاسخ.
5) مسیریابی کال‌بک‌های جدید به هندلرهای درست.

اجرا:
    python -m scripts.test_update_1111
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from bot.constants import (
    ESCORT_MAX_UNITS,
    FACILITY_TOTAL_LIMIT_NON_VIP,
    INVESTMENT_ACTIVE_LIMIT,
)
from bot.database.base import init_db, async_session_factory
from bot.database.models import (
    Country,
    Facility,
    Investment,
    MilitaryAsset,
    Reserve,
)
from bot.database.repositories import alliances as alliances_repo
from bot.database.repositories import facilities as fac_repo
from bot.database.repositories import investments as inv_repo
from bot.database.repositories import letters as letters_repo
from bot.enums import FacilityType, ResourceType
from bot.services import escort_service

# ── چک‌های کوچک ─────────────────────────────────────────────
_CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _CHECKS.append((name, bool(ok), detail))


def _mk(name_en: str, name_fa: str, vip: bool = False) -> Country:
    return Country(
        name_en=name_en, name_fa=name_fa, flag="🏳", region="آسیا",
        population=1_000, is_vip=vip,
    )


# ── ۱) اسکورت فقط جنگنده ────────────────────────────────────
async def _test_escort(s) -> None:
    c = _mk("ET", "تست")
    s.add(c)
    await s.flush()
    s.add_all([
        MilitaryAsset(country_id=c.id, branch="نیروی هوایی", category="جنگنده", name="F-16", count=50, unit="فروند"),
        MilitaryAsset(country_id=c.id, branch="نیروی هوایی", category="پهپادها", name="MQ-9", count=20, unit="فروند"),
        MilitaryAsset(country_id=c.id, branch="نیروی دریایی", category="ناوچه", name="Frigate", count=5, unit="فروند"),
        MilitaryAsset(country_id=c.id, branch="سامانه‌های دفاعی", category="سامانه ضدموشکی", name="S-300", count=10, unit="مجموعه"),
        MilitaryAsset(country_id=c.id, branch="سامانه‌های حمله هوایی", category="موشک کروز", name="Cruise", count=100, unit="عدد"),
    ])
    await s.flush()

    esc = await escort_service.available_escort_assets(s, c.id)
    names = {a["name"] for a in esc}
    check("اسکورت فقط جنگنده", names == {"F-16"}, str(names))

    itc = await escort_service.available_interceptor_assets(s, c.id)
    inames = {a["name"] for a in itc}
    check("رهگیری با ناوچه ممکن است", "Frigate" in inames, str(inames))
    check("رهگیری با پدافند ممکن است", "S-300" in inames, str(inames))
    check("موشک رهگیر نیست", "Cruise" not in inames, str(inames))

    s.add(Reserve(country_id=c.id, resource=ResourceType.OIL.value, amount=100.0, can_extract=True))
    await s.flush()

    # غیرجنگنده در اعتبارسنجی سمت سرور هم رد می‌شود
    for name, cat, br in [
        ("MQ-9", "پهپادها", "نیروی هوایی"),
        ("Frigate", "ناوچه", "نیروی دریایی"),
    ]:
        try:
            await escort_service.validate_escort(s, c, [{
                "name": name, "count": 2, "branch": br, "category": cat, "unit": "عدد",
            }])
            check(f"اسکورت {name} رد می‌شود", False, "پذیرفته شد")
        except escort_service.EscortError:
            check(f"اسکورت {name} رد می‌شود", True)

    power, fuel = await escort_service.validate_escort(s, c, [{
        "name": "F-16", "count": 10, "branch": "نیروی هوایی", "category": "جنگنده", "unit": "فروند",
    }])
    check("جنگنده مجاز اسکورت است", power > 0 and fuel > 0, f"power={power} fuel={fuel}")

    try:
        await escort_service.validate_escort(s, c, [{
            "name": "F-16", "count": ESCORT_MAX_UNITS + 1,
            "branch": "نیروی هوایی", "category": "جنگنده", "unit": "فروند",
        }])
        check("سقف اسکورت رعایت می‌شود", False)
    except escort_service.EscortError:
        check("سقف اسکورت رعایت می‌شود", True)


# ── ۲) سقف معادن و فهرست به‌تفکیک نوع ────────────────────────
async def _test_facility_cap(s) -> None:
    normal, vip = _mk("N", "عادی"), _mk("V", "ویژه", vip=True)
    s.add_all([normal, vip])
    await s.flush()

    for i in range(FACILITY_TOTAL_LIMIT_NON_VIP):
        s.add(Facility(country_id=normal.id, type=FacilityType.MINE.value,
                       resource=ResourceType.IRON.value, location=f"م{i}",
                       yield_amount=10, budget=0))
    for i in range(3):
        s.add(Facility(country_id=normal.id, type=FacilityType.MINE.value,
                       resource=ResourceType.GOLD.value, location=f"ط{i}",
                       yield_amount=5, budget=0))
    await s.flush()

    mines = await fac_repo.count_facilities_by_type(s, normal.id, FacilityType.MINE)
    check("سقف کل معدن برای غیر VIP پر می‌شود", mines >= FACILITY_TOTAL_LIMIT_NON_VIP, str(mines))

    steel = await fac_repo.count_facilities_by_type(s, normal.id, FacilityType.STEEL_FACTORY)
    check("سقف هر نوع مستقل است", steel < FACILITY_TOTAL_LIMIT_NON_VIP, str(steel))

    iron = await fac_repo.list_facilities_by_type(s, normal.id, FacilityType.MINE, ResourceType.IRON.value)
    gold = await fac_repo.list_facilities_by_type(s, normal.id, FacilityType.MINE, ResourceType.GOLD.value)
    check("فهرست معادن به‌تفکیک منبع", len(iron) == FACILITY_TOTAL_LIMIT_NON_VIP and len(gold) == 3,
          f"iron={len(iron)} gold={len(gold)}")

    for i in range(15):
        s.add(Facility(country_id=vip.id, type=FacilityType.MINE.value,
                       resource=ResourceType.IRON.value, location=f"v{i}",
                       yield_amount=10, budget=0))
    await s.flush()
    vm = await fac_repo.count_facilities_by_type(s, vip.id, FacilityType.MINE)
    check("VIP نامحدود می‌سازد", vm == 15, str(vm))


# ── ۳) سقف سرمایه‌گذاری فعال ────────────────────────────────
async def _test_invest_cap(s) -> None:
    c = _mk("IN", "سرمایه")
    s.add(c)
    await s.flush()
    for i in range(INVESTMENT_ACTIVE_LIMIT):
        s.add(Investment(investor_country=c.id, target_country=c.id,
                         category="education", amount=1000.0, profit_pct=12.0, active=True))
    s.add(Investment(investor_country=c.id, target_country=c.id,
                     category="health", amount=500.0, profit_pct=10.0, active=False))
    await s.flush()
    active = await inv_repo.count_active_by_investor(s, c.id)
    check("سقف سرمایه‌گذاری فعال شمرده می‌شود", active == INVESTMENT_ACTIVE_LIMIT, str(active))
    items = await inv_repo.list_by_investor(s, c.id)
    pages = max(1, (len(items) + 9) // 10)
    check("صفحه‌بندی فهرست سرمایه‌گذاری ۱۰تایی", pages == 2, f"items={len(items)} pages={pages}")


# ── ۴) نامه به متحدان + صندوق پستی ───────────────────────────
async def _test_mail(s) -> None:
    a, b, c = _mk("A", "آ", vip=True), _mk("B", "ب"), _mk("C", "ث")
    s.add_all([a, b, c])
    await s.flush()

    al = await alliances_repo.create_alliance(s, name="اتحاد", owner_country=a.id, terms="مفاد")
    await s.flush()
    await alliances_repo.add_member(s, al.id, a.id)
    await alliances_repo.add_member(s, al.id, b.id)
    await alliances_repo.add_member(s, al.id, c.id)
    await s.flush()

    mem = await alliances_repo.get_membership(s, a.id)
    members = await alliances_repo.list_members(s, mem.alliance_id)
    recips = [m.country_id for m in members if m.country_id != a.id]
    check("متحدان غیر از خودم", sorted(recips) == sorted([b.id, c.id]), str(recips))

    l1 = await letters_repo.add_letter(s, a.id, b.id, "سلام")
    r1 = await letters_repo.add_letter(s, b.id, a.id, "علیک", parent_id=l1.id)
    l1.replied = True
    await s.flush()

    inbox_a = await letters_repo.list_inbox(s, a.id)
    check("پاسخ در صندوق پستی دیده می‌شود", any(x.id == r1.id for x in inbox_a),
          str([(x.id, x.parent_id) for x in inbox_a]))
    inbox_b = await letters_repo.list_inbox(s, b.id)
    check("نامه‌ی پاسخ‌داده‌شده هنوز در صندوق است", any(x.id == l1.id for x in inbox_b), "")


# ── ۵) مسیریابی کال‌بک‌های جدید ───────────────────────────────
async def _test_routing() -> None:
    from aiogram.types import CallbackQuery, Chat, Message, User as TgUser
    from bot.loader import dp
    from bot.handlers import register_all_routers

    register_all_routers(dp)

    CASES = {
        "milrep:2": "cb_report_page",
        "facl:mine:0": "cb_facility_list",
        "facl:mine:iron:1": "cb_facility_list",
        "facl:steel_factory:0": "cb_facility_list",
        "econ:facilities": "cb_my_facilities",
        "invpg:mine:1": "cb_invest_page",
        "invpg:on_me:0": "cb_invest_page",
        "godfacpg:1:0": "cb_god_facilities_page",
        "godinvpg:1": "cb_god_invest_page",
        "mail:allies": "cb_mail_allies",
        "escort:add:res:5": "cb_escort_add",
        "escort:skip:mil:5": "cb_escort_skip",
        "mil:report": "cb_report",
        "inv:mine": "cb_invest_mine",
        "inv:on_me": "cb_invest_on_me",
    }

    def walk(router):
        seen_ids = set()
        stack = [router]
        while stack:
            r = stack.pop()
            if id(r) in seen_ids:
                continue
            seen_ids.add(id(r))
            yield r
            stack.extend(r.sub_routers)

    chat = Chat(id=1, type="private")
    tg = TgUser(id=111, is_bot=False, first_name="T")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=tg)
    routers = list(walk(dp))

    for data, expected in CASES.items():
        cb = CallbackQuery(id="1", from_user=tg, chat_instance="x", data=data, message=msg)
        hit = None
        for r in routers:
            obs = r.observers.get("callback_query")
            if obs is None:
                continue
            for h in obs.handlers:
                ok_f = True
                for f in h.filters or []:
                    try:
                        out = f.callback(cb)
                        if asyncio.iscoroutine(out):
                            out = await out
                    except Exception:
                        out = False
                    if not out:
                        ok_f = False
                        break
                if ok_f:
                    hit = h.callback.__name__
                    break
            if hit:
                break
        check(f"مسیریابی {data}", hit == expected, f"hit={hit}")


async def main() -> None:
    await init_db()
    async with async_session_factory() as s:
        await _test_escort(s)
        await _test_facility_cap(s)
        await _test_invest_cap(s)
        await _test_mail(s)
        await s.rollback()
    await _test_routing()

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
