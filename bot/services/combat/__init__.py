"""
پکیج موتور نبرد (v1.10.6).

نتیجه‌ی هر عملیات نظامی اینجا و به‌صورت کاملاً محاسباتی تعیین می‌شود
(بدون فراخوانی هوش مصنوعی). AI فقط از روی اعداد خروجی، متن خبر را می‌نویسد.

- `profiles`: پروفایل قدرت هر دسته تجهیزات + ضریب کیفیت از روی نام
- `power`: محاسبه‌ی قدرت تهاجمی و پدافندی
- `engine`: هسته‌ی محاسبه‌ی نبرد (امکان‌سنجی، رهگیری، تلفات، اثرات اقتصادی)
"""

from .engine import BattleInput, BattleResult, resolve_battle
from .power import CommittedAsset, PowerBreakdown, allowed_branches_for, defense_power, strike_power
from .profiles import AssetProfile, profile_for, quality_multiplier

__all__ = [
    "AssetProfile",
    "BattleInput",
    "BattleResult",
    "CommittedAsset",
    "PowerBreakdown",
    "allowed_branches_for",
    "defense_power",
    "profile_for",
    "quality_multiplier",
    "resolve_battle",
    "strike_power",
]
