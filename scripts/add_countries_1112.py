"""
افزودن سه کشور نروژ، افغانستان و تایوان به داده‌ی پایه (v1.11.2).

اعداد بر پایه‌ی داده‌ی واقعی ۲۰۲۵/۲۰۲۶ هستند و مثل بقیه‌ی کشورهای بازی با
ضریب ۰.۹ مقیاس شده‌اند تا تعادل با ۳۶ کشور موجود حفظ شود.

این اسکریپت یک‌بار اجرا می‌شود و هر دو فایل `data/countries.json` و
`data/geography.json` را به‌روز می‌کند. اجرای دوباره بی‌اثر است (idempotent).

اجرا:
    python -m scripts.add_countries_1112
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNTRIES_FILE = ROOT / "data" / "countries.json"
GEO_FILE = ROOT / "data" / "geography.json"


def _res(amount: float, can_extract: bool) -> dict:
    return {"amount": amount, "can_extract": can_extract}


def _mil(branch: str, category: str, name: str, unit: str, count: int) -> dict:
    return {
        "branch": branch,
        "category": category,
        "name": name,
        "unit": unit,
        "count": count,
    }


# شاخه‌ها و دسته‌ها دقیقاً مطابق بقیه‌ی کشورها
GROUND = "نیروی زمینی"
DEFENSE = "سامانه‌های دفاعی"
VEHICLES = "خودروهای زمینی"
AIR = "نیروی هوایی"
NAVY = "نیروی دریایی"
STRIKE = "سامانه‌های حمله هوایی"


# ============================================================
#  🇳🇴 نروژ — عضو ناتو، ثروتمند، ارتش کوچک ولی کاملاً مدرن
# ============================================================
NORWAY = {
    "name_en": "Norway",
    "name_fa": "نروژ",
    "flag": "🇳🇴",
    "region": "europe",
    "is_vip": False,
    "population": 5_600_000,
    "economy": {
        "economic_power": 76,        # GDP ~۵۰۶ میلیارد دلار + صندوق ثروت ملی عظیم
        "budget": 250_000_000_000,
        "growth": "up",
        "inflation": 2.5,
        "unemployment": 3.9,
        "energy_status": "excellent",  # صادرکننده‌ی بزرگ نفت و گاز
        "foreign_trade": "positive",
        "govt_debt": 196_000_000_000,  # ۳۸.۷٪ تولید ناخالص
        "public_satisfaction": 82,
        "stability": 88,
    },
    "reserves": {
        "coal": _res(1_500_000, True),        # معادن سوالبارد
        "aluminum": _res(1_400_000, True),    # بزرگ‌ترین تولیدکننده‌ی آلومینیوم اروپا
        "iron": _res(3_000_000, True),        # سیدوارانگر
        "steel": _res(600_000, False),
        "oil": _res(760, True),               # دریای شمال
        "gas": _res(14_000, True),            # دومین صادرکننده‌ی گاز اروپا
        "gold": _res(0, False),
        "uranium": _res(8_000, False),        # ذخیره دارد ولی استخراج نمی‌کند
    },
    "military": [
        _mil(GROUND, "سرباز آماده نبرد", "پرسنل آماده نبرد", "نفر", 22_500),

        _mil(DEFENSE, "سامانه ضدموشکی", "NASAMS III", "سامانه", 9),
        _mil(DEFENSE, "سامانه ضدموشکی", "NOMADS (NASAMS متحرک)", "سامانه", 5),
        _mil(DEFENSE, "توپخانه زمین به زمین", "K9 VIDAR", "عراده", 25),

        _mil(VEHICLES, "تانک", "Leopard 2A4NO", "دستگاه", 32),
        _mil(VEHICLES, "تانک", "Leopard 2A8 NOR", "دستگاه", 2),
        _mil(VEHICLES, "نفربر زرهی", "CV9030N Mk IIIb", "دستگاه", 66),
        _mil(VEHICLES, "نفربر زرهی", "CV90 RWS STING", "دستگاه", 25),
        _mil(VEHICLES, "نفربر زرهی", "CV90 RWS Multi BK", "دستگاه", 22),
        _mil(VEHICLES, "نفربر زرهی", "M113A2/F3", "دستگاه", 259),

        _mil(AIR, "جنگنده", "F-35A Lightning II", "فروند", 47),
        _mil(AIR, "هواپیماهای ترابری", "C-130J-30 Super Hercules", "فروند", 4),
        _mil(AIR, "هواپیماهای پشتیبانی", "P-8A Poseidon", "فروند", 5),
        _mil(AIR, "بالگرد", "AW101 SAR Queen", "فروند", 14),
        _mil(AIR, "بالگرد", "Bell 412 SP/HP", "فروند", 16),
        _mil(AIR, "بالگرد", "MH-60R Seahawk", "فروند", 3),

        _mil(NAVY, "ناوشکن", "Fridtjof Nansen-class", "فروند", 4),
        _mil(NAVY, "ناوچه", "Skjold-class", "فروند", 5),
        _mil(NAVY, "زیر دریایی", "Ula-class", "فروند", 5),

        _mil(STRIKE, "موشک کروز", "NSM (Naval Strike Missile)", "موشک", 180),
        _mil(STRIKE, "موشک کروز", "JSM (Joint Strike Missile)", "موشک", 90),
    ],
}


# ============================================================
#  🇦🇫 افغانستان — امارت اسلامی؛ تجهیزات غنیمتی، بدون توان هوایی
# ============================================================
AFGHANISTAN = {
    "name_en": "Afghanistan",
    "name_fa": "افغانستان",
    "flag": "🇦🇫",
    "region": "middle_east",
    "is_vip": False,
    "population": 43_000_000,
    "economy": {
        "economic_power": 15,
        "budget": 3_000_000_000,
        "growth": "flat",
        "inflation": 3.0,
        "unemployment": 14.0,
        "energy_status": "weak",
        "foreign_trade": "negative",
        "govt_debt": 1_400_000_000,
        "public_satisfaction": 35,
        "stability": 40,
    },
    "reserves": {
        "coal": _res(4_000_000, True),
        "aluminum": _res(0, False),
        "iron": _res(20_000_000, False),   # ذخیره‌ی عظیم حاجی‌گک، بدون توان استخراج
        "steel": _res(50_000, False),
        "oil": _res(90, False),            # حوضه‌ی آمودریا، تقریباً بهره‌برداری‌نشده
        "gas": _res(500, True),
        "gold": _res(30, True),
        "uranium": _res(1_500, False),
    },
    "military": [
        _mil(GROUND, "سرباز آماده نبرد", "پرسنل آماده نبرد", "نفر", 135_000),

        _mil(DEFENSE, "سامانه ضدموشکی", "ZU-23-2", "سامانه", 16),
        _mil(DEFENSE, "سامانه ضدموشکی", "FIM-92 Stinger (غنیمتی)", "سامانه", 45),
        _mil(DEFENSE, "توپخانه زمین به زمین", "M-30 122mm", "عراده", 209),
        _mil(DEFENSE, "توپخانه زمین به زمین", "D-30 122mm", "عراده", 37),
        _mil(DEFENSE, "توپخانه زمین به زمین", "BM-21 Grad", "عراده", 3),

        _mil(VEHICLES, "تانک", "T-55", "دستگاه", 99),
        _mil(VEHICLES, "تانک", "T-62M", "دستگاه", 90),
        _mil(VEHICLES, "نفربر زرهی", "M1117 Guardian (غنیمتی)", "دستگاه", 572),
        _mil(VEHICLES, "نفربر زرهی", "BTR-70", "دستگاه", 324),
        _mil(VEHICLES, "نفربر زرهی", "BMP-1", "دستگاه", 315),
        _mil(VEHICLES, "نفربر زرهی", "M113A2 (غنیمتی)", "دستگاه", 156),
        _mil(VEHICLES, "نفربر زرهی", "BMP-2", "دستگاه", 135),
        _mil(VEHICLES, "نفربر زرهی", "MaxxPro MRAP (غنیمتی)", "دستگاه", 63),
        _mil(VEHICLES, "نفربر زرهی", "BTR-50", "دستگاه", 90),

        _mil(AIR, "جنگنده", "A-29 Super Tucano", "فروند", 1),
        _mil(AIR, "پهپادها", "ScanEagle (غنیمتی)", "فروند", 6),
        _mil(AIR, "هواپیماهای ترابری", "Cessna 208 Caravan", "فروند", 5),
        _mil(AIR, "هواپیماهای ترابری", "An-32", "فروند", 2),
        _mil(AIR, "هواپیماهای ترابری", "An-26", "فروند", 1),
        _mil(AIR, "بالگرد", "Mi-8/17", "فروند", 6),
        _mil(AIR, "بالگرد", "UH-60 Black Hawk (غنیمتی)", "فروند", 6),
        _mil(AIR, "بالگرد", "MD-530F Defender", "فروند", 5),
        _mil(AIR, "بالگرد", "Mi-24/35", "فروند", 4),
    ],
}


# ============================================================
#  🇹🇼 تایوان — اقتصاد پیشرفته، ارتش سنگین و مدرن، بدون منابع
# ============================================================
TAIWAN = {
    "name_en": "Taiwan",
    "name_fa": "تایوان",
    "flag": "🇹🇼",
    "region": "east_asia",
    "is_vip": False,
    "population": 23_400_000,
    "economy": {
        "economic_power": 79,          # مرکز جهانی نیمه‌هادی (TSMC)
        "budget": 133_000_000_000,
        "growth": "up",
        "inflation": 1.7,
        "unemployment": 3.4,
        "energy_status": "weak",       # ۹۸٪ انرژی وارداتی
        "foreign_trade": "positive",
        "govt_debt": 240_000_000_000,  # ۲۷.۱٪ تولید ناخالص
        "public_satisfaction": 66,
        "stability": 58,               # تنش دائمی با چین
    },
    "reserves": {
        "coal": _res(200_000, False),
        "aluminum": _res(100_000, False),
        "iron": _res(0, False),
        "steel": _res(6_000_000, False),  # صنعت فولاد بزرگ از سنگ‌آهن وارداتی
        "oil": _res(1, False),
        "gas": _res(6, True),             # میدان‌های کوچک ساحلی
        "gold": _res(20, True),
        "uranium": _res(0, False),
    },
    "military": [
        _mil(GROUND, "سرباز آماده نبرد", "پرسنل آماده نبرد", "نفر", 152_100),

        _mil(DEFENSE, "سامانه ضدموشکی", "Patriot PAC-3", "سامانه", 8),
        _mil(DEFENSE, "سامانه ضدموشکی", "Tien Kung III (آسمان‌کمان ۳)", "سامانه", 11),
        _mil(DEFENSE, "سامانه ضدموشکی", "Tien Kung II (آسمان‌کمان ۲)", "سامانه", 5),
        _mil(DEFENSE, "سامانه ضدموشکی", "M1097 Avenger", "سامانه", 67),
        _mil(DEFENSE, "سامانه ضدموشکی", "Antelope (بزکوهی)", "سامانه", 45),
        _mil(DEFENSE, "توپخانه زمین به زمین", "M114 155mm", "عراده", 306),
        _mil(DEFENSE, "توپخانه زمین به زمین", "M109A2/A5", "عراده", 198),
        _mil(DEFENSE, "توپخانه زمین به زمین", "M110A2 203mm", "عراده", 63),
        _mil(DEFENSE, "توپخانه زمین به زمین", "Thunderbolt-2000 MLRS", "عراده", 45),
        _mil(DEFENSE, "توپخانه زمین به زمین", "M142 HIMARS", "عراده", 10),

        _mil(VEHICLES, "تانک", "M60A3 TTS", "دستگاه", 432),
        _mil(VEHICLES, "تانک", "CM-11 Brave Tiger", "دستگاه", 405),
        _mil(VEHICLES, "تانک", "M1A2T Abrams", "دستگاه", 97),
        _mil(VEHICLES, "نفربر زرهی", "CM-21", "دستگاه", 855),
        _mil(VEHICLES, "نفربر زرهی", "CM-32 Clouded Leopard", "دستگاه", 585),

        _mil(AIR, "جنگنده", "F-16V Block 20", "فروند", 127),
        _mil(AIR, "جنگنده", "F-CK-1 Ching-kuo (IDF)", "فروند", 116),
        _mil(AIR, "جنگنده", "Mirage 2000-5", "فروند", 48),
        _mil(AIR, "پهپادها", "ALTIUS 600M-V (پهپاد انتحاری)", "فروند", 262),
        _mil(AIR, "پهپادها", "Chien Hsiang (پهپاد ضدرادار)", "فروند", 94),
        _mil(AIR, "پهپادها", "Cardinal II", "فروند", 49),
        _mil(AIR, "پهپادها", "Albatross I (رعد شاهین)", "فروند", 29),
        _mil(AIR, "پهپادها", "MQ-9B SeaGuardian", "فروند", 2),
        _mil(AIR, "هواپیماهای ترابری", "C-130H Hercules", "فروند", 17),
        _mil(AIR, "هواپیماهای پشتیبانی", "E-2K Hawkeye 2000", "فروند", 5),
        _mil(AIR, "هواپیماهای پشتیبانی", "P-3C Orion", "فروند", 11),
        _mil(AIR, "بالگرد", "AH-1W SuperCobra", "فروند", 56),
        _mil(AIR, "بالگرد", "UH-60M Black Hawk", "فروند", 40),
        _mil(AIR, "بالگرد", "OH-58D Kiowa Warrior", "فروند", 33),
        _mil(AIR, "بالگرد", "AH-64E Apache", "فروند", 26),
        _mil(AIR, "بالگرد", "S-70C(M) Thunderhawk", "فروند", 15),
        _mil(AIR, "بالگرد", "CH-47SD Chinook", "فروند", 7),

        _mil(NAVY, "ناوشکن", "Kee Lung-class (Kidd)", "فروند", 4),
        _mil(NAVY, "ناوچه", "Cheng Kung-class", "فروند", 9),
        _mil(NAVY, "ناوچه", "Tuo Chiang-class", "فروند", 8),
        _mil(NAVY, "ناوچه", "Kang Ding-class (La Fayette)", "فروند", 5),
        _mil(NAVY, "ناوچه", "Chi Yang-class (Knox)", "فروند", 5),
        _mil(NAVY, "ناوچه", "Kuang Hua VI (قایق موشک‌انداز)", "فروند", 27),
        _mil(NAVY, "زیر دریایی", "Hai Lung-class", "فروند", 2),
        _mil(NAVY, "زیر دریایی", "Hai Shih-class (آموزشی)", "فروند", 2),

        _mil(STRIKE, "موشک کروز", "Hsiung Feng III (بادپای ۳)", "موشک", 360),
        _mil(STRIKE, "موشک کروز", "Hsiung Feng II (بادپای ۲)", "موشک", 315),
        _mil(STRIKE, "موشک کروز", "Hsiung Sheng (بادپیروز)", "موشک", 180),
        _mil(STRIKE, "موشک کروز", "RGM-84L Harpoon (ساحلی)", "موشک", 180),
        _mil(STRIKE, "موشک کروز", "Yun Feng (ابربادپا)", "موشک", 45),
    ],
}


# ---------- جغرافیا ----------
# فقط همسایه‌هایی ذکر می‌شوند که در بازی حضور دارند.
GEO_NEW = {
    "Norway": {
        "continent": "Europe",
        "coords": [59.9, 10.8],          # اسلو
        "neighbors": ["Sweden", "Russia"],
        "seas": ["atlantic", "north_sea", "arctic"],
    },
    "Afghanistan": {
        "continent": "Asia",
        "coords": [34.5, 69.2],          # کابل
        "neighbors": ["Iran", "Pakistan", "China"],
        "seas": [],                       # محصور در خشکی
    },
    "Taiwan": {
        "continent": "Asia",
        "coords": [25.0, 121.6],         # تایپه
        "neighbors": [],                  # جزیره
        "seas": ["pacific", "east_china_sea", "south_china_sea"],
    },
}

# همسایگی باید دوطرفه باشد؛ این کشورها باید کشور جدید را در فهرست خود ببینند.
REVERSE_NEIGHBORS = {
    "Sweden": "Norway",
    "Russia": "Norway",
    "Iran": "Afghanistan",
    "Pakistan": "Afghanistan",
    "China": "Afghanistan",
}

NEW_COUNTRIES = [NORWAY, AFGHANISTAN, TAIWAN]


def main() -> None:
    # ---------- countries.json ----------
    data = json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))
    existing = {c["name_en"] for c in data["countries"]}

    added = []
    for country in NEW_COUNTRIES:
        if country["name_en"] in existing:
            print(f"⏭  {country['name_en']} از قبل هست — رد شد")
            continue
        data["countries"].append(country)
        added.append(country["name_en"])

    if added:
        COUNTRIES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"✅ countries.json: {', '.join(added)} افزوده شد "
              f"(مجموع {len(data['countries'])} کشور)")

    # ---------- geography.json ----------
    geo = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    gc = geo["countries"]

    geo_added = []
    for name, entry in GEO_NEW.items():
        if name in gc:
            print(f"⏭  {name} در geography از قبل هست — رد شد")
            continue
        gc[name] = entry
        geo_added.append(name)

    # همسایگی دوطرفه
    for host, newcomer in REVERSE_NEIGHBORS.items():
        if host not in gc:
            print(f"⚠️  {host} در geography نیست — همسایگی {newcomer} ثبت نشد")
            continue
        neighbors = gc[host].setdefault("neighbors", [])
        if newcomer not in neighbors:
            neighbors.append(newcomer)
            print(f"🔗 {host} ← همسایه‌ی {newcomer} شد")

    if geo_added or REVERSE_NEIGHBORS:
        GEO_FILE.write_text(
            json.dumps(geo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"✅ geography.json به‌روز شد ({len(gc)} کشور)")

    # ---------- گزارش ----------
    for country in NEW_COUNTRIES:
        total = sum(m["count"] for m in country["military"])
        print(f"\n{country['flag']} {country['name_fa']} — "
              f"{len(country['military'])} قلم تجهیزات، مجموع {total:,} واحد")


if __name__ == "__main__":
    main()
