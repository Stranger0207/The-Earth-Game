"""سرویس هسته محاسبات تراز کلان جهانی، مانیتورینگ منابع، حسابرسی و داشبورد آماری."""

from __future__ import annotations

import csv
import io
import json
import logging
import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    DEFAULT_BASE_PRICES,
    GLOBAL_REPORT_DEFAULT_PERIOD_HOURS,
    GLOBAL_REPORT_DEFICIT_CRITICAL_RATIO,
    GLOBAL_REPORT_DEFICIT_WARN_RATIO,
    GLOBAL_REPORT_SURPLUS_CRITICAL_RATIO,
    MARKET_MAX_PRICE_FACTOR,
    MARKET_MIN_PRICE_FACTOR,
    MIL_FACTORY_BUILD_RESOURCES,
    MIL_FACTORY_INTAKE,
    NUCLEAR_FACILITY_RESOURCES,
    SPY_SATELLITE_ALUMINUM_COST,
    SPY_SATELLITE_OIL_COST,
    SPY_SATELLITE_STEEL_COST,
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from ..database.models import (
    Country,
    Deployment,
    Facility,
    GlobalReport,
    MarketPrice,
    MilitaryFactory,
    NuclearFacility,
    Reserve,
    ResourceSale,
    Satellite,
)
from ..database.repositories import global_reports as global_reports_repo
from ..enums import (
    RESOURCE_EMOJI,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    FacilityType,
    MilitaryFactoryType,
    NuclearFacilityType,
    ResourceType,
)
from ..utils.numbers import fa_money, fa_number, to_fa_digits
from ..utils.ui import DIVIDER, header

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime | None) -> datetime:
    """تضمین قرارگیری datetime در تایم‌زون UTC."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_in_window(dt: datetime | None, start: datetime, end: datetime) -> bool:
    """بررسی قرارگیری یک زمان در پنجره گزارش با مدیریت اختلاف تایم‌زون SQLite/Postgres."""
    if dt is None:
        return False
    dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return start <= dt_utc <= end


async def generate_global_report(
    session: AsyncSession,
    period_hours: int = GLOBAL_REPORT_DEFAULT_PERIOD_HOURS,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> tuple[GlobalReport, dict]:
    """
    تولید و ثبت اسنپشات تراز کلان جهانی برای یک بازه زمانی مشخص (۸، ۲۴ یا ۷۲ ساعته).
    شامل موجودی کل، تولید فعال، مصرف صنعتی/نظامی/رویدادی، خالص جریان، سهم ۳ دارنده برتر،
    شاخص‌های مالی، تحلیل بازار و حسابرسی انحراف داده (Audit Delta Check).
    """
    end_time = _ensure_utc(end_time)
    if start_time is None:
        start_time = end_time - timedelta(hours=period_hours)
    else:
        start_time = _ensure_utc(start_time)

    # ۱. واکشی کشورها و ذخایر
    countries_res = await session.execute(select(Country))
    countries: list[Country] = list(countries_res.scalars().all())
    countries_by_id: dict[int, Country] = {c.id: c for c in countries}

    reserves_res = await session.execute(select(Reserve))
    all_reserves: list[Reserve] = list(reserves_res.scalars().all())

    # ذخایر بر اساس منبع و کشور
    stocks: dict[str, float] = {r.value: 0.0 for r in ResourceType}
    res_country_holdings: dict[str, list[tuple[Country, float]]] = {
        r.value: [] for r in ResourceType
    }
    country_reserves_map: dict[int, dict[str, float]] = {c.id: {} for c in countries}

    for res in all_reserves:
        r_type = res.resource
        if r_type in stocks:
            stocks[r_type] += res.amount
            c = countries_by_id.get(res.country_id)
            if c is not None:
                res_country_holdings[r_type].append((c, res.amount))
                country_reserves_map[c.id][r_type] = res.amount

    # ۲. محاسبه سهم و تمرکز ۳ دارنده برتر هر منبع
    top_holders: dict[str, dict] = {}
    for r_type, holdings in res_country_holdings.items():
        holdings.sort(key=lambda x: x[1], reverse=True)
        tot_stock = stocks.get(r_type, 0.0)
        top3_list = []
        top3_sum_pct = 0.0
        for c, amt in holdings[:3]:
            share_pct = (amt / tot_stock * 100.0) if tot_stock > 0 else 0.0
            top3_list.append(
                {
                    "country_id": c.id,
                    "name": c.name_fa,
                    "flag": c.flag,
                    "amount": round(amt, 2),
                    "share_pct": round(share_pct, 1),
                }
            )
            top3_sum_pct += share_pct
        top_holders[r_type] = {
            "list": top3_list,
            "top3_share_pct": round(top3_sum_pct, 1),
        }

    # ۳. محاسبه تولید و مصرف صنعتی تأسیسات فعال
    production: dict[str, float] = {r.value: 0.0 for r in ResourceType}
    consumption_industrial: dict[str, float] = {r.value: 0.0 for r in ResourceType}

    fac_res = await session.execute(select(Facility).where(Facility.active == True))  # noqa: E712
    active_facilities: list[Facility] = list(fac_res.scalars().all())

    for f in active_facilities:
        interval_h = f.yield_interval_h if f.yield_interval_h > 0 else 24
        factor = period_hours / interval_h

        f_type_str = f.type.value if hasattr(f.type, "value") else str(f.type)
        if f_type_str in (FacilityType.STEEL_FACTORY.value, "steel_factory"):
            out_amt = (
                f.yield_amount if f.yield_amount > 0 else STEEL_FACTORY_OUTPUT_PER_24H
            ) * factor
            in_amt = (
                f.intake_amount if f.intake_amount > 0 else STEEL_FACTORY_IRON_INTAKE_PER_24H
            ) * factor
            production[ResourceType.STEEL.value] += out_amt
            consumption_industrial[ResourceType.IRON.value] += in_amt
        elif f_type_str in (FacilityType.OIL_PLATFORM.value, "oil_platform"):
            production[ResourceType.OIL.value] += f.yield_amount * factor
        elif f_type_str in (FacilityType.GAS_PLATFORM.value, "gas_platform"):
            production[ResourceType.GAS.value] += f.yield_amount * factor
        elif f.resource and f.resource in production:
            production[f.resource] += f.yield_amount * factor

    # ۴. محاسبه مصرف کارخانه‌های نظامی فعال
    consumption_military: dict[str, float] = {r.value: 0.0 for r in ResourceType}
    mf_res = await session.execute(
        select(MilitaryFactory).where(MilitaryFactory.active == True)  # noqa: E712
    )
    active_mfacs: list[MilitaryFactory] = list(mf_res.scalars().all())

    for mf in active_mfacs:
        interval_h = mf.yield_interval_h if mf.yield_interval_h > 0 else 24
        factor = period_hours / interval_h
        try:
            mftype = MilitaryFactoryType(mf.factory_type)
        except (ValueError, KeyError):
            mftype = None
        if mftype and mftype in MIL_FACTORY_INTAKE:
            for r_key, r_amt in MIL_FACTORY_INTAKE[mftype].items():
                res_str = r_key.value if hasattr(r_key, "value") else str(r_key)
                if res_str in consumption_military:
                    consumption_military[res_str] += r_amt * factor

    # ۵. مصارف ایونت‌محور رخداده در پنجره [start_time, end_time]
    consumption_events: dict[str, float] = {r.value: 0.0 for r in ResourceType}

    # الف) ساخت کارخانه‌های نظامی جدید در بازه
    all_mf_res = await session.execute(select(MilitaryFactory))
    for mf in all_mf_res.scalars().all():
        if _is_in_window(mf.created_at, start_time, end_time):
            try:
                mftype = MilitaryFactoryType(mf.factory_type)
            except (ValueError, KeyError):
                mftype = None
            if mftype and mftype in MIL_FACTORY_BUILD_RESOURCES:
                for r_key, r_amt in MIL_FACTORY_BUILD_RESOURCES[mftype].items():
                    res_str = r_key.value if hasattr(r_key, "value") else str(r_key)
                    if res_str in consumption_events:
                        consumption_events[res_str] += r_amt

    # ب) پرتاب ماهواره‌های فضایی
    all_sat_res = await session.execute(select(Satellite))
    for sat in all_sat_res.scalars().all():
        if _is_in_window(sat.created_at, start_time, end_time):
            consumption_events[ResourceType.OIL.value] += SPY_SATELLITE_OIL_COST
            consumption_events[ResourceType.STEEL.value] += SPY_SATELLITE_STEEL_COST
            consumption_events[ResourceType.ALUMINUM.value] += SPY_SATELLITE_ALUMINUM_COST

    # ج) استقرار نیرو
    all_dep_res = await session.execute(select(Deployment))
    for dep in all_dep_res.scalars().all():
        if _is_in_window(dep.created_at, start_time, end_time):
            consumption_events[ResourceType.OIL.value] += dep.oil_cost

    # د) تأسیسات هسته‌ای
    all_nfac_res = await session.execute(select(NuclearFacility))
    for nf in all_nfac_res.scalars().all():
        if _is_in_window(nf.created_at, start_time, end_time):
            try:
                nftype = NuclearFacilityType(nf.facility_type)
            except (ValueError, KeyError):
                nftype = None
            if nftype and nftype in NUCLEAR_FACILITY_RESOURCES:
                for r_key, r_amt in NUCLEAR_FACILITY_RESOURCES[nftype].items():
                    res_str = r_key.value if hasattr(r_key, "value") else str(r_key)
                    if res_str in consumption_events:
                        consumption_events[res_str] += r_amt

    # ۶. خالص جریان و تعیین پرچم ریسک
    total_consumption: dict[str, float] = {}
    consumption_breakdown: dict[str, dict] = {}
    net_flow: dict[str, float] = {}
    risk_flags: dict[str, dict] = {}

    for rtype in ResourceType:
        rk = rtype.value
        c_ind = consumption_industrial.get(rk, 0.0)
        c_mil = consumption_military.get(rk, 0.0)
        c_eve = consumption_events.get(rk, 0.0)
        c_tot = c_ind + c_mil + c_eve

        total_consumption[rk] = c_tot
        consumption_breakdown[rk] = {
            "total": round(c_tot, 2),
            "industrial": round(c_ind, 2),
            "military": round(c_mil, 2),
            "events": round(c_eve, 2),
        }

        nf = production.get(rk, 0.0) - c_tot
        net_flow[rk] = nf

        if c_tot > 0:
            ratio = nf / c_tot
            if ratio <= GLOBAL_REPORT_DEFICIT_CRITICAL_RATIO:
                flag_code = "CRITICAL_DEFICIT"
                flag_fa = "🔴 کسری بحرانی"
            elif ratio <= GLOBAL_REPORT_DEFICIT_WARN_RATIO:
                flag_code = "WARN_DEFICIT"
                flag_fa = "🟡 کسری هشدار"
            elif ratio >= GLOBAL_REPORT_SURPLUS_CRITICAL_RATIO:
                flag_code = "CRITICAL_SURPLUS"
                flag_fa = "🔵 مازاد شدید"
            elif nf < 0:
                flag_code = "MINOR_DEFICIT"
                flag_fa = "🟠 کسری جزئی"
            else:
                flag_code = "BALANCED"
                flag_fa = "🟢 تراز مثبت"
        else:
            if production.get(rk, 0.0) > 0:
                ratio = 1.0
                flag_code = "SURPLUS_NO_CONS"
                flag_fa = "🟢 تولید بدون مصرف"
            else:
                ratio = 0.0
                flag_code = "ZERO_FLOW"
                flag_fa = "⚪️ بدون تغییر"

        risk_flags[rk] = {
            "code": flag_code,
            "text": flag_fa,
            "ratio": round(ratio, 2),
        }

    # ۷. شاخص‌های مالی و اعتباری کلان
    total_budget = sum(c.budget for c in countries)
    total_debt = sum(c.govt_debt for c in countries)
    sat_list = [c.public_satisfaction for c in countries]
    stab_list = [c.stability for c in countries]

    mean_sat = round(statistics.mean(sat_list), 1) if sat_list else 0.0
    median_sat = round(statistics.median(sat_list), 1) if sat_list else 0.0
    mean_stab = round(statistics.mean(stab_list), 1) if stab_list else 0.0
    median_stab = round(statistics.median(stab_list), 1) if stab_list else 0.0

    credit_counts: dict[str, int] = {}
    for c in countries:
        cr = c.credit_rating or "normal"
        credit_counts[cr] = credit_counts.get(cr, 0) + 1

    macro = {
        "total_budget": round(total_budget, 2),
        "total_debt": round(total_debt, 2),
        "mean_sat": mean_sat,
        "median_sat": median_sat,
        "mean_stab": mean_stab,
        "median_stab": median_stab,
        "credit_ratings": credit_counts,
        "total_countries": len(countries),
    }

    # ۸. تحلیل بازار و معاملات اخیر WTO
    mp_res = await session.execute(select(MarketPrice))
    market_prices = {mp.resource: mp for mp in mp_res.scalars().all()}
    market_data: dict[str, dict] = {}

    for rtype in ResourceType:
        rk = rtype.value
        base_p = DEFAULT_BASE_PRICES.get(rtype, 100.0)
        mp = market_prices.get(rk)
        if mp is not None:
            curr_p = mp.current_price
            base_p = mp.base_price or base_p
            trend = mp.trend
            chg = mp.change_pct
        else:
            curr_p = base_p
            trend = "STABLE"
            chg = 0.0

        ratio = round(curr_p / base_p, 2) if base_p > 0 else 1.0
        market_data[rk] = {
            "current": round(curr_p, 2),
            "base": round(base_p, 2),
            "ratio": ratio,
            "trend": trend,
            "change_pct": round(chg, 1),
            "min_corridor": round(base_p * MARKET_MIN_PRICE_FACTOR, 2),
            "max_corridor": round(base_p * MARKET_MAX_PRICE_FACTOR, 2),
        }

    trades_res = await session.execute(
        select(ResourceSale).order_by(desc(ResourceSale.created_at)).limit(10)
    )
    recent_trades = []
    for t in trades_res.scalars().all():
        seller = countries_by_id.get(t.seller_country)
        buyer = countries_by_id.get(t.buyer_country)
        recent_trades.append(
            {
                "id": t.id,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "seller_id": t.seller_country,
                "seller_name": seller.name_fa if seller else f"کشور {t.seller_country}",
                "seller_flag": seller.flag if seller else "🏴",
                "buyer_id": t.buyer_country,
                "buyer_name": buyer.name_fa if buyer else f"کشور {t.buyer_country}",
                "buyer_flag": buyer.flag if buyer else "🏴",
                "resource": t.resource,
                "amount": round(t.amount, 2),
                "price": round(t.price, 2),
                "transport_mode": t.transport_mode,
                "status": t.status,
                "transport_fee": round(t.transport_fee, 2),
                "strait_toll_fee": round(t.strait_toll_fee, 2),
            }
        )

    # ۹. حسابرسی اسنپشات و محاسبه انحراف داده (Audit Delta Check)
    prev_report = await global_reports_repo.get_report_near(
        session, target_time=start_time, period_hours=period_hours
    )
    audit_data: dict[str, dict] = {}
    is_baseline = True
    has_drift = False

    if prev_report and prev_report.payload_json:
        try:
            prev_payload = json.loads(prev_report.payload_json)
            prev_stocks = prev_payload.get("stocks", {})
            if prev_stocks:
                is_baseline = False
                for rtype in ResourceType:
                    rk = rtype.value
                    stk_start = prev_stocks.get(rk, 0.0)
                    stk_end = stocks.get(rk, 0.0)
                    expected_end = stk_start + production.get(rk, 0.0) - total_consumption.get(rk, 0.0)
                    delta = stk_end - expected_end
                    if abs(delta) > 1e-2:
                        has_drift = True
                    audit_data[rk] = {
                        "stock_start": round(stk_start, 2),
                        "stock_end": round(stk_end, 2),
                        "expected_end": round(expected_end, 2),
                        "delta": round(delta, 2),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error parsing prev_report payload_json: %s", exc)
            is_baseline = True

    if is_baseline:
        for rtype in ResourceType:
            rk = rtype.value
            curr = stocks.get(rk, 0.0)
            audit_data[rk] = {
                "stock_start": round(curr, 2),
                "stock_end": round(curr, 2),
                "expected_end": round(curr, 2),
                "delta": 0.0,
            }
        audit_summary = "📌 اسنپشات پایه (نخستین اسنپشات دوره‌ای)"
    elif has_drift:
        audit_summary = "⚠️ عدم انطباق تراز (مشاهده انحراف داده در بازه)"
    else:
        audit_summary = "✅ تراز کامل و پایدار (انحراف صفر)"

    # ۱۰. اسنپشات کشوری برای اکسپورت CSV
    country_stocks_export = []
    for c in countries:
        res_dict = country_reserves_map.get(c.id, {})
        country_stocks_export.append(
            {
                "country_id": c.id,
                "name_fa": c.name_fa,
                "name_en": c.name_en,
                "flag": c.flag,
                "region": c.region,
                "is_vip": c.is_vip,
                "budget": round(c.budget, 2),
                "govt_debt": round(c.govt_debt, 2),
                "credit_rating": c.credit_rating,
                "public_satisfaction": round(c.public_satisfaction, 1),
                "stability": round(c.stability, 1),
                "reserves": {
                    rtype.value: round(res_dict.get(rtype.value, 0.0), 2)
                    for rtype in ResourceType
                },
            }
        )

    # پکیج نهایی گزارش
    payload = {
        "period_hours": period_hours,
        "period_start": start_time.isoformat(),
        "period_end": end_time.isoformat(),
        "generated_at": end_time.isoformat(),
        "stocks": {k: round(v, 2) for k, v in stocks.items()},
        "production": {k: round(v, 2) for k, v in production.items()},
        "consumption": consumption_breakdown,
        "net_flow": {k: round(v, 2) for k, v in net_flow.items()},
        "risk_flags": risk_flags,
        "top_holders": top_holders,
        "macro": macro,
        "market": market_data,
        "trades": recent_trades,
        "audit": {
            "is_baseline": is_baseline,
            "has_drift": has_drift,
            "summary_text": audit_summary,
            "previous_report_id": prev_report.id if (prev_report and not is_baseline) else None,
            "delta_details": audit_data,
        },
        "country_stocks": country_stocks_export,
    }

    short_text = render_short_report(payload)
    report_record = GlobalReport(
        period_hours=period_hours,
        period_start=start_time,
        period_end=end_time,
        generated_at=end_time,
        payload_json=json.dumps(payload, ensure_ascii=False),
        short_text=short_text,
    )
    await global_reports_repo.add_report(session, report_record)
    return report_record, payload


def render_short_report(data: dict) -> str:
    """رندر گزارش خلاصه و متراکم تراز جهانی برای لاگ ۸ ساعته و نمایش سریع."""
    hours = data.get("period_hours", 8)
    macro = data.get("macro", {})
    stocks = data.get("stocks", {})
    prod = data.get("production", {})
    cons = data.get("consumption", {})
    net = data.get("net_flow", {})
    risk = data.get("risk_flags", {})
    audit = data.get("audit", {})

    lines = [
        header(f"گزارش تراز کلان جهانی ({to_fa_digits(hours)} ساعته)", "🌐"),
        "",
        "📊 <b>شاخص‌های کلان سرور:</b>",
        f"💵 نقدینگی کل: {fa_money(macro.get('total_budget', 0))}",
        f"📉 بدهی کل دولت‌ها: {fa_money(macro.get('total_debt', 0))}",
        f"😊 رضایت: میانگین {fa_number(macro.get('mean_sat', 0), 1)}٪ | میانه {fa_number(macro.get('median_sat', 0), 1)}٪",
        f"🏛 ثبات: میانگین {fa_number(macro.get('mean_stab', 0), 1)}٪ | میانه {fa_number(macro.get('median_stab', 0), 1)}٪",
        "",
        "📦 <b>تراز ۸ منبع استراتژیک جهان:</b>",
    ]

    for rtype in ResourceType:
        rk = rtype.value
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        stk = stocks.get(rk, 0.0)
        p = prod.get(rk, 0.0)

        c_info = cons.get(rk, {})
        c_tot = c_info.get("total", 0.0) if isinstance(c_info, dict) else c_info
        nf = net.get(rk, 0.0)

        rf_info = risk.get(rk, {})
        rf_text = rf_info.get("text", "⚪️") if isinstance(rf_info, dict) else "⚪️"

        lines.append(f"{emoji} <b>{name}:</b> {fa_number(stk)} {unit}")
        lines.append(
            f"   ↳ تولید: +{fa_number(p)} | مصرف: -{fa_number(c_tot)} | خالص: {fa_number(nf)} [{rf_text}]"
        )

    audit_txt = audit.get("summary_text", "✅ تراز پایدار")
    lines.append("")
    lines.append(f"🔍 <b>وضعیت حسابرسی (Audit):</b> {audit_txt}")
    return "\n".join(lines)


def render_full_report(data: dict) -> list[str]:
    """
    رندر گزارش جامع تحلیلی ادمین به صورت چندبخشی با تضمین عدم تجاوز از محدودیت طول پیام تلگرام.
    """
    hours = data.get("period_hours", 8)
    macro = data.get("macro", {})
    stocks = data.get("stocks", {})
    prod = data.get("production", {})
    cons = data.get("consumption", {})
    net = data.get("net_flow", {})
    risk = data.get("risk_flags", {})
    top_h = data.get("top_holders", {})
    market = data.get("market", {})
    audit = data.get("audit", {})

    # بخش اول: شاخص‌های مالی و جدول جامع تراز ۸ منبع
    part1_lines = [
        header(f"گزارش تحلیلی تراز جهانی — بخش ۱ ({to_fa_digits(hours)}h)", "📈"),
        "",
        "🏛 <b>شاخص‌های کلان و اعتباری سرور:</b>",
        f"• تعداد کل کشورها: {to_fa_digits(macro.get('total_countries', 0))}",
        f"• نقدینگی کل سرور: {fa_money(macro.get('total_budget', 0))}",
        f"• بدهی کل دولت‌ها: {fa_money(macro.get('total_debt', 0))}",
        f"• رضایت عمومی: میانگین {fa_number(macro.get('mean_sat', 0), 1)}٪ | میانه {fa_number(macro.get('median_sat', 0), 1)}٪",
        f"• ثبات داخلی: میانگین {fa_number(macro.get('mean_stab', 0), 1)}٪ | میانه {fa_number(macro.get('median_stab', 0), 1)}٪",
    ]

    ratings = macro.get("credit_ratings", {})
    if ratings:
        cr_parts = [f"{k}: {to_fa_digits(v)}" for k, v in ratings.items()]
        part1_lines.append(f"• توزیع رتبه‌های اعتباری: {', '.join(cr_parts)}")

    part1_lines.append("")
    part1_lines.append("📊 <b>جدول تفصیلی تراز ذخایر استراتژیک:</b>")

    for rtype in ResourceType:
        rk = rtype.value
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        stk = stocks.get(rk, 0.0)
        p = prod.get(rk, 0.0)
        c_info = cons.get(rk, {})
        c_tot = c_info.get("total", 0.0) if isinstance(c_info, dict) else c_info
        c_ind = c_info.get("industrial", 0.0) if isinstance(c_info, dict) else 0.0
        c_mil = c_info.get("military", 0.0) if isinstance(c_info, dict) else 0.0
        c_eve = c_info.get("events", 0.0) if isinstance(c_info, dict) else 0.0
        nf = net.get(rk, 0.0)
        rf_text = risk.get(rk, {}).get("text", "⚪️")
        top3_pct = top_h.get(rk, {}).get("top3_share_pct", 0.0)

        part1_lines.append(f"{emoji} <b>{name}</b> ({rf_text}):")
        part1_lines.append(f"   • موجودی کل: {fa_number(stk)} {unit} (تمرکز ۳ کشور: {to_fa_digits(top3_pct)}٪)")
        part1_lines.append(f"   • تولید بازه: +{fa_number(p)} {unit}")
        part1_lines.append(
            f"   • مصرف کل: -{fa_number(c_tot)} {unit} [صنعتی: {fa_number(c_ind)} | نظامی: {fa_number(c_mil)} | ساخت‌وساز: {fa_number(c_eve)}]"
        )
        part1_lines.append(f"   • خالص جریان: <b>{fa_number(nf)} {unit}</b>")
        part1_lines.append("")

    part1_text = "\n".join(part1_lines)

    # بخش دوم: بازار، حسابرسی و وضعیت انحراف
    part2_lines = [
        header(f"گزارش تحلیلی تراز جهانی — بخش ۲ ({to_fa_digits(hours)}h)", "💹"),
        "",
        "💹 <b>نرخ‌های لحظه‌ای بازار جهانی WTO:</b>",
    ]

    for rtype in ResourceType:
        rk = rtype.value
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        m_info = market.get(rk, {})
        curr = m_info.get("current", 0.0)
        base = m_info.get("base", 0.0)
        ratio = m_info.get("ratio", 1.0)
        trend = m_info.get("trend", "STABLE")
        chg = m_info.get("change_pct", 0.0)

        t_emoji = "🟢" if trend == "UP" else ("🔴" if trend == "DOWN" else "⚪️")
        part2_lines.append(
            f"{emoji} {name}: {fa_money(curr)} / {unit} | پایه: {fa_money(base)} | ضریب: {to_fa_digits(ratio)}x ({t_emoji} {chg:+.1f}٪)"
        )

    part2_lines.append("")
    part2_lines.append("🔍 <b>حسابرسی داده و مانیتورینگ انحراف (Audit Delta Check):</b>")
    part2_lines.append(f"• وضعیت کلی: <b>{audit.get('summary_text', '')}</b>")

    delta_details = audit.get("delta_details", {})
    if delta_details:
        for rtype in ResourceType:
            rk = rtype.value
            name = RESOURCE_FA.get(rtype, rk)
            unit = RESOURCE_UNIT_FA.get(rtype, "")
            d_info = delta_details.get(rk, {})
            d = d_info.get("delta", 0.0)
            stk_s = d_info.get("stock_start", 0.0)
            exp_e = d_info.get("expected_end", 0.0)
            stk_e = d_info.get("stock_end", 0.0)

            status_icon = "✅" if abs(d) < 1e-2 else "⚠️"
            part2_lines.append(
                f"{status_icon} {name}: شروع={fa_number(stk_s)} | انتظار={fa_number(exp_e)} | واقعی={fa_number(stk_e)} | اختلاف={fa_number(d)} {unit}"
            )

    part2_text = "\n".join(part2_lines)

    # اگر مجموع کاراکترها زیر سقف بود می‌توان یک پیام فرستاد؛ در غیر اینصورت دو پیام
    if len(part1_text) + len(part2_text) < 3800:
        combined = f"{part1_text}\n\n{DIVIDER}\n\n{part2_text}"
        return [combined]
    return [part1_text, part2_text]


def render_top_holders_report(data: dict) -> str:
    """رندر گزارش تمرکز ذخایر و ۳ دارنده برتر هر منبع در جهان."""
    hours = data.get("period_hours", 8)
    top_h = data.get("top_holders", {})
    stocks = data.get("stocks", {})

    lines = [
        header(f"تمرکز ذخایر ۳ دارنده برتر جهان ({to_fa_digits(hours)}h)", "🏆"),
        "فهرست کشورهای دارنده بیشترین ذخایر استراتژیک به همراه سهم درصدی:",
        "",
    ]

    for rtype in ResourceType:
        rk = rtype.value
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        tot = stocks.get(rk, 0.0)
        h_info = top_h.get(rk, {})
        h_list = h_info.get("list", [])
        top3_pct = h_info.get("top3_share_pct", 0.0)

        lines.append(f"{emoji} <b>{name}</b> (موجودی کل: {fa_number(tot)} {unit}):")
        if not h_list:
            lines.append("   - رکوردی برای نمایش وجود ندارد.")
        else:
            for idx, c in enumerate(h_list, 1):
                flag = c.get("flag", "🏴")
                cname = c.get("name", "")
                amt = c.get("amount", 0.0)
                pct = c.get("share_pct", 0.0)
                lines.append(
                    f"   {to_fa_digits(idx)}. {flag} <b>{cname}</b>: {fa_number(amt)} {unit} ({to_fa_digits(pct)}٪)"
                )
        lines.append(f"   ↳ <i>مجموع سهم ۳ کشور برتر: {to_fa_digits(top3_pct)}٪</i>")
        lines.append("")

    return "\n".join(lines)


def render_market_trades_report(data: dict) -> str:
    """رندر وضعیت بازار لحظه‌ای WTO و ۱۰ معامله آخر."""
    hours = data.get("period_hours", 8)
    market = data.get("market", {})
    trades = data.get("trades", [])

    lines = [
        header(f"وضعیت بازار جهانی و معاملات WTO ({to_fa_digits(hours)}h)", "💹"),
        "",
        "📊 <b>نرخ‌های جاری و کریدور قیمتی (۰.۳x تا ۴.۰x):</b>",
    ]

    for rtype in ResourceType:
        rk = rtype.value
        emoji = RESOURCE_EMOJI.get(rtype, "📦")
        name = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        m_info = market.get(rk, {})
        curr = m_info.get("current", 0.0)
        base = m_info.get("base", 0.0)
        ratio = m_info.get("ratio", 1.0)
        trend = m_info.get("trend", "STABLE")
        chg = m_info.get("change_pct", 0.0)
        t_emoji = "🟢" if trend == "UP" else ("🔴" if trend == "DOWN" else "⚪️")

        lines.append(
            f"{emoji} {name}: <b>{fa_money(curr)}</b> / {unit} | ضریب: {to_fa_digits(ratio)}x ({t_emoji} {chg:+.1f}٪)"
        )

    lines.append("")
    lines.append("📦 <b>۱۰ معامله اخیر ثبت‌شده در WTO:</b>")

    if not trades:
        lines.append("هیچ معامله‌ای در تاریخچه اخیر ثبت نشده است.")
    else:
        for t in trades:
            s_flag = t.get("seller_flag", "🏴")
            s_name = t.get("seller_name", "")
            b_flag = t.get("buyer_flag", "🏴")
            b_name = t.get("buyer_name", "")
            r_str = t.get("resource", "")
            try:
                r_enum = ResourceType(r_str)
                r_emoji = RESOURCE_EMOJI.get(r_enum, "📦")
                r_name = RESOURCE_FA.get(r_enum, r_str)
                unit = RESOURCE_UNIT_FA.get(r_enum, "")
            except (ValueError, KeyError):
                r_emoji = "📦"
                r_name = r_str
                unit = ""

            amt = t.get("amount", 0.0)
            price = t.get("price", 0.0)
            mode = t.get("transport_mode", "SEA")
            status = t.get("status", "")
            mode_icon = "🚢" if mode == "SEA" else ("✈️" if mode == "AIR" else "🚛")

            lines.append(
                f"{mode_icon} {s_flag} {s_name} ➔ {b_flag} {b_name} | {r_emoji} {fa_number(amt)} {unit} {r_name} | {fa_money(price)} [{status}]"
            )

    return "\n".join(lines)


def generate_csv_reports(data: dict) -> dict[str, bytes]:
    """
    تولید ۱۰۰٪ در رم ۳ فایل CSV استاندارد با انکودینگ utf-8-sig جهت خوانایی بدون نقص در اکسل ویندوز:
    1. global_resources_ledger.csv: ترازنامه کامل ۸ منبع
    2. country_stocks.csv: موجودی تک‌تک کشورها و شاخص‌های مالی
    3. wto_trades.csv: سوابق معاملات WTO
    """
    csv_files: dict[str, bytes] = {}

    # ۱. global_resources_ledger.csv
    stocks = data.get("stocks", {})
    prod = data.get("production", {})
    cons = data.get("consumption", {})
    net = data.get("net_flow", {})
    risk = data.get("risk_flags", {})
    top_h = data.get("top_holders", {})
    market = data.get("market", {})
    audit_deltas = data.get("audit", {}).get("delta_details", {})

    ledger_buf = io.StringIO()
    ledger_writer = csv.writer(ledger_buf)
    ledger_writer.writerow(
        [
            "Resource",
            "Name_FA",
            "Unit",
            "Global_Stock",
            "Production",
            "Consumption_Industrial",
            "Consumption_Military",
            "Consumption_Events",
            "Total_Consumption",
            "Net_Flow",
            "Risk_Flag",
            "Top3_Share_Pct",
            "Base_Price_USD",
            "Current_Price_USD",
            "Price_Ratio",
            "Audit_Delta",
        ]
    )

    for rtype in ResourceType:
        rk = rtype.value
        name_fa = RESOURCE_FA.get(rtype, rk)
        unit = RESOURCE_UNIT_FA.get(rtype, "")
        stk = stocks.get(rk, 0.0)
        p = prod.get(rk, 0.0)
        c_info = cons.get(rk, {})
        c_tot = c_info.get("total", 0.0) if isinstance(c_info, dict) else c_info
        c_ind = c_info.get("industrial", 0.0) if isinstance(c_info, dict) else 0.0
        c_mil = c_info.get("military", 0.0) if isinstance(c_info, dict) else 0.0
        c_eve = c_info.get("events", 0.0) if isinstance(c_info, dict) else 0.0
        nf = net.get(rk, 0.0)
        rf_text = risk.get(rk, {}).get("text", "")
        top3_pct = top_h.get(rk, {}).get("top3_share_pct", 0.0)
        m_info = market.get(rk, {})
        base_p = m_info.get("base", 0.0)
        curr_p = m_info.get("current", 0.0)
        ratio = m_info.get("ratio", 1.0)
        d_val = audit_deltas.get(rk, {}).get("delta", 0.0)

        ledger_writer.writerow(
            [
                rk,
                name_fa,
                unit,
                stk,
                p,
                c_ind,
                c_mil,
                c_eve,
                c_tot,
                nf,
                rf_text,
                top3_pct,
                base_p,
                curr_p,
                ratio,
                d_val,
            ]
        )

    csv_files["global_resources_ledger.csv"] = ledger_buf.getvalue().encode("utf-8-sig")

    # ۲. country_stocks.csv
    c_stocks = data.get("country_stocks", [])
    country_buf = io.StringIO()
    country_writer = csv.writer(country_buf)

    header_cols = [
        "Country_ID",
        "Country_Name",
        "Country_Name_EN",
        "Flag",
        "Region",
        "Is_VIP",
        "Budget_USD",
        "Govt_Debt_USD",
        "Credit_Rating",
        "Public_Satisfaction",
        "Stability",
    ] + [rtype.value for rtype in ResourceType]

    country_writer.writerow(header_cols)

    for item in c_stocks:
        res_dict = item.get("reserves", {})
        row = [
            item.get("country_id"),
            item.get("name_fa"),
            item.get("name_en"),
            item.get("flag"),
            item.get("region"),
            "YES" if item.get("is_vip") else "NO",
            item.get("budget"),
            item.get("govt_debt"),
            item.get("credit_rating"),
            item.get("public_satisfaction"),
            item.get("stability"),
        ] + [res_dict.get(rtype.value, 0.0) for rtype in ResourceType]
        country_writer.writerow(row)

    csv_files["country_stocks.csv"] = country_buf.getvalue().encode("utf-8-sig")

    # ۳. wto_trades.csv
    trades = data.get("trades", [])
    trades_buf = io.StringIO()
    trades_writer = csv.writer(trades_buf)
    trades_writer.writerow(
        [
            "Trade_ID",
            "Created_At",
            "Seller_ID",
            "Seller_Country",
            "Buyer_ID",
            "Buyer_Country",
            "Resource",
            "Amount",
            "Price_USD",
            "Transport_Mode",
            "Status",
            "Transport_Fee",
            "Strait_Toll",
        ]
    )

    for t in trades:
        trades_writer.writerow(
            [
                t.get("id"),
                t.get("created_at"),
                t.get("seller_id"),
                t.get("seller_name"),
                t.get("buyer_id"),
                t.get("buyer_name"),
                t.get("resource"),
                t.get("amount"),
                t.get("price"),
                t.get("transport_mode"),
                t.get("status"),
                t.get("transport_fee"),
                t.get("strait_toll_fee"),
            ]
        )

    csv_files["wto_trades.csv"] = trades_buf.getvalue().encode("utf-8-sig")
    return csv_files
