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


def render_official_profile(role_key: str, user_name: str | None = None, member: CabinetMember | None = None) -> str:
    """تولید متن معرفی پنل و سربرگ میز کار مقام دولتی به همراه شاخص‌های قدرت v2.6."""
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
    ]

    if member is not None:
        lines.extend([
            f"👑 <b>سرمایه سیاسی:</b> {fa_number(member.political_capital)} / ۱۰۰",
            f"💰 <b>بودجه وزارتخانه:</b> {fa_money(member.allocated_budget)}",
            f"⚡️ <b>امتیاز کارآمدی:</b> {fa_number(member.efficiency_score)}٪",
            f"🕵️ <b>مظنونیت امنیتی:</b> {fa_number(member.leak_suspicion)}٪",
            "────────────────────",
        ])

    lines.extend([
        f"📋 <b>شرح وظایف و اختیارات:</b>\n{desc}",
        "────────────────────",
    ])
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


# ============================================================
#  موتور بحران‌های خودکار (Crisis Engine - v2.6)
# ============================================================

FALLBACK_CRISES = [
    {
        "title": "حمله سایبری گسترده به سرورهای پنتاگون و شبکه بانکی وال‌استریت",
        "description": "یک گروه هکری ناشناس بدافزار پیشرفته‌ای را به سامانه‌های پرداخت فدرال و ارتباطات پنتاگون تزریق کرده و اطلاعات لجستیکی در معرض خطر قرار دارد.",
        "category": "cyber_attack",
        "primary_role": "tech_efficiency",
        "secondary_role": "secretary_defense",
        "severity": 4,
        "options": [
            {"title": "فعال‌سازی قرنطینه کامل سایبری و ارتقای فایروال کوانتومی", "cost_budget": 500.0, "cost_capital": 0, "efficiency_delta": 5},
            {"title": "همکاری اطلاعاتی پنتاگون با غول‌های فناوری سیلیکون‌ولی", "cost_budget": 0.0, "cost_capital": 10, "efficiency_delta": 3},
            {"title": "انکار رسمی حمله و قطع موقت سوئیچ تبادلات بانکی مشکوک", "cost_budget": 0.0, "cost_capital": 0, "efficiency_delta": -5},
        ],
    },
    {
        "title": "شیوع زنجیره‌ای سویه ناشناخته تنفسی و آلودگی شدید منابع آب در اوهایو",
        "description": "گزارش‌های فوری از مراکز درمانی حاکی از شیوع مسمومیت بیولوژیک و افت راندمان نیروی کار در ایالت‌های صنعتی مرکزی است.",
        "category": "health_epidemic",
        "primary_role": "health_crisis",
        "secondary_role": "treasury_secretary",
        "severity": 4,
        "options": [
            {"title": "تخصیص بسته اضطراری درمانی و اعزام تیم‌های FEMA", "cost_budget": 800.0, "cost_capital": 0, "efficiency_delta": 4},
            {"title": "قرنطینه بهداشتی ایالت‌ها و بازرسی فوری کارخانه‌های شیمیایی", "cost_budget": 200.0, "cost_capital": 15, "efficiency_delta": 2},
            {"title": "توزیع گسترده مکمل‌های تقویتی و توصیه‌های ایمنی عمومی", "cost_budget": 50.0, "cost_capital": 5, "efficiency_delta": 0},
        ],
    },
    {
        "title": "نفوذ کارتل‌های فرامرزی در مرز تگزاس و کشف حلقه جاسوسی در پنتاگون",
        "description": "گارد مرزی موفق به رهگیری کاروان سلاح سنگین شده و سیا از افشای برخی کدهای دسترسی نظامی به سفارتخانه‌های رقیب خبر می‌دهد.",
        "category": "border_spy",
        "primary_role": "homeland_security",
        "secondary_role": "cia_director",
        "severity": 3,
        "options": [
            {"title": "عملیات ضربتی دستگیری جاسوسان و بستن کریدورهای مرزی", "cost_budget": 400.0, "cost_capital": 5, "efficiency_delta": 6},
            {"title": "تغذیه اطلاعات گمراه‌کننده به شبکه نفوذ (عملیات فریب)", "cost_budget": 100.0, "cost_capital": 10, "efficiency_delta": 4},
            {"title": "افزایش گشت‌های هوایی با پهپادهای شناسایی بدون سر و صدا", "cost_budget": 250.0, "cost_capital": 0, "efficiency_delta": 2},
        ],
    },
    {
        "title": "موج سنگین اخبار جعلی و انتشار اسناد محرمانه جعلی علیه رئیس‌جمهور",
        "description": "شبکه‌های خبری موج تبلیغاتی هماهنگی در مورد بروز بحران در کابینه به راه انداخته‌اند و شاخص رضایت عمومی دچار تلاطم شده است.",
        "category": "press_scandal",
        "primary_role": "press_secretary",
        "secondary_role": "president",
        "severity": 3,
        "options": [
            {"title": "برگزاری کنفرانس فوری زنده کاخ سفید و افشای عوامل پشت‌پرده", "cost_budget": 50.0, "cost_capital": 10, "efficiency_delta": 5},
            {"title": "شکایت رسمی وزارت دادگستری و جریمه رسانه‌های نشر اکاذیب", "cost_budget": 0.0, "cost_capital": 15, "efficiency_delta": 2},
            {"title": "انتشار دستاوردهای اقتصادی اخیر و نادیده گرفتن حواشی", "cost_budget": 0.0, "cost_capital": 5, "efficiency_delta": 0},
        ],
    },
    {
        "title": "رهگیری اسکادران بمب‌افکن‌های ناشناس در نزدیکی حریم هوایی آلاسکا",
        "description": "رادارهای NORAD و ماهواره‌های هشدار اولیه تحرکات غیرعادی یگان‌های هوایی فراقاره‌ای را در فاصله ۱۰۰ مایلی خاک آمریکا ثبت کرده‌اند.",
        "category": "airspace_threat",
        "primary_role": "joint_chiefs",
        "secondary_role": "centcom_commander",
        "severity": 5,
        "options": [
            {"title": "اسکرامبل فوری جنگنده‌های F-22 و اعلام آمادگی پدافندی", "cost_budget": 600.0, "cost_capital": 5, "efficiency_delta": 5},
            {"title": "ارسال هشدار رادیویی سخت و اخطار شلیک در صورت نقض حریم", "cost_budget": 0.0, "cost_capital": 10, "efficiency_delta": 3},
            {"title": "فراخوان جلسه اضطراری مشاور امنیت ملی و بررسی مسیرها", "cost_budget": 0.0, "cost_capital": 5, "efficiency_delta": 1},
        ],
    },
    {
        "title": "اعتصاب سراسری بنادر شرقی، تشنج بورس و جهش ناگهانی تورم هفتگی",
        "description": "اتحادیه‌های حمل‌ونقل دریایی خطوط تخلیه کانتینرها را متوقف کرده و بهای کالاهای اساسی و انرژی رو به افزایش گذاشته است.",
        "category": "labor_strike",
        "primary_role": "treasury_secretary",
        "secondary_role": "vice_president",
        "severity": 4,
        "options": [
            {"title": "تزریق نقدینگی به زنجیره تامین و توافق اعطای یارانه سوخت", "cost_budget": 1200.0, "cost_capital": 0, "efficiency_delta": 4},
            {"title": "مذاکره مستقیم معاون رئیس‌جمهور با سران اتحادیه‌ها و حل بحران", "cost_budget": 200.0, "cost_capital": 15, "efficiency_delta": 5},
            {"title": "استفاده از اختیارات قانون تافت-هارتلی و الزام به کار فوری", "cost_budget": 0.0, "cost_capital": 20, "efficiency_delta": -2},
        ],
    },
    {
        "title": "شکایت قضایی هماهنگ ۱۲ ایالت علیه دستورات فدرال انرژی و تعرفه‌ها",
        "description": "دادستان‌های ایالتی با تشکیل پرونده در دادگاه‌های استیناف، اجرای تعرفه‌ها و مقررات فدرال را به چالش کشیده‌اند.",
        "category": "states_lawsuit",
        "primary_role": "attorney_general",
        "secondary_role": "vice_president",
        "severity": 3,
        "options": [
            {"title": "دفاعیه محکم در دیوان عالی و اثبات انطباق با اختیارات ریاست‌جمهوری", "cost_budget": 100.0, "cost_capital": 10, "efficiency_delta": 5},
            {"title": "نشست با فرمانداران معترض و تعدیل مفاد مناقشه‌برانگیز", "cost_budget": 300.0, "cost_capital": 10, "efficiency_delta": 3},
            {"title": "اعمال فشار بودجه‌ای فدرال بر ایالت‌های سرکش", "cost_budget": 0.0, "cost_capital": 25, "efficiency_delta": -4},
        ],
    },
]


