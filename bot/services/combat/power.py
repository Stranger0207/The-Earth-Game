"""
محاسبه‌ی قدرت رزمی (v1.10.6).

قدرت تهاجمی نیروی اعزامی و قدرت پدافندی کشور مدافع را از روی تجهیزات واقعی
محاسبه می‌کند. هیچ فراخوانی AI اینجا نیست — همه‌چیز قطعی و تست‌پذیر است.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...enums import OperationType
from .profiles import profile_for, quality_multiplier

# ---------- نگاشت نوع عملیات به شاخه‌های مجاز ----------
# هر نوع حمله فقط با تجهیزات متناسب خودش قابل اجراست.
OPERATION_BRANCHES: dict[OperationType, frozenset[str]] = {
    OperationType.GROUND_ASSAULT: frozenset({
        "نیروی زمینی", "خودروهای زمینی", "سامانه‌های دفاعی",
    }),
    OperationType.AIR_STRIKE: frozenset({
        "نیروی هوایی", "سامانه‌های حمله هوایی",
    }),
    OperationType.NAVAL_STRIKE: frozenset({
        "نیروی دریایی", "سامانه‌های حمله هوایی",
    }),
    OperationType.INTERCEPTION: frozenset({
        "نیروی هوایی", "نیروی دریایی", "سامانه‌های دفاعی",
    }),
}

# شاخه‌هایی که در برابر هر نوع حمله نقش پدافندی دارند.
# سامانه‌های دفاعی همیشه حاضرند؛ بقیه بسته به نوع تهدید.
DEFENSE_BRANCHES: dict[OperationType, frozenset[str]] = {
    OperationType.GROUND_ASSAULT: frozenset({
        "سامانه‌های دفاعی", "خودروهای زمینی", "نیروی زمینی",
    }),
    OperationType.AIR_STRIKE: frozenset({
        "سامانه‌های دفاعی", "نیروی هوایی",
    }),
    OperationType.NAVAL_STRIKE: frozenset({
        "سامانه‌های دفاعی", "نیروی دریایی", "نیروی هوایی",
    }),
    OperationType.INTERCEPTION: frozenset({
        "نیروی دریایی", "نیروی هوایی",
    }),
}


@dataclass
class CommittedAsset:
    """یک قلم تجهیزات اعزامی به عملیات."""

    name: str
    count: int
    branch: str = ""
    category: str = ""
    unit: str = "عدد"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "count": self.count,
            "branch": self.branch,
            "category": self.category,
            "unit": self.unit,
        }

    @staticmethod
    def from_dict(data: dict) -> "CommittedAsset":
        return CommittedAsset(
            name=data.get("name", ""),
            count=int(data.get("count", 0) or 0),
            branch=data.get("branch", ""),
            category=data.get("category", ""),
            unit=data.get("unit", "عدد"),
        )


@dataclass
class PowerBreakdown:
    """تفکیک قدرت محاسبه‌شده (برای نمایش به بازیکن و ورودی خبرنویس)."""

    total: float = 0.0
    per_asset: dict[str, float] = field(default_factory=dict)
    total_units: int = 0
    max_range_km: float = 0.0

    def top_assets(self, limit: int = 3) -> list[str]:
        """نام مؤثرترین تجهیزات (برای ذکر در متن خبر)."""
        ranked = sorted(self.per_asset.items(), key=lambda kv: kv[1], reverse=True)
        return [name for name, _ in ranked[:limit]]


def strike_power(assets: list[CommittedAsset]) -> PowerBreakdown:
    """
    قدرت تهاجمی مجموعه‌ای از تجهیزات اعزامی.
    برد کل عملیات = بیشترین بردِ میان اقلام اعزامی.
    """
    breakdown = PowerBreakdown()
    for asset in assets:
        if asset.count <= 0:
            continue
        profile = profile_for(asset.category)
        quality = quality_multiplier(asset.name)
        power = profile.attack * quality * asset.count
        if power <= 0:
            continue
        breakdown.total += power
        breakdown.per_asset[asset.name] = breakdown.per_asset.get(asset.name, 0.0) + power
        breakdown.total_units += asset.count
        breakdown.max_range_km = max(breakdown.max_range_km, profile.range_km)
    return breakdown


def defense_power(
    defender_assets: list[CommittedAsset], operation_type: OperationType
) -> PowerBreakdown:
    """
    قدرت پدافندی کشور مدافع در برابر یک نوع حمله.
    فقط شاخه‌های مرتبط با آن تهدید شمرده می‌شوند.
    """
    allowed = DEFENSE_BRANCHES.get(operation_type)
    breakdown = PowerBreakdown()
    for asset in defender_assets:
        if asset.count <= 0:
            continue
        if allowed is not None and asset.branch not in allowed:
            continue
        profile = profile_for(asset.category)
        quality = quality_multiplier(asset.name)
        power = profile.defense * quality * asset.count
        if power <= 0:
            continue
        breakdown.total += power
        breakdown.per_asset[asset.name] = breakdown.per_asset.get(asset.name, 0.0) + power
        breakdown.total_units += asset.count
    return breakdown


def allowed_branches_for(operation_type: OperationType) -> frozenset[str] | None:
    """شاخه‌های تجهیزاتی مجاز برای یک نوع عملیات (None = بدون محدودیت)."""
    return OPERATION_BRANCHES.get(operation_type)


def filter_usable_assets(
    assets: list[CommittedAsset], operation_type: OperationType
) -> list[CommittedAsset]:
    """تجهیزاتی که برای این نوع عملیات قابل‌استفاده‌اند."""
    allowed = allowed_branches_for(operation_type)
    if allowed is None:
        return list(assets)
    return [a for a in assets if a.branch in allowed]


def consumable_names(assets: list[CommittedAsset]) -> set[str]:
    """نام اقلام مصرف‌شدنی (موشک‌ها) که پس از عملیات به موجودی برنمی‌گردند."""
    return {a.name for a in assets if profile_for(a.category).consumable}
