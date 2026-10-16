"""سرویس منطق بازی برای رول‌ها و پروژه‌های امنیتی (آپدیت شماره ۲)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    MAX_ROLE_PAGE_LEN,
    ROLE_HEADER_MAX_LEN,
    SECURITY_ROLE_COST,
)
from ..database.models import Country, SecurityRole
from ..enums import SecurityRoleStatus
from ..utils.numbers import fa_money, fa_number
from ..utils.ui import DIVIDER, header

logger = logging.getLogger(__name__)


def validate_role_page(text: str) -> tuple[bool, str]:
    """اعتبارسنجی متن صفحه رول: خالی نبودن و عدم عبور از ۴۰۰۰ کاراکتر."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False, "متن صفحه نمی‌تواند خالی باشد."
    if len(cleaned) > MAX_ROLE_PAGE_LEN:
        return (
            False,
            f"طول متن صفحه ({fa_number(len(cleaned))} کاراکتر) از سقف مجاز "
            f"({fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر) بیشتر است.",
        )
    return True, ""


def build_security_role_header(
    role: SecurityRole, country: Country, page_num: int
) -> str:
    """ساخت سربرگ کوتاه (زیر ۹۶ کاراکتر) برای پیام رول امنیتی."""
    hdr = (
        f"🛡 <b>پروژه امنیتی</b> | {country.flag} {country.name_fa} | "
        f"📄 صفحه {fa_number(page_num)} از {fa_number(role.total_pages)}"
    )
    if len(hdr) > ROLE_HEADER_MAX_LEN:
        return hdr[:ROLE_HEADER_MAX_LEN]
    return hdr


def render_security_role_message(
    role: SecurityRole, country: Country, page_num: int
) -> str:
    """رندر پیام نمایش صفحه پروژه امنیتی."""
    hdr = build_security_role_header(role, country, page_num)
    page_text = role.get_page_text(page_num)
    title_line = f"📌 <b>عنوان پروژه:</b> {role.title}"

    return (
        f"{hdr}\n"
        f"{title_line}\n"
        f"{DIVIDER}\n\n"
        f"{page_text}"
    )


async def submit_security_role(
    session: AsyncSession, role: SecurityRole, country: Country
) -> tuple[bool, str]:
    """
    ارسال نهایی رول امنیتی:
    - بررسی بودجه (حداقل ۲۰M$)
    - کسر ۲۰,۰۰۰,۰۰۰ دلار از بودجه کشور
    - تغییر وضعیت به PENDING_REVIEW
    """
    if country.budget < SECURITY_ROLE_COST:
        return (
            False,
            f"❌ موجودی بودجه کشور شما ({fa_money(country.budget)}) برای ثبت این پروژه "
            f"کافی نیست. هزینه مورد نیاز: {fa_money(SECURITY_ROLE_COST)}.",
        )

    country.budget -= SECURITY_ROLE_COST
    role.status = SecurityRoleStatus.PENDING_REVIEW.value
    role.submitted_at = datetime.now(timezone.utc)
    await session.flush()
    return True, "پروژه با موفقیت ارسال شد."


async def approve_security_role(
    session: AsyncSession, role: SecurityRole, admin_id: int
) -> None:
    """تایید رول امنیتی توسط مدیریت و ثبت رسمی در آرشیو کشور."""
    role.status = SecurityRoleStatus.APPROVED.value
    role.reviewed_by = admin_id
    role.reviewed_at = datetime.now(timezone.utc)
    await session.flush()


async def reject_security_role(
    session: AsyncSession,
    role: SecurityRole,
    country: Country,
    admin_id: int,
    reason: str,
) -> None:
    """رد رول امنیتی، ثبت دلیل رد و عودت ۲۰ میلیون دلار به بودجه کشور."""
    role.status = SecurityRoleStatus.REJECTED.value
    role.rejection_reason = reason
    role.reviewed_by = admin_id
    role.reviewed_at = datetime.now(timezone.utc)
    # عودت وجه
    country.budget += SECURITY_ROLE_COST
    await session.flush()
