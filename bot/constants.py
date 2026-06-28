"""
ثابت‌های عددی بازی که مستقیماً از پلی‌بوک استخراج شده‌اند.
هزینه‌ی ساخت‌وسازها، بازدهی‌ها، کول‌داون‌ها و قوانین زمانی اینجا متمرکز شده‌اند
تا تنظیم سختی بازی در یک نقطه ممکن باشد.
"""

from __future__ import annotations

from .enums import FACILITY_FA, FacilityType, MilitaryFactoryType, ResourceType

# ============================================================
#  بازدهی پیش‌فرض ذخایر طبیعی (پلی‌بوک: بازدهی ۷۲ ساعته‌ی اولیه)
# ============================================================
DEFAULT_RESERVE_YIELD_HOURS = 72  # ساعت

# ============================================================
#  هزینه و بازدهی معدن (در هر ۲۴ ساعت) — بخش «فرم احداث معدن»
# ============================================================
MINE_COST_USD = 20_000_000  # 20M$
MINE_YIELD_PER_24H: dict[ResourceType, float] = {
    ResourceType.COAL: 33_000,      # تن
    ResourceType.ALUMINUM: 17_000,  # تن
    ResourceType.IRON: 27_000,      # تن
    ResourceType.GOLD: 0.7,         # تن ≈ ۷۰۰ کیلوگرم → در واحد کیلوگرم: 700
}
# طلا در دیتابیس با واحد کیلوگرم نگه داشته می‌شود
GOLD_MINE_YIELD_KG_PER_24H = 700

# ============================================================
#  کارخانه فولاد — بخش «فرم احداث کارخانه فولاد»
# ============================================================
STEEL_FACTORY_COST_USD = 50_000_000     # 50M$
STEEL_FACTORY_IRON_INTAKE_PER_24H = 20_000  # تن آهن مصرفی در ۲۴ ساعت
STEEL_FACTORY_OUTPUT_PER_24H = 10_000       # تن فولاد تولیدی در ۲۴ ساعت

# ============================================================
#  سکوی نفتی — بخش «فرم احداث سکوی نفتی»
# ============================================================
OIL_PLATFORM_COST_USD = 150_000_000         # 150M$
OIL_PLATFORM_OUTPUT_PER_24H = 1             # میلیون بشکه در ۲۴ ساعت

# ============================================================
#  سکوی گازی — بخش «فرم احداث سکوی گازی»
# ============================================================
GAS_PLATFORM_COST_USD = 130_000_000         # 130M$
GAS_PLATFORM_OUTPUT_PER_24H = 20            # میلیون متر مکعب در ۲۴ ساعت

# جدول هزینه‌ی هر نوع تأسیسات برای دسترسی سریع
FACILITY_COST_USD: dict[FacilityType, int] = {
    FacilityType.MINE: MINE_COST_USD,
    FacilityType.STEEL_FACTORY: STEEL_FACTORY_COST_USD,
    FacilityType.OIL_PLATFORM: OIL_PLATFORM_COST_USD,
    FacilityType.GAS_PLATFORM: GAS_PLATFORM_COST_USD,
}

# ============================================================
#  کول‌داون‌ها (محدودیت‌های زمانی پلی‌بوک)
# ============================================================
RESOURCE_SALE_COOLDOWN_HOURS = 1    # هر کشور هر ۱ ساعت یک‌بار فروش ذخیره (v1.8)
ADVISOR_COOLDOWN_HOURS = 24         # مشاور AI هر ۲۴ ساعت یک‌بار در هر دامنه

# محدودیت ساخت تأسیسات/کارخانه — پنجره‌ی زمانی مشترک
BUILD_LIMIT_WINDOW_HOURS = 12

# محدودیت ساخت به تفکیک نوع تأسیسات (v1.9): تعداد مجاز در هر پنجره‌ی ۱۲ ساعته.
# هر «گروه» = (کلید، مجموعه‌ی FacilityType، سقف تعداد، نام فارسی).
# دکل نفتی و گازی یک سهمیه‌ی مشترک دارند (طبق متن آپدیت: «دکل نفتی و گازی: ۳ تا»).
BUILD_LIMIT_GROUPS: list[tuple[str, frozenset[FacilityType], int, str]] = [
    ("mining", frozenset({FacilityType.MINE}), 5, "تأسیسات معدنی"),
    ("steel", frozenset({FacilityType.STEEL_FACTORY}), 2, "کارخانه فولاد"),
    ("oilgas", frozenset({FacilityType.OIL_PLATFORM, FacilityType.GAS_PLATFORM}), 3, "دکل نفت و گاز"),
]


