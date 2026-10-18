"""
سرویس جغرافیا (v1.10.6): همسایگی، فاصله، دسترسی دریایی و مسیر محموله‌ها.

داده از data/geography.json خوانده و در حافظه کش می‌شود (بدون I/O در هر فراخوانی).
این لایه پایه‌ی امکان‌سنجی حملات، رهگیری محموله و گشت مرزی است.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
from collections import deque
from functools import lru_cache
from pathlib import Path


logger = logging.getLogger(__name__)

# مسیر فایل داده‌ی جغرافیا
_GEO_FILE = Path(__file__).resolve().parents[2] / "data" / "geography.json"

# --- رده‌های فاصله ---
TIER_NEIGHBOR = "neighbor"              # همسایه‌ی زمینی
TIER_REGIONAL = "regional"              # هم‌منطقه / فاصله‌ی متوسط
TIER_CONTINENTAL = "continental"        # همان قاره ولی دور
TIER_INTERCONTINENTAL = "intercontinental"  # فراقاره‌ای

# آستانه‌های فاصله (کیلومتر) برای تعیین رده
_REGIONAL_MAX_KM = 3000.0
_CONTINENTAL_MAX_KM = 8000.0

# حداکثر انحراف مجاز مسیر نسبت به خط مستقیم (برای تشخیص «روی مسیر بودن»)
_MAX_DETOUR_RATIO = 1.35
# سقف مطلق انحراف (کیلومتر) — جلوی ورود کشورهای بی‌ربط به مسیرهای طولانی را می‌گیرد
_MAX_DETOUR_KM = 1200.0


@lru_cache(maxsize=1)
def _load_geo() -> dict[str, dict]:
    """خواندن و کش‌کردن داده‌ی جغرافیا (یک‌بار در طول عمر پروسه)."""
    try:
        raw = json.loads(_GEO_FILE.read_text(encoding="utf-8"))
        return raw.get("countries", {})
    except Exception as exc:  # noqa: BLE001 — نبود فایل نباید ربات را بشکند
        logger.exception("Failed to load geography.json: %s", exc)
        return {}


def get_geo(name_en: str) -> dict | None:
    """داده‌ی جغرافیایی یک کشور بر اساس نام انگلیسی (name_en)."""
    return _load_geo().get(name_en)


def has_geo_data(name_en: str) -> bool:
    """آیا برای این کشور داده‌ی جغرافیایی داریم؟"""
    return name_en in _load_geo()


def are_neighbors(a_en: str, b_en: str) -> bool:
    """آیا دو کشور همسایه‌ی زمینی هستند؟ (دوطرفه بررسی می‌شود)"""
    if a_en == b_en:
        return False
    a = get_geo(a_en)
    b = get_geo(b_en)
    if a is None or b is None:
        return False
    return b_en in a.get("neighbors", []) or a_en in b.get("neighbors", [])


def neighbors_of(name_en: str) -> list[str]:
    """فهرست همسایگان زمینی یک کشور (نام انگلیسی)."""
    geo = get_geo(name_en)
    return list(geo.get("neighbors", [])) if geo else []


def shared_seas(a_en: str, b_en: str) -> list[str]:
    """دریاها/اقیانوس‌های مشترک بین دو کشور."""
    a = get_geo(a_en)
    b = get_geo(b_en)
    if a is None or b is None:
        return []
    return sorted(set(a.get("seas", [])) & set(b.get("seas", [])))


def shares_sea(a_en: str, b_en: str) -> bool:
    """آیا دو کشور به آب مشترکی دسترسی دارند؟ (پیش‌نیاز حمله‌ی دریایی)"""
    return bool(shared_seas(a_en, b_en))


def is_landlocked(name_en: str) -> bool:
    """آیا کشور محصور در خشکی است (بدون دسترسی دریایی)؟"""
    geo = get_geo(name_en)
    return bool(geo) and not geo.get("seas", [])


def distance_km(a_en: str, b_en: str) -> float:
    """
    فاصله‌ی هوایی بین پایتخت دو کشور (کیلومتر) با فرمول هاورساین.
    اگر داده نبود، مقدار محافظه‌کارانه‌ی بزرگ برمی‌گردد تا حمله‌ی دور رد شود.
    """
    a = get_geo(a_en)
    b = get_geo(b_en)
    if a is None or b is None:
        return 9999.0

    lat1, lon1 = a.get("coords", [0.0, 0.0])
    lat2, lon2 = b.get("coords", [0.0, 0.0])

    r = 6371.0  # شعاع زمین (کیلومتر)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)

    h = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def distance_tier(a_en: str, b_en: str) -> str:
    """
    رده‌ی فاصله‌ی دو کشور. همسایگی زمینی بر فاصله‌ی عددی اولویت دارد
    (مثلاً روسیه–چین همسایه‌اند هرچند پایتخت‌هایشان دور است).
    """
    if are_neighbors(a_en, b_en):
        return TIER_NEIGHBOR

    a = get_geo(a_en)
    b = get_geo(b_en)
    same_continent = bool(a and b) and a.get("continent") == b.get("continent")
    km = distance_km(a_en, b_en)

    if km <= _REGIONAL_MAX_KM:
        return TIER_REGIONAL
    if same_continent and km <= _CONTINENTAL_MAX_KM:
        return TIER_CONTINENTAL
    return TIER_INTERCONTINENTAL


def _is_between(origin_en: str, dest_en: str, candidate: str, total: float) -> bool:
    """
    آیا کشور سوم واقعاً روی مسیر مبدأ→مقصد است؟

    دو شرط:
    ۱. بین دو طرف باشد (فاصله‌اش به هیچ‌کدام از کل مسیر بیشتر نباشد).
    ۲. انحراف از خط مستقیم کم باشد — هم نسبی و هم مطلق.

    شرط دوم مهم است: در مسیرهای طولانی (مثل چین→آلمان با ۷۰۰۰ کیلومتر)،
    انحراف نسبی ۳۵٪ یعنی ۲۴۰۰ کیلومتر که کشورهای کاملاً بی‌ربط (مثل هند)
    را هم داخل مسیر می‌آورد. سقف مطلق جلوی این را می‌گیرد.
    """
    d_origin = distance_km(origin_en, candidate)
    d_dest = distance_km(candidate, dest_en)
    if d_origin >= total or d_dest >= total:
        return False

    detour = (d_origin + d_dest) - total
    return detour <= total * (_MAX_DETOUR_RATIO - 1.0) and detour <= _MAX_DETOUR_KM


def _land_path(origin_en: str, dest_en: str) -> list[str]:
    """
    کوتاه‌ترین زنجیره‌ی همسایگی زمینی بین دو کشور (BFS روی گراف همسایگان).
    خروجی: کشورهای واسط (بدون مبدأ و مقصد). اگر راه زمینی نباشد، لیست خالی.
    """
    if origin_en == dest_en:
        return []

    queue: deque[tuple[str, list[str]]] = deque([(origin_en, [])])
    seen = {origin_en}
    while queue:
        current, path = queue.popleft()
        for nxt in neighbors_of(current):
            if nxt in seen:
                continue
            if nxt == dest_en:
                return path  # واسط‌ها تا قبل از مقصد
            seen.add(nxt)
            queue.append((nxt, path + [nxt]))
    return []


def _land_corridor(origin_en: str, dest_en: str, total: float) -> set[str]:
    """
    همه‌ی کشورهایی که در «کریدور زمینی» بین مبدأ و مقصد قرار دارند.

    چرا فقط BFS کافی نیست: کوتاه‌ترین زنجیره‌ی همسایگی لزوماً مسیر واقعی
    محموله نیست. مثلاً روسیه→هند از نظر همسایگی از چین می‌گذرد، ولی مسیر
    واقعی از ایران/آذربایجان/پاکستان عبور می‌کند. اینجا هر کشوری که هم
    هندسی بین دو طرف باشد و هم از طریق همسایگی به یکی از آن‌ها وصل باشد،
    روی مسیر حساب می‌شود.
    """
    corridor: set[str] = set()

    for candidate in _load_geo():
        if candidate in (origin_en, dest_en):
            continue
        if not _is_between(origin_en, dest_en, candidate, total):
            continue
        # باید از طریق خشکی به یکی از دو طرف متصل باشد (همسایه یا همسایه‌ی همسایه)
        linked = (
            are_neighbors(candidate, origin_en)
            or are_neighbors(candidate, dest_en)
            or bool(set(neighbors_of(candidate)) & set(neighbors_of(origin_en)))
            or bool(set(neighbors_of(candidate)) & set(neighbors_of(dest_en)))
        )
        if linked:
            corridor.add(candidate)

    return corridor


def route_crosses(origin_en: str, dest_en: str) -> list[str]:
    """
    کشورهایی که مسیر یک محموله از خاک یا آب آن‌ها می‌گذرد (برای رهگیری محموله).

    مدل دو مسیره:
    - **مسیر زمینی:** کریدور زمینی بین دو کشور — هر کشوری که هندسی وسط باشد
      و از راه خشکی به یکی از دو طرف متصل باشد.
    - **مسیر دریایی:** اگر مبدأ و مقصد آب مشترک داشته باشند، کشورهای ساحلیِ
      همان آب که هندسی بین آن دو قرار دارند.

    در هر دو حالت کشور واسط باید واقعاً بین مبدأ و مقصد باشد، تا کشوری مثل
    کانادا در مسیر «آمریکا → بریتانیا» ظاهر نشود.
    """
    if origin_en == dest_en or are_neighbors(origin_en, dest_en):
        return []

    total = distance_km(origin_en, dest_en)
    if total >= 9999.0:
        return []

    on_route: set[str] = set()

    # --- مسیر زمینی: کریدور بین دو کشور ---
    on_route |= _land_corridor(origin_en, dest_en, total)

    # --- مسیر دریایی: کشورهای ساحلیِ آبِ مشترکِ مبدأ و مقصد ---
    common_seas = set(shared_seas(origin_en, dest_en))
    if common_seas:
        for candidate, data in _load_geo().items():
            if candidate in (origin_en, dest_en):
                continue
            if not common_seas & set(data.get("seas", [])):
                continue
            if _is_between(origin_en, dest_en, candidate, total):
                on_route.add(candidate)

    return sorted(on_route)


def is_on_route(watcher_en: str, origin_en: str, dest_en: str) -> bool:
    """آیا محموله‌ی مبدأ→مقصد از قلمرو این کشور عبور می‌کند؟"""
    return watcher_en in route_crosses(origin_en, dest_en)


def describe_position(a_en: str, b_en: str) -> str:
    """توصیف فارسی موقعیت دو کشور نسبت به هم (برای نمایش در پنل و خبر)."""
    tier = distance_tier(a_en, b_en)
    km = distance_km(a_en, b_en)
    labels = {
        TIER_NEIGHBOR: "همسایه‌ی مرزی",
        TIER_REGIONAL: "هم‌منطقه",
        TIER_CONTINENTAL: "هم‌قاره (دوردست)",
        TIER_INTERCONTINENTAL: "فراقاره‌ای",
    }
    label = labels.get(tier, tier)
    sea = "دارای آب مشترک" if shares_sea(a_en, b_en) else "بدون آب مشترک"
    return f"{label} — {km:,.0f} کیلومتر — {sea}"


# ============================================================
#  ژئوپلیتیک تنگه‌های استراتژیک جهان و گراف دریایی (آپدیت ۳ و ۱۱)
# ============================================================

STRAITS_DEFINITIONS: dict[str, dict] = {
    "hormuz": {
        "id": "hormuz",
        "name_fa": "تنگه هرمز",
        "name_en": "Strait of Hormuz",
        "controller": "Iran",
        "coords": [26.56, 56.25],
        "connects": ("persian_gulf", "gulf_of_oman"),
        "description": "شاهراه انرژی جهان، اتصال خلیج فارس به دریای عمان و اقیانوس هند",
    },
    "bering": {
        "id": "bering",
        "name_fa": "تنگه برینگ",
        "name_en": "Bering Strait",
        "controller": "USA",
        "coords": [65.80, -168.90],
        "connects": ("pacific", "arctic"),
        "description": "گذرگاه استراتژیک اقیانوس آرام شمالی و قطب شمال",
    },
    "dover": {
        "id": "dover",
        "name_fa": "تنگه دوور (مانش)",
        "name_en": "Strait of Dover",
        "controller": "Britain",
        "coords": [51.13, 1.45],
        "connects": ("atlantic", "north_sea"),
        "description": "کانال مانش، مسیر اتصال دریای شمال و اروپای شمالی به اقیانوس اطلس",
    },
    "bosphorus": {
        "id": "bosphorus",
        "name_fa": "تنگه بسفر",
        "name_en": "Bosphorus Strait",
        "controller": "Turkey",
        "coords": [41.11, 29.07],
        "connects": ("black_sea", "mediterranean"),
        "description": "گذرگاه حیاتی دریای سیاه به دریای مدیترانه",
    },
    "dardanelles": {
        "id": "dardanelles",
        "name_fa": "تنگه داردانل",
        "name_en": "Dardanelles Strait",
        "controller": "Turkey",
        "coords": [40.20, 26.40],
        "connects": ("black_sea", "mediterranean"),
        "description": "تنگه مکمل بسفر در کنترل ترکیه جهت اتصال به اژه و مدیترانه",
    },
    "gibraltar": {
        "id": "gibraltar",
        "name_fa": "تنگه جبل‌الطارق",
        "name_en": "Strait of Gibraltar",
        "controller": "Spain",
        "coords": [35.98, -5.60],
        "connects": ("mediterranean", "atlantic"),
        "description": "تنها معبر طبیعی اتصال دریای مدیترانه به اقیانوس اطلس",
    },
    "laperouse": {
        "id": "laperouse",
        "name_fa": "تنگه لاپروش (سویا)",
        "name_en": "La Perouse Strait",
        "controller": "Japan",
        "coords": [45.70, 142.00],
        "connects": ("sea_of_japan", "pacific"),
        "description": "مسیر دریای ژاپن و اختسک به اقیانوس آرام شمالی",
    },
    "tsushima": {
        "id": "tsushima",
        "name_fa": "تنگه تسوشیما",
        "name_en": "Tsushima Strait",
        "controller": "SouthKorea",
        "coords": [34.40, 129.50],
        "connects": ("east_china_sea", "sea_of_japan"),
        "description": "معبر استراتژیک دریای چین شرقی به دریای ژاپن",
    },
    "bab_el_mandeb": {
        "id": "bab_el_mandeb",
        "name_fa": "تنگه باب‌المندب",
        "name_en": "Bab el-Mandeb Strait",
        "controller": "Yemen",
        "coords": [12.58, 43.33],
        "connects": ("red_sea", "arabian_sea"),
        "description": "ورودی جنوبی دریای سرخ و شاهراه اتصال آسیا به اروپا",
    },
    "kerch": {
        "id": "kerch",
        "name_fa": "تنگه کرچ",
        "name_en": "Kerch Strait",
        "controller": "Russia",
        "coords": [45.31, 36.52],
        "connects": ("black_sea", "azov_sea"),
        "description": "مسیر اتصال دریای آزوف به دریای سیاه",
    },
    "messina": {
        "id": "messina",
        "name_fa": "تنگه مسینا",
        "name_en": "Strait of Messina",
        "controller": "Italy",
        "coords": [38.24, 15.63],
        "connects": ("mediterranean_west", "mediterranean_east"),
        "description": "گذرگاه مابین سیسیل و شبه‌جزیره ایتالیا در مرکز مدیترانه",
    },
    "suez": {
        "id": "suez",
        "name_fa": "کانال سوئز",
        "name_en": "Suez Canal",
        "controller": "Egypt",
        "coords": [29.97, 32.56],
        "connects": ("red_sea", "mediterranean"),
        "description": "آبراه تاریخی اتصال آسیا و خاورمیانه به اروپا",
    },
    "taiwan_strait": {
        "id": "taiwan_strait",
        "name_fa": "تنگه تایوان",
        "name_en": "Taiwan Strait",
        "controller": "Taiwan",
        "coords": [24.00, 119.50],
        "connects": ("south_china_sea", "east_china_sea"),
        "description": "معبر پرتردد اتصال دریای چین جنوبی به دریای چین شرقی و اقیانوس آرام",
    },
    "oresund": {
        "id": "oresund",
        "name_fa": "تنگه سوند (دانمارک/سوئد)",
        "name_en": "Oresund Strait",
        "controller": "Sweden",
        "coords": [55.75, 12.70],
        "connects": ("baltic_sea", "north_sea"),
        "description": "ورودی انحصاری دریای بالتیک به دریای شمال و اقیانوس اطلس",
    },
}

# یال‌های ارتباطی کریدورهای دریایی و تنگه‌های جهان: (مبدأ، مقصد، شناسه تنگه یا None، وزن مسافتی)
_MARITIME_CORRIDOR_COORDS: dict[str, list[float]] = {
    # آمریکای شمالی و جنوبی (حوضه اطلس)
    "us_east": [37.0, -75.5],             # خروجی خلیج چساپیک و بنادر اطلس آمریکا (نورفک/نیویورک)
    "mid_atlantic": [36.0, -40.0],         # میانه اقیانوس اطلس شمالی
    "north_atlantic": [48.0, -25.0],       # مسیر اطلس شمالی به بریتانیا و کانال مانش
    "azores_gate": [36.0, -18.0],          # معبر جنوب مجمع‌الجزایر آزور به سمت جبل‌الطارق
    "brazil_coast": [-23.0, -42.0],        # کریدور ساحلی اطلس جنوبی (ریودوژانیرو/سنتوس)
    "equator_atlantic": [0.0, -25.0],      # اقیانوس اطلس استوایی

    # اروپای غربی، دریای شمال و بالتیک
    "portugal_coast": [40.0, -10.0],       # اقیانوس اطلس روبه‌روی پرتغال و لیسبون
    "bay_of_biscay": [45.0, -7.0],         # خلیج بیسکای (فرانسه/شمال اسپانیا)
    "english_channel_west": [49.5, -4.5],  # مدخل غربی کانال مانش
    "dover": [51.13, 1.45],                # تنگه دوور
    "north_sea_mid": [54.5, 4.5],          # مرکز دریای شمال (آلمان/بریتانیا)
    "oresund": [55.75, 12.70],             # تنگه اورسوند (دانمارک/سوئد)
    "baltic_mid": [56.5, 19.0],            # مرکز دریای بالتیک (سوئد/لهستان/روسیه)

    # مدیترانه و دریای سیاه
    "gibraltar": [35.98, -5.60],           # تنگه جبل‌الطارق
    "west_med": [36.5, 0.0],               # غرب مدیترانه (جنوب اسپانیا)
    "central_med": [35.5, 15.0],           # مرکز مدیترانه (جنوب سیسیل/مالت)
    "messina": [38.24, 15.63],             # تنگه مسینا
    "east_med": [34.5, 25.0],              # شرق مدیترانه (جنوب کرت/یونان)
    "suez_north": [31.5, 32.3],            # مدخل شمالی کانال سوئز (بندر سعید)
    "suez": [29.97, 32.56],                # کانال سوئز
    "bosphorus": [41.11, 29.07],           # تنگه بسفر
    "dardanelles": [40.20, 26.40],         # تنگه داردانل
    "black_sea_mid": [43.5, 34.0],         # مرکز دریای سیاه (ترکیه/روسیه/اوکراین)
    "kerch": [45.31, 36.52],               # تنگه کرچ

    # دریای سرخ، خلیج فارس و اقیانوس هند
    "red_sea_mid": [21.0, 38.0],           # مرکز دریای سرخ
    "bab_el_mandeb": [12.58, 43.33],       # تنگه باب‌المندب
    "gulf_of_aden": [12.5, 48.0],          # خلیج عدن
    "persian_gulf_mid": [27.0, 51.5],      # مرکز خلیج فارس (ایران/قطر/عربستان)
    "hormuz": [26.56, 56.25],              # تنگه هرمز
    "gulf_of_oman": [24.5, 59.0],          # دریای عمان
    "arabian_sea_mid": [12.0, 60.0],       # مرکز دریای عربی
    "sri_lanka_south": [5.5, 80.5],        # گذرگاه دریایی جنوب سری‌لانکا/هند

    # آسیای شرقی و اقیانوس آرام غربی
    "malacca_north": [5.5, 95.5],          # ورودی دریای آندامان به تنگه مالاکا
    "singapore": [1.3, 103.8],             # تنگه مالاکا و سنگاپور
    "south_china_sea_mid": [10.0, 112.0],  # مرکز دریای چین جنوبی
    "south_china_sea_north": [18.0, 115.0], # شمال دریای چین جنوبی
    "taiwan_strait": [24.0, 119.5],        # تنگه تایوان
    "shanghai_gate": [31.2, 122.5],        # آب‌های دریای چین شرقی روبه‌روی شانگهای
    "bohai_gate": [38.5, 119.5],           # خلیج بوهای و مدخل دریایی تیانجین/پکن
    "tsushima": [34.40, 129.50],           # تنگه تسوشیما (کره/ژاپن)
    "sea_of_japan_mid": [38.0, 134.0],     # مرکز دریای ژاپن
    "laperouse": [45.70, 142.00],          # تنگه لاپروش (ژاپن/روسیه)
    "bering": [65.80, -168.90],            # تنگه برینگ
}

_MARITIME_CORRIDOR_EDGES: list[tuple[str, str, str | None, float]] = [
    # شبکه اقیانوس اطلس و قاره آمریکا
    ("us_east", "mid_atlantic", None, 1.0),
    ("mid_atlantic", "azores_gate", None, 1.0),
    ("mid_atlantic", "north_atlantic", None, 1.0),
    ("north_atlantic", "english_channel_west", None, 1.0),
    ("azores_gate", "gibraltar", "gibraltar", 1.0),
    ("azores_gate", "portugal_coast", None, 1.0),
    ("brazil_coast", "equator_atlantic", None, 1.0),
    ("equator_atlantic", "azores_gate", None, 1.5),

    # اروپای غربی، دریای شمال و بالتیک
    ("portugal_coast", "gibraltar", "gibraltar", 1.0),
    ("portugal_coast", "bay_of_biscay", None, 1.0),
    ("bay_of_biscay", "english_channel_west", None, 1.0),
    ("english_channel_west", "dover", "dover", 1.0),
    ("dover", "north_sea_mid", None, 1.0),
    ("north_sea_mid", "oresund", "oresund", 1.0),
    ("oresund", "baltic_mid", None, 1.0),

    # دریای مدیترانه
    ("gibraltar", "west_med", None, 1.0),
    ("west_med", "central_med", None, 1.0),
    ("central_med", "east_med", None, 1.0),
    ("central_med", "messina", "messina", 1.0),
    ("messina", "west_med", None, 1.0),
    ("east_med", "suez_north", None, 1.0),
    ("suez_north", "suez", "suez", 1.0),

    # دریای سیاه
    ("black_sea_mid", "bosphorus", "bosphorus", 1.0),
    ("bosphorus", "dardanelles", "dardanelles", 1.0),
    ("dardanelles", "east_med", None, 1.0),
    ("black_sea_mid", "kerch", "kerch", 1.0),

    # دریای سرخ و باب‌المندب
    ("suez", "red_sea_mid", None, 1.0),
    ("red_sea_mid", "bab_el_mandeb", "bab_el_mandeb", 1.0),
    ("bab_el_mandeb", "gulf_of_aden", None, 1.0),
    ("gulf_of_aden", "arabian_sea_mid", None, 1.0),

    # خلیج فارس
    ("persian_gulf_mid", "hormuz", "hormuz", 1.0),
    ("hormuz", "gulf_of_oman", None, 1.0),
    ("gulf_of_oman", "arabian_sea_mid", None, 1.0),

    # اقیانوس هند به آسیای شرقی
    ("arabian_sea_mid", "sri_lanka_south", None, 1.0),
    ("sri_lanka_south", "malacca_north", None, 1.0),
    ("malacca_north", "singapore", None, 1.0),
    ("singapore", "south_china_sea_mid", None, 1.0),
    ("south_china_sea_mid", "south_china_sea_north", None, 1.0),
    ("south_china_sea_north", "taiwan_strait", "taiwan_strait", 1.0),
    ("taiwan_strait", "shanghai_gate", None, 1.0),
    ("shanghai_gate", "bohai_gate", None, 1.0),

    # ژاپن و شبه‌جزیره کره
    ("shanghai_gate", "tsushima", "tsushima", 1.0),
    ("tsushima", "sea_of_japan_mid", None, 1.0),
    ("sea_of_japan_mid", "laperouse", "laperouse", 1.0),
]

# نگاشت کشورهای ساحلی به گره‌های ورودی/خروجی شبکه دریایی
_COUNTRY_MARITIME_GATEWAYS: dict[str, list[str]] = {
    "China": ["bohai_gate", "shanghai_gate"],
    "Japan": ["sea_of_japan_mid", "shanghai_gate"],
    "SouthKorea": ["tsushima", "shanghai_gate"],
    "NorthKorea": ["sea_of_japan_mid"],
    "Australia": ["singapore", "sri_lanka_south"],
    "India": ["sri_lanka_south", "arabian_sea_mid"],
    "Iran": ["persian_gulf_mid"],
    "Pakistan": ["arabian_sea_mid", "gulf_of_oman"],
    "Oman": ["gulf_of_oman", "arabian_sea_mid"],
    "SaudiArabia": ["persian_gulf_mid", "red_sea_mid"],
    "Azerbaijan": [],
    "Qatar": ["persian_gulf_mid"],
    "UAE": ["persian_gulf_mid"],
    "Syria": ["east_med"],
    "Iraq": ["persian_gulf_mid"],
    "Egypt": ["suez_north", "red_sea_mid"],
    "Yemen": ["bab_el_mandeb", "gulf_of_aden"],
    "Russia": ["black_sea_mid", "baltic_mid"],
    "Britain": ["english_channel_west", "north_sea_mid"],
    "France": ["bay_of_biscay", "west_med", "english_channel_west"],
    "Germany": ["north_sea_mid", "oresund"],
    "Israel": ["east_med", "suez_north"],
    "Turkey": ["dardanelles", "bosphorus", "east_med"],
    "Italy": ["central_med"],
    "Spain": ["gibraltar", "portugal_coast", "west_med"],
    "Poland": ["baltic_mid"],
    "Ukraine": ["black_sea_mid"],
    "Sweden": ["oresund", "baltic_mid"],
    "Switzerland": [],
    "Greece": ["east_med"],
    "USA": ["us_east"],
    "Brazil": ["brazil_coast"],
    "Mexico": ["us_east"],
    "Canada": ["us_east"],
    "Argentina": ["brazil_coast"],
    "Colombia": ["us_east"],
    "Norway": ["north_sea_mid"],
    "Afghanistan": [],
    "Taiwan": ["taiwan_strait"],
}


@lru_cache(maxsize=1)
def _build_maritime_graph() -> dict[str, list[tuple[str, str | None, float]]]:
    """ساخت گراف مجاورت کریدورهای دریایی و تنگه‌ها."""
    adj: dict[str, list[tuple[str, str | None, float]]] = {}
    for u, v, strait, weight in _MARITIME_CORRIDOR_EDGES:
        adj.setdefault(u, []).append((v, strait, weight))
        adj.setdefault(v, []).append((u, strait, weight))
    return adj


def get_strait_def(strait_id: str) -> dict | None:
    """مشخصات تعریف‌شده یک تنگه با شناسه انگلیسی."""
    return STRAITS_DEFINITIONS.get(strait_id)


def list_all_strait_defs() -> list[dict]:
    """لیست مشخصات تمام تنگه‌های استراتژیک بازی."""
    return list(STRAITS_DEFINITIONS.values())


def get_straits_for_country(country_name_en: str) -> list[dict]:
    """لیست تنگه‌هایی که تحت کنترل یک کشور خاص هستند."""
    return [
        s for s in STRAITS_DEFINITIONS.values()
        if s["controller"] == country_name_en
    ]


def can_use_sea_transport(origin_en: str, dest_en: str) -> bool:
    """
    آیا امکان حمل‌ونقل دریایی بین دو کشور وجود دارد؟
    شرط: هر دو کشور باید دسترسی به دریاهای باز اقیانوسی داشته باشند.
    کشورهای محصور در خشکی یا کشوری که فقط به دریای خزر دسترسی دارد نمی‌توانند با اقیانوس مبادله دریایی کنند.
    """
    geo_orig = get_geo(origin_en)
    geo_dest = get_geo(dest_en)
    if not geo_orig or not geo_dest:
        return False

    seas_orig = set(geo_orig.get("seas", []))
    seas_dest = set(geo_dest.get("seas", []))

    if not seas_orig or not seas_dest:
        return False

    # اگر هر دو فقط در خزر باشند امکان تردد محدود داخلی هست
    if seas_orig == {"caspian_sea"} and seas_dest == {"caspian_sea"}:
        return True
    # اگر یکی فقط خزر باشد و دیگری دریاهای دیگر، راه آبی باز نیست
    if seas_orig == {"caspian_sea"} or seas_dest == {"caspian_sea"}:
        return False

    return True


def _find_maritime_corridor_route(
    origin_en: str, dest_en: str
) -> tuple[list[str], list[str]]:
    """
    مسیریابی بهینه روی گراف کریدورهای آبی جهان با الگوریتم دایکسترا.
    خروجی: (فهرست شناسه گره‌های مسیر دریایی، فهرست تنگه‌های استراتژیک عبوری)
    """
    if not can_use_sea_transport(origin_en, dest_en) or origin_en == dest_en:
        return [], []

    starts = _COUNTRY_MARITIME_GATEWAYS.get(origin_en, [])
    ends = _COUNTRY_MARITIME_GATEWAYS.get(dest_en, [])
    if not starts or not ends:
        return [], []

    graph = _build_maritime_graph()
    best_path: list[str] = []
    best_straits: list[str] = []
    min_cost = float("inf")

    for s_start in starts:
        for s_end in ends:
            if s_start == s_end:
                return [s_start], []

            pq: list[tuple[float, str, list[str], list[str]]] = [
                (0.0, s_start, [s_start], [])
            ]
            visited: dict[str, float] = {}

            while pq:
                cost, curr, path, straits = heapq.heappop(pq)
                if curr == s_end:
                    if cost < min_cost:
                        min_cost = cost
                        best_path = path
                        best_straits = straits
                    break

                if curr in visited and visited[curr] <= cost:
                    continue
                visited[curr] = cost

                for nxt, strait_id, weight in graph.get(curr, []):
                    new_straits = straits + ([strait_id] if strait_id else [])
                    heapq.heappush(pq, (cost + weight, nxt, path + [nxt], new_straits))

    return best_path, best_straits


def get_route_straits(origin_en: str, dest_en: str) -> list[str]:
    """
    استخراج لیست تنگه‌هایی که کشتی در مسیر دریایی بین دو کشور باید از آنها عبور کند.
    اگر دو کشور در یک حوضچه آبی مشترک بدون تنگه باشند، لیست خالی برمی‌گردد.
    """
    if not can_use_sea_transport(origin_en, dest_en) or origin_en == dest_en:
        return []

    _, straits = _find_maritime_corridor_route(origin_en, dest_en)
    return straits


def get_strait_coords(strait_id: str) -> list[float] | None:
    """مختصات جغرافیایی یک تنگه [lat, lon]."""
    s_def = get_strait_def(strait_id)
    if not s_def:
        return None
    return s_def.get("coords")


def get_maritime_waypoints(origin_en: str, dest_en: str) -> list[list[float]]:
    """
    تولید نقاط مسیر دریایی (Waypoints) بین دو کشور:
    مختصات پایتخت/بندر مبدأ ⬅️ گذرگاه‌های دریایی و تنگه‌های استراتژیک مسیر ⬅️ پایتخت/بندر مقصد.
    تمامی نقاط بین‌راهی از کریدورهای آبی باز عبور می‌کنند تا خط مستقیم از روی خشکی‌ها نگذرد.
    """
    geo_orig = get_geo(origin_en)
    geo_dest = get_geo(dest_en)
    orig_coords: list[float] = geo_orig.get("coords", [0.0, 0.0]) if geo_orig else [0.0, 0.0]
    dest_coords: list[float] = geo_dest.get("coords", [0.0, 0.0]) if geo_dest else [0.0, 0.0]

    if not can_use_sea_transport(origin_en, dest_en) or origin_en == dest_en:
        return [orig_coords, dest_coords]

    path_nodes, _ = _find_maritime_corridor_route(origin_en, dest_en)
    if not path_nodes:
        return [orig_coords, dest_coords]

    points: list[list[float]] = [orig_coords]
    for node in path_nodes:
        c = _MARITIME_CORRIDOR_COORDS.get(node)
        if c:
            if points and points[-1] == c:
                continue
            points.append(c)

    if points[-1] != dest_coords:
        points.append(dest_coords)

    return points


def get_air_waypoints(origin_en: str, dest_en: str) -> list[list[float]]:
    """نقاط مسیر ترابری هوایی یا پروازهای دیپلماتیک (مبدأ ⬅️ مقصد)."""
    geo_orig = get_geo(origin_en)
    geo_dest = get_geo(dest_en)
    orig_coords: list[float] = geo_orig.get("coords", [0.0, 0.0]) if geo_orig else [0.0, 0.0]
    dest_coords: list[float] = geo_dest.get("coords", [0.0, 0.0]) if geo_dest else [0.0, 0.0]
    return [orig_coords, dest_coords]


