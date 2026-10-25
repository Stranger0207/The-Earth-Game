"""سرویس محاسبه و رندر ترازنامه بازدهی روزانه کشور (ترازنامه درآمد خالص ۲۴ ساعته)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ECON_SAT_LEVEL_CONFIG,
    GAS_PLATFORM_OUTPUT_PER_24H,
    GOLD_MINE_YIELD_KG_PER_24H,
    INVESTMENT_CATEGORIES,
    MIL_FACTORY_INTAKE,
    MINE_YIELD_PER_24H,
    OIL_PLATFORM_OUTPUT_PER_24H,
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from ..database.models import (
    Country,
    EconomicProject,
    Facility,
    Investment,
    MilitaryFactory,
    Satellite,
)
from ..enums import (
    FACILITY_FA,
    MIL_FACTORY_FA,
    RESOURCE_EMOJI,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    EconomicProjectStatus,
    FacilityType,
    MilitaryFactoryType,
    ResourceType,
)
from ..utils.numbers import fa_money, fa_number
from ..utils.ui import DIVIDER, header


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def compute_country_daily_yield(
    session: AsyncSession, country: Country
) -> dict[str, Any]:
    """
    محاسبه جامع کلیه بازدهی‌ها و مصارف ۲۴ ساعته کشور شامل:
    - تأسیسات اقتصادی انفرادی و مشترک
    - سرمایه‌گذاری‌های داخلی و خارجی
    - پروژه‌ها و رول‌های اقتصادی تاییدشده
    - ماهواره اقتصادی فعال در مدار
    - تولیدات و مصارف کارخانه‌های نظامی فعال
    - جمع کل خالص نقدینگی و منابع
    """
    now = _utcnow()
    cid = country.id

    # ۱. تأسیسات (تأسیسات خود کشور + تأسیسات مشترک با کشورهای دیگر)
    stmt_fac = select(Facility).where(
        or_(Facility.country_id == cid, Facility.partner_country == cid)
    )
    res_fac = await session.execute(stmt_fac)
    all_facs = res_fac.scalars().all()

    active_facs: list[Facility] = []
    stopped_facs_count = 0

    fac_resources_produced: dict[str, float] = {}  # resource -> daily amount
    fac_resources_consumed: dict[str, float] = {}  # resource -> daily amount
    fac_summary_list: list[dict[str, Any]] = []
    earliest_fac_next: datetime | None = None

    for f in all_facs:
        # اگر متوقف است
        if not getattr(f, "active", True):
            if f.country_id == cid:
                stopped_facs_count += 1
            continue

        active_facs.append(f)

        # محاسبه سهم مالکیت
        is_creator = (f.country_id == cid)
        partner_pct = float(getattr(f, "partner_percent", 0) or 0)
        has_partner = (f.partner_country is not None and partner_pct > 0)

        if has_partner:
            if is_creator:
                share_pct = 100.0 - partner_pct
            else:
                share_pct = partner_pct
        else:
            share_pct = 100.0

        share_ratio = share_pct / 100.0

        # محاسبه بازدهی ۲۴ ساعته بر اساس نوع
        ftype_str = f.type
        rtype_str = f.resource
        item_title = ""
        produced_str = ""

        if ftype_str == FacilityType.STEEL_FACTORY.value:
            # مصرف آهن و تولید فولاد
            intake_iron = STEEL_FACTORY_IRON_INTAKE_PER_24H * share_ratio
            output_steel = STEEL_FACTORY_OUTPUT_PER_24H * share_ratio

            fac_resources_consumed["iron"] = fac_resources_consumed.get("iron", 0.0) + intake_iron
            fac_resources_produced["steel"] = fac_resources_produced.get("steel", 0.0) + output_steel

            item_title = "کارخانه فولاد"
            produced_str = f"+{fa_number(output_steel)} تن فولاد (مصرف: {fa_number(intake_iron)} تن آهن)"
        elif ftype_str == FacilityType.OIL_PLATFORM.value:
            out_oil = OIL_PLATFORM_OUTPUT_PER_24H * share_ratio
            fac_resources_produced["oil"] = fac_resources_produced.get("oil", 0.0) + out_oil
            item_title = "دکل نفت"
            produced_str = f"+{fa_number(out_oil)} بشکه نفت"
        elif ftype_str == FacilityType.GAS_PLATFORM.value:
            out_gas = GAS_PLATFORM_OUTPUT_PER_24H * share_ratio
            fac_resources_produced["gas"] = fac_resources_produced.get("gas", 0.0) + out_gas
            item_title = "دکل گاز"
            produced_str = f"+{fa_number(out_gas)} مترمکعب گاز"
        elif ftype_str == FacilityType.MINE.value and rtype_str:
            try:
                rtype = ResourceType(rtype_str)
                rname = RESOURCE_FA.get(rtype, rtype_str)
                runit = RESOURCE_UNIT_FA.get(rtype, "")
            except Exception:
                rname, runit = rtype_str, ""

            base_yield = f.yield_amount
            if base_yield <= 0:
                if rtype_str == ResourceType.GOLD.value:
                    base_yield = GOLD_MINE_YIELD_KG_PER_24H
                else:
                    base_yield = MINE_YIELD_PER_24H.get(ResourceType(rtype_str), 0.0)

            out_amount = base_yield * share_ratio
            fac_resources_produced[rtype_str] = fac_resources_produced.get(rtype_str, 0.0) + out_amount
            item_title = f"معدن {rname}"
            produced_str = f"+{fa_number(out_amount)} {runit}"
        else:
            item_title = f.type
            produced_str = f"+{fa_number(f.yield_amount)}"

        # زمان باقیمانده تا تیک بعدی این تأسیسات
        last_y = _aware(f.last_yield_at)
        interval_h = getattr(f, "yield_interval_h", 24) or 24
        if last_y:
            next_t = last_y + timedelta(hours=interval_h)
            if earliest_fac_next is None or next_t < earliest_fac_next:
                earliest_fac_next = next_t

        partner_info = f" (سهم: {fa_number(share_pct)}٪)" if has_partner else ""
        fac_summary_list.append({
            "name": item_title + partner_info,
            "output": produced_str,
            "location": f.location or "خاک خودی",
            "is_joint": has_partner,
            "share_pct": share_pct,
        })

    # ۲. سرمایه‌گذاری‌ها (Investments)
    stmt_inv = select(Investment).where(
        Investment.investor_country == cid,
        Investment.active == True,
    )
    res_inv = await session.execute(stmt_inv)
    active_invs = res_inv.scalars().all()

    daily_inv_cash = 0.0
    inv_summary_list: list[dict[str, Any]] = []

    for inv in active_invs:
        profit_24h = inv.amount * inv.profit_pct / 100.0
        daily_inv_cash += profit_24h
        cat_fa, _ = INVESTMENT_CATEGORIES.get(inv.category, (inv.category, inv.profit_pct))
        is_foreign = (inv.target_country != cid)
        inv_summary_list.append({
            "category": cat_fa,
            "amount": inv.amount,
            "profit_pct": inv.profit_pct,
            "profit_cash": profit_24h,
            "is_foreign": is_foreign,
        })

    # ۳. پروژه‌ها و رول‌های اقتصادی فعال (Economic Projects)
    stmt_proj = select(EconomicProject).where(
        EconomicProject.country_id == cid,
        EconomicProject.status == EconomicProjectStatus.ACTIVE.value,
    )
    res_proj = await session.execute(stmt_proj)
    active_projs = res_proj.scalars().all()

    daily_proj_cash = 0.0
    proj_resources_produced: dict[str, float] = {}
    proj_summary_list: list[dict[str, Any]] = []

    for p in active_projs:
        p_cash_72h = p.yield_cash_72h or 0.0
        p_cash_daily = p_cash_72h / 3.0
        daily_proj_cash += p_cash_daily

        # بازدهی ذخایر پروژه
        r_daily_dict: dict[str, float] = {}
        for rk, rv in (p.yield_resources_dict or {}).items():
            r_daily = float(rv) / 3.0
            r_daily_dict[rk] = r_daily
            proj_resources_produced[rk] = proj_resources_produced.get(rk, 0.0) + r_daily

        proj_summary_list.append({
            "title": p.title,
            "cash_72h": p_cash_72h,
            "cash_daily": p_cash_daily,
            "resources_daily": r_daily_dict,
        })

    # ۴. ماهواره اقتصادی (Economic Satellite)
    stmt_sat = select(Satellite).where(
        Satellite.country_id == cid,
        Satellite.satellite_type == "economic",
        Satellite.status == "in_orbit",
    )
    res_sat = await session.execute(stmt_sat)
    active_sat = res_sat.scalars().first()

    sat_info: dict[str, Any] | None = None
    daily_sat_cash = 0.0

    if active_sat:
        level = getattr(active_sat, "level", 1) or 1
        cfg = ECON_SAT_LEVEL_CONFIG.get(level, {"yield_usd": 100_000_000.0})
        yield_72h = cfg["yield_usd"]
        daily_sat_cash = yield_72h / 3.0

        ref_time = _aware(active_sat.last_yield_at or active_sat.orbit_at or active_sat.launch_at)
        rem_sec = 0
        if ref_time:
            passed = (now - ref_time).total_seconds()
            rem_sec = max(0, int(72 * 3600 - passed))
        rem_hours = rem_sec // 3600
        rem_mins = (rem_sec % 3600) // 60

        sat_info = {
            "level": level,
            "yield_72h": yield_72h,
            "yield_daily": daily_sat_cash,
            "rem_hours": rem_hours,
            "rem_mins": rem_mins,
        }

    # ۵. کارخانه‌های نظامی فعال (Military Factories)
    stmt_mf = select(MilitaryFactory).where(
        MilitaryFactory.country_id == cid,
        MilitaryFactory.active == True,
    )
    res_mf = await session.execute(stmt_mf)
    active_mfs = res_mf.scalars().all()

    mil_resources_consumed: dict[str, float] = {}
    mil_summary_list: list[dict[str, Any]] = []

    for mf in active_mfs:
        try:
            mftype = MilitaryFactoryType(mf.factory_type)
            intake = MIL_FACTORY_INTAKE.get(mftype, {})
            fa_type = MIL_FACTORY_FA.get(mftype, mf.factory_type)
        except Exception:
            intake = {}
            fa_type = mf.factory_type

        # نرمال‌سازی مصرف به ازای ۲۴ ساعت (اگر چرخه ۱۴۴ ساعت است تقسیم بر ۶ می‌شود)
        cycle_hours = getattr(mf, "yield_interval_h", 24) or 24
        day_ratio = 24.0 / float(cycle_hours)
        daily_intake_for_this: dict[str, float] = {}

        for rk, amt in intake.items():
            daily_amt = amt * day_ratio
            daily_intake_for_this[rk] = daily_amt
            mil_resources_consumed[rk] = mil_resources_consumed.get(rk, 0.0) + daily_amt

        mil_summary_list.append({
            "name": mf.asset_name,
            "type_fa": fa_type,
            "yield_amount": mf.yield_amount,
            "unit": mf.unit or "واحد",
            "cycle_h": cycle_hours,
            "daily_intake": daily_intake_for_this,
        })

    # ۶. جمع کل خالص درآمد نقدی و خالص تولید منابع
    net_daily_cash = daily_inv_cash + daily_proj_cash + daily_sat_cash

    # تجمیع منابع تولیدی و مصرفی
    all_resource_keys = set(fac_resources_produced.keys()) | set(proj_resources_produced.keys()) | set(fac_resources_consumed.keys()) | set(mil_resources_consumed.keys())
    net_resources: dict[str, float] = {}

    for rk in all_resource_keys:
        prod = fac_resources_produced.get(rk, 0.0) + proj_resources_produced.get(rk, 0.0)
        cons = fac_resources_consumed.get(rk, 0.0) + mil_resources_consumed.get(rk, 0.0)
        net_resources[rk] = prod - cons

    # زمان تقریبی تا تیک بعدی
    next_tick_str = "کمتر از ۱ ساعت"
    if earliest_fac_next and earliest_fac_next > now:
        rem_sec = int((earliest_fac_next - now).total_seconds())
        rem_h = rem_sec // 3600
        rem_m = (rem_sec % 3600) // 60
        if rem_h > 0:
            next_tick_str = f"{fa_number(rem_h)} ساعت و {fa_number(rem_m)} دقیقه"
        else:
            next_tick_str = f"{fa_number(rem_m)} دقیقه"

    return {
        "active_facs": fac_summary_list,
        "stopped_facs_count": stopped_facs_count,
        "active_invs": inv_summary_list,
        "daily_inv_cash": daily_inv_cash,
        "active_projs": proj_summary_list,
        "daily_proj_cash": daily_proj_cash,
        "sat_info": sat_info,
        "daily_sat_cash": daily_sat_cash,
        "active_mfs": mil_summary_list,
        "net_daily_cash": net_daily_cash,
        "net_resources": net_resources,
        "next_tick_str": next_tick_str,
    }


def format_daily_yield_report(country: Country, data: dict[str, Any]) -> str:
    """فرمت پیام شیک و جامع ترازنامه بازدهی روزانه کشور."""
    lines: list[str] = [
        header("ترازنامه درآمد و بازدهی روزانه (۲۴ ساعت)", "📊"),
        f"کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"این ترازنامه ریزِ تمامی دریافتی‌های نقدی و تولید خالص منابع کشور شما را در هر ۲۴ ساعت محاسبه و نمایش می‌دهد.\n"
        f"{DIVIDER}",
    ]

    # ۱. تأسیسات اقتصادی
    lines.append("🏭 <b>تأسیسات اقتصادی:</b>")
    active_facs = data.get("active_facs", [])
    if active_facs:
        # خلاصه‌سازی بر اساس نام مشابه جهت جلوگیری از پیام‌های بیش از حد طولانی
        fac_counts: dict[str, int] = {}
        fac_outputs: dict[str, str] = {}
        for f in active_facs:
            k = f"{f['name']}|{f['output']}"
            fac_counts[k] = fac_counts.get(k, 0) + 1
            fac_outputs[k] = f"• {f['name']}: <b>{f['output']}</b>"

        for k, count in fac_counts.items():
            base_str = fac_outputs[k]
            if count > 1:
                base_str += f" (تعداد: {fa_number(count)})"
            lines.append(base_str)
    else:
        lines.append("• هیچ تأسیسات فعالی احداث نشده است.")

    stopped = data.get("stopped_facs_count", 0)
    if stopped > 0:
        lines.append(f"• ⏸ <b>{fa_number(stopped)} واحد متوقف‌شده</b> (بدون بازدهی و هزینه)")
    lines.append("")

    # ۲. سرمایه‌گذاری‌ها
    lines.append("📈 <b>سود سرمایه‌گذاری‌ها (۲۴ ساعته):</b>")
    active_invs = data.get("active_invs", [])
    if active_invs:
        for inv in active_invs[:8]:  # نمایش تا ۸ مورد اول برای حفظ خوانایی
            scope = "خارجی" if inv["is_foreign"] else "داخلی"
            lines.append(
                f"• {inv['category']} ({scope} - {fa_number(inv['profit_pct'])}٪): "
                f"<b>+{fa_money(inv['profit_cash'])}</b>"
            )
        if len(active_invs) > 8:
            lines.append(f"• و {fa_number(len(active_invs) - 8)} سرمایه‌گذاری فعال دیگر...")
        lines.append(f"💵 <i>مجموع سود سرمایه‌گذاری: {fa_money(data['daily_inv_cash'])} در روز</i>")
    else:
        lines.append("• در حال حاضر سرمایه‌گذاری فعالی ندارید.")
    lines.append("")

    # ۳. پروژه‌ها و رول‌های اقتصادی
    active_projs = data.get("active_projs", [])
    if active_projs:
        lines.append("📜 <b>رول‌ها و پروژه‌های اقتصادی فعال:</b>")
        for p in active_projs:
            lines.append(
                f"• 🏗 {p['title']}: <b>+{fa_money(p['cash_daily'])}/روز</b> "
                f"(معادل {fa_money(p['cash_72h'])} هر ۷۲ ساعت)"
            )
        lines.append("")

    # ۴. ماهواره اقتصادی
    sat_info = data.get("sat_info")
    if sat_info:
        lines.append("🛰 <b>ماهواره اقتصادی (در مدار):</b>")
        lines.append(
            f"• ماهواره سطح {fa_number(sat_info['level'])}: "
            f"<b>+{fa_money(sat_info['yield_daily'])}/روز</b> "
            f"(معادل {fa_money(sat_info['yield_72h'])} هر ۷۲ساعت)\n"
            f"  ⏳ واریز بعدی: {fa_number(sat_info['rem_hours'])} ساعت و {fa_number(sat_info['rem_mins'])} دقیقه دیگر"
        )
        lines.append("")

    # ۵. صنایع و کارخانه‌های نظامی فعال
    active_mfs = data.get("active_mfs", [])
    if active_mfs:
        lines.append("⚙️ <b>کارخانه‌های نظامی فعال (تولید و مصرف منابع):</b>")
        for mf in active_mfs[:6]:
            cycle_desc = f"هر {fa_number(mf['cycle_h'])} ساعت"
            lines.append(f"• {mf['name']} ({mf['type_fa']}): +{fa_number(mf['yield_amount'])} {mf['unit']} ({cycle_desc})")
            if mf["daily_intake"]:
                intake_items = []
                for rk, amt in mf["daily_intake"].items():
                    try:
                        rname = RESOURCE_FA.get(ResourceType(rk), rk)
                    except Exception:
                        rname = rk
                    intake_items.append(f"{fa_number(amt)} {rname}")
                lines.append(f"   🔻 مصرف روزانه: {', '.join(intake_items)}")
        lines.append("")

    # ۶. کادر جمع کل بازدهی روزانه
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║        📦 جمع کل خالص بازدهی روزانه (۲۴ ساعت)        ║")
    lines.append("╠══════════════════════════════════════╣")

    # جمع درآمد نقدی
    net_cash = data.get("net_daily_cash", 0.0)
    lines.append(f"║ 💵 <b>درآمد خالص نقدی:</b> <b>{fa_money(net_cash)}</b>")

    # جمع خالص منابع
    lines.append("║ ⛏ <b>تولید خالص منابع در روز:</b>")
    net_res = data.get("net_resources", {})
    if net_res:
        for rk, amt in sorted(net_res.items()):
            if abs(amt) < 0.001:
                continue
            try:
                rtype = ResourceType(rk)
                remoji = RESOURCE_EMOJI.get(rtype, "📦")
                rname = RESOURCE_FA.get(rtype, rk)
                runit = RESOURCE_UNIT_FA.get(rtype, "")
            except Exception:
                remoji, rname, runit = "📦", rk, ""

            sign = "+" if amt > 0 else ""
            lines.append(f"║   {remoji} {rname}: <b>{sign}{fa_number(amt)} {runit}</b>")
    else:
        lines.append("║   • تغییری در منابع ثبت نشده است.")

    lines.append(f"║ ⏳ <b>زمان تقریبی واریز بعدی:</b> {data.get('next_tick_str', 'به زودی')}")
    lines.append("╚══════════════════════════════════════╝")

    return "\n".join(lines)
