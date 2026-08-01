"""
تبدیل نتیجه‌ی خام نبرد به واقعیت‌های خبری (v1.10.6).

موتور نبرد اعداد می‌دهد؛ این ماژول آن‌ها را به متن فارسی خوانا تبدیل می‌کند
تا خبرنویس AI فقط «روایت» کند، نه اینکه عدد از خودش دربیاورد.

همچنین قالب‌های پشتیبان (بدون AI) اینجاست تا اگر هوش مصنوعی در دسترس نبود،
خبر همچنان منتشر شود و متن‌ها تکراری هم نباشند.
"""

from __future__ import annotations

import random

from ...enums import OPERATION_FA, TARGET_FA, OperationType, TargetType
from ...utils.numbers import fa_number

# ---------- نقشه‌ی فازهای خبری ----------
# بر اساس تعداد فاز (که موتور نبرد از شدت عملیات تعیین می‌کند)
_PHASE_PLANS: dict[int, list[str]] = {
    3: ["opening", "damage", "summary"],
    5: ["opening", "defense", "damage", "reaction", "summary"],
    7: ["opening", "defense", "damage", "second_wave", "damage", "reaction", "summary"],
    9: [
        "opening", "defense", "damage", "second_wave", "defense",
        "damage", "reaction", "reaction", "summary",
    ],
}


def phase_plan(total_phases: int) -> list[str]:
    """فهرست نوع فازها برای یک عملیات با تعداد فاز مشخص."""
    if total_phases in _PHASE_PLANS:
        return list(_PHASE_PLANS[total_phases])
    # تعداد غیراستاندارد: از نزدیک‌ترین نقشه استفاده و کوتاه/بلند کن
    nearest = min(_PHASE_PLANS, key=lambda k: abs(k - total_phases))
    plan = list(_PHASE_PLANS[nearest])
    while len(plan) < total_phases:
        plan.insert(-1, "damage")
    return plan[:total_phases]


def _losses_text(losses: list[dict]) -> str:
    """تلفات تجهیزات را به متن فارسی تبدیل می‌کند."""
    if not losses:
        return "بدون تلفات تجهیزاتی گزارش‌شده"
    parts = [
        f"{fa_number(item.get('count', 0))} {item.get('unit', 'عدد')} {item.get('name', '')}".strip()
        for item in losses[:5]
        if item.get("count")
    ]
    return "، ".join(parts) if parts else "بدون تلفات تجهیزاتی گزارش‌شده"


def facts_to_text(facts: dict, phase_kind: str) -> str:
    """
    واقعیت‌های مرتبط با یک فاز خبری را به متن فارسی برمی‌گرداند.
    هر فاز فقط داده‌ی مربوط به خودش را می‌بیند تا خبرها محتوای متفاوتی داشته باشند.
    """
    attacker = facts.get("attacker", "کشور مهاجم")
    defender = facts.get("defender", "کشور مدافع")

    try:
        op_fa = OPERATION_FA[OperationType(facts.get("operation_type", ""))]
    except (ValueError, KeyError):
        op_fa = "عملیات نظامی"
    try:
        target_fa = TARGET_FA[TargetType(facts.get("target_type", ""))]
    except (ValueError, KeyError):
        target_fa = "هدف نظامی"

    common = [f"مهاجم: {attacker}", f"مدافع: {defender}", f"نوع عملیات: {op_fa}", f"هدف: {target_fa}"]
    attack_assets = facts.get("top_attack_assets") or []
    defense_assets = facts.get("top_defense_assets") or []

    if phase_kind == "opening":
        common.append(f"تجهیزات اصلی مهاجم: {'، '.join(attack_assets) or 'نامشخص'}")
        common.append(f"تعداد کل واحدهای درگیر: {fa_number(facts.get('units_committed', 0))}")
        if facts.get("distance_km"):
            common.append(f"فاصله‌ی هدف: {fa_number(facts['distance_km'])} کیلومتر")

    elif phase_kind == "defense":
        common.append(f"سامانه‌های پدافندی فعال مدافع: {'، '.join(defense_assets) or 'نامشخص'}")
        common.append(f"درصد رهگیری موفق پدافند: {fa_number(facts.get('intercept_pct', 0))}٪")
        if facts.get("patrol_active"):
            common.append("گشت دفاعی مدافع در منطقه فعال بود و در رهگیری نقش داشت")

    elif phase_kind == "damage":
        common.append(f"درصد خسارت به هدف: {fa_number(facts.get('infra_damage_pct', 0))}٪")
        common.append(f"تلفات تجهیزات مدافع: {_losses_text(facts.get('defender_losses', []))}")
        if facts.get("civilian_casualties"):
            common.append(f"تلفات غیرنظامی: {fa_number(facts['civilian_casualties'])} نفر")

    elif phase_kind == "second_wave":
        common.append("موج دوم حمله در جریان است")
        common.append(f"تجهیزات درگیر: {'، '.join(attack_assets) or 'نامشخص'}")
        common.append(f"تلفات مهاجم تا این لحظه: {_losses_text(facts.get('attacker_losses', []))}")

    elif phase_kind == "reaction":
        common.append(f"نتیجه‌ی فعلی درگیری: {facts.get('outcome', 'نامشخص')}")
        if facts.get("civilian_casualties"):
            common.append(f"تلفات غیرنظامی: {fa_number(facts['civilian_casualties'])} نفر (زمینه‌ی محکومیت بین‌المللی)")
        if facts.get("nuclear_deterrence"):
            common.append("مدافع دارای زرادخانه‌ی هسته‌ای است و عامل بازدارندگی مطرح شده")

    else:  # summary
        common.append(f"نتیجه‌ی نهایی: {facts.get('outcome', 'نامشخص')}")
        common.append(f"خسارت نهایی به هدف: {fa_number(facts.get('infra_damage_pct', 0))}٪")
        common.append(f"تلفات مهاجم: {_losses_text(facts.get('attacker_losses', []))}")
        common.append(f"تلفات مدافع: {_losses_text(facts.get('defender_losses', []))}")

    return "\n".join(f"- {line}" for line in common)