async def generate_new_crisis(session: AsyncSession) -> Any:
    """تولید یک بحران جدید دو ساعته در صورت وجود ظرفیت."""
    from datetime import datetime, timedelta, timezone
    from ..database.repositories import cabinet as cabinet_repo

    now = datetime.now(timezone.utc)
    template = random.choice(FALLBACK_CRISES)
    expires_at = now + timedelta(hours=2)

    crisis = await cabinet_repo.create_crisis(
        session=session,
        title=template["title"],
        description=template["description"],
        category=template["category"],
        primary_role=template["primary_role"],
        secondary_role=template["secondary_role"],
        severity=template["severity"],
        options=template["options"],
        expires_at=expires_at,
    )
    return crisis


async def resolve_crisis_step(
    session: AsyncSession, crisis_id: int, role_key: str, option_index: int
) -> tuple[bool, str]:
    """ثبت انتخاب راهکار و بررسی حل نهایی بحران."""
    from ..database.repositories import cabinet as cabinet_repo

    crisis = await cabinet_repo.get_crisis(session, crisis_id)
    if not crisis or crisis.status != "ACTIVE":
        return False, "این بحران دیگر فعال نیست."

    import json
    options = json.loads(crisis.options_json)
    if option_index < 0 or option_index >= len(options):
        return False, "راهکار انتخابی نامعتبر است."

    chosen = options[option_index]
    # بررسی و کسر بودجه یا سرمایه سیاسی
    member = await cabinet_repo.get_member_by_role(session, role_key)
    if member:
        cost_budget = chosen.get("cost_budget", 0.0)
        cost_capital = chosen.get("cost_capital", 0)
        if (member.allocated_budget or 0.0) < cost_budget:
            return False, f"بودجه وزارتخانه برای این راهکار کافی نیست (نیاز: {fa_money(cost_budget)})."
        if (member.political_capital or 0) < cost_capital:
            return False, f"سرمایه سیاسی برای این راهکار کافی نیست (نیاز: {cost_capital} واحد)."

        if cost_budget > 0:
            await cabinet_repo.modify_budget(session, role_key, -cost_budget)
        if cost_capital > 0:
            await cabinet_repo.modify_capital(session, role_key, -cost_capital)

    crisis, is_resolved = await cabinet_repo.approve_crisis_option(session, crisis_id, role_key, option_index)
    if is_resolved:
        # اعطای پاداش مهار بحران به هر دو مقام مسئول
        await cabinet_repo.modify_capital(session, crisis.primary_role, 10)
        await cabinet_repo.modify_capital(session, crisis.secondary_role, 10)
        await cabinet_repo.modify_efficiency(session, crisis.primary_role, 5)
        await cabinet_repo.modify_efficiency(session, crisis.secondary_role, 5)
        return True, "✅ بحران با توافق و اقدام مشترک هر دو مقام مسئول با موفقیت مهار شد! (+۱۰ سرمایه سیاسی و +۵ کارآمدی)"

    return True, "✔️ راهکار شما با موفقیت ثبت شد. به محض تایید مقام همکار، بحران مهار خواهد شد."


