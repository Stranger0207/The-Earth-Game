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
    URANIUM = "uranium"      # اورانیوم — تن (v1.10.4 — پیش‌نیاز برنامه‌ی هسته‌ای)


# نام فارسی هر ذخیره برای نمایش
RESOURCE_FA: dict[ResourceType, str] = {
    ResourceType.COAL: "ذغال سنگ",
    ResourceType.ALUMINUM: "آلومینیوم",
    ResourceType.IRON: "آهن",
    ResourceType.STEEL: "فولاد",
    ResourceType.OIL: "نفت",
    ResourceType.GAS: "گاز",
    ResourceType.GOLD: "طلا",
    ResourceType.URANIUM: "اورانیوم",
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
    ResourceType.URANIUM: "تن",
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
    ResourceType.URANIUM: "☢️",
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


class GovernmentType(str, enum.Enum):
    """انواع نظام حاکمیتی کشورها (v1.10.2)."""

    REPUBLIC = "republic"                        # جمهوری
    DEMOCRACY = "democracy"                      # دموکراسی
    MONARCHY = "monarchy"                        # پادشاهی
    CONSTITUTIONAL_MONARCHY = "const_monarchy"   # پادشاهی مشروطه
    COMMUNISM = "communism"                      # کمونیسم
    THEOCRACY = "theocracy"                      # تئوکراسی (حکومت دینی)
    DICTATORSHIP = "dictatorship"                # دیکتاتوری
    FEDERAL = "federal"                          # فدرال


# نام فارسی هر نظام
GOVERNMENT_FA: dict[GovernmentType, str] = {
    GovernmentType.REPUBLIC: "جمهوری",
    GovernmentType.DEMOCRACY: "دموکراسی",
    GovernmentType.MONARCHY: "پادشاهی",
    GovernmentType.CONSTITUTIONAL_MONARCHY: "پادشاهی مشروطه",
    GovernmentType.COMMUNISM: "کمونیسم",
    GovernmentType.THEOCRACY: "تئوکراسی",
    GovernmentType.DICTATORSHIP: "دیکتاتوری",
    GovernmentType.FEDERAL: "فدرال",
}

# ایموجی نظام‌ها
GOVERNMENT_EMOJI: dict[GovernmentType, str] = {
    GovernmentType.REPUBLIC: "🏛",
    GovernmentType.DEMOCRACY: "🗳",
    GovernmentType.MONARCHY: "👑",
    GovernmentType.CONSTITUTIONAL_MONARCHY: "👑",
    GovernmentType.COMMUNISM: "☭",
    GovernmentType.THEOCRACY: "🕌",
    GovernmentType.DICTATORSHIP: "🦅",
    GovernmentType.FEDERAL: "🏢",
}


class ProtestType(str, enum.Enum):
    """انواع اعتراضات داخلی (v1.10.2)."""

    ECONOMIC = "economic"      # اعتراض اقتصادی
    POLITICAL = "political"    # اعتراض سیاسی
    SOCIAL = "social"          # اعتراض اجتماعی
    LABOR = "labor"            # اعتراض کارگری


PROTEST_FA: dict[ProtestType, str] = {
    ProtestType.ECONOMIC: "اعتراض اقتصادی",
    ProtestType.POLITICAL: "اعتراض سیاسی",
    ProtestType.SOCIAL: "اعتراض اجتماعی",
    ProtestType.LABOR: "اعتراض کارگری",
}

PROTEST_EMOJI: dict[ProtestType, str] = {
    ProtestType.ECONOMIC: "📉",
    ProtestType.POLITICAL: "✊",
    ProtestType.SOCIAL: "📢",
    ProtestType.LABOR: "🔧",
}


class ProtestStatus(str, enum.Enum):
    """وضعیت یک اعتراض (v1.10.2)."""

    ACTIVE = "active"                  # فعال — در جریان
    SUPPRESSED = "suppressed"          # سرکوب‌شده
    IN_PARLIAMENT = "in_parliament"    # ارجاع به مجلس
    REFERENDUM = "referendum"          # در حال رفراندوم (منتظر رأی ادمین)
    RESOLVED = "resolved"              # حل‌شده


PROTEST_STATUS_FA: dict[ProtestStatus, str] = {
    ProtestStatus.ACTIVE: "🔴 فعال",
    ProtestStatus.SUPPRESSED: "🟤 سرکوب‌شده",
    ProtestStatus.IN_PARLIAMENT: "🟡 در مجلس",
    ProtestStatus.REFERENDUM: "🟠 رفراندوم",
    ProtestStatus.RESOLVED: "🟢 حل‌شده",
}


class LawStatus(str, enum.Enum):
    """وضعیت لایحه‌ی پیشنهادی به مجلس (v1.10.2)."""

    DRAFT = "draft"                # پیش‌نویس (ارسال‌نشده)
    IN_PARLIAMENT = "in_parliament"  # در حال بررسی مجلس
    APPROVED = "approved"          # تصویب‌شده
    REJECTED = "rejected"          # ردشده


LAW_STATUS_FA: dict[LawStatus, str] = {
    LawStatus.DRAFT: "📝 پیش‌نویس",
    LawStatus.IN_PARLIAMENT: "🏛 در مجلس",
    LawStatus.APPROVED: "✅ تصویب‌شده",
    LawStatus.REJECTED: "❌ ردشده",
}


# ============================================================
#  ☢️ برنامه‌ی هسته‌ای (v1.10.4) — فقط کشورهای VIP
# ============================================================


class NuclearPhase(int, enum.Enum):
    """فازهای پنج‌گانه‌ی توسعه‌ی هسته‌ای."""

    NONE = 0            # برنامه‌ای آغاز نشده
    MINING = 1          # فاز ۱: استخراج و آسیاب (کیک زرد)
    CONVERSION = 2      # فاز ۲: تبدیل به UF6 و زیرساخت
    ENRICHMENT = 3      # فاز ۳: غنی‌سازی
    WEAPONIZATION = 4   # فاز ۴: طراحی و مونتاژ کلاهک
    DELIVERY = 5        # فاز ۵: آزمایش و سامانه‌ی حمل


NUCLEAR_PHASE_FA: dict[NuclearPhase, str] = {
    NuclearPhase.NONE: "بدون برنامه",
    NuclearPhase.MINING: "فاز ۱ — استخراج و آسیاب",
    NuclearPhase.CONVERSION: "فاز ۲ — تبدیل و زیرساخت",
    NuclearPhase.ENRICHMENT: "فاز ۳ — غنی‌سازی",
    NuclearPhase.WEAPONIZATION: "فاز ۴ — تسلیحاتی‌سازی",
    NuclearPhase.DELIVERY: "فاز ۵ — آزمایش و سامانه‌ی حمل",
}


class NuclearTechType(str, enum.Enum):
    """فناوری‌های قابل‌تحقیق در مسیر هسته‌ای."""

    GEOLOGY_2 = "geology_2"          # زمین‌شناسی سطح ۲ + نقشه‌ی منابع
    IND_CHEMISTRY = "ind_chemistry"  # شیمی صنعتی (تبدیل کیک زرد به UF6)
    CENTRIFUGE = "centrifuge"        # متالورژی و ساخت سانتریفیوژ
    COMP_PHYSICS = "comp_physics"    # فیزیک محاسباتی (طراحی کلاهک)
    DELIVERY_SYS = "delivery_sys"    # سامانه‌ی حمل (موشک/بمب‌افکن)


class NuclearFacilityType(str, enum.Enum):
    """انواع تأسیسات برنامه‌ی هسته‌ای."""

    MILL = "mill"                    # آسیاب کیک زرد (فاز ۱)
    CONVERSION = "conversion"        # کارخانه‌ی تبدیل به UF6 (فاز ۲)
    ENRICHMENT_HALL = "enrich_hall"  # سالن غنی‌سازی — میزبان سانتریفیوژها (فاز ۳)
    CENTRIFUGE_PLANT = "cent_plant"  # کارخانه‌ی ساخت سانتریفیوژ
    WEAPONS_LAB = "weapons_lab"      # آزمایشگاه تسلیحاتی (فاز ۴)
    TEST_SITE = "test_site"          # سایت آزمایش هسته‌ای (فاز ۵)


class NuclearFacilityStatus(str, enum.Enum):
    """وضعیت یک تأسیسات هسته‌ای."""

    BUILDING = "building"      # در حال ساخت
    ACTIVE = "active"          # فعال
    DAMAGED = "damaged"        # آسیب‌دیده (بازدهی کاهش‌یافته)
    DESTROYED = "destroyed"    # نابودشده


NUCLEAR_FACILITY_STATUS_FA: dict[NuclearFacilityStatus, str] = {
    NuclearFacilityStatus.BUILDING: "🏗 در حال ساخت",
    NuclearFacilityStatus.ACTIVE: "🟢 فعال",
    NuclearFacilityStatus.DAMAGED: "🟠 آسیب‌دیده",
    NuclearFacilityStatus.DESTROYED: "🔴 نابودشده",
}


class WarheadStatus(str, enum.Enum):
    """وضعیت یک کلاهک هسته‌ای."""

    ASSEMBLING = "assembling"  # در حال مونتاژ
    ASSEMBLED = "assembled"    # مونتاژشده (در انبار)
    MOUNTED = "mounted"        # نصب‌شده روی سامانه‌ی حمل
    TESTED = "tested"          # در آزمایش هسته‌ای مصرف شد


WARHEAD_STATUS_FA: dict[WarheadStatus, str] = {
    WarheadStatus.ASSEMBLING: "🔧 در حال مونتاژ",
    WarheadStatus.ASSEMBLED: "☢️ مونتاژشده",
    WarheadStatus.MOUNTED: "🚀 نصب‌شده",
    WarheadStatus.TESTED: "💥 مصرف‌شده در آزمایش",
}


class DeliverySystem(str, enum.Enum):
    """سامانه‌های حمل کلاهک هسته‌ای."""

    BALLISTIC = "ballistic"    # موشک بالستیک
    BOMBER = "bomber"          # بمب‌افکن استراتژیک
    SUBMARINE = "submarine"    # زیردریایی


DELIVERY_SYSTEM_FA: dict[DeliverySystem, str] = {
    DeliverySystem.BALLISTIC: "🚀 موشک بالستیک",
    DeliverySystem.BOMBER: "✈️ بمب‌افکن استراتژیک",
    DeliverySystem.SUBMARINE: "🚢 زیردریایی",
}
