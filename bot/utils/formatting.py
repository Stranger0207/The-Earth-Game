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


def render_military_panel(country: Country, assets: list[MilitaryAsset]) -> str:
    """⚔️ پنل اطلاعات نیروها (فرمت پلی‌بوک)، گروه‌بندی‌شده بر اساس زیربخش."""
    lines = [
        "⚔️ <b>«اطلاعات نیروها»</b> ⚔️",
        f"🏴 نام کشور: {country.name_fa} {country.flag}",
        f"👥 جمعیت کشور: {fa_number(country.population)} نفر",
        "",
    ]

    # گروه‌بندی تجهیزات بر اساس زیربخش (branch) و سپس دسته (category)
    branches: "OrderedDict[str, OrderedDict[str, list[MilitaryAsset]]]" = OrderedDict()
    for a in assets:
        branches.setdefault(a.branch or "سایر", OrderedDict()).setdefault(
            a.category, []
        ).append(a)

    for branch, categories in branches.items():
        lines.append(f"⚔️ <b>«{branch}»</b> ⚔️")
        for category, items in categories.items():
            lines.append(f"• <u>{category}</u>:")
            for item in items:
                lines.append(
                    f"   ◦ {item.name} — {fa_number(item.count)} {item.unit}"
                )
        lines.append("")

    return "\n".join(lines).strip()