async def process_crisis_expiration(session: AsyncSession, bot: Any = None) -> list[int]:
    """بررسی و انقضای بحران‌های گذشته از ۲ ساعت و اعمال جریمه‌ها."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from ..database.models.cabinet import CabinetCrisis
    from ..database.repositories import cabinet as cabinet_repo
    from ..services.news_service import send_log, publish_news
    from ..enums import NewsCategory

    now = datetime.now(timezone.utc)
    stmt = select(CabinetCrisis).where(
        CabinetCrisis.status == "ACTIVE",
        CabinetCrisis.expires_at <= now,
    )
    result = await session.execute(stmt)
    expired = list(result.scalars().all())

    failed_ids = []
    usa = await get_usa_country(session)

    for c in expired:
        c.status = "FAILED"
        failed_ids.append(c.id)

        # جریمه دو مقام مسئول
        await cabinet_repo.modify_capital(session, c.primary_role, -10)
        await cabinet_repo.modify_capital(session, c.secondary_role, -10)
        await cabinet_repo.modify_efficiency(session, c.primary_role, -10)
        await cabinet_repo.modify_efficiency(session, c.secondary_role, -10)

        # افت شاخص‌های آمریکا
        if usa:
            usa.public_satisfaction = max(0.0, (usa.public_satisfaction or 60.0) - 5.0)
            usa.stability = max(0.0, (usa.stability or 60.0) - 5.0)

        if bot:
            msg = (
                f"🚨 <b>شکست در مهار بحران ملی ایالات متحده</b>\n\n"
                f"📌 <b>عنوان بحران:</b> {c.title}\n"
                f"⚠️ مقامات مسئول به دلیل عدم اقدام در مهلت ۲ ساعته جریمه شدند. (-۱۰ سرمایه سیاسی و افت رضایت عمومی ملت)"
            )
            try:
                await send_log(bot, msg)
                await publish_news(bot, NewsCategory.DIPLOMACY, msg)
            except Exception:
                pass

    if expired:
        await session.flush()
    return failed_ids


# ============================================================
#  اجرای عملیات‌های زنجیره‌ای تکمیل‌شده (v2.6)
# ============================================================


async def execute_completed_operation(session: AsyncSession, op_id: int) -> tuple[bool, str]:
    """اعمال اثر نهایی پرونده پس از اتمام تمام مراحل زنجیره."""
    from ..database.repositories import cabinet as cabinet_repo

    op = await cabinet_repo.get_operation(session, op_id)
    if not op or op.status != "COMPLETED":
        return False, "پرونده تکمیل نشده است."

    usa = await get_usa_country(session)
    # پاداش سرمایه سیاسی به آغازگر
    await cabinet_repo.modify_capital(session, op.initiator_role, 10)

    if op.op_type == "military_deployment":
        if usa:
            usa.readiness = min(100.0, (usa.readiness or 0.0) + 15.0)
        return True, "🪖 عملیات نظامی با موفقیت نهایی شد و یگان‌ها در مواضع مستقر شدند (+۱۵ آمادگی رزم ارتش)."

    elif op.op_type == "diplomatic_economic":
        if usa:
            usa.economic_power = min(100.0, (usa.economic_power or 50.0) + 2.0)
        return True, "🌐 بسته دیپلماتیک و معاهدات بین‌المللی با امضای رئیس‌جمهور رسمیت یافت و ابلاغ شد."

    elif op.op_type == "aerospace_rd":
        if usa:
            usa.economic_power = min(100.0, (usa.economic_power or 50.0) + 1.5)
        return True, "🚀 پروژه هوافضا و صنایع دفاعی تایید و وارد خط تولید/پرتاب مداری گردید."

    elif op.op_type == "intel_security":
        await cabinet_repo.modify_efficiency(session, "homeland_security", 5)
        await cabinet_repo.modify_efficiency(session, "cia_director", 5)
        return True, "🕵️ عملیات امنیتی مشترک با موفقیت اجرا و تهدید نفوذ خارجی خنثی گردید."

    elif op.op_type == "congressional_bill":
        if usa:
            usa.public_satisfaction = min(100.0, (usa.public_satisfaction or 60.0) + 4.0)
            usa.stability = min(100.0, (usa.stability or 60.0) + 3.0)
        return True, "🏛 لایحه با توشیح رئیس‌جمهور به قانون فدرال ایالات متحده تبدیل شد (+۴ رضایت عمومی)."

    return True, "✅ عملیات با موفقیت تکمیل و ثبت شد."


# ============================================================
#  ابزارهای عملیاتی میز کار ۱۵ مقام (v2.6)
# ============================================================


async def issue_executive_order(
    session: AsyncSession,
    arg2: int | str,
    arg3: str,
    arg4: str | None = None,
) -> tuple[bool, str]:
    """صدور فرمان اجرایی فوری توسط رئیس‌جمهور (هزینه ۲۵ سرمایه سیاسی)."""
    from ..database.repositories import cabinet as cabinet_repo

    if arg4 is not None:
        user_id_or_role = arg2
        title = arg3
        content = arg4
    else:
        if isinstance(arg2, int):
            user_id_or_role = arg2
            title = arg3
            content = ""
        elif arg2 in [r.value for r in CabinetRole] or arg2 == "president":
            user_id_or_role = arg2
            title = arg3
            content = ""
        else:
            user_id_or_role = CabinetRole.PRESIDENT.value
            title = str(arg2)
            content = arg3

    if isinstance(user_id_or_role, int):
        member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
        u_id = user_id_or_role
    else:
        member = await cabinet_repo.get_member_by_role(session, str(user_id_or_role))
        u_id = member.user_id if member and member.user_id else 0

    if not member or member.role_key != CabinetRole.PRESIDENT.value:
        return False, "فقط رئیس‌جمهور ایالات متحده می‌تواند فرمان اجرایی صادر کند."

    if (member.political_capital or 0) < 25:
        return False, "سرمایه سیاسی ناکافی است (حداقل ۲۵ واحد لازم است)."

    await cabinet_repo.modify_capital(session, member.role_key, -25)
    usa = await get_usa_country(session)
    if usa:
        usa.public_satisfaction = min(100.0, (usa.public_satisfaction or 60.0) + 5.0)
        usa.stability = min(100.0, (usa.stability or 60.0) + 4.0)

    order_desc = f"صدور فرمان اجرایی: {title}" + (f" - {content[:40]}" if content else "")
    await cabinet_repo.log_action(session, member.role_key, u_id, "executive_order", order_desc)
    return True, f"📜 فرمان اجرایی «{title}» با توشیح رئیس‌جمهور ابلاغ شد (+۵ رضایت عمومی، +۴ ثبات ملی)."


async def lobby_senate(
    session: AsyncSession,
    user_id_or_role: int | str,
    op_id_or_title: int | str = "",
) -> tuple[bool, str]:
    """لابی‌گری در سنا توسط معاون رئیس‌جمهور (هزینه ۱۰ سرمایه سیاسی)."""
    from ..database.repositories import cabinet as cabinet_repo

    if isinstance(user_id_or_role, int):
        member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
        u_id = user_id_or_role
    else:
        member = await cabinet_repo.get_member_by_role(session, str(user_id_or_role))
        u_id = member.user_id if member and member.user_id else 0

    if not member or member.role_key != CabinetRole.VICE_PRESIDENT.value:
        return False, "فقط معاون رئیس‌جمهور صلاحیت ریاست بر صحن سنا را دارد."

    if (member.political_capital or 0) < 10:
        return False, "سرمایه سیاسی ناکافی برای لابی‌گری در سنا (حداقل ۱۰ واحد)."

    await cabinet_repo.modify_capital(session, member.role_key, -10)

    if isinstance(op_id_or_title, int):
        op, is_done = await cabinet_repo.sign_operation_step(session, op_id_or_title, member.role_key, u_id)
        if not op:
            return False, "پرونده یافت نشد یا در انتظار تایید سنا نیست."
        await cabinet_repo.modify_capital(session, member.role_key, 5)
        return True, "🏛 لابی‌گری با سناتورها موفقیت‌آمیز بود و رای اکثریت سنا اخذ گردید (+۵ سرمایه سیاسی)."
    else:
        bill_title = str(op_id_or_title) if op_id_or_title else "لایحه اضطراری ملی"
        usa = await get_usa_country(session)
        if usa:
            usa.stability = min(100.0, (usa.stability or 60.0) + 3.0)
            usa.public_satisfaction = min(100.0, (usa.public_satisfaction or 60.0) + 2.0)
        await cabinet_repo.modify_capital(session, member.role_key, 5)
        await cabinet_repo.log_action(session, member.role_key, u_id, "senate_lobby", f"لابی‌گری در سنا: {bill_title}")
        return True, f"🏛 لابی‌گری با سناتورها موفقیت‌آمیز بود و رای اکثریت سنا پیرامون «{bill_title}» تصویب شد (+۳ ثبات ملی، +۵ سرمایه سیاسی)."


async def scan_leak_hunter(
    session: AsyncSession, user_id_or_role: int | str | None = None
) -> tuple[bool, str]:
    """اسکن ضدجاسوسی و شناسایی متهمان درز اطلاعات توسط وزیر امنیت داخلی."""
    from ..database.repositories import cabinet as cabinet_repo

    if user_id_or_role is not None:
        if isinstance(user_id_or_role, int):
            member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
        else:
            member = await cabinet_repo.get_member_by_role(session, user_id_or_role)
        if not member or member.role_key != CabinetRole.HOMELAND_SECURITY.value:
            return False, "تنها وزیر امنیت داخلی مجاز به اسکن ضدجاسوسی فدرال است."

    members = await cabinet_repo.list_members(session)
    suspects = []
    lines = ["🔍 <b>نتایج اسکن ضدجاسوسی فدرال (Leak Hunter):</b>"]
    for m in members:
        if (m.leak_suspicion or 0) >= 30:
            suspects.append(m)
            # جریمه سنگین افشاگر
            m.political_capital = max(0, (m.political_capital or 50) - 15)
            m.efficiency_score = max(0, (m.efficiency_score or 80) - 10)
            susp = m.leak_suspicion
            m.leak_suspicion = 0
            lines.append(f"🚨 مقام <b>{m.role_key}</b> با شاخص مظنونیت {susp}٪ شناسایی و توبیخ شد (-۱۵ سرمایه سیاسی، -۱۰ کارآمدی).")

    if not suspects:
        lines.append("✅ هیچ مقام مظنونی در کابینه شناسایی نشد (سوءظن کلیه مقامات زیر ۳۰٪ است).")

    return True, "\n".join(lines)


async def conduct_press_briefing(
    session: AsyncSession, user_id_or_role: int | str, answer: str
) -> tuple[bool, str]:
    """پاسخ به خبرنگاران در کنفرانس خبری کاخ سفید توسط سخنگو."""
    from ..database.repositories import cabinet as cabinet_repo

    if isinstance(user_id_or_role, int):
        member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
        u_id = user_id_or_role
    else:
        member = await cabinet_repo.get_member_by_role(session, user_id_or_role)
        u_id = member.user_id if member and member.user_id else 0

    if not member or member.role_key != CabinetRole.PRESS_SECRETARY.value:
        return False, "فقط سخنگوی کاخ سفید صلاحیت برگزاری نشست خبری را دارد."

    usa = await get_usa_country(session)
    if usa:
        usa.public_satisfaction = min(100.0, (usa.public_satisfaction or 60.0) + 3.0)

    await cabinet_repo.modify_capital(session, member.role_key, 8)
    await cabinet_repo.log_action(session, member.role_key, u_id, "press_briefing", f"کنفرانس مطبوعاتی: {answer[:60]}")
    return True, "🎤 کنفرانس مطبوعاتی با موفقیت برگزار شد (+۳ رضایت عمومی، +۸ سرمایه سیاسی سخنگو)."


async def request_department_budget(
    session: AsyncSession, user_id_or_role: int | str, amount: float, reason: str
) -> tuple[bool, str]:
    """ارسال درخواست بودجه به وزیر خزانه‌داری توسط هر مقام."""
    from ..database.repositories import cabinet as cabinet_repo

    if isinstance(user_id_or_role, int):
        member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
        u_id = user_id_or_role
    else:
        member = await cabinet_repo.get_member_by_role(session, user_id_or_role)
        u_id = member.user_id if member and member.user_id else 0

    if not member:
        return False, "شما دارای سمتی در کابینه نیستید."

    req = await cabinet_repo.create_budget_request(session, member.role_key, u_id, amount, reason)
    return True, f"🏦 درخواست تخصیص بودجه به مبلغ {fa_money(amount)} برای وزیر خزانه‌داری ارسال شد (شماره درخواست: #{req.id})."


async def approve_or_reject_budget_request(
    session: AsyncSession,
    arg2: int | str,
    arg3: int | str | None = None,
    action: str | bool = True,
    notes: str = "",
) -> tuple[bool, str]:
    """تایید یا رد درخواست بودجه توسط وزیر خزانه‌داری."""
    from ..database.repositories import cabinet as cabinet_repo

    if isinstance(arg3, int) or (isinstance(arg3, str) and arg3.isdigit()):
        user_id_or_role = arg2
        req_id = int(arg3)
    else:
        user_id_or_role = CabinetRole.TREASURY_SECRETARY.value
        req_id = int(arg2)
        if arg3 is not None:
            action = arg3

    if isinstance(user_id_or_role, int):
        treasury_member = await cabinet_repo.get_member_by_user(session, user_id_or_role)
    else:
        treasury_member = await cabinet_repo.get_member_by_role(session, user_id_or_role)

    if not treasury_member or treasury_member.role_key != CabinetRole.TREASURY_SECRETARY.value:
        return False, "فقط وزیر خزانه‌داری مجاز به تایید و تخصیص بودجه است."

    req = await cabinet_repo.get_budget_request(session, req_id)
    if not req or req.status != "pending":
        return False, "درخواست بودجه یافت نشد یا قبلاً بررسی شده است."

    usa = await get_usa_country(session)
    is_approve = action in ("approve", True)
    is_half = action == "half"

    if is_approve:
        alloc_amount = req.amount
        if usa and usa.budget < alloc_amount:
            return False, "خزانه فدرال برای این تخصیص موجودی کافی ندارد."
        if usa:
            usa.budget -= alloc_amount
        await cabinet_repo.modify_budget(session, req.requester_role, alloc_amount)
        await cabinet_repo.resolve_budget_request(session, req_id, "approved", notes)
        await cabinet_repo.modify_capital(session, treasury_member.role_key, 5)
        return True, f"✅ درخواست بودجه تایید و مبلغ {fa_money(alloc_amount)} به حساب وزارتخانه واریز شد."

    elif is_half:
        alloc_amount = req.amount / 2.0
        if usa and usa.budget < alloc_amount:
            return False, "خزانه فدرال برای این تخصیص موجودی کافی ندارد."
        if usa:
            usa.budget -= alloc_amount
        req.amount = alloc_amount
        await cabinet_repo.modify_budget(session, req.requester_role, alloc_amount)
        await cabinet_repo.resolve_budget_request(session, req_id, "adjusted", notes)
        await cabinet_repo.modify_capital(session, treasury_member.role_key, 3)
        return True, f"✂️ درخواست بودجه تعدیل شد و مبلغ ۵۰٪ ({fa_money(alloc_amount)}) به حساب وزارتخانه واریز شد."

    else:
        await cabinet_repo.resolve_budget_request(session, req_id, "rejected", notes)
        return True, f"❌ درخواست بودجه رد شد: {notes}"


async def leak_confidential_info(
    session: AsyncSession,
    user_id_or_role: int | str | None = None,
    target_role: str = "",
    headline: str = "",
    content: str = "",
    leaker_role: int | str | None = None,
) -> tuple[bool, str]:
    """درز دادن اطلاعات ناشناس علیه یک وزارتخانه به رسانه‌ها."""
    from ..database.repositories import cabinet as cabinet_repo

    actual_user_or_role = leaker_role if leaker_role is not None else user_id_or_role
    if isinstance(actual_user_or_role, int):
        member = await cabinet_repo.get_member_by_user(session, actual_user_or_role)
        u_id = actual_user_or_role
    else:
        member = await cabinet_repo.get_member_by_role(session, actual_user_or_role)
        u_id = member.user_id if member and member.user_id else 0

    if not member:
        return False, "شما عضوی از کابینه نیستید."

    # ثبت افشاگری
    await cabinet_repo.create_leak(session, member.role_key, u_id, target_role, headline, content)
    # جریمه قربانی: -10 سرمایه سیاسی
    await cabinet_repo.modify_capital(session, target_role, -10)
    # افزایش سوءظن افشاگر: +30
    await cabinet_repo.modify_leak_suspicion(session, member.role_key, 30)

    # اثر منفی بر رضایت عمومی کشور
    usa = await get_usa_country(session)
    if usa:
        usa.public_satisfaction = max(0.0, (usa.public_satisfaction or 60.0) - 2.0)

    return True, "📰 اسناد به صورت ناشناس در اختیار رسانه‌ها قرار گرفت (-۱۰ سرمایه سیاسی مقام هدف، +۳۰ سوءظن امنیتی شما)."


async def claim_agenda_reward(session: AsyncSession, user_id_or_agenda_id: int) -> tuple[bool, str]:
    """بررسی و دریافت پاداش ماموریت مخفی ۲۴ ساعته مقام."""
    from ..database.repositories import cabinet as cabinet_repo

    agenda = await cabinet_repo.get_agenda(session, user_id_or_agenda_id)
    if not agenda:
        member = await cabinet_repo.get_member_by_user(session, user_id_or_agenda_id)
        if member:
            agenda = await cabinet_repo.get_active_agenda(session, member.role_key)

    if not agenda:
        return False, "ماموریت فعالی برای دریافت پاداش یافت نشد."

    if not agenda.is_completed:
        return False, "شما هنوز ماموریت خود را به اتمام نرسانده‌اید."

    # پاداش تکمیل ماموریت
    reward = agenda.reward_capital or 15
    await cabinet_repo.modify_capital(session, agenda.role_key, reward)
    await cabinet_repo.complete_agenda(session, agenda.id)
    return True, f"🎯 ماموریت «{agenda.title}» تکمیل شد و {reward} واحد سرمایه سیاسی به شما تعلق گرفت!"

