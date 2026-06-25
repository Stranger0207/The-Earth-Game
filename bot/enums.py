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


class MilitaryFactoryType(str, enum.Enum):
    """انواع کارخانه‌های نظامی برای بازتولید تجهیزات (v1.7)."""

    ANTI_MISSILE = "anti_missile"          # سامانه ضد موشکی
    ARTILLERY = "artillery"                # توپخانه زمین به زمین
    TANK = "tank"                          # تانک
    APC = "apc"                            # نفربر زرهی
    FIGHTER = "fighter"                    # جنگنده
    TRANSPORT_AIRCRAFT = "transport_aircraft"  # هواپیمای ترابری
    DRONE = "drone"                        # پهپاد
    HELICOPTER = "helicopter"              # بالگرد
    CORVETTE = "corvette"                  # ناوچه
    DESTROYER = "destroyer"                # ناوشکن
    BALLISTIC_MISSILE = "ballistic_missile"  # موشک بالستیک
    CRUISE_MISSILE = "cruise_missile"      # موشک کروز


# نام فارسی کارخانه‌ها (برای دکمه‌ها و پیام‌ها)
MIL_FACTORY_FA: dict[MilitaryFactoryType, str] = {
    MilitaryFactoryType.ANTI_MISSILE: "کارخانه سامانه ضد موشکی",
    MilitaryFactoryType.ARTILLERY: "کارخانه توپخانه زمین به زمین",
    MilitaryFactoryType.TANK: "کارخانه تانک",
    MilitaryFactoryType.APC: "کارخانه نفربر زرهی",
    MilitaryFactoryType.FIGHTER: "کارخانه جنگنده",
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: "کارخانه هواپیمای ترابری",
    MilitaryFactoryType.DRONE: "کارخانه پهپاد",
    MilitaryFactoryType.HELICOPTER: "کارخانه بالگرد",
    MilitaryFactoryType.CORVETTE: "کارخانه ناوچه",
    MilitaryFactoryType.DESTROYER: "کارخانه ناوشکن",
    MilitaryFactoryType.BALLISTIC_MISSILE: "کارخانه موشک بالستیک",
    MilitaryFactoryType.CRUISE_MISSILE: "کارخانه موشک کروز",
}

# نگاشت نوع کارخانه به «دسته‌ی تجهیزات» (category) دقیقاً مطابق داده‌ی countries.json
# تا تجهیزات قابل‌بازتولید کشور از روی همین دسته فیلتر شوند.
MIL_FACTORY_CATEGORY: dict[MilitaryFactoryType, str] = {
    MilitaryFactoryType.ANTI_MISSILE: "سامانه ضدموشکی",
    MilitaryFactoryType.ARTILLERY: "توپخانه زمین به زمین",
    MilitaryFactoryType.TANK: "تانک",
    MilitaryFactoryType.APC: "نفربر زرهی",
    MilitaryFactoryType.FIGHTER: "جنگنده",
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: "هواپیماهای ترابری",
    MilitaryFactoryType.DRONE: "پهپادها",
    MilitaryFactoryType.HELICOPTER: "بالگرد",
    MilitaryFactoryType.CORVETTE: "ناوچه",
    MilitaryFactoryType.DESTROYER: "ناوشکن",
    MilitaryFactoryType.BALLISTIC_MISSILE: "موشک بالستیک",
    MilitaryFactoryType.CRUISE_MISSILE: "موشک کروز",
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


class SanctionType(str, enum.Enum):
    """انواع تحریم (v1.5)."""

    OIL_TRADE = "oil_trade"            # تحریم تجارت نفت
    GAS_TRADE = "gas_trade"            # تحریم تجارت گاز
    STEEL_TRADE = "steel_trade"        # تحریم تجارت فولاد
    MINERAL_TRADE = "mineral_trade"    # تحریم تجارت منابع معدنی
    FINANCIAL = "financial"            # تحریم مالی و بانکی (انتقال پول در WTO)
    ARMS = "arms"                      # تحریم تسلیحاتی (خرید/فروش سلاح)
    TRANSPORT = "transport"            # تحریم حمل‌ونقل (خطوط بین‌المللی WTO)
    DIPLOMATIC = "diplomatic"          # تحریم دیپلماتیک (قطع/کاهش روابط)
    INDIVIDUAL = "individual"          # تحریم فردی (ممنوعیت سفر مقامات)


# نام فارسی هر نوع تحریم
SANCTION_FA: dict[SanctionType, str] = {
    SanctionType.OIL_TRADE: "تحریم تجارت نفت",
    SanctionType.GAS_TRADE: "تحریم تجارت گاز",
    SanctionType.STEEL_TRADE: "تحریم تجارت فولاد",
    SanctionType.MINERAL_TRADE: "تحریم تجارت منابع معدنی",
    SanctionType.FINANCIAL: "تحریم مالی و بانکی",
    SanctionType.ARMS: "تحریم تسلیحاتی",
    SanctionType.TRANSPORT: "تحریم حمل‌ونقل",
    SanctionType.DIPLOMATIC: "تحریم دیپلماتیک",
    SanctionType.INDIVIDUAL: "تحریم فردی",
}