def build_limit_group_for(ftype: FacilityType) -> tuple[str, frozenset[FacilityType], int, str]:
    """گروه محدودیت ساختِ مربوط به یک نوع تأسیسات را برمی‌گرداند."""
    for group in BUILD_LIMIT_GROUPS:
        if ftype in group[1]:
            return group
    # پیش‌فرض امن (نباید رخ دهد): سهمیه‌ی تک‌نوعی ۳تایی
    return ("other", frozenset({ftype}), 3, FACILITY_FA.get(ftype, "تأسیسات"))


# کارخانه‌ی نظامی: هر ۱۲ ساعت ۲ تا (v1.9)
MIL_FACTORY_BUILD_LIMIT = 2

# سیستم اتحاد (v1.9): حداکثر تعداد کشورهایی که سازنده می‌تواند به اتحاد بیاورد (به‌جز خودش)
ALLIANCE_MAX_MEMBERS = 6

# ============================================================
#  سرمایه‌گذاری (v1.9): دسته‌ها و درصد سود در هر ۲۴ ساعت
#  ساختار: کلید → (نام فارسی، درصد سود ۲۴ساعته)
# ============================================================
INVESTMENT_CATEGORIES: dict[str, tuple[str, float]] = {
    "human_capital": ("سرمایه انسانی", 15.0),
    "education": ("آموزش", 12.0),
    "health": ("سلامت", 10.0),
    "science_tech": ("علم و فناوری", 20.0),
    "culture_art": ("فرهنگ و هنر", 7.0),
    "environment": ("محیط زیست", 8.0),
    "tourism": ("گردشگری", 9.0),
    "security_defense": ("امنیت و دفاع", 6.0),
    "intl_relations": ("روابط بین‌الملل", 7.0),
    "digital_economy": ("اقتصاد دیجیتال", 18.0),
}

INVESTMENT_YIELD_INTERVAL_H = 24       # سود سرمایه‌گذاری هر ۲۴ ساعت
INVEST_SATISFACTION_GAIN = 0.5         # افزایش رضایت عمومی (هر چرخه، داخلی یا خارجی)
# اثر سرمایه‌گذاری خارجی روی کشور هدف (هر چرخه‌ی ۲۴ساعته)
FOREIGN_INVEST_SATISFACTION_GAIN = 1.0
FOREIGN_INVEST_UNEMPLOYMENT_DROP = 0.3
FOREIGN_INVEST_INFLATION_DROP = 0.15

# ============================================================
#  کول‌داون کنش‌های دیپلماتیک (v1.9)
# ============================================================
MEETING_COOLDOWN_HOURS = 3            # دیدار حضوری: هر ۳ ساعت ۱ نشست
SPEECH_COOLDOWN_MINUTES = 10         # بیانیه (سخنرانی): هر ۱۰ دقیقه ۱
PHONE_CALL_COOLDOWN_MINUTES = 30     # تماس تلفنی: هر ۳۰ دقیقه ۱

# ============================================================
#  زمان‌بندی کنش‌های دیپلماتیک
# ============================================================
PHONE_CALL_DURATION_MINUTES = 5     # حداکثر مدت تماس تلفنی
MEETING_DURATION_MINUTES = 60       # مدت دیدار حضوری (یک ساعت)

# ============================================================
#  اثر ساخت‌وساز بر شاخص‌های اقتصادی (مدل ساده‌سازی‌شده)
#  هر تأسیسات جدید کمی بیکاری را کم و رضایت/قدرت را زیاد می‌کند.
# ============================================================
FACILITY_UNEMPLOYMENT_DROP = 0.3   # درصد کاهش بیکاری به ازای هر تأسیسات
FACILITY_SATISFACTION_GAIN = 1.0   # افزایش رضایت عمومی
FACILITY_ECON_POWER_GAIN = 0.5     # افزایش قدرت اقتصادی (از ۱۰۰)
FACILITY_INFLATION_DROP = 0.1      # کاهش تورم به‌خاطر افزایش تولید داخلی (v1.5)

