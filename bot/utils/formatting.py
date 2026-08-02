"""رندر پنل‌های نمایشی (اقتصاد، ذخایر، نظامی) مطابق فرمت پلی‌بوک."""

from __future__ import annotations

from collections import OrderedDict

from ..database.models import Country, MilitaryAsset, Reserve
from ..enums import (
    RESOURCE_EMOJI,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    ResourceType,
)
from .numbers import fa_money, fa_number

# نگاشت مقادیر داخلی به متن فارسی برای نمایش
_GROWTH_FA = {"up": "⬆️ صعودی", "flat": "➡️ ثابت", "down": "⬇️ نزولی"}
_ENERGY_FA = {
    "weak": "ضعیف",
    "medium": "متوسط",
    "good": "خوب",
    "excellent": "عالی",
}
_TRADE_FA = {"negative": "منفی", "balanced": "متعادل", "positive": "مثبت"}


def render_economy_panel(country: Country) -> str:
    """📊 گزارش وضعیت اقتصادی کشور (فرمت پلی‌بوک)."""
    lines = [
        "📊 <b>گزارش وضعیت اقتصادی کشور</b>",
        f"🏴 کشور: {country.flag} {country.name_fa}",
        f"💰 قدرت اقتصاد: {fa_number(country.economic_power)} / ۱۰۰",
        f"💸 بودجه: {fa_money(country.budget)}",
        f"📈 رشد اقتصادی: {_GROWTH_FA.get(country.growth, country.growth)}",
        f"💸 نرخ تورم: {fa_number(country.inflation, 1)}٪",
        f"👥 بیکاری: {fa_number(country.unemployment, 1)}٪",
        f"⚡ وضعیت انرژی: {_ENERGY_FA.get(country.energy_status, country.energy_status)}",
        f"📦 تجارت خارجی: {_TRADE_FA.get(country.foreign_trade, country.foreign_trade)}",
        f"📉 بدهی دولت: {fa_money(country.govt_debt)}",
        f"😊 رضایت عمومی: {fa_number(country.public_satisfaction)} / ۱۰۰",
        f"🏛 ثبات داخلی: {fa_number(country.stability)} / ۱۰۰",
    ]
    return "\n".join(lines)


def render_reserves_panel(country: Country, reserves: list[Reserve]) -> str:
    """نمایش لیست ذخایر یک کشور."""
    lines = [f"📦 <b>ذخایر استراتژیک {country.flag} {country.name_fa}</b>", ""]
    # ترتیب نمایش بر اساس ترتیب تعریف‌شده در ResourceType
    by_type = {r.resource: r for r in reserves}
    for rtype in ResourceType:
        r = by_type.get(rtype.value)
        if r is None:
            continue
        emoji = RESOURCE_EMOJI[rtype]
        name = RESOURCE_FA[rtype]
        unit = RESOURCE_UNIT_FA[rtype]
        extract = "✅" if r.can_extract else "🚫"
        lines.append(
            f"{emoji} {name}: {fa_number(r.amount)} {unit}  (استخراج: {extract})"
        )
    return "\n".join(lines)


# ترتیب نمایش زیربخش‌های نظامی مطابق فرمت پلی‌بوک (نه الفبایی).
# (v1.11.1) همین ترتیب مبنای صفحه‌بندی پنل تجهیزات است: هر زیربخش = یک صفحه.
MILITARY_BRANCH_ORDER: list[str] = [
    "نیروی زمینی",
    "سامانه‌های دفاعی",
    "خودروهای زمینی",
    "نیروی هوایی",
    "نیروی دریایی",
    "سامانه‌های حمله هوایی",
]

# ایموجی هر زیربخش برای سربرگ صفحه
MILITARY_BRANCH_EMOJI: dict[str, str] = {
    "نیروی زمینی": "🪖",
    "سامانه‌های دفاعی": "🛡",
    "خودروهای زمینی": "🚙",
    "نیروی هوایی": "✈️",
    "نیروی دریایی": "🚢",
    "سامانه‌های حمله هوایی": "🚀",
}


