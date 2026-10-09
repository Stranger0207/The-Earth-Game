"""توابع دسترسی داده (Repository) برای گیم‌مود مقاماتی دولت فدرال آمریکا."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...constants import CABINET_ROLES_DATA
from ...enums import CabinetRole
from ..models.cabinet import (
    CabinetActionLog,
    CabinetInquiry,
    CabinetInspection,
    CabinetMeeting,
    CabinetMember,
    CabinetMemo,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def init_default_roles(session: AsyncSession) -> None:
    """اطمینان از وجود داشتن ردیف‌های هر ۱۵ مقام در جدول cabinet_members."""
    result = await session.execute(select(CabinetMember.role_key))
    existing_keys = set(result.scalars().all())

    created = False
    for role in CabinetRole:
        if role.value not in existing_keys:
            member = CabinetMember(
                role_key=role.value,
                user_id=None,
                is_active=True,
                approval_rating=50.0,
            )
            session.add(member)
            created = True

    if created:
        await session.flush()


async def list_members(session: AsyncSession) -> list[CabinetMember]:
    """دریافت تمام اعضای کابینه با ترتیب رتبه سازمانی."""
    await init_default_roles(session)
    result = await session.execute(
        select(CabinetMember).options(selectinload(CabinetMember.user))
    )
    members = list(result.scalars().all())

    # مرتب‌سازی بر اساس رتبه مقام
    def get_rank(m: CabinetMember) -> int:
        role_enum = CabinetRole(m.role_key) if m.role_key in [r.value for r in CabinetRole] else None
        if role_enum and role_enum in CABINET_ROLES_DATA:
            return CABINET_ROLES_DATA[role_enum].get("rank", 99)
        return 99

    members.sort(key=get_rank)
    return members


async def get_member_by_role(
    session: AsyncSession, role_key: str
) -> CabinetMember | None:
    """یافتن مقام بر اساس کلید نقش."""
    await init_default_roles(session)
    result = await session.execute(
        select(CabinetMember)
        .where(CabinetMember.role_key == role_key)
        .options(selectinload(CabinetMember.user))
    )
    return result.scalar_one_or_none()


async def get_member_by_user(
    session: AsyncSession, user_id: int
) -> CabinetMember | None:
    """یافتن مقامی که این کاربر تلگرام متصدی آن است."""
    result = await session.execute(
        select(CabinetMember)
        .where(CabinetMember.user_id == user_id)
        .options(selectinload(CabinetMember.user))
    )
    return result.scalar_one_or_none()


async def claim_member_role(
    session: AsyncSession, role_key: str, user_id: int
) -> bool:
    """تصدی یک سمت توسط کاربر در صورت خالی بودن."""
    # اگر کاربر قبلاً سمتی دارد نمی‌تواند دو سمت همزمان داشته باشد
    current = await get_member_by_user(session, user_id)
    if current is not None:
        if current.role_key == role_key:
            return True
        return False

    member = await get_member_by_role(session, role_key)
    if member is None or member.user_id is not None:
        return False  # سمت پر است یا نامعتبر

    member.user_id = user_id
    member.claimed_at = _utcnow()
    await session.flush()
    return True


async def vacate_member_role(session: AsyncSession, role_key: str) -> bool:
    """استعفا یا آزادسازی یک سمت در کابینه."""
    member = await get_member_by_role(session, role_key)
    if member is None:
        return False
    member.user_id = None
    member.claimed_at = None
    await session.flush()
    return True


# ============================================================
#  مکاتبات و یادداشت‌های درون‌سازمانی (Memos)
# ============================================================


async def create_memo(
    session: AsyncSession,
    sender_role: str,
    recipient_role: str,
    sender_user_id: int,
    subject: str,
    body: str,
    is_urgent: bool = False,
) -> CabinetMemo:
    """ثبت یادداشت یا نامه درون‌کابینه‌ای."""
    memo = CabinetMemo(
        sender_role=sender_role,
        recipient_role=recipient_role,
        sender_user_id=sender_user_id,
        subject=subject,
        body=body,
        is_urgent=is_urgent,
        is_read=False,
    )
    session.add(memo)
    await session.flush()
    return memo


async def list_memos_for_role(
    session: AsyncSession, role_key: str, limit: int = 15
) -> list[CabinetMemo]:
    """دریافت نامه‌های دریافتی یا ارسالی یک مقام."""
    result = await session.execute(
        select(CabinetMemo)
        .where(
            or_(
                CabinetMemo.recipient_role == role_key,
                CabinetMemo.recipient_role == "all",
                CabinetMemo.sender_role == role_key,
            )
        )
        .order_by(CabinetMemo.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_memo(session: AsyncSession, memo_id: int) -> CabinetMemo | None:
    """دریافت یک نامه بر اساس آی‌دی."""
    return await session.get(CabinetMemo, memo_id)


# ============================================================
#  استعلام اطلاعات بین ارگان‌ها (Inquiries)
# ============================================================


async def create_inquiry(
    session: AsyncSession,
    from_role: str,
    to_role: str,
    sender_user_id: int,
    topic: str,
    question: str,
) -> CabinetInquiry:
    """ثبت استعلام اطلاعات از یک ارگان دیگر."""
    inquiry = CabinetInquiry(
        from_role=from_role,
        to_role=to_role,
        sender_user_id=sender_user_id,
        topic=topic,
        question=question,
        status="pending",
    )
    session.add(inquiry)
    await session.flush()
    return inquiry


async def get_inquiry(
    session: AsyncSession, inquiry_id: int
) -> CabinetInquiry | None:
    return await session.get(CabinetInquiry, inquiry_id)


async def answer_inquiry(
    session: AsyncSession, inquiry_id: int, response: str
) -> bool:
    """پاسخ به استعلام اطلاعات توسط ارگان مقصد."""
    inquiry = await get_inquiry(session, inquiry_id)
    if inquiry is None:
        return False
    inquiry.response = response
    inquiry.status = "answered"
    inquiry.answered_at = _utcnow()
    await session.flush()
    return True


async def list_inquiries_for_role(
    session: AsyncSession, role_key: str, limit: int = 15
) -> list[CabinetInquiry]:
    """فهرست استعلام‌های دریافتی یا ارسالی این مقام."""
    result = await session.execute(
        select(CabinetInquiry)
        .where(
            or_(
                CabinetInquiry.to_role == role_key,
                CabinetInquiry.from_role == role_key,
            )
        )
        .order_by(CabinetInquiry.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ============================================================
#  بازرسی ویژه دادستان کل (Inspections)
# ============================================================


async def create_inspection(
    session: AsyncSession,
    target_role: str,
    target_user_id: int | None,
    initiated_by_user_id: int,
    reason: str,
    findings: str | None = None,
) -> CabinetInspection:
    """ثبت پرونده بازرسی ویژه از یک وزارتخانه یا مقام."""
    inspection = CabinetInspection(
        target_role=target_role,
        target_user_id=target_user_id,
        initiated_by_user_id=initiated_by_user_id,
        reason=reason,
        findings=findings,
        status="open",
    )
    session.add(inspection)
    await session.flush()
    return inspection


async def list_inspections(
    session: AsyncSession, target_role: str | None = None, limit: int = 15
) -> list[CabinetInspection]:
    """فهرست پرونده‌های بازرسی قضایی."""
    stmt = select(CabinetInspection)
    if target_role:
        stmt = stmt.where(CabinetInspection.target_role == target_role)
    stmt = stmt.order_by(CabinetInspection.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_inspection(
    session: AsyncSession, inspection_id: int
) -> CabinetInspection | None:
    return await session.get(CabinetInspection, inspection_id)


# ============================================================
#  دیدارها و تماس‌های امن کابینه (Meetings & Calls)
# ============================================================


async def create_meeting(
    session: AsyncSession,
    host_role: str,
    guest_role: str,
    host_user_id: int,
    guest_user_id: int,
    meeting_type: str = "meeting",
) -> CabinetMeeting:
    """ایجاد درخواست دیدار یا تماس امن میان دو مقام."""
    meeting = CabinetMeeting(
        host_role=host_role,
        guest_role=guest_role,
        host_user_id=host_user_id,
        guest_user_id=guest_user_id,
        meeting_type=meeting_type,
        status="pending",
    )
    session.add(meeting)
    await session.flush()
    return meeting


async def get_meeting(
    session: AsyncSession, meeting_id: int
) -> CabinetMeeting | None:
    return await session.get(CabinetMeeting, meeting_id)


async def get_active_meeting_for_user(
    session: AsyncSession, user_id: int
) -> CabinetMeeting | None:
    """بررسی اینکه آیا کاربر هم‌اکنون در دیدار یا تماس فعال است یا خیر."""
    result = await session.execute(
        select(CabinetMeeting).where(
            or_(
                CabinetMeeting.host_user_id == user_id,
                CabinetMeeting.guest_user_id == user_id,
            ),
            CabinetMeeting.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def end_meeting(session: AsyncSession, meeting_id: int) -> bool:
    """پایان دادن به نشست یا تماس امن."""
    meeting = await get_meeting(session, meeting_id)
    if meeting is None:
        return False
    meeting.status = "ended"
    await session.flush()
    return True


# ============================================================
#  لاگ اقدامات رسمی کابینه (Action Logs)
# ============================================================


async def log_action(
    session: AsyncSession,
    role_key: str,
    user_id: int,
    action_type: str,
    description: str,
) -> CabinetActionLog:
    """ثبت یک اقدام اداری، فرمان یا تصمیم کلان در لاگ رسمی کابینه."""
    entry = CabinetActionLog(
        role_key=role_key,
        user_id=user_id,
        action_type=action_type,
        description=description,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_recent_logs(
    session: AsyncSession, role_key: str | None = None, limit: int = 15
) -> list[CabinetActionLog]:
    """فهرست آخرین لاگ‌های اداری و فرامین دولت."""
    stmt = select(CabinetActionLog)
    if role_key:
        stmt = stmt.where(CabinetActionLog.role_key == role_key)
    stmt = stmt.order_by(CabinetActionLog.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
