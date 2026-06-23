"""
منطق نظامی مشترک: فرمت گزارش تلفات و اعمال خسارت روی تجهیزات.
(توسط هندلر نظامی و زمان‌بند استفاده می‌شود.)
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.repositories import military as mil_repo
from ..utils.numbers import fa_number


def _format_loss_lines(losses: list[dict]) -> str:
    """فهرست تلفات را به متن چندخطی تبدیل می‌کند."""
    if not losses:
        return "   ◦ بدون تلفات قابل‌توجه"
    lines = []
    for loss in losses:
        name = loss.get("name", "?")
        count = loss.get("count", 0)
        lines.append(f"   ◦ {name}: {fa_number(count)}")
    return "\n".join(lines)


def format_casualties_log(
    attacker_name: str,
    defender_name: str,
    attack_type_fa: str,
    result: dict,
) -> str:
    """
    گزارش دقیق تلفات برای کانال لاگ مدیران (v1.5).
    شامل آمار دقیق هر دو طرف تا مالک به‌صورت دستی در اخبار نظامی اعلام کند.
    """
    outcome = result.get("outcome", "نامشخص")
    attacker_losses = result.get("attacker_losses", [])
    defender_losses = result.get("defender_losses", [])
    return (
        f"🎯 <b>گزارش نتیجه‌ی {attack_type_fa}</b>\n\n"
        f"🔴 مهاجم: {attacker_name}\n"
        f"🔵 مدافع: {defender_name}\n"
        f"🏁 نتیجه: {outcome}\n\n"
        f"💥 <b>تلفات مهاجم:</b>\n{_format_loss_lines(attacker_losses)}\n\n"
        f"💥 <b>تلفات مدافع:</b>\n{_format_loss_lines(defender_losses)}\n\n"
        f"📝 جزئیات: {result.get('player_report', '—')}"
    )


async def apply_losses(
    session: AsyncSession,
    attacker_id: int,
    defender_id: int,
    result: dict,
) -> None:
    """تلفات اعلام‌شده توسط AI را روی تجهیزات دو طرف اعمال می‌کند."""
    for loss in result.get("attacker_losses", []):
        await mil_repo.reduce_count(
            session, attacker_id, loss.get("name", ""), int(loss.get("count", 0) or 0)
        )
    for loss in result.get("defender_losses", []):
        await mil_repo.reduce_count(
            session, defender_id, loss.get("name", ""), int(loss.get("count", 0) or 0)
        )