def group_military_by_branch(
    assets: list[MilitaryAsset],
) -> "OrderedDict[str, OrderedDict[str, list[MilitaryAsset]]]":
    """
    تجهیزات را به زیربخش → دسته → اقلام گروه‌بندی می‌کند (با ترتیب پلی‌بوک).

    اقلام با موجودی صفر نمایش داده نمی‌شوند.
    """
    branches: "OrderedDict[str, OrderedDict[str, list[MilitaryAsset]]]" = OrderedDict()
    for a in assets:
        if a.count <= 0:
            continue
        branches.setdefault(a.branch or "سایر", OrderedDict()).setdefault(
            a.category, []
        ).append(a)

    # مرتب‌سازی بر اساس ترتیب پلی‌بوک؛ زیربخش‌های ناشناس آخر می‌آیند
    return OrderedDict(
        sorted(
            branches.items(),
            key=lambda kv: MILITARY_BRANCH_ORDER.index(kv[0])
            if kv[0] in MILITARY_BRANCH_ORDER
            else len(MILITARY_BRANCH_ORDER),
        )
    )


def military_branch_pages(assets: list[MilitaryAsset]) -> list[str]:
    """
    فهرست زیربخش‌هایی که کشور در آن‌ها تجهیزات دارد (به ترتیب پلی‌بوک).

    هر عضو این فهرست یک «صفحه» در پنل تجهیزات است.
    """
    return list(group_military_by_branch(assets).keys())


def render_military_branch(
    country: Country,
    assets: list[MilitaryAsset],
    branch: str,
    *,
    page_index: int = 0,
    page_total: int = 1,
) -> str:
    """
    ⚔️ رندر **یک زیربخش** از تجهیزات کشور (یک صفحه از پنل).

    (v1.11.1) جایگزین نمایش یک‌جای همه‌ی تجهیزات؛ چون متن کامل از سقف پیام
    تلگرام رد می‌شد و بریده می‌شد.
    """
    grouped = group_military_by_branch(assets)
    categories = grouped.get(branch, OrderedDict())
    emoji = MILITARY_BRANCH_EMOJI.get(branch, "⚔️")

    total_units = sum(item.count for items in categories.values() for item in items)

    lines = [
        f"{emoji} <b>«{branch}»</b> {emoji}",
        f"🏴 {country.flag} {country.name_fa}",
        f"📦 مجموع: {fa_number(total_units)} واحد "
        f"| 📄 صفحه {fa_number(page_index + 1)} از {fa_number(page_total)}",
        "",
    ]

    if not categories:
        lines.append("—  در این زیربخش تجهیزاتی ثبت نشده است.")
        return "\n".join(lines)

    for category, items in categories.items():
        lines.append(f"• <u>{category}</u>:")
        for item in items:
            lines.append(f"   ◦ {item.name} — {fa_number(item.count)} {item.unit}")
        lines.append("")

    return "\n".join(lines).strip()


def render_military_panel(country: Country, assets: list[MilitaryAsset]) -> str:
    """
    ⚔️ پنل اطلاعات نیروها (فرمت پلی‌بوک)، گروه‌بندی‌شده بر اساس زیربخش.

    نمایش یک‌جای همه‌ی زیربخش‌ها؛ برای متن‌های بلند از نسخه‌ی صفحه‌بندی‌شده
    (`render_military_branch`) استفاده کنید.
    """
    lines = [
        "⚔️ <b>«اطلاعات نیروها»</b> ⚔️",
        f"🏴 نام کشور: {country.name_fa} {country.flag}",
        f"👥 جمعیت کشور: {fa_number(country.population)} نفر",
        "",
    ]

    for branch, categories in group_military_by_branch(assets).items():
        lines.append(f"⚔️ <b>«{branch}»</b> ⚔️")
        for category, items in categories.items():
            lines.append(f"• <u>{category}</u>:")
            for item in items:
                lines.append(
                    f"   ◦ {item.name} — {fa_number(item.count)} {item.unit}"
                )
        lines.append("")

    return "\n".join(lines).strip()
