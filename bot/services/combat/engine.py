"""
هسته‌ی موتور نبرد (v1.10.6) — محاسبه‌ی کاملاً قطعی نتیجه‌ی عملیات.

فلسفه: نتیجه‌ی نبرد را **کد** تعیین می‌کند نه هوش مصنوعی. تجهیزات واقعی
مهاجم در برابر پدافند واقعی مدافع سنجیده می‌شود، فاصله و آمادگی رزمی اثر
می‌گذارند و تلفات دقیقاً از موجودی کم می‌شود. AI فقط از روی همین اعداد،
متن خبر را می‌نویسد.

مراحل: امکان‌سنجی ← قدرت مؤثر ← پدافند ← تلفات مهاجم ← تلفات مدافع ←
بازدارندگی هسته‌ای ← تلفات غیرنظامی ← اثرات اقتصادی ← شدت و فازها.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ...constants import (
    AIR_DEFENSE_MAX_INTERCEPT_PCT,
    AIR_DEFENSE_MIN_INTERCEPT_PCT,
    ATTACKER_BUDGET_COST_BASE,
    ATTACKER_BUDGET_COST_PER_UNIT,
    ATTACKER_INFLATION_PER_OP,
    ATTACKER_LOSS_FROM_INTERCEPT_PCT,
    ATTACKER_SATISFACTION_PER_OP,
    ATTACKER_STABILITY_PER_OP,
    BASE_DEFENSE_BONUS_MAX_PCT,
    BASE_DEFENSE_BONUS_PCT,
    CIVILIAN_CASUALTIES_MAX,
    CIVILIAN_CASUALTIES_PER_POWER,
    CIVILIAN_POPULATION_FACTOR,
    CIVILIAN_STRIKE_EXTRA_SATISFACTION,
    CIVILIAN_STRIKE_EXTRA_STABILITY,
    DEFENDER_BUDGET_LOSS_PER_10PCT,
    DEFENDER_INFLATION_PER_10PCT,
    DEFENDER_LOSS_BASE_PCT,
    DEFENDER_SATISFACTION_PER_10PCT,
    DEFENDER_STABILITY_PER_10PCT,
    DEFENSE_RATIO_SCALING,
    DISTANCE_FUEL_MULTIPLIER,
    DISTANCE_POWER_MULTIPLIER,
    LOSS_RANDOM_VARIANCE_PCT,
    OPERATION_BASE_FUEL,
    OPERATION_FUEL_PER_UNIT,
    OPERATION_INTENSITY_PHASES,
    OPERATION_MAX_RANGE_KM,
    PATROL_DEFENSE_BONUS_PCT,
    READINESS_TO_POWER_FACTOR,
    TARGET_ALLOWED_OPERATIONS,
    TARGET_VULNERABILITY,
)
from ...enums import CIVILIAN_TARGETS, OperationType, TargetType
from .power import (
    CommittedAsset,
    PowerBreakdown,
    allowed_branches_for,
    defense_power,
    strike_power,
)


@dataclass
class BattleInput:
    """همه‌ی ورودی‌های لازم برای محاسبه‌ی یک عملیات."""

    operation_type: OperationType
    target_type: TargetType

    attacker_name: str
    defender_name: str

    committed: list[CommittedAsset]           # تجهیزات اعزامی مهاجم
    defender_assets: list[CommittedAsset]     # کل تجهیزات مدافع

    distance_km: float = 0.0
    distance_tier: str = "regional"
    shares_sea: bool = False

    attacker_readiness: float = 0.0           # آمادگی رزمی مهاجم (۰ تا ۴۰)
    defender_readiness: float = 0.0
    attacker_commander_bonus: float = 0.0     # درصد بونوس فرمانده مربوطه
    defender_commander_bonus: float = 0.0

    defender_patrol_active: bool = False      # گشت فعال از نوع مرتبط
    defender_base_count: int = 0              # تعداد پایگاه‌های فعال مدافع
    defender_population: int = 0
    nuclear_deterrence_pct: float = 0.0       # بازدارندگی هسته‌ای مدافع (۰ تا ۳۰)

    has_forward_base: bool = False            # پایگاه نزدیک هدف (برد را آزاد می‌کند)
    seed: int | None = None                   # برای بازتولیدپذیری نتایج


@dataclass
class BattleResult:
    """نتیجه‌ی کامل محاسبه‌شده‌ی یک عملیات."""

    feasible: bool = True
    reject_reason: str = ""

    attack_power: float = 0.0
    defense_power: float = 0.0
    intercept_pct: float = 0.0
    penetrating_power: float = 0.0

    attacker_losses: list[dict] = field(default_factory=list)
    defender_losses: list[dict] = field(default_factory=list)
    civilian_casualties: int = 0
    infra_damage_pct: float = 0.0

    econ_effects: dict = field(default_factory=dict)
    fuel_cost: float = 0.0
    budget_cost: float = 0.0

    outcome: str = ""
    intensity: int = 1
    total_phases: int = 3
    phase_interval_min: int = 1

    # داده‌های خام برای خبرنویس (نام تجهیزات مؤثر، درصدها و ...)
    facts: dict = field(default_factory=dict)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _check_feasibility(data: BattleInput, power: PowerBreakdown) -> tuple[bool, str]:
    """
    امکان‌سنجی عملیات: تجهیزات مناسب، برد کافی و تناسب هدف با نوع حمله.
    خروجی: (امکان‌پذیر؟، دلیل رد)
    """
    if not data.committed or power.total_units <= 0:
        return False, "هیچ تجهیزاتی برای این عملیات اعزام نشده است."

    # تجهیزات باید با نوع عملیات بخوانند
    allowed = allowed_branches_for(data.operation_type)
    if allowed is not None:
        if not any(a.branch in allowed for a in data.committed if a.count > 0):
            return False, "تجهیزات انتخابی با این نوع عملیات تناسب ندارند."

    # هدف باید با نوع عملیات بخواند
    allowed_ops = TARGET_ALLOWED_OPERATIONS.get(data.target_type)
    if allowed_ops is not None and data.operation_type not in allowed_ops:
        return False, "این نوع هدف با این نوع عملیات قابل هدف‌گیری نیست."

    # حمله‌ی دریایی نیاز به آب مشترک دارد
    if data.operation_type == OperationType.NAVAL_STRIKE and not data.shares_sea:
        return False, "کشور هدف با شما آب مشترک ندارد؛ حمله‌ی دریایی ممکن نیست."

    # بررسی برد: هم سقف نوع عملیات، هم برد واقعی تجهیزات اعزامی
    if not data.has_forward_base:
        max_op_range = OPERATION_MAX_RANGE_KM.get(data.operation_type, 20000.0)
        if data.distance_km > max_op_range:
            return False, (
                f"فاصله‌ی هدف ({data.distance_km:,.0f} کیلومتر) از برد این نوع عملیات بیشتر است."
            )
        # برد تک‌تک تجهیزات فقط برای عملیات «رفت و برگشتی» معنا دارد.
        # نیروی زمینی وارد خاک دشمن می‌شود و با برد سامانه سنجیده نمی‌شود.
        if (
            data.operation_type != OperationType.GROUND_ASSAULT
            and power.max_range_km > 0
            and data.distance_km > power.max_range_km
        ):
            return False, (
                "تجهیزات انتخابی برد کافی برای رسیدن به هدف را ندارند. "
                "تجهیزات بردبلندتر انتخاب کنید یا از پایگاه نزدیک‌تر اقدام کنید."
            )

    return True, ""


def _intensity_to_phases(intensity: int) -> tuple[int, int]:
    """تعداد فاز خبری و فاصله‌ی بین فازها بر اساس شدت عملیات."""
    for max_intensity, phases, interval in OPERATION_INTENSITY_PHASES:
        if intensity <= max_intensity:
            return phases, interval
    last = OPERATION_INTENSITY_PHASES[-1]
    return last[1], last[2]


def _distribute_losses(
    assets: list[CommittedAsset], loss_ratio: float, rng: random.Random
) -> list[dict]:
    """
    تلفات را به نسبت میان اقلام درگیر پخش می‌کند.
    هر قلم نوسان تصادفی مستقل دارد تا نتیجه یکنواخت به‌نظر نرسد.
    """
    losses: list[dict] = []
    if loss_ratio <= 0:
        return losses

    for asset in assets:
        if asset.count <= 0:
            continue
        variance = rng.uniform(
            1.0 - LOSS_RANDOM_VARIANCE_PCT / 100.0,
            1.0 + LOSS_RANDOM_VARIANCE_PCT / 100.0,
        )
        lost = asset.count * loss_ratio * variance
        # گرد کردن احتمالی: کسر اعشاری شانس یک واحد اضافه می‌دهد
        whole = int(lost)
        if rng.random() < (lost - whole):
            whole += 1
        whole = min(whole, asset.count)
        if whole > 0:
            losses.append({
                "name": asset.name,
                "count": whole,
                "unit": asset.unit,
                "category": asset.category,
            })
    return losses


def resolve_battle(data: BattleInput) -> BattleResult:
    """
    محاسبه‌ی کامل یک عملیات. خروجی همه‌چیز را برای ذخیره در DB و
    نوشتن خبر آماده می‌کند.
    """
    rng = random.Random(data.seed)
    result = BattleResult()

    # ---------- ۱) قدرت خام مهاجم ----------
    attack_bd = strike_power(data.committed)

    # ---------- ۲) امکان‌سنجی ----------
    feasible, reason = _check_feasibility(data, attack_bd)
    if not feasible:
        result.feasible = False
        result.reject_reason = reason
        return result

    # ---------- ۳) قدرت مؤثر (فاصله + آمادگی + فرمانده) ----------
    distance_mult = DISTANCE_POWER_MULTIPLIER.get(data.distance_tier, 0.8)
    readiness_mult = 1.0 + (data.attacker_readiness * READINESS_TO_POWER_FACTOR / 100.0)
    commander_mult = 1.0 + (data.attacker_commander_bonus / 100.0)
    effective_attack = attack_bd.total * distance_mult * readiness_mult * commander_mult

    # ---------- ۴) پدافند مدافع ----------
    defense_bd = defense_power(data.defender_assets, data.operation_type)
    def_readiness_mult = 1.0 + (data.defender_readiness * READINESS_TO_POWER_FACTOR / 100.0)
    def_commander_mult = 1.0 + (data.defender_commander_bonus / 100.0)
    effective_defense = defense_bd.total * def_readiness_mult * def_commander_mult

    # درصد رهگیری از نسبت پدافند به حمله
    if effective_attack <= 0:
        ratio = 0.0
    else:
        ratio = effective_defense / (effective_attack + effective_defense)
    intercept_pct = ratio * DEFENSE_RATIO_SCALING

    # بونوس‌های پدافندی
    if data.defender_patrol_active:
        intercept_pct += PATROL_DEFENSE_BONUS_PCT
    base_bonus = min(
        data.defender_base_count * BASE_DEFENSE_BONUS_PCT, BASE_DEFENSE_BONUS_MAX_PCT
    )
    intercept_pct += base_bonus

    # نوسان تصادفی پدافند (شب/روز، غافلگیری، خطای انسانی)
    intercept_pct *= rng.uniform(0.88, 1.12)
    intercept_pct = _clamp(
        intercept_pct, AIR_DEFENSE_MIN_INTERCEPT_PCT, AIR_DEFENSE_MAX_INTERCEPT_PCT
    )

    penetrating = effective_attack * (1.0 - intercept_pct / 100.0)

    result.attack_power = round(effective_attack, 2)
    result.defense_power = round(effective_defense, 2)
    result.intercept_pct = round(intercept_pct, 1)
    result.penetrating_power = round(penetrating, 2)

    # ---------- ۵) تلفات مهاجم (از بخش رهگیری‌شده) ----------
    attacker_loss_ratio = (
        intercept_pct / 100.0 * ATTACKER_LOSS_FROM_INTERCEPT_PCT / 100.0
    )
    result.attacker_losses = _distribute_losses(data.committed, attacker_loss_ratio, rng)

    # ---------- ۶) خسارت و تلفات مدافع ----------
    vulnerability = TARGET_VULNERABILITY.get(data.target_type, 1.0)
    # خسارت زیرساخت: تابع اشباع‌شونده تا درصد از ۱۰۰ نگذرد
    damage_scale = penetrating * vulnerability
    infra_damage = 100.0 * (1.0 - pow(2.718281828, -damage_scale / 900.0))
    result.infra_damage_pct = round(_clamp(infra_damage, 0.0, 100.0), 1)

    # تلفات تجهیزات مدافع: فقط شاخه‌های درگیر در پدافند
    from .power import DEFENSE_BRANCHES

    engaged_branches = DEFENSE_BRANCHES.get(data.operation_type, frozenset())
    engaged_defenders = [
        a for a in data.defender_assets if a.branch in engaged_branches and a.count > 0
    ]
    defender_loss_ratio = (
        (1.0 - intercept_pct / 100.0) * DEFENDER_LOSS_BASE_PCT / 100.0 * vulnerability
    )
    # مدافع کل زرادخانه‌اش درگیر نیست؛ فقط بخشی از آن در محل حمله حاضر است
    defender_loss_ratio *= 0.12
    defender_losses = _distribute_losses(engaged_defenders, defender_loss_ratio, rng)

    # ---------- ۷) بازدارندگی هسته‌ای ----------
    if data.nuclear_deterrence_pct > 0:
        factor = 1.0 - data.nuclear_deterrence_pct / 100.0
        for item in defender_losses:
            item["count"] = max(0, int(item["count"] * factor))
        defender_losses = [i for i in defender_losses if i["count"] > 0]
        result.infra_damage_pct = round(result.infra_damage_pct * factor, 1)

    result.defender_losses = defender_losses

    # ---------- ۸) تلفات غیرنظامی ----------
    if data.target_type in CIVILIAN_TARGETS:
        base_casualties = penetrating * CIVILIAN_CASUALTIES_PER_POWER
        population_mult = 1.0 + data.defender_population * CIVILIAN_POPULATION_FACTOR
        casualties = base_casualties * population_mult * rng.uniform(0.7, 1.3)
        if data.nuclear_deterrence_pct > 0:
            casualties *= 1.0 - data.nuclear_deterrence_pct / 100.0
        result.civilian_casualties = int(_clamp(casualties, 0, CIVILIAN_CASUALTIES_MAX))

    # ---------- ۹) هزینه‌ها و اثرات اقتصادی ----------
    base_fuel = OPERATION_BASE_FUEL.get(data.operation_type, 1.0)
    fuel_mult = DISTANCE_FUEL_MULTIPLIER.get(data.distance_tier, 1.5)
    result.fuel_cost = round(
        (base_fuel + attack_bd.total_units * OPERATION_FUEL_PER_UNIT) * fuel_mult, 2
    )
    result.budget_cost = round(
        ATTACKER_BUDGET_COST_BASE + attack_bd.total_units * ATTACKER_BUDGET_COST_PER_UNIT, 2
    )

    damage_units = result.infra_damage_pct / 10.0
    econ: dict[str, float] = {
        "defender_satisfaction_delta": round(damage_units * DEFENDER_SATISFACTION_PER_10PCT, 2),
        "defender_stability_delta": round(damage_units * DEFENDER_STABILITY_PER_10PCT, 2),
        "defender_inflation_delta": round(damage_units * DEFENDER_INFLATION_PER_10PCT, 2),
        "defender_budget_loss": round(damage_units * DEFENDER_BUDGET_LOSS_PER_10PCT, 2),
        "attacker_satisfaction_delta": ATTACKER_SATISFACTION_PER_OP,
        "attacker_stability_delta": ATTACKER_STABILITY_PER_OP,
        "attacker_inflation_delta": ATTACKER_INFLATION_PER_OP,
    }
    # حمله به غیرنظامیان: فشار افکار عمومی و انزوای بین‌المللی برای مهاجم
    if result.civilian_casualties > 0:
        econ["attacker_satisfaction_delta"] += CIVILIAN_STRIKE_EXTRA_SATISFACTION
        econ["attacker_stability_delta"] += CIVILIAN_STRIKE_EXTRA_STABILITY
    result.econ_effects = econ

    # ---------- نتیجه‌ی نبرد ----------
    if intercept_pct >= 75:
        result.outcome = "خنثی‌سازی حمله توسط پدافند مدافع"
    elif intercept_pct >= 55:
        result.outcome = "برتری مدافع"
    elif result.infra_damage_pct >= 60:
        result.outcome = "پیروزی قاطع مهاجم"
    elif result.infra_damage_pct >= 25:
        result.outcome = "برتری مهاجم"
    else:
        result.outcome = "درگیری بی‌نتیجه"

    # ---------- شدت عملیات (۱ تا ۱۰) ----------
    # ترکیبی از حجم نیرو، خسارت واردشده و تلفات غیرنظامی
    volume_score = min(4.0, attack_bd.total_units / 60.0)
    damage_score = result.infra_damage_pct / 100.0 * 4.0
    civilian_score = 2.0 if result.civilian_casualties > 2000 else (
        1.0 if result.civilian_casualties > 0 else 0.0
    )
    intensity = int(round(1 + volume_score + damage_score + civilian_score))
    result.intensity = int(_clamp(intensity, 1, 10))
    result.total_phases, result.phase_interval_min = _intensity_to_phases(result.intensity)

    # ---------- واقعیت‌های خام برای خبرنویس ----------
    result.facts = {
        "attacker": data.attacker_name,
        "defender": data.defender_name,
        "operation_type": data.operation_type.value,
        "target_type": data.target_type.value,
        "distance_km": int(data.distance_km),
        "top_attack_assets": attack_bd.top_assets(3),
        "top_defense_assets": defense_bd.top_assets(3),
        "units_committed": attack_bd.total_units,
        "intercept_pct": result.intercept_pct,
        "infra_damage_pct": result.infra_damage_pct,
        "attacker_losses": result.attacker_losses,
        "defender_losses": result.defender_losses,
        "civilian_casualties": result.civilian_casualties,
        "outcome": result.outcome,
        "intensity": result.intensity,
        "nuclear_deterrence": data.nuclear_deterrence_pct > 0,
        "patrol_active": data.defender_patrol_active,
    }

    return result
