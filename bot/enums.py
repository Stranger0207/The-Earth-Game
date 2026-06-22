"""
شمارش‌گرها (Enum) و ثابت‌های نوع‌دار بازی.
همه‌جا از این مقادیر استفاده می‌شود تا از رشته‌های سحرآمیز (magic strings) پرهیز شود.
"""

from __future__ import annotations

import enum


class ResourceType(str, enum.Enum):
    """انواع ذخایر استراتژیک کشورها."""

    COAL = "coal"            # ذغال سنگ — تن
    ALUMINUM = "aluminum"    # آلومینیوم — تن
    IRON = "iron"            # آهن — تن
    STEEL = "steel"          # فولاد — تن
    OIL = "oil"              # نفت — میلیون بشکه
    GAS = "gas"              # گاز — میلیون متر مکعب
    GOLD = "gold"            # طلا — کیلوگرم


# نام فارسی هر ذخیره برای نمایش
RESOURCE_FA: dict[ResourceType, str] = {
    ResourceType.COAL: "ذغال سنگ",
    ResourceType.ALUMINUM: "آلومینیوم",
    ResourceType.IRON: "آهن",
    ResourceType.STEEL: "فولاد",
    ResourceType.OIL: "نفت",
    ResourceType.GAS: "گاز",
    ResourceType.GOLD: "طلا",
}

# واحد شمارش هر ذخیره
RESOURCE_UNIT_FA: dict[ResourceType, str] = {
    ResourceType.COAL: "تن",
    ResourceType.ALUMINUM: "تن",
    ResourceType.IRON: "تن",
    ResourceType.STEEL: "تن",
    ResourceType.OIL: "میلیون بشکه",
    ResourceType.GAS: "میلیون متر مکعب",
    ResourceType.GOLD: "کیلوگرم",
}

# ایموجی هر ذخیره برای نمایش زیباتر
RESOURCE_EMOJI: dict[ResourceType, str] = {
    ResourceType.COAL: "🪨",
    ResourceType.ALUMINUM: "🔩",
    ResourceType.IRON: "⛓",
    ResourceType.STEEL: "🏗",
    ResourceType.OIL: "🛢",
    ResourceType.GAS: "⛽",
    ResourceType.GOLD: "🥇",
}


class FacilityType(str, enum.Enum):
    """انواع تأسیساتی که یک کشور می‌تواند احداث کند."""

    MINE = "mine"                    # معدن (ذغال/آلومینیوم/آهن/طلا)
    STEEL_FACTORY = "steel_factory"  # کارخانه فولاد
    OIL_PLATFORM = "oil_platform"    # سکوی نفتی
    GAS_PLATFORM = "gas_platform"    # سکوی گازی


FACILITY_FA: dict[FacilityType, str] = {
    FacilityType.MINE: "معدن",
    FacilityType.STEEL_FACTORY: "کارخانه فولاد",
    FacilityType.OIL_PLATFORM: "سکوی نفتی",
    FacilityType.GAS_PLATFORM: "سکوی گازی",
}


class AttackType(str, enum.Enum):
    """انواع حملات نظامی."""

    AIR = "air"            # حمله هوایی
    GROUND = "ground"      # حمله زمینی
    NAVAL = "naval"        # حمله دریایی
    SABOTAGE = "sabotage"  # حمله خرابکارانه


ATTACK_FA: dict[AttackType, str] = {
    AttackType.AIR: "حمله هوایی",
    AttackType.GROUND: "حمله زمینی",
    AttackType.NAVAL: "حمله دریایی",
    AttackType.SABOTAGE: "حمله خرابکارانه",
}


class Region(str, enum.Enum):
    """مناطق جغرافیایی بازی."""

    EAST_ASIA = "east_asia"          # آسیای شرقی
    MIDDLE_EAST = "middle_east"      # خاورمیانه
    EUROPE = "europe"                # اروپا
    AMERICAS = "americas"            # آمریکای شمالی و جنوبی


REGION_FA: dict[Region, str] = {
    Region.EAST_ASIA: "آسیای شرقی",
    Region.MIDDLE_EAST: "خاورمیانه",
    Region.EUROPE: "اروپا",
    Region.AMERICAS: "آمریکای شمالی و جنوبی",
}


class UserRole(str, enum.Enum):
    """نقش کاربر در سیستم."""

    PLAYER = "player"  # بازیکن عادی
    ADMIN = "admin"    # مدیر بازی
    OWNER = "owner"    # مالک بازی


class ClaimStatus(str, enum.Enum):
    """وضعیت درخواست کشورگیری."""

    PENDING = "pending"    # در انتظار تأیید مالک
    APPROVED = "approved"  # تأییدشده
    REJECTED = "rejected"  # ردشده


class DiplomacyStatus(str, enum.Enum):
    """وضعیت کنش‌های دیپلماتیک (تماس، دیدار، قرارداد)."""

    PENDING = "pending"      # در انتظار تأیید طرف مقابل
    ACTIVE = "active"        # فعال / در جریان
    COMPLETED = "completed"  # پایان‌یافته
    REJECTED = "rejected"    # ردشده
    CANCELLED = "cancelled"  # لغوشده


class TradeStatus(str, enum.Enum):
    """وضعیت فروش/محموله‌ی ذخایر."""

    PENDING = "pending"        # در انتظار تأیید خریدار
    IN_TRANSIT = "in_transit"  # محموله در راه (WTO)
    DELIVERED = "delivered"    # تحویل‌شده
    REJECTED = "rejected"      # ردشده


class AttackStatus(str, enum.Enum):
    """وضعیت یک حمله."""

    PENDING = "pending"        # در انتظار تأیید سوخت توسط مهاجم
    IN_PROGRESS = "in_progress"  # در حال اجرا (در انتظار نتیجه)
    RESOLVED = "resolved"      # نتیجه اعلام شد
    CANCELLED = "cancelled"    # لغوشده


class NewsCategory(str, enum.Enum):
    """دسته‌بندی اخبار برای ارسال به کانال درست."""

    MILITARY = "military"      # کانال اخبار نظامی
    DIPLOMACY = "diplomacy"    # کانال اخبار دیپلماسی
    ECONOMY = "economy"        # کانال اخبار اقتصادی
    WTO = "wto"                # کانال سازمان انتقالات


class AdvisorDomain(str, enum.Enum):
    """دامنه‌ی مشاور هوش مصنوعی."""

    ECONOMY = "economy"
    DIPLOMACY = "diplomacy"
    MILITARY = "military"
