"""
تست موتور اخبار ضدتکرار (v1.10.6).

اجرا:
    PYTHONUTF8=1 python -m scripts.test_news_engine

بدون نیاز به دیتابیس یا هوش مصنوعی — منطق ضدتکرار، تنوع سبک‌ها و
قالب‌های پشتیبان به‌صورت خالص سنجیده می‌شوند.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bot.enums import NewsArchetype  # noqa: E402
from bot.services.news import archetypes, dedup  # noqa: E402
from bot.services.news import facts as facts_mod  # noqa: E402

_passed = 0
_failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed
    if condition:
        _passed += 1
        print(f"  ✅ {label}")
    else:
        _failed.append(f"{label} — {detail}")
        print(f"  ❌ {label} — {detail}")


SAMPLE_FACTS = {
    "attacker": "ایران",
    "defender": "اسرائیل",
    "operation_type": "air_strike",
    "target_type": "city",
    "top_attack_assets": ["F-14 Tomcat", "Shahed-136"],
    "top_defense_assets": ["Iron Dome", "F-35I"],
    "units_committed": 23,
    "intercept_pct": 66.1,
    "infra_damage_pct": 47.3,
    "distance_km": 1350,
    "attacker_losses": [{"name": "F-14 Tomcat", "count": 2, "unit": "فروند"}],
    "defender_losses": [{"name": "Iron Dome", "count": 1, "unit": "سامانه"}],
    "civilian_casualties": 1240,
    "outcome": "برتری مهاجم",
    "intensity": 7,
    "patrol_active": True,
    "nuclear_deterrence": False,
}


def main() -> int:
    print("=" * 60)
    print("تست موتور اخبار ضدتکرار")
    print("=" * 60)

    # --- ۱) تشخیص تکرار ---
    print("\n[۱] تشخیص تکرار")
    text_a = "🔴 خبر فوری — گزارش‌ها از آغاز حمله هوایی علیه پایگاه نظامی حکایت دارد."
    text_b = "🔴 خبر فوری — گزارش‌ها از آغاز حمله هوایی علیه پایگاه نظامی حکایت دارد."
    text_c = "‼️ سامانه‌های پدافندی وارد عمل شدند و موشک‌ها را در آسمان منهدم کردند."

    sh_a, sh_b, sh_c = (dedup.build_shingles(t) for t in (text_a, text_b, text_c))
    check("متن یکسان شباهت کامل دارد", dedup.similarity(sh_a, sh_b) > 0.99)
    check("متن متفاوت شباهت پایین دارد", dedup.similarity(sh_a, sh_c) < 0.3,
          f"{dedup.similarity(sh_a, sh_c):.3f}")
    check("هش متن یکسان برابر است", dedup.text_hash(text_a) == dedup.text_hash(text_b))
    check("هش متن متفاوت، متفاوت است", dedup.text_hash(text_a) != dedup.text_hash(text_c))

    encoded = dedup.encode_shingles(sh_a)
    check("encode/decode بدون افت کار می‌کند", dedup.decode_shingles(encoded) == sh_a)
    check("خبر تکراری تشخیص داده می‌شود", dedup.is_repetitive(text_a, [encoded]))
    check("خبر تازه تکراری تشخیص داده نمی‌شود", not dedup.is_repetitive(text_c, [encoded]))
    check("مقایسه با فهرست خالی امن است", dedup.max_similarity(text_a, []) == 0.0)
    check("متن خالی کرش نمی‌کند", dedup.build_shingles("") == set())

    # نرمال‌سازی حروف عربی/فارسی
    arabic = "گزارشها از حمله عليه پایگاه نظامی در خاك دشمن حكایت دارد"
    persian = "گزارشها از حمله علیه پایگاه نظامی در خاک دشمن حکایت دارد"
    check(
        "حروف عربی و فارسی یکسان‌سازی می‌شوند",
        dedup.similarity(dedup.build_shingles(arabic), dedup.build_shingles(persian)) > 0.9,
    )

    # --- ۲) عبارات شاخص ---
    print("\n[۲] استخراج عبارات شاخص")
    phrases = dedup.extract_key_phrases(text_a)
    check("عبارات شاخص استخراج می‌شود", len(phrases) > 0)
    check("کلیشه‌ی «خبر فوری» شناسایی می‌شود", any("خبر فوری" in p for p in phrases))
    check("عبارات قابل ذخیره‌سازی‌اند", "|" in dedup.encode_phrases(phrases) or len(phrases) == 1)

    # --- ۳) نقشه‌ی فازها ---
    print("\n[۳] نقشه‌ی فازهای خبری")
    for count in (3, 5, 7, 9):
        plan = facts_mod.phase_plan(count)
        check(f"نقشه‌ی {count} فازی دقیقاً {count} مرحله دارد", len(plan) == count, str(plan))
    check("نقشه با فاز آغازین شروع می‌شود", facts_mod.phase_plan(5)[0] == "opening")
    check("نقشه با جمع‌بندی تمام می‌شود", facts_mod.phase_plan(5)[-1] == "summary")
    check("تعداد غیراستاندارد هم پشتیبانی می‌شود", len(facts_mod.phase_plan(4)) == 4)

    # --- ۴) واقعیت‌های هر فاز ---
    print("\n[۴] واقعیت‌های هر فاز")
    texts = {
        kind: facts_mod.facts_to_text(SAMPLE_FACTS, kind)
        for kind in ("opening", "defense", "damage", "second_wave", "reaction", "summary")
    }
    check("همه‌ی فازها متن تولید می‌کنند", all(len(t) > 30 for t in texts.values()))
    check("فازها محتوای یکسان ندارند", len(set(texts.values())) == len(texts))
    check("فاز پدافند درصد رهگیری را دارد", "رهگیری" in texts["defense"])
    check("فاز خسارت درصد خسارت را دارد", "خسارت" in texts["damage"])
    check("فاز خسارت تلفات غیرنظامی را گزارش می‌کند", "غیرنظامی" in texts["damage"])
    check("فاز جمع‌بندی نتیجه‌ی نهایی را دارد", "نتیجه‌ی نهایی" in texts["summary"])
    check("نام تجهیزات واقعی در فاز آغازین می‌آید", "F-14" in texts["opening"])
    check("گشت فعال در فاز پدافند ذکر می‌شود", "گشت" in texts["defense"])

    empty_facts = facts_mod.facts_to_text({}, "opening")
    check("واقعیت‌های خالی کرش نمی‌کند", len(empty_facts) > 0)

    # --- ۵) قالب‌های پشتیبان ---
    print("\n[۵] قالب‌های پشتیبان (بدون AI)")
    variants = {
        facts_mod.fallback_news(SAMPLE_FACTS, "opening", random.Random(i)) for i in range(10)
    }
    check("قالب پشتیبان چند نسخه‌ی متفاوت دارد", len(variants) >= 2, f"{len(variants)} نسخه")
    check("قالب پشتیبان نام کشورها را جایگزین می‌کند",
          all("ایران" in v or "اسرائیل" in v for v in variants))
    check("قالب پشتیبان placeholder باقی نمی‌گذارد",
          not any("{" in v or "}" in v for v in variants))
    check(
        "قالب پشتیبان برای فاز ناشناخته هم کار می‌کند",
        len(facts_mod.fallback_news(SAMPLE_FACTS, "unknown_phase", random.Random(1))) > 10,
    )
    check(
        "قالب پشتیبان با واقعیت‌های خالی کرش نمی‌کند",
        len(facts_mod.fallback_news({}, "opening", random.Random(1))) > 10,
    )

    # --- ۶) چرخش آرکه‌تایپ‌ها ---
    print("\n[۶] چرخش سبک‌های خبری")
    used: list[str] = []
    picks: list[str] = []
    for i in range(8):
        arch = archetypes.pick_archetype("opening", used, random.Random(i))
        picks.append(arch.value)
        used.append(arch.value)
    check("۸ انتخاب متوالی همه یکتا هستند", len(set(picks)) == 8, str(picks))

    exhausted = archetypes.pick_archetype("opening", [a.value for a in NewsArchetype], random.Random(1))
    check("پس از مصرف همه‌ی سبک‌ها هم سبکی برمی‌گرداند", isinstance(exhausted, NewsArchetype))

    check("هر سبک راهنمای نوشتن دارد",
          all(len(archetypes.guide_for(a)) > 20 for a in NewsArchetype))
    check("راهنمای سبک‌ها یکتا هستند",
          len({archetypes.guide_for(a) for a in NewsArchetype}) == len(list(NewsArchetype)))

    # --- خلاصه ---
    print("\n" + "=" * 60)
    total = _passed + len(_failed)
    if _failed:
        print(f"❌ {len(_failed)} از {total} بررسی شکست خورد:")
        for item in _failed:
            print(f"   • {item}")
        return 1
    print(f"✅ همه‌ی {total} بررسی موفق بود.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