# ============================================================
#  اثر تجارت ذخایر بر تورم (v1.5)
#  فروشنده: عرضه‌ی داخلی کم و تقاضا بالا می‌رود → تورم بالا
#  خریدار: عرضه‌ی داخلی بالا می‌رود → تورم پایین
# ============================================================
SALE_SELLER_INFLATION_DELTA = 0.2   # افزایش تورم کشور فروشنده
SALE_BUYER_INFLATION_DELTA = -0.15  # کاهش تورم کشور خریدار
SALE_SELLER_ECON_POWER_GAIN = 0.2   # درآمد ارزی → تقویت اندک اقتصاد فروشنده

# آستانه‌ی هشدار کمبود ذخایر — اگر مقدار از این کمتر شد، اعتراضات اعلام می‌شود
RESOURCE_SHORTAGE_THRESHOLD = 0.0

# جریمه‌ی نقض قرارداد (پلی‌بوک ماده ۶): ۱ میلیارد دلار
CONTRACT_BREACH_PENALTY_USD = 1_000_000_000

# ============================================================
#  🏭 کارخانه‌های نظامی (v1.7) — بازتولید تجهیزات
#  واحد منابع در دیتابیس: ذغال/آلومینیوم/آهن/فولاد = تن، نفت = میلیون بشکه،
#  گاز = میلیون متر مکعب، طلا = کیلوگرم. (طلا در متن آپدیت گاهی «تن» بود که اینجا به کیلوگرم تبدیل شده.)
# ============================================================

# هزینه‌ی ساخت هر کارخانه (دلار)
MIL_FACTORY_COST_USD: dict[MilitaryFactoryType, int] = {
    MilitaryFactoryType.ANTI_MISSILE: 5_000_000_000,
    MilitaryFactoryType.ARTILLERY: 1_000_000_000,
    MilitaryFactoryType.TANK: 2_500_000_000,
    MilitaryFactoryType.APC: 1_200_000_000,
    MilitaryFactoryType.FIGHTER: 20_000_000_000,
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: 10_000_000_000,
    MilitaryFactoryType.DRONE: 500_000_000,
    MilitaryFactoryType.HELICOPTER: 4_000_000_000,
    MilitaryFactoryType.CORVETTE: 2_000_000_000,
    MilitaryFactoryType.DESTROYER: 5_000_000_000,
    MilitaryFactoryType.BALLISTIC_MISSILE: 6_000_000_000,
    MilitaryFactoryType.CRUISE_MISSILE: 3_000_000_000,
}

# منابع لازم برای ساخت کارخانه (یک‌بار، هنگام احداث) — کلیدها مقدار ResourceType
MIL_FACTORY_BUILD_RESOURCES: dict[MilitaryFactoryType, dict[str, float]] = {
    MilitaryFactoryType.ANTI_MISSILE: {"coal": 400_000, "aluminum": 250_000, "iron": 600_000, "steel": 900_000, "oil": 0.3, "gas": 0.5, "gold": 2_000},
    MilitaryFactoryType.ARTILLERY: {"coal": 300_000, "aluminum": 120_000, "iron": 500_000, "steel": 700_000, "oil": 0.2, "gas": 0.3, "gold": 800},
    MilitaryFactoryType.TANK: {"coal": 600_000, "aluminum": 150_000, "iron": 900_000, "steel": 1_200_000, "oil": 0.4, "gas": 0.35, "gold": 1_000},
    MilitaryFactoryType.APC: {"coal": 400_000, "aluminum": 180_000, "iron": 600_000, "steel": 800_000, "oil": 0.25, "gas": 0.3, "gold": 700},
    MilitaryFactoryType.FIGHTER: {"coal": 800_000, "aluminum": 1_200_000, "iron": 700_000, "steel": 1_000_000, "oil": 0.6, "gas": 0.8, "gold": 5_000},
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: {"coal": 700_000, "aluminum": 900_000, "iron": 600_000, "steel": 900_000, "oil": 0.5, "gas": 0.7, "gold": 3_000},
    MilitaryFactoryType.DRONE: {"coal": 150_000, "aluminum": 300_000, "iron": 200_000, "steel": 250_000, "oil": 0.15, "gas": 0.2, "gold": 500},
    MilitaryFactoryType.HELICOPTER: {"coal": 500_000, "aluminum": 600_000, "iron": 500_000, "steel": 700_000, "oil": 0.4, "gas": 0.5, "gold": 2_000},
    MilitaryFactoryType.CORVETTE: {"coal": 900_000, "aluminum": 300_000, "iron": 1_200_000, "steel": 1_500_000, "oil": 0.6, "gas": 0.7, "gold": 3_000},
    MilitaryFactoryType.DESTROYER: {"coal": 1_200_000, "aluminum": 400_000, "iron": 1_600_000, "steel": 2_000_000, "oil": 0.8, "gas": 0.9, "gold": 6_000},
    MilitaryFactoryType.BALLISTIC_MISSILE: {"coal": 600_000, "aluminum": 500_000, "iron": 700_000, "steel": 900_000, "oil": 0.7, "gas": 0.8, "gold": 2_500},
    MilitaryFactoryType.CRUISE_MISSILE: {"coal": 500_000, "aluminum": 450_000, "iron": 600_000, "steel": 800_000, "oil": 0.6, "gas": 0.7, "gold": 2_000},
}