# ---------- قالب‌های پشتیبان (بدون AI) ----------
# هر فاز چند قالب دارد تا حتی بدون هوش مصنوعی، متن‌ها یکسان نباشند.
_FALLBACK_TEMPLATES: dict[str, list[str]] = {
    "opening": [
        "🔴 <b>خبر فوری</b> — گزارش‌ها از آغاز {op} {attacker} علیه {target} در خاک {defender} حکایت دارد.",
        "‼️ {attacker} دقایقی پیش {op} گسترده‌ای را علیه {target} {defender} آغاز کرد.",
        "🔴 شنیده‌ها از فعال‌شدن آژیرها در {defender} پس از آغاز {op} {attacker} خبر می‌دهد.",
    ],
    "defense": [
        "🔴 سامانه‌های پدافندی {defender} فعال شدند؛ گزارش‌ها از رهگیری بخشی از اهداف مهاجم حکایت دارد.",
        "‼️ درگیری شدید پدافند {defender} با نیروهای مهاجم در چند محور ادامه دارد.",
        "🔴 پدافند {defender} وارد عمل شد و بخشی از حمله را ناکام گذاشت.",
    ],
    "damage": [
        "🔴 گزارش‌های اولیه از خسارت به {target} در {defender} دریافت شد.",
        "‼️ تصاویر منتشرشده خسارات واردشده به {target} {defender} را تأیید می‌کند.",
        "🔴 ارزیابی‌های میدانی از آسیب به {target} در خاک {defender} خبر می‌دهد.",
    ],
    "second_wave": [
        "🔴 موج دوم {op} {attacker} آغاز شد؛ درگیری‌ها ادامه دارد.",
        "‼️ گزارش‌ها از ورود موج تازه‌ای از نیروهای {attacker} به منطقه‌ی عملیات حکایت دارد.",
    ],
    "reaction": [
        "🔴 واکنش‌های بین‌المللی به عملیات {attacker} علیه {defender} در حال انتشار است.",
        "‼️ محافل دیپلماتیک نسبت به تشدید تنش میان {attacker} و {defender} هشدار دادند.",
    ],
    "summary": [
        "🔴 <b>جمع‌بندی عملیات</b> — {op} {attacker} علیه {defender} با نتیجه‌ی «{outcome}» پایان یافت.",
        "‼️ درگیری میان {attacker} و {defender} فروکش کرد؛ نتیجه: {outcome}.",
    ],
}


def fallback_news(facts: dict, phase_kind: str, rng: random.Random | None = None) -> str:
    """
    تولید خبر بدون هوش مصنوعی (پشتیبان). متن‌ها تصادفی انتخاب می‌شوند
    تا حتی در حالت پشتیبان هم خبرها عیناً تکراری نباشند.
    """
    generator = rng or random
    templates = _FALLBACK_TEMPLATES.get(phase_kind) or _FALLBACK_TEMPLATES["opening"]

    try:
        op_fa = OPERATION_FA[OperationType(facts.get("operation_type", ""))]
    except (ValueError, KeyError):
        op_fa = "عملیات نظامی"
    try:
        target_fa = TARGET_FA[TargetType(facts.get("target_type", ""))]
    except (ValueError, KeyError):
        target_fa = "اهداف نظامی"

    return generator.choice(templates).format(
        attacker=facts.get("attacker", "کشور مهاجم"),
        defender=facts.get("defender", "کشور مدافع"),
        op=op_fa,
        target=target_fa,
        outcome=facts.get("outcome", "نامشخص"),
    )
