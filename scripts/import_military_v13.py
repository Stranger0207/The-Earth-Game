"""
ایمپورت تجهیزات نظامی نسخه v1.3 از فایل متنی «اطلاعات نیروها».
این اسکریپت فایل txt را پارس می‌کند و داده‌ی نظامی هر کشور را در data/countries.json
جایگزین می‌کند (تطبیق کشورها بر اساس پرچم انجام می‌شود).

فقط تجهیزات و تعداد سرباز وارد می‌شوند؛ جمعیت و اقتصاد دست‌نخورده می‌مانند.
تجهیزات با تعداد صفر یا بدون عدد مشخص، نادیده گرفته می‌شوند.

اجرا:
    python -m scripts.import_military_v13 "مسیر/فایل.txt"
اگر مسیر داده نشود، از مسیر پیش‌فرض دانلودها استفاده می‌شود.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "countries.json"

# مسیر پیش‌فرض فایل آپدیت
DEFAULT_TXT = Path.home() / "Downloads" / "__⚔️«اطلاعات نیروها»⚔️_.txt"

# تبدیل ارقام فارسی به انگلیسی
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

# الگوی استخراج پرچم (دو نماد منطقه‌ای پشت‌سرهم)
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")

# الگوی نام زیربخش بین « و »
_BRANCH_RE = re.compile(r"«([^»]+)»")

# جداکننده‌ی شمارش در آیتم‌ها: فاصله + خط‌تیره + فاصله
_ITEM_SPLIT_RE = re.compile(r"\s[–—-]\s")

# نگاشت نام زیربخش فایل به نام استاندارد در ربات
_BRANCH_NORMALIZE = {
    "نیرو هوایی": "نیروی هوایی",
}


def to_int(text: str) -> int | None:
    """اولین عدد یک رشته (با ارقام فارسی/جداکننده) را به int تبدیل می‌کند."""
    s = text.translate(_FA_DIGITS).replace("،", "").replace(",", "").strip()
    m = re.match(r"\d+", s)
    return int(m.group()) if m else None


def _strip_leading_symbols(text: str) -> str:
    """ایموجی و نمادهای ابتدای رشته را حذف می‌کند تا متن فارسی/لاتین باقی بماند."""
    return re.sub(r"^[^؀-ۿA-Za-z]+", "", text).strip()


def parse_blocks(raw: str) -> list[dict]:
    """متن فایل را به بلوک‌های هر کشور می‌شکند و تجهیزات را استخراج می‌کند."""
    # شکستن بر اساس خطوط جداکننده‌ی زیرخط
    chunks = re.split(r"(?m)^_{5,}\s*$", raw)
    results: list[dict] = []

    for chunk in chunks:
        flag_match = _FLAG_RE.search(chunk)
        # فقط بلوک‌هایی که خط «نام کشور» دارند کشور واقعی‌اند
        if "نام کشور" not in chunk or flag_match is None:
            continue
        # پرچم را از خط «نام کشور» می‌گیریم (نه از پرچم‌های احتمالی دیگر)
        flag = None
        for line in chunk.splitlines():
            if "نام کشور" in line:
                fm = _FLAG_RE.search(line)
                if fm:
                    flag = fm.group()
                break
        if flag is None:
            continue

        assets: list[dict] = []
        current_branch = "سایر"
        current_category = ""

        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue

            # زیربخش (branch)
            bm = _BRANCH_RE.search(line)
            if bm and "اطلاعات نیروها" not in line:
                name = bm.group(1).strip()
                current_branch = _BRANCH_NORMALIZE.get(name, name)
                current_category = ""
                continue

            # خط سرباز آماده نبرد
            if "سرباز آماده نبرد" in line:
                count = to_int(line.split(":", 1)[-1])
                if count:
                    assets.append({
                        "branch": "نیروی زمینی",
                        "category": "سرباز آماده نبرد",
                        "name": "پرسنل آماده نبرد",
                        "unit": "نفر",
                        "count": count,
                    })
                continue

            # خطوط آیتم (بولت)
            if line.startswith("•"):
                body = line.lstrip("•").strip()
                parts = _ITEM_SPLIT_RE.split(body, maxsplit=1)
                if len(parts) < 2:
                    continue  # بدون عدد مشخص → رد
                name = parts[0].strip()
                rest = parts[1].strip()
                count = to_int(rest)
                if not count:  # صفر یا نامشخص → رد
                    continue
                unit = re.sub(r"^[۰-۹0-9,،.\s]+", "", rest).strip() or "عدد"
                assets.append({
                    "branch": current_branch,
                    "category": current_category or "سایر",
                    "name": name,
                    "unit": unit,
                    "count": count,
                })
                continue

            # خط دسته‌بندی (category) — دارای «:» و بدون پرچم/جمعیت
            if ":" in line and "جمعیت" not in line and "نام کشور" not in line:
                cat = _strip_leading_symbols(line.split(":", 1)[0])
                if cat:
                    current_category = cat
                continue

        results.append({"flag": flag, "assets": assets})

    return results


def main() -> None:
    txt_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TXT
    if not txt_path.exists():
        print(f"❌ فایل یافت نشد: {txt_path}")
        sys.exit(1)

    raw = txt_path.read_text(encoding="utf-8")
    blocks = parse_blocks(raw)
    print(f"📄 {len(blocks)} بلوک کشور از فایل استخراج شد.")

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    by_flag = {c["flag"]: c for c in data["countries"]}

    matched = 0
    unmatched = []
    for block in blocks:
        country = by_flag.get(block["flag"])
        if country is None:
            unmatched.append(block["flag"])
            continue
        country["military"] = block["assets"]
        matched += 1
        print(f"  ✅ {block['flag']} {country['name_fa']}: {len(block['assets'])} قلم تجهیزات")

    if unmatched:
        print(f"⚠️ پرچم‌های بدون تطبیق: {unmatched}")

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"💾 {matched} کشور در countries.json به‌روزرسانی شد.")


if __name__ == "__main__":
    main()
