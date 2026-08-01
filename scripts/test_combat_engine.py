"""
تست موتور نبرد محاسباتی (v1.10.6).

اجرا:
    PYTHONUTF8=1 python -m scripts.test_combat_engine

بدون نیاز به دیتابیس، توکن یا هوش مصنوعی — موتور نبرد کاملاً قطعی است.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bot.enums import OperationType, TargetType  # noqa: E402
from bot.services.combat import BattleInput, CommittedAsset, resolve_battle  # noqa: E402

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


# ---------- نیروهای نمونه ----------
def small_air() -> list[CommittedAsset]:
    return [
        CommittedAsset("F-14 Tomcat", 8, "نیروی هوایی", "جنگنده", "فروند"),
        CommittedAsset("Shahed-136", 15, "نیروی هوایی", "پهپادها", "فروند"),
    ]


def massive_air() -> list[CommittedAsset]:
    return [
        CommittedAsset("B-2 Spirit", 12, "نیروی هوایی", "بمب‌افکن", "فروند"),
        CommittedAsset("F-35A", 60, "نیروی هوایی", "جنگنده", "فروند"),
        CommittedAsset("Tomahawk", 80, "سامانه‌های حمله هوایی", "موشک کروز", "موشک"),
    ]


def ground_force() -> list[CommittedAsset]:
    return [
        CommittedAsset("T-90", 200, "خودروهای زمینی", "تانک", "دستگاه"),
        CommittedAsset("پرسنل آماده نبرد", 50_000, "نیروی زمینی", "سرباز آماده نبرد", "نفر"),
        CommittedAsset("توپخانه", 80, "سامانه‌های دفاعی", "توپخانه زمین به زمین", "عراده"),
    ]


def light_ad() -> list[CommittedAsset]:
    return [CommittedAsset("HAWK", 3, "سامانه‌های دفاعی", "سامانه ضدموشکی", "سامانه")]


def heavy_ad() -> list[CommittedAsset]:
    return [
        CommittedAsset("S-400", 20, "سامانه‌های دفاعی", "سامانه ضدموشکی", "سامانه"),
        CommittedAsset("Su-57", 30, "نیروی هوایی", "جنگنده", "فروند"),
    ]


def run(
    committed: list[CommittedAsset],
    defenders: list[CommittedAsset],
    *,
    op: OperationType = OperationType.AIR_STRIKE,
    target: TargetType = TargetType.MILITARY_BASE,
    km: float = 800.0,
    tier: str = "regional",
    seed: int = 7,
    **kwargs,
):
    """اجرای سریع یک سناریو."""
    return resolve_battle(
        BattleInput(
            operation_type=op,
            target_type=target,
            attacker_name="مهاجم",
            defender_name="مدافع",
            committed=committed,
            defender_assets=defenders,
            distance_km=km,
            distance_tier=tier,
            seed=seed,
            **kwargs,
        )
    )


def main() -> int:
    print("=" * 60)
    print("تست موتور نبرد محاسباتی")
    print("=" * 60)

    # --- ۱) امکان‌سنجی ---
    print("\n[۱] امکان‌سنجی و رد عملیات نامعتبر")
    check("عملیات بدون تجهیزات رد می‌شود", not run([], light_ad()).feasible)
    check(
        "تانک برای حمله‌ی هوایی رد می‌شود",
        not run(
            [CommittedAsset("T-72", 50, "خودروهای زمینی", "تانک", "دستگاه")], light_ad()
        ).feasible,
    )
    check(
        "حمله‌ی دریایی بدون آب مشترک رد می‌شود",
        not run(
            [CommittedAsset("ناوشکن", 5, "نیروی دریایی", "ناوشکن", "فروند")],
            light_ad(),
            op=OperationType.NAVAL_STRIKE,
            target=TargetType.PORT,
            shares_sea=False,
        ).feasible,
    )
    check(
        "حمله‌ی زمینی فراقاره‌ای رد می‌شود",
        not run(ground_force(), light_ad(), op=OperationType.GROUND_ASSAULT, km=10_000).feasible,
    )
    check(
        "تأسیسات هسته‌ای با حمله‌ی دریایی رد می‌شود",
        not run(
            [CommittedAsset("ناوشکن", 5, "نیروی دریایی", "ناوشکن", "فروند")],
            light_ad(),
            op=OperationType.NAVAL_STRIKE,
            target=TargetType.NUCLEAR_SITE,
            shares_sea=True,
        ).feasible,
    )
    check(
        "نیروی زمینی در فاصله‌ی همسایگی مجاز است (باگ برد رفع شده)",
        run(ground_force(), light_ad(), op=OperationType.GROUND_ASSAULT, km=750, tier="neighbor").feasible,
    )
    check(
        "پایگاه پیشرو محدودیت برد را برمی‌دارد",
        run(massive_air(), light_ad(), km=11_000, tier="intercontinental", has_forward_base=True).feasible,
    )

    # --- ۲) مقیاس قدرت در برابر پدافند ---
    print("\n[۲] مقیاس قدرت و پدافند")
    small_light = run(small_air(), light_ad())
    small_heavy = run(small_air(), heavy_ad())
    massive_light = run(massive_air(), light_ad(), km=3000, tier="continental", has_forward_base=True)
    massive_heavy = run(massive_air(), heavy_ad(), km=3000, tier="continental", has_forward_base=True)

    check(
        "پدافند سنگین بیشتر از سبک رهگیری می‌کند",
        small_heavy.intercept_pct > small_light.intercept_pct,
        f"{small_heavy.intercept_pct} vs {small_light.intercept_pct}",
    )
    check(
        "حمله‌ی کوچک به پدافند سنگین عملاً خنثی می‌شود",
        small_heavy.intercept_pct >= 70 and small_heavy.infra_damage_pct < 10,
        f"int={small_heavy.intercept_pct} dmg={small_heavy.infra_damage_pct}",
    )
    check(
        "حمله‌ی عظیم به پدافند سبک خسارت سنگین می‌زند",
        massive_light.infra_damage_pct >= 60,
        f"dmg={massive_light.infra_damage_pct}",
    )
    check(
        "حمله‌ی بزرگ‌تر خسارت بیشتری از حمله‌ی کوچک می‌زند",
        massive_light.infra_damage_pct > small_light.infra_damage_pct,
    )
    check(
        "پدافند سنگین خسارت حمله‌ی عظیم را کم می‌کند",
        massive_heavy.infra_damage_pct < massive_light.infra_damage_pct,
        f"{massive_heavy.infra_damage_pct} vs {massive_light.infra_damage_pct}",
    )
    check("درصد رهگیری هرگز از ۱۰۰ بیشتر نیست", massive_heavy.intercept_pct <= 100.0)
    check("خسارت زیرساخت هرگز از ۱۰۰ بیشتر نیست", massive_light.infra_damage_pct <= 100.0)

    # --- ۳) تلفات ---
    print("\n[۳] تلفات")
    check("مهاجم در برابر پدافند سنگین تلفات می‌دهد", len(small_heavy.attacker_losses) > 0)
    check(
        "تلفات هرگز از تعداد اعزامی بیشتر نیست",
        all(
            item["count"] <= next(a.count for a in small_air() if a.name == item["name"])
            for item in small_heavy.attacker_losses
        ),
    )
    check("مدافع هم تلفات می‌دهد", len(massive_light.defender_losses) > 0)
    check(
        "تلفات مهاجم در پدافند سنگین بیشتر از پدافند سبک است",
        sum(i["count"] for i in small_heavy.attacker_losses)
        > sum(i["count"] for i in small_light.attacker_losses),
    )

    # --- ۴) تلفات غیرنظامی ---
    print("\n[۴] تلفات غیرنظامی")
    city = run(
        massive_air(), light_ad(), target=TargetType.CITY, km=3000, tier="continental",
        defender_population=90_000_000, has_forward_base=True,
    )
    base = run(
        massive_air(), light_ad(), target=TargetType.MILITARY_BASE, km=3000, tier="continental",
        defender_population=90_000_000, has_forward_base=True,
    )
    check("حمله به شهر تلفات غیرنظامی دارد", city.civilian_casualties > 0)
    check("حمله به پایگاه نظامی تلفات غیرنظامی ندارد", base.civilian_casualties == 0)
    check("تلفات غیرنظامی از سقف نمی‌گذرد", city.civilian_casualties <= 50_000)
    check(
        "حمله به غیرنظامیان رضایت مهاجم را بیشتر کم می‌کند",
        city.econ_effects["attacker_satisfaction_delta"]
        < base.econ_effects["attacker_satisfaction_delta"],
    )

    # --- ۵) دفاع لایه‌ای ---
    print("\n[۵] دفاع لایه‌ای")
    plain = run(massive_air(), light_ad(), km=3000, tier="continental", has_forward_base=True)
    with_patrol = run(
        massive_air(), light_ad(), km=3000, tier="continental",
        defender_patrol_active=True, has_forward_base=True,
    )
    with_bases = run(
        massive_air(), light_ad(), km=3000, tier="continental",
        defender_base_count=5, has_forward_base=True,
    )
    check("گشت فعال رهگیری را بالا می‌برد", with_patrol.intercept_pct > plain.intercept_pct)
    check("پایگاه‌های مدافع رهگیری را بالا می‌برند", with_bases.intercept_pct > plain.intercept_pct)

    # --- ۶) بازدارندگی هسته‌ای ---
    print("\n[۶] بازدارندگی هسته‌ای")
    no_nuke = run(
        massive_air(), light_ad(), target=TargetType.CITY, km=3000, tier="continental",
        defender_population=90_000_000, has_forward_base=True,
    )
    with_nuke = run(
        massive_air(), light_ad(), target=TargetType.CITY, km=3000, tier="continental",
        defender_population=90_000_000, nuclear_deterrence_pct=30.0, has_forward_base=True,
    )
    check(
        "بازدارندگی خسارت زیرساخت را کم می‌کند",
        with_nuke.infra_damage_pct < no_nuke.infra_damage_pct,
        f"{with_nuke.infra_damage_pct} vs {no_nuke.infra_damage_pct}",
    )
    check(
        "بازدارندگی تلفات غیرنظامی را کم می‌کند",
        with_nuke.civilian_casualties < no_nuke.civilian_casualties,
    )

    # --- ۷) آمادگی رزمی و فرمانده ---
    print("\n[۷] آمادگی رزمی و فرمانده")
    cold = run(small_air(), heavy_ad(), attacker_readiness=0.0)
    ready = run(small_air(), heavy_ad(), attacker_readiness=40.0)
    check(
        "آمادگی رزمی بالا قدرت حمله را افزایش می‌دهد",
        ready.attack_power > cold.attack_power,
        f"{ready.attack_power} vs {cold.attack_power}",
    )
    led = run(small_air(), heavy_ad(), attacker_commander_bonus=10.0)
    check("بونوس فرمانده قدرت حمله را افزایش می‌دهد", led.attack_power > cold.attack_power)
    guarded = run(small_air(), heavy_ad(), defender_commander_bonus=10.0)
    check("بونوس فرمانده مدافع پدافند را تقویت می‌کند", guarded.defense_power > cold.defense_power)

    # --- ۸) هزینه‌ها ---
    print("\n[۸] هزینه‌ها")
    near = run(massive_air(), light_ad(), km=500, tier="neighbor", has_forward_base=True)
    far = run(massive_air(), light_ad(), km=11_000, tier="intercontinental", has_forward_base=True)
    check("سوخت عملیات مثبت است", near.fuel_cost > 0)
    check("عملیات دورتر سوخت بیشتری می‌خواهد", far.fuel_cost > near.fuel_cost,
          f"{far.fuel_cost} vs {near.fuel_cost}")
    check("هزینه‌ی بودجه مثبت است", near.budget_cost > 0)
    check(
        "نیروی بیشتر هزینه‌ی بیشتری دارد",
        near.budget_cost > run(small_air(), light_ad()).budget_cost,
    )
    check(
        "مهاجم همیشه هزینه‌ی داخلی می‌دهد",
        near.econ_effects["attacker_satisfaction_delta"] < 0
        and near.econ_effects["attacker_inflation_delta"] > 0,
    )

    # --- ۹) شدت و فازها ---
    print("\n[۹] شدت عملیات و فازهای خبری")
    check("شدت در بازه‌ی ۱ تا ۱۰ است", 1 <= city.intensity <= 10, str(city.intensity))
    check("عملیات بزرگ شدت بیشتری از عملیات کوچک دارد",
          massive_light.intensity > small_heavy.intensity)
    check("تعداد فاز با شدت متناسب است", city.total_phases >= plain.total_phases or city.intensity <= plain.intensity)
    check("فاصله‌ی فازها مثبت است", city.phase_interval_min >= 1)
    check("تعداد فاز در بازه‌ی معقول است", 3 <= city.total_phases <= 9)

    # --- ۱۰) بازتولیدپذیری ---
    print("\n[۱۰] بازتولیدپذیری")
    a = run(massive_air(), heavy_ad(), seed=123)
    b = run(massive_air(), heavy_ad(), seed=123)
    c = run(massive_air(), heavy_ad(), seed=456)
    check("همان seed نتیجه‌ی یکسان می‌دهد", a.infra_damage_pct == b.infra_damage_pct)
    check("seed متفاوت نتیجه‌ی متفاوت می‌دهد",
          a.infra_damage_pct != c.infra_damage_pct or a.intercept_pct != c.intercept_pct)

    # --- ۱۱) واقعیت‌های خبری ---
    print("\n[۱۱] واقعیت‌های خبری")
    check("نام تجهیزات مؤثر مهاجم ثبت می‌شود", len(city.facts.get("top_attack_assets", [])) > 0)
    check("واقعیت‌ها شامل درصد رهگیری است", "intercept_pct" in city.facts)
    check("واقعیت‌ها شامل نتیجه است", bool(city.facts.get("outcome")))
    check("واقعیت‌ها شامل شدت است", city.facts.get("intensity") == city.intensity)

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
