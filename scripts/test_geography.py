"""
تست لایه‌ی جغرافیا (v1.10.6).

اجرا:
    PYTHONUTF8=1 python -m scripts.test_geography

نیازی به دیتابیس یا توکن واقعی ندارد؛ فقط داده‌ی JSON و توابع محاسباتی را می‌سنجد.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bot.services import geo_service as geo  # noqa: E402

_passed = 0
_failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """یک بررسی را ثبت می‌کند."""
    global _passed
    if condition:
        _passed += 1
        print(f"  ✅ {label}")
    else:
        _failed.append(f"{label} — {detail}")
        print(f"  ❌ {label} — {detail}")


def main() -> int:
    print("=" * 60)
    print("تست لایه‌ی جغرافیا")
    print("=" * 60)

    countries_file = _ROOT / "data" / "countries.json"
    game_countries = {
        c["name_en"] for c in json.loads(countries_file.read_text(encoding="utf-8"))["countries"]
    }
    geo_countries = set(geo._load_geo().keys())

    # --- ۱) پوشش داده ---
    print("\n[۱] پوشش داده")
    missing = game_countries - geo_countries
    extra = geo_countries - game_countries
    check("همه‌ی کشورهای بازی در geography.json هستند", not missing, f"جامانده: {missing}")
    check("کشور اضافی در geography.json نیست", not extra, f"اضافی: {extra}")

    # --- ۲) سلامت ساختار ---
    print("\n[۲] سلامت ساختار")
    broken_coords, broken_neighbors = [], []
    for name, data in geo._load_geo().items():
        coords = data.get("coords") or []
        if len(coords) != 2 or not (-90 <= coords[0] <= 90) or not (-180 <= coords[1] <= 180):
            broken_coords.append(name)
        for n in data.get("neighbors", []):
            if n not in geo_countries:
                broken_neighbors.append(f"{name}->{n}")
    check("مختصات همه‌ی کشورها معتبر است", not broken_coords, f"خراب: {broken_coords}")
    check("همه‌ی همسایگان شناخته‌شده‌اند", not broken_neighbors, f"ناشناخته: {broken_neighbors}")

    asymmetric = [
        f"{c}<->{n}"
        for c in geo_countries
        for n in geo.neighbors_of(c)
        if n in geo_countries and not geo.are_neighbors(c, n)
    ]
    check("همسایگی‌ها متقارن‌اند", not asymmetric, f"نامتقارن: {asymmetric}")

    # --- ۳) فاصله و رده ---
    print("\n[۳] فاصله و رده‌بندی")
    check("ایران–عراق همسایه است", geo.are_neighbors("Iran", "Iraq"))
    check("ایران–آمریکا همسایه نیست", not geo.are_neighbors("Iran", "USA"))
    check("ایران–آمریکا فراقاره‌ای است", geo.distance_tier("Iran", "USA") == geo.TIER_INTERCONTINENTAL)
    check("روسیه–چین با وجود فاصله، همسایه محسوب می‌شود", geo.distance_tier("Russia", "China") == geo.TIER_NEIGHBOR)
    check("فاصله متقارن است", abs(geo.distance_km("Iran", "China") - geo.distance_km("China", "Iran")) < 1.0)
    check("فاصله‌ی کشور با خودش صفر است", geo.distance_km("Iran", "Iran") < 1.0)
    check(
        "ژاپن–کره جنوبی نزدیک‌تر از ژاپن–برزیل است",
        geo.distance_km("Japan", "SouthKorea") < geo.distance_km("Japan", "Brazil"),
    )

    # --- ۴) دسترسی دریایی ---
    print("\n[۴] دسترسی دریایی")
    check("ایران–عمان آب مشترک دارند", geo.shares_sea("Iran", "Oman"))
    check("سوئیس محصور در خشکی است", geo.is_landlocked("Switzerland"))
    check("سوئیس با هیچ‌کس آب مشترک ندارد", not geo.shares_sea("Switzerland", "Italy"))
    check("آمریکا–ژاپن از اقیانوس آرام مشترک‌اند", geo.shares_sea("USA", "Japan"))

    # --- ۵) مسیر محموله (رهگیری) ---
    print("\n[۵] مسیر محموله")
    check("همسایه‌ها مسیر واسط ندارند", geo.route_crosses("Iran", "Iraq") == [])
    check("مسیر با خودش خالی است", geo.route_crosses("Iran", "Iran") == [])

    cn_de = geo.route_crosses("China", "Germany")
    check("چین→آلمان از روسیه می‌گذرد", "Russia" in cn_de, str(cn_de))
    check("چین→آلمان از هند نمی‌گذرد", "India" not in cn_de, str(cn_de))

    fr_pl = geo.route_crosses("France", "Poland")
    check("فرانسه→لهستان از آلمان می‌گذرد", "Germany" in fr_pl, str(fr_pl))

    ir_il = geo.route_crosses("Iran", "Israel")
    check("ایران→اسرائیل از عراق می‌گذرد", "Iraq" in ir_il, str(ir_il))

    check("برزیل→آرژانتین (همسایه) واسط ندارد", geo.route_crosses("Brazil", "Argentina") == [])
    check(
        "کشور بی‌ربط روی مسیر نیست",
        not geo.is_on_route("Brazil", "Russia", "India"),
    )
    check(
        "مبدأ و مقصد خودشان روی مسیر نیستند",
        "China" not in cn_de and "Germany" not in cn_de,
        str(cn_de),
    )

    # --- ۶) مقاومت در برابر داده‌ی ناموجود ---
    print("\n[۶] مقاومت")
    check("کشور ناشناخته کرش نمی‌کند", geo.get_geo("Atlantis") is None)
    check("فاصله‌ی کشور ناشناخته امن است", geo.distance_km("Atlantis", "Iran") >= 9999.0)
    check("همسایگی کشور ناشناخته False است", not geo.are_neighbors("Atlantis", "Iran"))
    check("مسیر کشور ناشناخته خالی است", geo.route_crosses("Atlantis", "Iran") == [])

    # --- خلاصه ---
    print("\n" + "=" * 60)
    total = _passed + len(_failed)
    if _failed:
        print(f"❌ {len(_failed)} از {total} بررسی شکست خورد:")
        for f in _failed:
            print(f"   • {f}")
        return 1
    print(f"✅ همه‌ی {total} بررسی موفق بود.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
