"""
ثابت‌های عددی بازی که مستقیماً از پلی‌بوک استخراج شده‌اند.
هزینه‌ی ساخت‌وسازها، بازدهی‌ها، کول‌داون‌ها و قوانین زمانی اینجا متمرکز شده‌اند
تا تنظیم سختی بازی در یک نقطه ممکن باشد.
"""

from __future__ import annotations

from .enums import (
    FACILITY_FA,
    FacilityType,
    GovernmentType,
    MilitaryFactoryType,
    NuclearFacilityType,
    NuclearTechType,
    ResourceType,
)

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
    ResourceType.URANIUM: 12,       # تن سنگ اورانیوم در ۲۴ ساعت (v1.10.4)
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

# تأسیسات مشترک: هر ۱۲ ساعت ۳ تا (v1.11) — از همان پنجره‌ی BUILD_LIMIT_WINDOW_HOURS استفاده می‌کند
JOINT_BUILD_LIMIT = 3

# سرمایه‌گذاری: هر ۱۲ ساعت ۲ تا (v1.11)
INVESTMENT_LIMIT = 2

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
# حداقل مبلغ سرمایه‌گذاری خارجی برای انتشار خبر در کانال اقتصاد (v1.10.5):
# سرمایه‌گذاری‌های کوچک‌تر از ۱۰۰ میلیارد دلار در کانال منتشر نمی‌شوند.
FOREIGN_INVEST_NEWS_MIN_USD = 100_000_000_000

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
# v1.10.1: زمان پرواز دیپلماتیک ثابت شد (دیگر بر اساس فاصله/AI نیست) — از هر کشور به هر کشور
FLIGHT_DURATION_MINUTES = 30        # مدت پرواز تا کشور مقصد (ثابت برای همه)
# اگر در طول نشست فعال این مدت هیچ پیامی میان طرفین ردوبدل نشود، ربات خودکار نشست را می‌بندد
MEETING_IDLE_TIMEOUT_MINUTES = 10   # تایم‌اوت سکوت نشست

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
# v1.10.5: طلا کاملاً از هزینه‌ی ساخت حذف شد (موجودی طلای کشورها بسیار کمتر از
# نیاز قبلی بود و باعث خطای «کمبود طلا» می‌شد).
MIL_FACTORY_BUILD_RESOURCES: dict[MilitaryFactoryType, dict[str, float]] = {
    MilitaryFactoryType.ANTI_MISSILE: {"coal": 400_000, "aluminum": 250_000, "iron": 600_000, "steel": 900_000, "oil": 0.3, "gas": 0.5},
    MilitaryFactoryType.ARTILLERY: {"coal": 300_000, "aluminum": 120_000, "iron": 500_000, "steel": 700_000, "oil": 0.2, "gas": 0.3},
    MilitaryFactoryType.TANK: {"coal": 600_000, "aluminum": 150_000, "iron": 900_000, "steel": 1_200_000, "oil": 0.4, "gas": 0.35},
    MilitaryFactoryType.APC: {"coal": 400_000, "aluminum": 180_000, "iron": 600_000, "steel": 800_000, "oil": 0.25, "gas": 0.3},
    MilitaryFactoryType.FIGHTER: {"coal": 800_000, "aluminum": 1_200_000, "iron": 700_000, "steel": 1_000_000, "oil": 0.6, "gas": 0.8},
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: {"coal": 700_000, "aluminum": 900_000, "iron": 600_000, "steel": 900_000, "oil": 0.5, "gas": 0.7},
    MilitaryFactoryType.DRONE: {"coal": 150_000, "aluminum": 300_000, "iron": 200_000, "steel": 250_000, "oil": 0.15, "gas": 0.2},
    MilitaryFactoryType.HELICOPTER: {"coal": 500_000, "aluminum": 600_000, "iron": 500_000, "steel": 700_000, "oil": 0.4, "gas": 0.5},
    MilitaryFactoryType.CORVETTE: {"coal": 900_000, "aluminum": 300_000, "iron": 1_200_000, "steel": 1_500_000, "oil": 0.6, "gas": 0.7},
    MilitaryFactoryType.DESTROYER: {"coal": 1_200_000, "aluminum": 400_000, "iron": 1_600_000, "steel": 2_000_000, "oil": 0.8, "gas": 0.9},
    MilitaryFactoryType.BALLISTIC_MISSILE: {"coal": 600_000, "aluminum": 500_000, "iron": 700_000, "steel": 900_000, "oil": 0.7, "gas": 0.8},
    MilitaryFactoryType.CRUISE_MISSILE: {"coal": 500_000, "aluminum": 450_000, "iron": 600_000, "steel": 800_000, "oil": 0.6, "gas": 0.7},
}

