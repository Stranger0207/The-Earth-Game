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
        "connects": ("persian_gulf", "gulf_of_oman"),
        "description": "شاهراه انرژی جهان، اتصال خلیج فارس به دریای عمان و اقیانوس هند",
    },
    "bering": {
        "id": "bering",
        "name_fa": "تنگه برینگ",
        "name_en": "Bering Strait",
        "controller": "USA",
        "connects": ("pacific", "arctic"),
        "description": "گذرگاه استراتژیک اقیانوس آرام شمالی و قطب شمال",
    },
    "dover": {
        "id": "dover",
        "name_fa": "تنگه دوور (مانش)",
        "name_en": "Strait of Dover",
        "controller": "Britain",
        "connects": ("atlantic", "north_sea"),
        "description": "کانال مانش، مسیر اتصال دریای شمال و اروپای شمالی به اقیانوس اطلس",
    },
    "bosphorus": {
        "id": "bosphorus",
        "name_fa": "تنگه بسفر",
        "name_en": "Bosphorus Strait",
        "controller": "Turkey",
        "connects": ("black_sea", "mediterranean"),
        "description": "گذرگاه حیاتی دریای سیاه به دریای مدیترانه",
    },
    "dardanelles": {
        "id": "dardanelles",
        "name_fa": "تنگه داردانل",
        "name_en": "Dardanelles Strait",
        "controller": "Turkey",
        "connects": ("black_sea", "mediterranean"),
        "description": "تنگه مکمل بسفر در کنترل ترکیه جهت اتصال به اژه و مدیترانه",
    },
    "gibraltar": {
        "id": "gibraltar",
        "name_fa": "تنگه جبل‌الطارق",
        "name_en": "Strait of Gibraltar",
        "controller": "Spain",
        "connects": ("mediterranean", "atlantic"),
        "description": "تنها معبر طبیعی اتصال دریای مدیترانه به اقیانوس اطلس",
    },
    "laperouse": {
        "id": "laperouse",
        "name_fa": "تنگه لاپروش (سویا)",
        "name_en": "La Perouse Strait",
        "controller": "Japan",
        "connects": ("sea_of_japan", "pacific"),
        "description": "مسیر دریای ژاپن و اختسک به اقیانوس آرام شمالی",
    },
    "tsushima": {
        "id": "tsushima",
        "name_fa": "تنگه تسوشیما",
        "name_en": "Tsushima Strait",
        "controller": "SouthKorea",
        "connects": ("east_china_sea", "sea_of_japan"),
        "description": "معبر استراتژیک دریای چین شرقی به دریای ژاپن",
    },
    "bab_el_mandeb": {
        "id": "bab_el_mandeb",
        "name_fa": "تنگه باب‌المندب",
        "name_en": "Bab el-Mandeb Strait",
        "controller": "Yemen",
        "connects": ("red_sea", "arabian_sea"),
        "description": "ورودی جنوبی دریای سرخ و شاهراه اتصال آسیا به اروپا",
    },
    "kerch": {
        "id": "kerch",
        "name_fa": "تنگه کرچ",
        "name_en": "Kerch Strait",
        "controller": "Russia",
        "connects": ("black_sea", "azov_sea"),
        "description": "مسیر اتصال دریای آزوف به دریای سیاه",
    },
    "messina": {
        "id": "messina",
        "name_fa": "تنگه مسینا",
        "name_en": "Strait of Messina",
        "controller": "Italy",
        "connects": ("mediterranean_west", "mediterranean_east"),
        "description": "گذرگاه مابین سیسیل و شبه‌جزیره ایتالیا در مرکز مدیترانه",
    },
    "suez": {
        "id": "suez",
        "name_fa": "کانال سوئز",
        "name_en": "Suez Canal",
        "controller": "Egypt",
        "connects": ("red_sea", "mediterranean"),
        "description": "آبراه تاریخی اتصال آسیا و خاورمیانه به اروپا",
    },
    "taiwan_strait": {
        "id": "taiwan_strait",
        "name_fa": "تنگه تایوان",
        "name_en": "Taiwan Strait",
        "controller": "Taiwan",
        "connects": ("south_china_sea", "east_china_sea"),
        "description": "معبر پرتردد اتصال دریای چین جنوبی به دریای چین شرقی و اقیانوس آرام",
    },
    "oresund": {
        "id": "oresund",
        "name_fa": "تنگه سوند (دانمارک/سوئد)",
        "name_en": "Oresund Strait",
        "controller": "Sweden",
        "connects": ("baltic_sea", "north_sea"),
        "description": "ورودی انحصاری دریای بالتیک به دریای شمال و اقیانوس اطلس",
    },
}

