"""
پکیج موتور نبرد (v1.10.6).

نتیجه‌ی هر عملیات نظامی اینجا و به‌صورت کاملاً محاسباتی تعیین می‌شود
(بدون فراخوانی هوش مصنوعی). AI فقط از روی اعداد خروجی، متن خبر را می‌نویسد.

- `profiles`: پروفایل قدرت هر دسته تجهیزات + ضریب کیفیت از روی نام
- `power`: محاسبه‌ی قدرت تهاجمی و پدافندی
- `engine`: هسته‌ی محاسبه‌ی نبرد (امکان‌سنجی، رهگیری، تلفات، اثرات اقتصادی)
"""

from .power import CommittedAsset, PowerBreakdown, consumable_names, strike_power
from .profiles import AssetProfile, profile_for, quality_multiplier

__all__ = [
    "AssetProfile",
    "CommittedAsset",
    "PowerBreakdown",
    "consumable_names",
    "profile_for",
    "quality_multiplier",
    "strike_power",
]