# مصرف منابع در هر چرخه‌ی بازدهی (متن آپدیت: «مصرف روزانه»)
# v1.10.5: طلا از مصرف چرخه‌ای هم حذف شد؛ پیش‌تر نبود طلا باعث می‌شد کارخانه
# بی‌سروصدا هیچ تولیدی نداشته باشد.
MIL_FACTORY_INTAKE: dict[MilitaryFactoryType, dict[str, float]] = {
    MilitaryFactoryType.ANTI_MISSILE: {"steel": 120_000, "aluminum": 60_000, "oil": 0.04, "gas": 0.09},
    MilitaryFactoryType.ARTILLERY: {"steel": 100_000, "iron": 80_000, "oil": 0.03, "gas": 0.07},
    MilitaryFactoryType.TANK: {"steel": 180_000, "iron": 120_000, "oil": 0.08, "gas": 0.06},
    MilitaryFactoryType.APC: {"steel": 130_000, "aluminum": 70_000, "oil": 0.05, "gas": 0.06},
    MilitaryFactoryType.FIGHTER: {"aluminum": 200_000, "steel": 150_000, "oil": 0.1, "gas": 0.15},
    MilitaryFactoryType.TRANSPORT_AIRCRAFT: {"aluminum": 150_000, "steel": 120_000, "oil": 0.08, "gas": 0.12},
    MilitaryFactoryType.DRONE: {"aluminum": 80_000, "steel": 60_000, "oil": 0.03, "gas": 0.05},
    MilitaryFactoryType.HELICOPTER: {"aluminum": 120_000, "steel": 100_000, "oil": 0.07, "gas": 0.09},
    MilitaryFactoryType.CORVETTE: {"steel": 250_000, "iron": 180_000, "oil": 0.12, "gas": 0.11},
    MilitaryFactoryType.DESTROYER: {"steel": 300_000, "iron": 220_000, "oil": 0.15, "gas": 0.14},
    MilitaryFactoryType.BALLISTIC_MISSILE: {"oil": 0.1, "gas": 0.1, "steel": 120_000, "aluminum": 90_000},
    MilitaryFactoryType.CRUISE_MISSILE: {"oil": 0.09, "gas": 0.09, "steel": 110_000, "aluminum": 100_000},
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

# ============================================================
#  🪖 استقرار نیرو (v1.11) — فقط برای کشورهای VIP
# ============================================================
# هزینه‌ی نفت استقرار: بین ۱ تا ۱۰ میلیون بشکه (وابسته به حجم نیروی اعزامی)
DEPLOY_OIL_COST_MIN = 1.0   # میلیون بشکه
DEPLOY_OIL_COST_MAX = 10.0  # میلیون بشکه
# ضریب تصادفی هزینه به ازای هر واحد تجهیزات (قبل از clamp به بازه‌ی بالا)
DEPLOY_OIL_PER_UNIT_MIN = 0.15
DEPLOY_OIL_PER_UNIT_MAX = 0.35

# نگاشت سه دسته‌ی کلانِ نیرو (زمینی/دریایی/هوایی) به مقادیر واقعی branch در countries.json.
# هر مقدار: (نام فارسی برای خبر، نام پایه‌ی عکس در D:\PictureDB\Military، مجموعه‌ی branchها).
DEPLOY_BRANCHES: dict[str, tuple[str, str, frozenset[str]]] = {
    "ground": ("زمینی", "ground", frozenset({"نیروی زمینی", "خودروهای زمینی", "سامانه‌های دفاعی"})),
    "navy": ("دریایی", "navy", frozenset({"نیروی دریایی"})),
    "air": ("هوایی", "air", frozenset({"نیروی هوایی", "سامانه‌های حمله هوایی"})),
}

# ============================================================
#  🏗 پایگاه‌های نظامی (v2.0) — فقط کشورهای VIP
# ============================================================
MILITARY_BASE_TYPES: dict[str, tuple[str, float, int]] = {
    "air_base": ("پایگاه هوایی", 20_000_000_000, 200),     # 20B$, capacity 200
    "ground_base": ("پایگاه زمینی", 15_000_000_000, 500),  # 15B$, capacity 500
    "naval_base": ("پایگاه دریایی", 25_000_000_000, 100),   # 25B$, capacity 100
}

MAX_FOREIGN_BASES_PER_OWNER = 5  # حداکثر پایگاه‌های خارجی یک کشور VIP
MAX_FOREIGN_BASES_PER_HOST = 3   # حداکثر پایگاه‌های خارجی مستقر در یک کشور میزبان

# ============================================================
#  🛰 ماهواره‌های جاسوسی فضایی (v2.0) — فقط برای کشورهای VIP
# ============================================================
SPY_SATELLITE_COST_USD = 15_000_000_000.0  # 15 Billion USD
SPY_SATELLITE_OIL_COST = 2.0               # 2 Million Barrels
SPY_SATELLITE_STEEL_COST = 500_000.0        # 500k Tons
SPY_SATELLITE_ALUMINUM_COST = 800_000.0     # 800k Tons

SPY_SATELLITE_LIFESPAN_DAYS = 7            # ۷ روز عمر مفید در مدار
SATELLITE_ORBIT_TIME_MINUTES = 30          # ۳۰ دقیقه زمان رسیدن به مدار

# ============================================================
#  🏛 سیستم حاکمیت (v1.10.2)
# ============================================================

# تعداد دفعات مجاز تغییر نظام حاکمیتی (یکی در بدو ورود، یکی در طول بازی)
GOVT_MAX_CHANGES = 2

# بونوس‌های هر نظام حاکمیتی — هنگام انتخاب/تغییر نظام اعمال می‌شوند
# کلیدها: satisfaction, stability, unemployment, inflation, economic_power
GOVERNMENT_BONUSES: dict[GovernmentType, dict[str, float]] = {
    GovernmentType.REPUBLIC:                  {"satisfaction": 3, "stability": 2, "unemployment": -1},
    GovernmentType.DEMOCRACY:                 {"satisfaction": 5, "stability": 1, "unemployment": -0.5},
    GovernmentType.MONARCHY:                  {"stability": 5, "economic_power": 2, "satisfaction": -2},
    GovernmentType.CONSTITUTIONAL_MONARCHY:   {"stability": 3, "satisfaction": 2, "economic_power": 1},
    GovernmentType.COMMUNISM:                 {"unemployment": -3, "inflation": -2, "satisfaction": -3, "stability": 3},
    GovernmentType.THEOCRACY:                 {"stability": 5, "satisfaction": -2, "economic_power": -1},
    GovernmentType.DICTATORSHIP:              {"stability": 8, "satisfaction": -5, "economic_power": 2},
    GovernmentType.FEDERAL:                   {"satisfaction": 2, "economic_power": 2, "stability": -1},
}

# ---------- مالیات ----------
# درآمد مالیاتی هر ۲۴ ساعت = tax_rate/100 × جمعیت × TAX_REVENUE_PER_CAPITA
TAX_REVENUE_PER_CAPITA = 50.0          # دلار به ازای هر نفر در نرخ ۱۰۰٪
TAX_YIELD_INTERVAL_H = 24             # بازه‌ی جمع‌آوری مالیات (ساعت)
TAX_DEFAULT_RATE = 10.0                # نرخ پیش‌فرض مالیات (درصد)
TAX_MIN_RATE = 0.0
TAX_MAX_RATE = 50.0
# تأثیر مالیات بر رضایت عمومی هر ۲۴ ساعت
TAX_SATISFACTION_THRESHOLDS: list[tuple[float, float]] = [
    # (حداکثر نرخ، تغییر رضایت)
    (10.0,  1.0),    # نرخ ≤ ۱۰٪: +۱ رضایت
    (15.0,  0.0),    # ≤ ۱۵٪: بدون تغییر
    (20.0, -1.0),    # ≤ ۲۰٪: -۱
    (30.0, -3.0),    # ≤ ۳۰٪: -۳
    (50.0, -5.0),    # ≤ ۵۰٪: -۵
]

# ---------- اعتراضات ----------
PROTEST_SATISFACTION_THRESHOLD = 30.0  # رضایت کمتر از این → شانس تولید اعتراض
PROTEST_TAX_THRESHOLD = 25.0          # مالیات بالاتر از این → شانس اعتراض اقتصادی
PROTEST_CHANCE_PER_TICK = 0.25         # احتمال تولید اعتراض در هر تیک (۰ تا ۱)
PROTEST_ACTIVE_STABILITY_DROP = 1.5    # کاهش ثبات هر ۲۴ ساعت به ازای هر اعتراض فعال
PROTEST_ACTIVE_SATISFACTION_DROP = 1.0 # کاهش رضایت هر ۲۴ ساعت
# اثر سرکوب اعتراض
SUPPRESS_STABILITY_GAIN = 2.0         # افزایش ثبات (موقت)
SUPPRESS_SATISFACTION_DROP = 3.0      # کاهش رضایت (مردم ناراضی‌ترند)
# اثر ارجاع به مجلس
PARLIAMENT_REFERRAL_STABILITY_GAIN = 1.0
PARLIAMENT_REFERRAL_SATISFACTION_GAIN = 1.5

# ---------- ویزا ----------
VISA_SATISFACTION_PENALTY = 0.5       # کاهش رضایت کشور هدف به ازای هر ویزای اجباری

# ============================================================
#  ☢️ برنامه‌ی توسعه‌ی هسته‌ای (v1.10.4) — فقط کشورهای VIP
# ============================================================
# مقیاس زمانی: هر «روز» سند اسپک = ۱۲ ساعت واقعیِ بازی (مقیاس نیم‌روز).
# کل مسیر فاز ۱ تا ۵ حدود ۶ روز واقعی طول می‌کشد.
NUCLEAR_DAY_HOURS = 12.0

# ---------- تحقیقات و فناوری ----------
# هر فناوری: (نام فارسی، هزینه‌ی دلاری، زمان تحقیق بر حسب «روزِ اسپک»، پیش‌نیاز)
NUCLEAR_TECHS: dict[NuclearTechType, tuple[str, float, float, NuclearTechType | None]] = {
    NuclearTechType.GEOLOGY_2: ("زمین‌شناسی سطح ۲ و نقشه‌ی منابع", 3_000_000_000.0, 0.5, None),
    NuclearTechType.IND_CHEMISTRY: ("شیمی صنعتی", 5_000_000_000.0, 1.0, NuclearTechType.GEOLOGY_2),
    NuclearTechType.CENTRIFUGE: ("متالورژی و فناوری سانتریفیوژ", 12_000_000_000.0, 1.5, NuclearTechType.IND_CHEMISTRY),
    NuclearTechType.COMP_PHYSICS: ("فیزیک محاسباتی و طراحی کلاهک", 20_000_000_000.0, 2.0, NuclearTechType.CENTRIFUGE),
    NuclearTechType.DELIVERY_SYS: ("سامانه‌ی حمل کلاهک", 15_000_000_000.0, 1.0, NuclearTechType.COMP_PHYSICS),
}

# ---------- تأسیسات هسته‌ای ----------
# هر تأسیسات: (نام فارسی، هزینه‌ی دلاری، زمان ساخت بر حسب «روزِ اسپک»، فناوری پیش‌نیاز، سقف تعداد)
NUCLEAR_FACILITIES: dict[NuclearFacilityType, tuple[str, float, float, NuclearTechType, int]] = {
    NuclearFacilityType.MILL: (
        "آسیاب کیک زرد", 8_000_000_000.0, 2.0, NuclearTechType.GEOLOGY_2, 3),
    NuclearFacilityType.CONVERSION: (
        "کارخانه‌ی تبدیل UF6", 14_000_000_000.0, 3.0, NuclearTechType.IND_CHEMISTRY, 2),
    NuclearFacilityType.CENTRIFUGE_PLANT: (
        "کارخانه‌ی سانتریفیوژ", 18_000_000_000.0, 2.0, NuclearTechType.CENTRIFUGE, 2),
    NuclearFacilityType.ENRICHMENT_HALL: (
        "سالن غنی‌سازی", 25_000_000_000.0, 3.0, NuclearTechType.CENTRIFUGE, 3),
    NuclearFacilityType.WEAPONS_LAB: (
        "آزمایشگاه تسلیحاتی", 30_000_000_000.0, 2.0, NuclearTechType.COMP_PHYSICS, 1),
    NuclearFacilityType.TEST_SITE: (
        "سایت آزمایش هسته‌ای", 10_000_000_000.0, 1.0, NuclearTechType.COMP_PHYSICS, 1),
}

# منابع لازم برای ساخت هر تأسیسات (به‌جز بودجه): {منبع: مقدار}
NUCLEAR_FACILITY_RESOURCES: dict[NuclearFacilityType, dict[ResourceType, float]] = {
    NuclearFacilityType.MILL: {ResourceType.STEEL: 200_000, ResourceType.COAL: 300_000},
    NuclearFacilityType.CONVERSION: {ResourceType.STEEL: 400_000, ResourceType.ALUMINUM: 150_000},
    NuclearFacilityType.CENTRIFUGE_PLANT: {ResourceType.STEEL: 350_000, ResourceType.ALUMINUM: 250_000},
    NuclearFacilityType.ENRICHMENT_HALL: {ResourceType.STEEL: 600_000, ResourceType.ALUMINUM: 300_000},
    NuclearFacilityType.WEAPONS_LAB: {ResourceType.STEEL: 500_000, ResourceType.GOLD: 500},
    NuclearFacilityType.TEST_SITE: {ResourceType.STEEL: 150_000, ResourceType.COAL: 200_000},
}

# هزینه‌ی اضافی ساخت زیرزمینی (ضریب هزینه و زمان) در عوض کاهش ریسک افشا
NUCLEAR_UNDERGROUND_COST_MULT = 2.2
NUCLEAR_UNDERGROUND_TIME_MULT = 1.6
NUCLEAR_UNDERGROUND_EXPOSURE_CUT = 0.45   # ضریب کاهش افشا برای تأسیسات زیرزمینی

# محدودیت ساخت تأسیسات هسته‌ای: حداکثر ۲ تأسیسات در هر پنجره‌ی ۱۲ ساعته
NUCLEAR_BUILD_LIMIT = 2

# ---------- فاز ۱: آسیاب کیک زرد ----------
# هر آسیاب در هر ۲۴ ساعت این مقدار سنگ اورانیوم مصرف و کیک زرد تولید می‌کند
MILL_URANIUM_INTAKE_PER_24H = 10.0    # تن سنگ اورانیوم
MILL_YELLOWCAKE_PER_24H = 6.0         # تن کیک زرد (U3O8)

# ---------- فاز ۲: تبدیل به UF6 ----------
CONVERSION_YELLOWCAKE_INTAKE_PER_24H = 5.0   # تن کیک زرد مصرفی
CONVERSION_UF6_PER_24H = 4.0                 # تن UF6 تولیدی

# ---------- فاز ۳: سانتریفیوژ و غنی‌سازی ----------
CENTRIFUGE_BATCH_SIZE = 500                  # هر چرخه‌ی تولید، این تعداد سانتریفیوژ می‌سازد
CENTRIFUGE_BATCH_COST_USD = 2_000_000_000.0  # هزینه‌ی دلاری هر چرخه
CENTRIFUGE_BATCH_STEEL = 80_000.0            # تن فولاد هر چرخه
CENTRIFUGE_BATCH_ALUMINUM = 60_000.0         # تن آلومینیوم هر چرخه
CENTRIFUGE_BATCH_HOURS = 6.0                 # زمان ساخت هر چرخه (ساعت)
CENTRIFUGE_SWU_PER_UNIT_PER_24H = 0.9        # SWU تولیدی هر سانتریفیوژ در ۲۴ ساعت
ENRICHMENT_HALL_CENTRIFUGE_CAPACITY = 6_000  # ظرفیت هر سالن غنی‌سازی

# رده‌های غنی‌سازی: (کلید، نام فارسی، درصد، SWU لازم برای هر کیلوگرم محصول، رده‌ی پیش‌نیاز)
ENRICHMENT_TIERS: list[tuple[str, str, float, float, str | None]] = [
    ("u235_35", "۳.۵٪ (سوخت نیروگاهی)", 3.5, 6.0, None),
    ("u235_20", "۲۰٪ (سوخت تحقیقاتی)", 20.0, 30.0, "u235_35"),
    ("u235_60", "۶۰٪ (آستانه‌ی تسلیحاتی)", 60.0, 90.0, "u235_20"),
    ("u235_90", "۹۰٪ (تسلیحاتی — HEU)", 90.0, 180.0, "u235_60"),
]

# مصرف UF6 برای هر کیلوگرم اورانیوم غنی‌شده‌ی ۳.۵٪ (کیلوگرم UF6)
UF6_KG_PER_KG_LEU = 9.0

# ---------- فاز ۴: مونتاژ کلاهک ----------
WARHEAD_HEU_REQUIRED_KG = 25.0            # کیلوگرم اورانیوم ۹۰٪ برای هر کلاهک
WARHEAD_ASSEMBLY_DAYS = 2.0               # زمان مونتاژ («روزِ اسپک»)
WARHEAD_ASSEMBLY_COST_USD = 8_000_000_000.0
WARHEAD_YIELD_KT_RANGE = (15.0, 150.0)    # بازه‌ی قدرت تصادفی کلاهک (کیلوتن)

# ---------- فاز ۵: آزمایش هسته‌ای ----------
NUCLEAR_TEST_DAYS = 1.0                   # زمان آماده‌سازی آزمایش («روزِ اسپک»)
NUCLEAR_TEST_COST_USD = 5_000_000_000.0
NUCLEAR_TEST_SATISFACTION_GAIN = 6.0      # افتخار ملی
NUCLEAR_TEST_STABILITY_DROP = 3.0         # فشار بین‌المللی
NUCLEAR_TEST_EXPOSURE = 100.0             # آزمایش = افشای کامل برنامه

# ---------- ریسک افشا (شاخص انباشتی ۰ تا ۱۰۰) ----------
# افزایش شاخص افشا به ازای هر اقدام در هر فاز (طبق درصدهای اسپک، به‌صورت انباشتی)
NUCLEAR_EXPOSURE_PER_PHASE: dict[int, float] = {
    1: 10.0,   # فاز ۱: ۱۰٪
    2: 25.0,   # فاز ۲: ۲۵٪
    3: 50.0,   # فاز ۳: ۵۰٪
    4: 75.0,   # فاز ۴: ۷۵٪
    5: 100.0,  # فاز ۵: افشای کامل
}
# ضریب تبدیل شاخص افشا به احتمال کشف در هر تیک زمان‌بند
NUCLEAR_DETECTION_CHANCE_FACTOR = 0.004
# پوشش صلح‌آمیز: سقف رده‌ی مجاز غنی‌سازی + ضریب کاهش افشا
NUCLEAR_CIVILIAN_COVER_TIER = "u235_20"
NUCLEAR_CIVILIAN_COVER_EXPOSURE_CUT = 0.6
# هزینه‌ی ۲۴ساعته‌ی برنامه‌ی ضدجاسوسی و میزان کاهش شاخص افشا
NUCLEAR_COUNTERINTEL_COST_USD = 4_000_000_000.0
NUCLEAR_COUNTERINTEL_EXPOSURE_DROP = 12.0

# ---------- بازدارندگی ----------
# به ازای هر کلاهک: افزایش قدرت نظامی و کاهش شانس موفقیت حمله‌ی دشمن (درصد)
NUCLEAR_DETERRENCE_POWER_PER_WARHEAD = 2.5
NUCLEAR_DETERRENCE_DEFENSE_PER_WARHEAD = 3.0
NUCLEAR_DETERRENCE_MAX_DEFENSE = 30.0

# ---------- خرابکاری سایبری (استاکس‌نت) ----------
CYBER_SABOTAGE_COST_USD = 6_000_000_000.0
CYBER_SABOTAGE_SUCCESS_BASE = 55.0            # درصد پایه‌ی موفقیت
CYBER_SABOTAGE_CENTRIFUGE_LOSS = (0.2, 0.6)   # بازه‌ی درصد سانتریفیوژهای نابودشده
CYBER_SABOTAGE_COOLDOWN_HOURS = 24


