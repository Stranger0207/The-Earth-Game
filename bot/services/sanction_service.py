"""
منطق تحریم (v1.5): اعمال اثرات واقعی تحریم بر شاخص‌های کشور هدف.

هر نوع تحریم بر مجموعه‌ای از شاخص‌ها اثر می‌گذارد و شدت آن (low/medium/high)
که توسط AI تعیین می‌شود، بزرگی اثر را مقیاس می‌دهد.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Country
from ..enums import SanctionType

# ضریب شدت تحریم
_SEVERITY_MULTIPLIER = {"low": 0.5, "medium": 1.0, "high": 1.8}

# اثر پایه‌ی هر نوع تحریم (در شدت medium) روی شاخص‌های کشور هدف.
# مقادیر منفی یعنی کاهش؛ inflation مثبت یعنی افت ارزش پول ملی.
# کلیدها: econ (قدرت اقتصادی), sat (رضایت), stab (ثبات), infl (تورم), trade (تجارت خارجی)
_BASE_EFFECTS: dict[SanctionType, dict[str, float]] = {
    SanctionType.OIL_TRADE: {"econ": -4, "sat": -2, "stab": -1, "infl": 3, "trade": -2},
    SanctionType.GAS_TRADE: {"econ": -3, "sat": -2, "stab": -1, "infl": 2.5, "trade": -2},
    SanctionType.STEEL_TRADE: {"econ": -3, "sat": -1, "stab": -1, "infl": 2, "trade": -2},
    SanctionType.MINERAL_TRADE: {"econ": -3, "sat": -1, "stab": -1, "infl": 2, "trade": -2},
    SanctionType.FINANCIAL: {"econ": -5, "sat": -3, "stab": -2, "infl": 4, "trade": -1},
    SanctionType.ARMS: {"econ": -1, "sat": -1, "stab": -3, "infl": 0.5, "trade": -1},
    SanctionType.TRANSPORT: {"econ": -3, "sat": -2, "stab": -1, "infl": 2, "trade": -3},
    SanctionType.DIPLOMATIC: {"econ": -1, "sat": -3, "stab": -3, "infl": 0.5, "trade": -1},
    SanctionType.INDIVIDUAL: {"econ": -0.5, "sat": -2, "stab": -1, "infl": 0, "trade": 0},
}

# مراحل تجارت خارجی برای بدتر/بهترشدن
_TRADE_STEPS = ["negative", "balanced", "positive"]


def _worsen_trade(current: str, steps: int) -> str:
    """تجارت خارجی را به اندازه‌ی steps مرحله بدتر می‌کند."""
    try:
        idx = _TRADE_STEPS.index(current)
    except ValueError:
        idx = 1
    idx = max(0, idx - steps)
    return _TRADE_STEPS[idx]


async def apply_sanction_effects(
    session: AsyncSession,
    target: Country,
    sanction_type: SanctionType,
    severity: str,
) -> dict[str, float]:
    """
    اثرات تحریم را روی کشور هدف اعمال می‌کند و خلاصه‌ی تغییرات را برمی‌گرداند.
    """
    mult = _SEVERITY_MULTIPLIER.get(severity, 1.0)
    effects = _BASE_EFFECTS.get(sanction_type, {})

    econ_d = effects.get("econ", 0) * mult
    sat_d = effects.get("sat", 0) * mult
    stab_d = effects.get("stab", 0) * mult
    infl_d = effects.get("infl", 0) * mult
    trade_d = effects.get("trade", 0) * mult

    target.economic_power = max(0.0, target.economic_power + econ_d)
    target.public_satisfaction = max(0.0, target.public_satisfaction + sat_d)
    target.stability = max(0.0, target.stability + stab_d)
    target.inflation = max(0.0, target.inflation + infl_d)
    # رشد اقتصادی هدف به نزولی تغییر می‌کند
    if econ_d < 0:
        target.growth = "down"
    # بدترشدن تجارت خارجی به تعداد مرحله‌ی متناسب با شدت
    if trade_d < 0:
        steps = 1 if mult < 1.5 else 2
        target.foreign_trade = _worsen_trade(target.foreign_trade, steps)

    return {
        "econ": econ_d,
        "sat": sat_d,
        "stab": stab_d,
        "infl": infl_d,
    }
