"""سرویس منطق بازی برای گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import CABINET_ROLES_DATA
from ..database.models import Country
from ..database.repositories import (
    cabinet as cabinet_repo,
    countries as countries_repo,
    military as military_repo,
    military_bases as bases_repo,
    nuclear as nuclear_repo,
    satellites as sat_repo,
)
from ..enums import CabinetRole
from ..utils.numbers import fa_number, fa_money


# وضعیت پیش‌فرض سیستم‌های سراسری دولت آمریکا
_GLOBAL_CABINET_STATE = {
    "defcon": 3,                    # DEFCON 1 تا 5 (پیش‌فرض 3: آمادگی متوسط نیروهای مسلح)
    "cyber_shield": "فعال (🟢)",    # وضعیت پدافند سایبری
    "threat_level": "زرد (مراقبتی)", # سطح هشدار امنیت ملی
    "health_index": 78.5,           # شاخص بهداشت و مدیریت بحران
}


def get_defcon_level() -> int:
    return _GLOBAL_CABINET_STATE["defcon"]


def set_defcon_level(level: int) -> int:
    level = max(1, min(5, level))
    _GLOBAL_CABINET_STATE["defcon"] = level
    return level


async def get_usa_country(session: AsyncSession) -> Country | None:
    """دریافت رکورد کشور ایالات متحده آمریکا از پایگاه داده با تمام روابط."""
    usa = await countries_repo.get_country_by_name(session, "USA")
    if usa is not None:
        return await countries_repo.get_country_with_relations(session, usa.id)
    return None


def can_access_domain(role_key: str, domain: str) -> bool:
    """بررسی اینکه آیا این مقام به حوزه اطلاعاتی مشخص دسترسی مستقیم دارد یا خیر."""
    role_enum = CabinetRole(role_key) if role_key in [r.value for r in CabinetRole] else None
    if not role_enum or role_enum not in CABINET_ROLES_DATA:
        return False

    allowed = CABINET_ROLES_DATA[role_enum].get("allowed_domains", [])
    return domain in allowed


def render_official_profile(role_key: str, user_name: str | None = None) -> str:
    """تولید متن معرفی پنل و سربرگ میز کار مقام دولتی."""
    role_enum = CabinetRole(role_key) if role_key in [r.value for r in CabinetRole] else None
    data = CABINET_ROLES_DATA.get(role_enum, {}) if role_enum else {}

    icon = data.get("icon", "🏛")
    title = data.get("title_fa", "مقام دولتی")
    official_name = data.get("official_name", "—")
    dept = data.get("department", "دولت فدرال")
    desc = data.get("description", "")

    player_str = f"👤 بازیکن متصدی: <b>{user_name}</b>" if user_name else "⚪️ وضعیت سمت: <i>خالی (بدون متصدی)</i>"

    lines = [
        f"{icon} <b>میز کار: {title}</b>",
        f"🇺🇸 <b>شخصیت رسمی:</b> {official_name}",
        f"🏛 <b>ارگان:</b> {dept}",
        f"{player_str}",
        "────────────────────",
        f"📋 <b>شرح وظایف و اختیارات:</b>\n{desc}",
        "────────────────────",
    ]
    return "\n".join(lines)


async def render_domain_report(
    session: AsyncSession, domain: str, role_key: str
) -> str:
    """رندر گزارش رسمی یک حوزه اطلاعاتی برای مقام دارای دسترسی یا استعلام‌شده."""
    usa = await get_usa_country(session)
    if usa is None:
        return "⚠️ اطلاعات پایه کشور ایالات متحده در دسترس نیست."

    if domain == "economy":
        reserves_text = ""
        for r in usa.reserves:
            from ..enums import RESOURCE_EMOJI, RESOURCE_FA, RESOURCE_UNIT_FA
            emoji = RESOURCE_EMOJI.get(r.resource_type, "📦")
            name = RESOURCE_FA.get(r.resource_type, r.resource_type.value)
            unit = RESOURCE_UNIT_FA.get(r.resource_type, "")
            reserves_text += f"\n  {emoji} {name}: <b>{fa_number(r.amount)}</b> {unit}"

        return (
            "💰 <b>گزارش محرمانه خزانه‌داری و وضعیت اقتصادی آمریکا</b>\n\n"
            f"💵 <b>بودجه در دسترس:</b> {fa_money(usa.budget)}\n"
            f"📈 <b>قدرت اقتصادی:</b> {fa_number(usa.economic_power)}/۱۰۰\n"
            f"📉 <b>تورم ملی:</b> {fa_number(usa.inflation)}٪\n"
            f"👥 <b>نرخ بیکاری:</b> {fa_number(usa.unemployment)}٪\n"
            f"🏛 <b>بدهی ملی فدرال:</b> {fa_money(usa.govt_debt)}\n"
            f"💵 <b>نرخ مالیات فدرال:</b> {fa_number(usa.tax_rate)}٪\n"
            f"📊 <b>رتبه اعتباری بین‌المللی:</b> {usa.credit_rating}\n\n"
            f"📦 <b>ذخایر استراتژیک ملی:</b>{reserves_text or ' (در حال بارگذاری)'}"
        )

    elif domain == "military":
        defcon = get_defcon_level()
        defcon_emojis = {1: "🔴 DEFCON 1 (جنگ اتمی)", 2: "🟠 DEFCON 2 (فوق‌العاده)", 3: "🟡 DEFCON 3 (آماده‌باش)", 4: "🟢 DEFCON 4 (پایش)", 5: "⚪️ DEFCON 5 (صلح)"}
        defcon_str = defcon_emojis.get(defcon, f"DEFCON {defcon}")

        assets_count = len(usa.military_assets)
        bases = await bases_repo.list_by_country(session, usa.id)
        satellites = await sat_repo.list_by_country(session, usa.id)
        nuke_prog = await nuclear_repo.get_program(session, usa.id)
        nuke_status = "فعال و بازدارنده ☢️" if nuke_prog else "بازدارندگی راهبردی فعال (زرادخانه آماده)"

        return (
            "🛡 <b>گزارش وضعیت رزمی و توان دفاعی پنتاگون</b>\n\n"
            f"🚨 <b>سطح هشدار آمادگی دفاعی:</b> {defcon_str}\n"
            f"⚔️ <b>اقلام تسلیحاتی ثبت‌شده:</b> {fa_number(assets_count)} رده\n"
            f"🏗 <b>پایگاه‌های نظامی فعال:</b> {fa_number(len(bases))} پایگاه\n"
            f"📡 <b>ماهواره‌های فضایی در مدار:</b> {fa_number(len(satellites))} ماهواره\n"
            f"☢️ <b>وضعیت زرادخانه هسته‌ای:</b> {nuke_status}\n"
            f"🛡 <b>ثبات امنیتی داخلی:</b> {fa_number(usa.stability)}/۱۰۰"
        )

    elif domain == "intel":
        return (
            "🕵️ <b>بولتن روزانه سازمان اطلاعات مرکزی (سیا) و امنیت داخلی</b>\n\n"
            f"🚨 <b>سطح هشدار امنیت ملی:</b> {_GLOBAL_CABINET_STATE['threat_level']}\n"
            f"🛡 <b>وضعیت سپر دفاع سایبری:</b> {_GLOBAL_CABINET_STATE['cyber_shield']}\n"
            f"👁 <b>شاخص اشراف اطلاعاتی بر رقبا:</b> ۹۴/۱۰۰\n"
            f"🌐 <b>رصد تحرکات بلوک‌های متخاصم:</b> تحت کنترل\n"
            "🔍 <b>پرونده‌های فعال ضدجاسوسی:</b> ۳ مورد در دست بررسی فدرال"
        )

    elif domain == "diplomacy":
        return (
            "🌍 <b>گزارش دیپلماسی بین‌المللی و روابط خارجی آمریکا</b>\n\n"
            f"🤝 <b>عضویت در پیمان‌ها و اتحادها:</b> ناتو (NATO)، متحدان کلیدی\n"
            f"🚫 <b>بسته‌های تحریمی فعال ایالات متحده:</b> نظارت کامل بر WTO\n"
            f"💵 <b>عوارض بین‌المللی جمع‌آوری‌شده:</b> {fa_money(usa.international_duties)}\n"
            f"🌐 <b>تراز تجاری بین‌المللی:</b> {usa.foreign_trade}"
        )

    elif domain == "tech":
        return (
            "💻 <b>گزارش دپارتمان کارآمدی (DOGE) و فناوری‌های پیشرفته</b>\n\n"
            "⚡️ <b>بهره‌وری اداری دولت فدرال:</b> ۸۲٪ (روند صعودی 📈)\n"
            "🤖 <b>پروژه‌های اتوماسیون با هوش مصنوعی:</b> فعال در ۱۲ وزارتخانه\n"
            "🛡 <b>سامانه دفاع سایبری ملی:</b> غیرقابل نفوذ\n"
            "💡 <b>پیشنهاد صرفه‌جویی بودجه جاری:</b> شناسایی ۱۸۰ میلیارد دلار ریخت‌وپاش زائد"
        )

    elif domain == "justice":
        inspections = await cabinet_repo.list_inspections(session, limit=5)
        insp_str = f"{len(inspections)} پرونده جاری" if inspections else "بدون پرونده فساد باز"
        return (
            "⚖️ <b>گزارش بازرسی و سلامت اداری وزارت دادگستری (DOJ)</b>\n\n"
            "🏛 <b>شاخص سلامت اداری و شفافیت:</b> ۹۱/۱۰۰\n"
            f"🔍 <b>پرونده‌های بازرسی ویژه:</b> {insp_str}\n"
            "⚖️ <b>تطابق مصوبات با قانون اساسی:</b> ۱۰۰٪ مورد تایید دادستان کل"
        )

    elif domain == "health":
        return (
            "☣️ <b>گزارش بهداشت، غذا و مدیریت بحران‌های ملی (HHS / RFK Jr.)</b>\n\n"
            f"🏥 <b>شاخص سلامت و نشاط عمومی ملت:</b> {fa_number(_GLOBAL_CABINET_STATE['health_index'])}/۱۰۰\n"
            "🚨 <b>وضعیت اپیدمی و تهدیدات بیولوژیک:</b> سفید و ایمن 🟢\n"
            "🍎 <b>اصلاحات استاندارد غذایی و دارویی:</b> در حال اجرا\n"
            "📦 <b>ذخایر استراتژیک بحران ملی:</b> تکمیل ۱۰۰٪"
        )

    elif domain == "press":
        return (
            "🎤 <b>گزارش دفتر مطبوعاتی کاخ سفید و نبض افکار عمومی</b>\n\n"
            f"👥 <b>شاخص رضایت عمومی از دولت:</b> {fa_number(usa.public_satisfaction)}٪\n"
            f"📰 <b>جو رسانه‌ای رسانه‌های داخلی:</b> در کنترل و هدایت\n"
            "📺 <b>آخرین کنفرانس خبری کاخ سفید:</b> منتشر شده در کانال رسمی"
        )

    return "گزارش مورد نظر یافت نشد."


def perform_doge_audit(target_role: str) -> dict[str, Any]:
    """انجام ممیزی کارآمدی سازمان‌ها توسط DOGE (ایلان ماسک / ویوک راماسوامی)."""
    role_enum = CabinetRole(target_role) if target_role in [r.value for r in CabinetRole] else None
    role_title = CABINET_ROLES_DATA.get(role_enum, {}).get("title_fa", target_role) if role_enum else target_role

    savings = random.randint(15, 85) * 1_000_000_000  # بین ۱۵ تا ۸۵ میلیارد دلار
    efficiency_gain = random.uniform(2.5, 8.0)
    recommendations = [
        "حذف برنامه‌های بوروکراتیک بدون خروجی ملموس",
        "جایگزینی سامانه‌های سنتی کاغذی با دستیارهای هوش مصنوعی",
        "تعدیل قراردادهای پیمانکاری گران‌قیمت با شرکت‌های وابسته",
        "ادغام دپارتمان‌های موازی و کاهش جلسات اداری بی‌فایده",
    ]
    return {
        "target_title": role_title,
        "savings": savings,
        "efficiency_gain": round(efficiency_gain, 1),
        "recommendation": random.choice(recommendations),
    }