# یال‌های اتصال دریاها: (مبدأ، مقصد، شناسه تنگه یا None در آب‌های آزاد، وزن مسافتی)
_MARITIME_EDGES: list[tuple[str, str, str | None, float]] = [
    ("persian_gulf", "gulf_of_oman", "hormuz", 1.0),
    ("gulf_of_oman", "arabian_sea", None, 1.0),
    ("arabian_sea", "indian_ocean", None, 1.0),
    ("bay_of_bengal", "indian_ocean", None, 1.0),
    ("red_sea", "arabian_sea", "bab_el_mandeb", 1.0),
    ("red_sea", "mediterranean", "suez", 1.0),
    ("black_sea", "mediterranean", "bosphorus", 1.0),
    ("mediterranean", "atlantic", "gibraltar", 1.0),
    ("atlantic", "north_sea", "dover", 1.0),
    ("north_sea", "baltic_sea", "oresund", 1.0),
    ("atlantic", "gulf_of_mexico", None, 1.0),
    ("atlantic", "arctic", None, 2.0),
    ("pacific", "arctic", "bering", 2.0),
    ("pacific", "sea_of_japan", "laperouse", 1.0),
    ("east_china_sea", "sea_of_japan", "tsushima", 1.0),
    ("south_china_sea", "east_china_sea", "taiwan_strait", 1.0),
    ("pacific", "south_china_sea", None, 1.0),
    ("pacific", "indian_ocean", None, 2.0),
    # مسیر طولانی دور دماغه امیدنیک آفریقا (وزن مسافتی بالا تا مسیر سوئز اولویت باشد)
    ("atlantic", "indian_ocean", None, 10.0),
]


@lru_cache(maxsize=1)
def _build_maritime_graph() -> dict[str, list[tuple[str, str | None, float]]]:
    """ساخت گراف مجاورت دریاها و تنگه‌ها."""
    adj: dict[str, list[tuple[str, str | None, float]]] = {}
    for u, v, strait, weight in _MARITIME_EDGES:
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


def get_route_straits(origin_en: str, dest_en: str) -> list[str]:
    """
    استخراج لیست تنگه‌هایی که کشتی در مسیر دریایی بین دو کشور باید از آنها عبور کند.
    اگر دو کشور آب مشترک داشته باشند، کشتی از همان آب مشترک بدون تنگه عبور می‌کند (لیست خالی).
    """
    if not can_use_sea_transport(origin_en, dest_en):
        return []

    geo_orig = get_geo(origin_en)
    geo_dest = get_geo(dest_en)
    if not geo_orig or not geo_dest:
        return []

    # دریاهای باز (به استثنای خزر برای مسیرهای بین‌المللی)
    seas_orig = [s for s in geo_orig.get("seas", []) if s != "caspian_sea"]
    seas_dest = [s for s in geo_dest.get("seas", []) if s != "caspian_sea"]

    # آب مشترک مستقیم
    if set(seas_orig) & set(seas_dest):
        return []

    graph = _build_maritime_graph()

    # یافتن کوتاه‌ترین مسیر میان هر جفت دریای مبدأ و مقصد با دایکسترا
    best_straits: list[str] = []
    min_cost = float("inf")

    for s_start in seas_orig:
        for s_end in seas_dest:
            pq: list[tuple[float, str, list[str]]] = [(0.0, s_start, [])]
            visited: dict[str, float] = {}

            while pq:
                cost, curr, straits = heapq.heappop(pq)
                if curr == s_end:
                    if cost < min_cost:
                        min_cost = cost
                        best_straits = straits
                    break

                if curr in visited and visited[curr] <= cost:
                    continue
                visited[curr] = cost

                for nxt, strait_id, weight in graph.get(curr, []):
                    new_straits = straits + ([strait_id] if strait_id else [])
                    heapq.heappush(pq, (cost + weight, nxt, new_straits))

    return best_straits

