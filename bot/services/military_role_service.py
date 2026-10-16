"""سرویس منطق بازی برای رول‌ها و عملیات‌های نظامی (آپدیت شماره ۲)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ROLE_HEADER_MAX_LEN,
)
from ..database.models import Country, MilitaryRole
from ..database.repositories import military as mil_repo
from ..enums import (
    MILITARY_ROLE_TYPE_EMOJI,
    MILITARY_ROLE_TYPE_FA,
    MilitaryRoleStatus,
    MilitaryRoleType,
)
from ..utils.numbers import fa_number
from ..utils.ui import DIVIDER, header

logger = logging.getLogger(__name__)


def build_military_role_header(
    role: MilitaryRole, attacker: Country, target: Country, page_num: int
) -> str:
    """ساخت سربرگ کوتاه (زیر ۹۶ کاراکتر) برای پیام رول نظامی."""
    try:
        op_t = MilitaryRoleType(role.op_type)
        emoji = MILITARY_ROLE_TYPE_EMOJI.get(op_t, "⚔️")
        name_fa = MILITARY_ROLE_TYPE_FA.get(op_t, "عملیات نظامی")
    except Exception:
        emoji = "⚔️"
        name_fa = "عملیات نظامی"

    hdr = (
        f"{emoji} <b>{name_fa}</b> | {attacker.flag} {attacker.name_fa} ⚔️ "
        f"{target.flag} {target.name_fa} | "
        f"📄 {fa_number(page_num)}/{fa_number(role.total_pages)}"
    )
    if len(hdr) > ROLE_HEADER_MAX_LEN:
        return hdr[:ROLE_HEADER_MAX_LEN]
    return hdr


def format_casualties_report(role: MilitaryRole) -> str:
    """تولید گزارش متنی از تلفات ثبت‌شده در این عملیات."""
    casualties = role.casualties_list
    if not casualties:
        return "بدون تلفات ثبت‌شده"

    lines: list[str] = []
    for c in casualties:
        side_tag = "⚔️ مهاجم" if c.get("side") == "attacker" else "🛡 مدافع"
        c_name = c.get("country_name", "")
        asset = c.get("asset_name", "")
        cnt = c.get("count", 0)
        lines.append(f"• {side_tag} ({c_name}): <b>{fa_number(cnt)}</b> واحد «{asset}»")
    return "\n".join(lines)


def render_military_role_message(
    role: MilitaryRole, attacker: Country, target: Country, page_num: int
) -> str:
    """رندر پیام نمایش صفحه رول نظامی."""
    hdr = build_military_role_header(role, attacker, target, page_num)
    page_text = role.get_page_text(page_num)
    title_line = f"📌 <b>عنوان عملیات:</b> {role.title}"

    casualties_text = ""
    cas_list = role.casualties_list
    if cas_list:
        casualties_text = (
            f"\n💥 <b>تلفات ثبت‌شده تاکنون:</b>\n"
            f"{format_casualties_report(role)}\n"
        )

    return (
        f"{hdr}\n"
        f"{title_line}"
        f"{casualties_text}\n"
        f"{DIVIDER}\n\n"
        f"{page_text}"
    )


async def submit_military_role(
    session: AsyncSession, role: MilitaryRole
) -> tuple[bool, str]:
    """ارسال نهایی رول نظامی به گروه عملیات ستاد."""
    role.status = MilitaryRoleStatus.PENDING_REVIEW.value
    role.submitted_at = datetime.now(timezone.utc)
    await session.flush()
    return True, "عملیات نظامی با موفقیت به ستاد فرماندهی ارسال شد."


async def record_casualty(
    session: AsyncSession,
    role: MilitaryRole,
    side: str,
    country: Country,
    asset_name: str,
    count: int,
    admin_id: int,
) -> tuple[bool, str, int]:
    """
    ثبت تلفات روی یکی از طرفین (مهاجم یا مدافع):
    - کسر از تجهیزات نظامی کشور با reduce_count
    - ثبت در تاریخچه تلفات رول
    """
    if count <= 0:
        return False, "تعداد تلفات باید بیشتر از صفر باشد.", 0

    await mil_repo.reduce_count(session, country.id, asset_name, count)
    asset = await mil_repo.get_asset_by_name(session, country.id, asset_name)
    remaining = asset.count if asset else 0

    role.add_casualty({
        "side": side,
        "country_id": country.id,
        "country_name": country.name_fa,
        "asset_name": asset_name,
        "count": count,
        "admin_id": admin_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await session.flush()
    return True, f"تلفات «{asset_name}» به تعداد {fa_number(count)} ثبت شد.", remaining


async def complete_military_role(
    session: AsyncSession, role: MilitaryRole, admin_id: int
) -> None:
    """پایان عملیات توسط ادمین و تغییر وضعیت به COMPLETED."""
    role.status = MilitaryRoleStatus.COMPLETED.value
    role.reviewed_by = admin_id
    role.completed_at = datetime.now(timezone.utc)
    await session.flush()