# مصرف منابع در هر چرخه‌ی بازدهی (متن آپدیت: «مصرف روزانه»)
MIL_FACTORY_INTAKE: dict[MilitaryFactoryType, dict[str, float]] = {
    MilitaryFactoryType.ANTI_MISSILE: {"steel": 120_000, "aluminum": 60_000, "oil": 0.04, "gas": 0.09, "gold": 200},
    MilitaryFactoryType.ARTILLERY: {"steel": 100_000, "iron": 80_000, "oil": 0.03, "gas": 0.07, "gold": 80},
    MilitaryFactoryType.TANK: {"steel": 180_000, "iron": 120_000, "oil": 0.08, "gas": 0.06, "gold": 100},
    MilitaryFactoryType.APC: {"steel": 130_000, "aluminum": 70_000, "oil": 0.05, "gas": 0.06, "gold": 70},
    MilitaryFactoryType.FIGHTER: {"aluminum": 200_000, "steel": 150_000, "oil": 0.1, "gas": 0.15, "gold": 400},
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: {"aluminum": 150_000, "steel": 120_000, "oil": 0.08, "gas": 0.12, "gold": 250},
    MilitaryFactoryType.DRONE: {"aluminum": 80_000, "steel": 60_000, "oil": 0.03, "gas": 0.05, "gold": 50},
    MilitaryFactoryType.HELICOPTER: {"aluminum": 120_000, "steel": 100_000, "oil": 0.07, "gas": 0.09, "gold": 150},
    MilitaryFactoryType.CORVETTE: {"steel": 250_000, "iron": 180_000, "oil": 0.12, "gas": 0.11, "gold": 200},
    MilitaryFactoryType.DESTROYER: {"steel": 300_000, "iron": 220_000, "oil": 0.15, "gas": 0.14, "gold": 300},
    MilitaryFactoryType.BALLISTIC_MISSILE: {"oil": 0.1, "gas": 0.1, "steel": 120_000, "aluminum": 90_000, "gold": 200},
    MilitaryFactoryType.CRUISE_MISSILE: {"oil": 0.09, "gas": 0.09, "steel": 110_000, "aluminum": 100_000, "gold": 150},
}

# تعداد تولید در هر چرخه و طول چرخه (ساعت). ناوچه/ناوشکن هر ۶ روز (۱۴۴ ساعت).
MIL_FACTORY_YIELD: dict[MilitaryFactoryType, tuple[int, int]] = {
    MilitaryFactoryType.ANTI_MISSILE: (5, 24),
    MilitaryFactoryType.ARTILLERY: (10, 24),
    MilitaryFactoryType.TANK: (20, 24),
    MilitaryFactoryType.APC: (20, 24),
    MilitaryFactoryType.FIGHTER: (5, 24),
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: (1, 24),
    MilitaryFactoryType.DRONE: (20, 24),
    MilitaryFactoryType.HELICOPTER: (8, 24),
    MilitaryFactoryType.CORVETTE: (5, 144),
    MilitaryFactoryType.DESTROYER: (2, 144),
    MilitaryFactoryType.BALLISTIC_MISSILE: (3, 24),
    MilitaryFactoryType.CRUISE_MISSILE: (5, 24),
}
