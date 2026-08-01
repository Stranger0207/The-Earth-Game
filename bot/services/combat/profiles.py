"""
پروفایل قدرت رزمی تجهیزات (v1.10.6).

هر «دسته» (category) از countries.json یک پروفایل عددی دارد:
قدرت تهاجمی، قدرت پدافندی، برد عملیاتی و اینکه آیا مصرف‌شدنی است.

جدول بر اساس دسته‌های واقعی داده ساخته شده، و ضرایب کیفیت از روی نام تجهیزات
تشخیص داده می‌شوند (مثلاً F-35 قوی‌تر از F-4 و B-2 قوی‌تر از B-52).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetProfile:
    """پروفایل رزمی یک دسته تجهیزات."""

    attack: float          # قدرت تهاجمی هر واحد
    defense: float         # قدرت پدافندی/دفاعی هر واحد
    range_km: float        # برد عملیاتی (کیلومتر)
    consumable: bool = False  # مصرف‌شدنی؟ (موشک پس از شلیک برنمی‌گردد)


# پروفایل پیش‌فرض برای دسته‌های ناشناخته (تا هیچ‌وقت KeyError نخوریم)
DEFAULT_PROFILE = AssetProfile(attack=1.0, defense=0.5, range_km=800.0)

# ---------- جدول اصلی: دسته → پروفایل ----------
# اعداد نسبی‌اند و برای تعادل بازی تنظیم شده‌اند، نه شبیه‌سازی نظامی دقیق.
ASSET_PROFILES: dict[str, AssetProfile] = {
    # --- نیروی زمینی ---
    # پرسنل تعدادشان میلیونی است، پس قدرت هر نفر بسیار کوچک نگه داشته می‌شود.
    "سرباز آماده نبرد": AssetProfile(attack=0.006, defense=0.010, range_km=400.0),

    # --- خودروهای زمینی ---
    "تانک": AssetProfile(attack=3.2, defense=2.4, range_km=600.0),
    "نفربر زرهی": AssetProfile(attack=1.4, defense=1.8, range_km=600.0),

    # --- سامانه‌های دفاعی ---
    # سامانه‌ی ضدموشکی ستون فقرات پدافند است: قدرت دفاعی بسیار بالا.
    "سامانه ضدموشکی": AssetProfile(attack=1.0, defense=16.0, range_km=350.0),
    "توپخانه زمین به زمین": AssetProfile(attack=4.5, defense=1.2, range_km=120.0),

    # --- نیروی هوایی ---
    "جنگنده": AssetProfile(attack=9.0, defense=6.5, range_km=1800.0),
    "بمب‌افکن": AssetProfile(attack=22.0, defense=2.0, range_km=9000.0),
    "بمب‌افکن / تهاجمی": AssetProfile(attack=14.0, defense=3.0, range_km=3500.0),
    "پهپادها": AssetProfile(attack=3.5, defense=1.0, range_km=1500.0),
    "بالگرد": AssetProfile(attack=2.8, defense=1.5, range_km=500.0),
    "هواپیماهای ترابری": AssetProfile(attack=0.2, defense=0.4, range_km=5000.0),
    "هواپیماهای پشتیبانی": AssetProfile(attack=0.8, defense=2.5, range_km=4000.0),

    # --- سامانه‌های حمله هوایی (مصرف‌شدنی) ---
    "موشک بالستیک": AssetProfile(attack=26.0, defense=0.0, range_km=3000.0, consumable=True),
    "موشک کروز": AssetProfile(attack=15.0, defense=0.0, range_km=2000.0, consumable=True),

    # --- نیروی دریایی ---
    "ناو هواپیمابر": AssetProfile(attack=45.0, defense=20.0, range_km=12000.0),
    "ناوشکن": AssetProfile(attack=13.0, defense=11.0, range_km=9000.0),
    "ناوچه": AssetProfile(attack=5.0, defense=4.0, range_km=3000.0),
    "زیر دریایی": AssetProfile(attack=18.0, defense=6.0, range_km=10000.0),
}

# ---------- ضرایب کیفیت بر اساس نام تجهیزات ----------
# اگر نام تجهیزات شامل یکی از این کلیدواژه‌ها باشد، ضریب اعمال می‌شود.
# ترتیب مهم است: اولین تطابق برنده است (خاص‌ترها اول).
QUALITY_KEYWORDS: list[tuple[tuple[str, ...], float]] = [
    # --- نسل پنجم و تسلیحات راهبردی (بسیار برتر) ---
    (("F-35", "F-22", "B-2 ", "B-21", "Su-57", "J-20", "J-35"), 1.75),
    # --- نسل ۴.۵ و سامانه‌های رده‌بالا ---
    (
        (
            "F-15EX", "F-15E", "F-15SA", "F-15I", "Rafale", "Eurofighter", "Typhoon",
            "Su-35", "Su-34", "J-16", "Gripen E", "F-16V", "Block 70", "Block 72",
            "S-400", "S-500", "THAAD", "Aegis", "Arrow 3", "Arrow 2/3", "David",
            "Tu-160", "B-1B", "Virginia", "Astute", "Seawolf", "Borei", "Yasen",
            "Arleigh Burke", "Type 055", "Maya-class", "Atago", "KDX-III",
            "DF-41", "DF-26", "Agni-V", "Trident", "Bulava", "Minuteman",
        ),
        1.45,
    ),
    # --- تجهیزات مدرن استاندارد ---
    (
        (
            "F-16", "F/A-18", "Su-30", "Su-27", "MiG-31", "J-10", "J-11",
            "Patriot", "PAC-3", "S-300", "Bavar", "Barak-8", "HQ-9", "Aster 30",
            "Leopard 2", "M1A2", "M1A1", "Challenger", "K2 ", "Type 99", "T-90",
            "Merkava", "Leclerc", "Altay", "FREMM", "Horizon", "Kolkata",
            "Akula", "Kilo", "Type 214", "Type 212", "Scorpene", "Collins",
            "Bayraktar", "Akıncı", "Global Hawk", "Reaper", "Heron TP", "CH-5",
        ),
        1.2,
    ),
    # --- تجهیزات قدیمی/محدود (تضعیف) ---
    (
        (
            "F-4", "F-5", "MiG-21", "MiG-23", "MiG-29", "Su-22", "Su-24",
            "B-52", "Tu-95", "H-6", "Tu-22M3", "AMX-30", "T-55", "T-62", "T-72",
            "Chieftain", "M60", "Type 59", "Type 69", "HAWK", "Crotale", "Buk-MB",
            "قدیمی", "محدود", "Cosmos-class", "midget", "Ghadir",
        ),
        0.65,
    ),
]

# اگر نام هیچ کلیدواژه‌ای نداشت
DEFAULT_QUALITY = 1.0


def quality_multiplier(asset_name: str) -> float:
    """ضریب کیفیت یک قلم تجهیزات را از روی نامش تشخیص می‌دهد."""
    if not asset_name:
        return DEFAULT_QUALITY
    for keywords, multiplier in QUALITY_KEYWORDS:
        for keyword in keywords:
            if keyword in asset_name:
                return multiplier
    return DEFAULT_QUALITY


def profile_for(category: str) -> AssetProfile:
    """پروفایل رزمی یک دسته را برمی‌گرداند (با fallback امن)."""
    return ASSET_PROFILES.get(category, DEFAULT_PROFILE)
