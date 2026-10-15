"""توابع دسترسی داده (Repository) برای گیم‌مود مقاماتی دولت فدرال آمریکا."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import json
from ...constants import CABINET_DEFAULT_BUDGET, CABINET_ROLES_DATA
from ...enums import CabinetRole
from ..models.cabinet import (
    CabinetActionLog,
    CabinetAgenda,
    CabinetBudgetRequest,
    CabinetCrisis,
    CabinetInquiry,
    CabinetInspection,
    CabinetLeak,
    CabinetMeeting,
    CabinetMember,
    CabinetMemo,
    CabinetOperation,
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
            budget = CABINET_DEFAULT_BUDGET.get(role.value, 10_000.0)
            member = CabinetMember(
                role_key=role.value,
                user_id=None,
                is_active=True,
                approval_rating=50.0,
                political_capital=50,
                allocated_budget=budget,
                leak_suspicion=0,
                efficiency_score=80,
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


# ============================================================
#  شاخص‌های قدرت، سرمایه سیاسی و بودجه (v2.6)
# ============================================================


async def modify_capital(session: AsyncSession, role_key: str, delta: int) -> int:
    """تغییر سرمایه سیاسی یک مقام (بین ۰ تا ۱۰۰). مقدار جدید را برمی‌گرداند."""
    member = await get_member_by_role(session, role_key)
    if not member:
        return 50
    cur = getattr(member, "political_capital", 50) or 50
    new_val = max(0, min(100, cur + delta))
    member.political_capital = new_val
    await session.flush()
    return new_val


async def modify_budget(session: AsyncSession, role_key: str, delta: float) -> float:
    """تغییر بودجه اختصاصی یک وزارتخانه (حداقل ۰)."""
    member = await get_member_by_role(session, role_key)
    if not member:
        return 0.0
    cur = getattr(member, "allocated_budget", 10_000.0) or 10_000.0
    new_val = max(0.0, cur + delta)
    member.allocated_budget = new_val
    await session.flush()
    return new_val


async def modify_leak_suspicion(session: AsyncSession, role_key: str, delta: int) -> int:
    """تغییر شاخص سوءظن افشاگری امنیتی (۰ تا ۱۰۰)."""
    member = await get_member_by_role(session, role_key)
    if not member:
        return 0
    cur = getattr(member, "leak_suspicion", 0) or 0
    new_val = max(0, min(100, cur + delta))
    member.leak_suspicion = new_val
    await session.flush()
    return new_val


async def modify_efficiency(session: AsyncSession, role_key: str, delta: int) -> int:
    """تغییر امتیاز کارآمدی عملکرد (۰ تا ۱۰۰)."""
    member = await get_member_by_role(session, role_key)
    if not member:
        return 80
    cur = getattr(member, "efficiency_score", 80) or 80
    new_val = max(0, min(100, cur + delta))
    member.efficiency_score = new_val
    await session.flush()
    return new_val


# ============================================================
#  زنجیره‌های عملیاتی چندمرحله‌ای (Cabinet Operations - v2.6)
# ============================================================


async def create_operation(
    session: AsyncSession,
    op_type: str,
    title: str,
    initiator_role: str,
    steps: list[dict],
    budget_cost: float = 0.0,
    payload: dict | None = None,
    expires_at: datetime | None = None,
) -> CabinetOperation:
    """ایجاد یک پرونده/عملیات بوروکراتیک جدید در زنجیره تایید."""
    op = CabinetOperation(
        op_type=op_type,
        title=title,
        initiator_role=initiator_role,
        current_step=1,
        steps_json=json.dumps(steps, ensure_ascii=False),
        signed_by_json=json.dumps([], ensure_ascii=False),
        status="PENDING",
        budget_cost=budget_cost,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        created_at=_utcnow(),
        expires_at=expires_at,
    )
    session.add(op)
    await session.flush()
    return op


async def get_operation(session: AsyncSession, op_id: int) -> CabinetOperation | None:
    return await session.get(CabinetOperation, op_id)


async def list_operations(
    session: AsyncSession,
    status: str | None = None,
    role_key: str | None = None,
    page: int = 1,
    limit: int = 10,
    offset: int | None = None,
) -> tuple[list[CabinetOperation], int]:
    """فهرست پرونده‌های عملیاتی با صفحه‌بندی ۱۰تایی و تعداد کل صفحات."""
    from sqlalchemy import func
    import math

    stmt_cnt = select(func.count(CabinetOperation.id))
    if status == "ACTIVE":
        stmt_cnt = stmt_cnt.where(
            CabinetOperation.status.in_(
                [
                    CabinetOperationStatus.PENDING.value,
                    CabinetOperationStatus.DOGE_FROZEN.value,
                    CabinetOperationStatus.DOJ_SUSPENDED.value,
                ]
            )
        )
    elif status == "HISTORY":
        stmt_cnt = stmt_cnt.where(
            CabinetOperation.status.in_(
                [
                    CabinetOperationStatus.EXECUTED.value,
                    CabinetOperationStatus.VETOED.value,
                ]
            )
        )
    elif status:
        stmt_cnt = stmt_cnt.where(CabinetOperation.status == status)

    if role_key:
        stmt_cnt = stmt_cnt.where(CabinetOperation.initiator_role == role_key)

    total_count = (await session.execute(stmt_cnt)).scalar() or 0
    total_pages = max(1, math.ceil(total_count / limit))

    if offset is None:
        offset = (page - 1) * limit

    stmt = select(CabinetOperation)
    if status == "ACTIVE":
        stmt = stmt.where(
            CabinetOperation.status.in_(
                [
                    CabinetOperationStatus.PENDING.value,
                    CabinetOperationStatus.DOGE_FROZEN.value,
                    CabinetOperationStatus.DOJ_SUSPENDED.value,
                ]
            )
        )
    elif status == "HISTORY":
        stmt = stmt.where(
            CabinetOperation.status.in_(
                [
                    CabinetOperationStatus.EXECUTED.value,
                    CabinetOperationStatus.VETOED.value,
                ]
            )
        )
    elif status:
        stmt = stmt.where(CabinetOperation.status == status)

    if role_key:
        stmt = stmt.where(CabinetOperation.initiator_role == role_key)

    stmt = stmt.order_by(CabinetOperation.id.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total_pages


async def list_pending_for_role(
    session: AsyncSession,
    role_key: str,
    page: int = 1,
    limit: int = 10,
) -> tuple[list[CabinetOperation], int]:
    """فهرست پرونده‌هایی که نوبت امضای مقام مشخص است."""
    import math

    stmt = select(CabinetOperation).where(
        CabinetOperation.status == CabinetOperationStatus.PENDING.value
    ).order_by(CabinetOperation.id.desc())
    result = await session.execute(stmt)
    all_pending = result.scalars().all()

    matched: list[CabinetOperation] = []
    for op in all_pending:
        try:
            steps = json.loads(op.steps_json)
            if 1 <= op.current_step <= len(steps):
                curr = steps[op.current_step - 1]
                if curr.get("role_key") == role_key:
                    matched.append(op)
        except Exception:
            continue

    total_count = len(matched)
    total_pages = max(1, math.ceil(total_count / limit))
    offset = (page - 1) * limit
    return matched[offset : offset + limit], total_pages


async def count_operations(session: AsyncSession, status: str | None = None) -> int:
    from sqlalchemy import func
    stmt = select(func.count(CabinetOperation.id))
    if status:
        stmt = stmt.where(CabinetOperation.status == status)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def sign_operation_step(
    session: AsyncSession, op_id: int, role_key: str, user_id: int
) -> tuple[CabinetOperation | None, bool]:
    """
    امضای مرحله جاری پرونده توسط مقام مسئول.
    خروجی: (پرونده، آیا کل زنجیره تکمیل شد؟)
    """
    op = await get_operation(session, op_id)
    if not op or op.status != "PENDING":
        return op, False

    steps = json.loads(op.steps_json)
    if op.current_step > len(steps):
        return op, True

    target_step = steps[op.current_step - 1]
    req_role = target_step.get("role")
    if req_role != "any" and req_role != role_key:
        return op, False

    history = json.loads(op.signed_by_json or "[]")
    history.append({
        "step": op.current_step,
        "role": role_key,
        "user_id": user_id,
        "signed_at": _utcnow().isoformat(),
    })
    op.signed_by_json = json.dumps(history, ensure_ascii=False)

    if op.current_step >= len(steps):
        op.status = "COMPLETED"
        await session.flush()
        return op, True
    else:
        op.current_step += 1
        await session.flush()
        return op, False


async def freeze_operation_doge(session: AsyncSession, op_id: int, role_key: str) -> CabinetOperation | None:
    """فریز پرونده به دلیل عدم صرفه اقتصادی توسط DOGE."""
    if role_key != CabinetRole.TECH_EFFICIENCY.value:
        return None
    op = await get_operation(session, op_id)
    if op and op.status == "PENDING":
        op.status = "DOGE_FROZEN"
        await session.flush()
    return op


async def suspend_operation_doj(session: AsyncSession, op_id: int, role_key: str) -> CabinetOperation | None:
    """تعلیق قضایی پرونده به دلیل مغایرت قانونی توسط دادستان کل."""
    if role_key != CabinetRole.ATTORNEY_GENERAL.value:
        return None
    op = await get_operation(session, op_id)
    if op and op.status == "PENDING":
        op.status = "DOJ_SUSPENDED"
        await session.flush()
    return op


async def unfreeze_operation(session: AsyncSession, op_id: int, unfreezer_role: str) -> CabinetOperation | None:
    """شکستن قفل پرونده‌های فریز یا تعلیق‌شده توسط رئیس‌جمهور یا معاون."""
    if unfreezer_role not in [CabinetRole.PRESIDENT.value, CabinetRole.VICE_PRESIDENT.value]:
        return None
    op = await get_operation(session, op_id)
    if op and op.status in ["DOGE_FROZEN", "DOJ_SUSPENDED"]:
        op.status = "PENDING"
        await session.flush()
    return op


async def veto_operation(session: AsyncSession, op_id: int, vetoer_role: str) -> CabinetOperation | None:
    """وتوی یک لایحه یا عملیات توسط رئیس‌جمهور."""
    if vetoer_role != CabinetRole.PRESIDENT.value:
        return None
    op = await get_operation(session, op_id)
    if op and op.status not in ["COMPLETED", "VETOED", "EXPIRED"]:
        op.status = "VETOED"
        await session.flush()
    return op


# ============================================================
#  موتور بحران‌های کابینه (Cabinet Crises - v2.6)
# ============================================================


async def create_crisis(
    session: AsyncSession,
    title: str,
    description: str,
    category: str,
    primary_role: str,
    secondary_role: str,
    severity: int,
    options: list[dict],
    expires_at: datetime,
) -> CabinetCrisis:
    crisis = CabinetCrisis(
        title=title,
        description=description,
        category=category,
        primary_role=primary_role,
        secondary_role=secondary_role,
        severity=severity,
        options_json=json.dumps(options, ensure_ascii=False),
        primary_approved=None,
        secondary_approved=None,
        status="ACTIVE",
        created_at=_utcnow(),
        expires_at=expires_at,
    )
    session.add(crisis)
    await session.flush()
    return crisis


async def get_crisis(session: AsyncSession, crisis_id: int) -> CabinetCrisis | None:
    return await session.get(CabinetCrisis, crisis_id)


async def list_crises(
    session: AsyncSession,
    status: str | None = None,
    page: int = 1,
    limit: int = 10,
    offset: int | None = None,
) -> tuple[list[CabinetCrisis], int]:
    """فهرست بحران‌ها با صفحه‌بندی ۱۰تایی و تعداد کل صفحات."""
    from sqlalchemy import func
    import math

    stmt_cnt = select(func.count(CabinetCrisis.id))
    if status:
        stmt_cnt = stmt_cnt.where(CabinetCrisis.status == status)
    total_count = (await session.execute(stmt_cnt)).scalar() or 0
    total_pages = max(1, math.ceil(total_count / limit))

    if offset is None:
        offset = (page - 1) * limit

    stmt = select(CabinetCrisis)
    if status:
        stmt = stmt.where(CabinetCrisis.status == status)
    stmt = stmt.order_by(CabinetCrisis.id.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total_pages


async def count_crises(session: AsyncSession, status: str | None = None) -> int:
    from sqlalchemy import func
    stmt = select(func.count(CabinetCrisis.id))
    if status:
        stmt = stmt.where(CabinetCrisis.status == status)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def approve_crisis_option(
    session: AsyncSession, crisis_id: int, role_key: str, option_index: int
) -> tuple[CabinetCrisis | None, bool]:
    """ثبت انتخاب راهکار توسط یکی از دو مقام مسئول بحران. در صورت تایید هر دو، بحران حل می‌شود."""
    crisis = await get_crisis(session, crisis_id)
    if not crisis or crisis.status != "ACTIVE":
        return crisis, False

    if role_key == crisis.primary_role:
        crisis.primary_approved = option_index
    elif role_key == crisis.secondary_role:
        crisis.secondary_approved = option_index
    else:
        return crisis, False

    is_resolved = (crisis.primary_approved is not None and crisis.secondary_approved is not None)
    if is_resolved:
        crisis.status = "RESOLVED"

    await session.flush()
    return crisis, is_resolved


# ============================================================
#  درخواست‌های بودجه وزارتخانه‌ها (Cabinet Budget Requests - v2.6)
# ============================================================


async def create_budget_request(
    session: AsyncSession,
    requester_role: str,
    user_id: int,
    amount: float,
    reason: str,
) -> CabinetBudgetRequest:
    req = CabinetBudgetRequest(
        requester_role=requester_role,
        requester_user_id=user_id,
        amount=amount,
        reason=reason,
        status="pending",
        created_at=_utcnow(),
    )
    session.add(req)
    await session.flush()
    return req


async def get_budget_request(
    session: AsyncSession, req_id: int
) -> CabinetBudgetRequest | None:
    return await session.get(CabinetBudgetRequest, req_id)


async def list_budget_requests(
    session: AsyncSession,
    role_key: str | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 10,
    offset: int | None = None,
) -> tuple[list[CabinetBudgetRequest], int]:
    """فهرست درخواست‌های بودجه با فیلتر مقام و صفحه‌بندی ۱۰تایی."""
    from sqlalchemy import func
    import math

    conds = []
    if role_key:
        conds.append(CabinetBudgetRequest.requester_role == role_key)
    if status:
        conds.append(CabinetBudgetRequest.status == status)

    stmt_cnt = select(func.count(CabinetBudgetRequest.id))
    if conds:
        stmt_cnt = stmt_cnt.where(*conds)
    total_count = (await session.execute(stmt_cnt)).scalar() or 0
    total_pages = max(1, math.ceil(total_count / limit))

    if offset is None:
        offset = (page - 1) * limit

    stmt = select(CabinetBudgetRequest)
    if conds:
        stmt = stmt.where(*conds)
    stmt = stmt.order_by(CabinetBudgetRequest.id.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total_pages


async def count_budget_requests(session: AsyncSession, status: str | None = None) -> int:
    from sqlalchemy import func
    stmt = select(func.count(CabinetBudgetRequest.id))
    if status:
        stmt = stmt.where(CabinetBudgetRequest.status == status)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def resolve_budget_request(
    session: AsyncSession,
    req_id: int,
    status: str,
    treasury_notes: str | None = None,
) -> CabinetBudgetRequest | None:
    req = await get_budget_request(session, req_id)
    if req and req.status == "pending":
        req.status = status
        req.treasury_notes = treasury_notes
        req.resolved_at = _utcnow()
        await session.flush()
    return req


# ============================================================
#  اهداف مخفی و افشاگری‌ها (Agendas & Leaks - v2.6)
# ============================================================


async def create_agenda(
    session: AsyncSession,
    role_key: str,
    title: str,
    description: str,
    target_type: str = "general",
    target_value: int = 1,
    reward_capital: int = 15,
    user_id: int = 0,
) -> CabinetAgenda:
    """ایجاد ماموریت محرمانه ۲۴ ساعته برای مقام دولتی."""
    from datetime import timedelta
    now = _utcnow()
    agenda = CabinetAgenda(
        role_key=role_key,
        user_id=user_id,
        title=title,
        description=description,
        reward_capital=reward_capital,
        is_completed=False,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(agenda)
    await session.flush()
    return agenda


async def get_agenda(session: AsyncSession, agenda_id: int) -> CabinetAgenda | None:
    """دریافت ماموریت محرمانه بر اساس شناسه."""
    return await session.get(CabinetAgenda, agenda_id)


async def get_active_agenda(session: AsyncSession, role_key: str) -> CabinetAgenda | None:
    """دریافت ماموریت محرمانه فعال مقام بر اساس سمت."""
    now = _utcnow()
    stmt = (
        select(CabinetAgenda)
        .where(
            CabinetAgenda.role_key == role_key,
            CabinetAgenda.expires_at > now,
        )
        .order_by(CabinetAgenda.id.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def get_or_create_agenda(
    session: AsyncSession, role_key: str, user_id: int
) -> CabinetAgenda:
    """دریافت هدف فعال یا تولید ماموریت جدید ۲۴ ساعته برای مقام."""
    now = _utcnow()
    result = await session.execute(
        select(CabinetAgenda).where(
            CabinetAgenda.role_key == role_key,
            CabinetAgenda.user_id == user_id,
            CabinetAgenda.expires_at > now,
            CabinetAgenda.is_completed == False,
        )
    )
    agenda = result.scalar_one_or_none()
    if agenda:
        return agenda

    import random
    from datetime import timedelta
    templates = [
        ("امضای پرونده در زنجیره بوروکراسی", "امروز حداقل ۱ پرونده زنجیره‌ای را در کارتابل امضا کن."),
        ("ارتقای بهره‌وری و کارآمدی وزارتخانه", "امتیاز کارآمدی وزارتخانه خود را بالای ۸۵ حفظ کن."),
        ("مدیریت بحران‌های ملی", "در حل و مهار یک بحران فعال فدرال مشارکت داشته باش."),
        ("مکاتبات و هماهنگی درون‌سازمانی", "یک یادداشت رسمی یا استعلام به ارگان‌های دیگر ارسال کن."),
        ("انضباط مالی و جذب منابع", "درخواست بودجه ثبت کن یا تراز مالی را مثبت نگه دار."),
    ]
    title, desc = random.choice(templates)
    agenda = CabinetAgenda(
        role_key=role_key,
        user_id=user_id,
        title=title,
        description=desc,
        reward_capital=15,
        is_completed=False,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(agenda)
    await session.flush()
    return agenda


async def complete_agenda(session: AsyncSession, agenda_id: int) -> CabinetAgenda | None:
    agenda = await session.get(CabinetAgenda, agenda_id)
    if agenda and not agenda.is_completed:
        agenda.is_completed = True
        await session.flush()
    return agenda


async def create_leak(
    session: AsyncSession,
    leaker_role: str,
    leaker_user_id: int,
    target_role: str,
    headline: str,
    content: str,
) -> CabinetLeak:
    leak = CabinetLeak(
        leaker_role=leaker_role,
        leaker_user_id=leaker_user_id,
        target_role=target_role,
        leak_headline=headline,
        leak_content=content,
        is_discovered=False,
        created_at=_utcnow(),
    )
    session.add(leak)
    await session.flush()
    return leak


async def get_leak(session: AsyncSession, leak_id: int) -> CabinetLeak | None:
    return await session.get(CabinetLeak, leak_id)


async def list_leaks(
    session: AsyncSession,
    page: int = 1,
    limit: int = 10,
    offset: int | None = None,
) -> tuple[list[CabinetLeak], int]:
    """فهرست درزهای اطلاعاتی با صفحه‌بندی ۱۰تایی و تعداد کل صفحات."""
    from sqlalchemy import func
    import math

    stmt_cnt = select(func.count(CabinetLeak.id))
    total_count = (await session.execute(stmt_cnt)).scalar() or 0
    total_pages = max(1, math.ceil(total_count / limit))

    if offset is None:
        offset = (page - 1) * limit

    stmt = select(CabinetLeak).order_by(CabinetLeak.id.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total_pages


async def discover_leak(
    session: AsyncSession, leak_id: int, discoverer_role: str
) -> CabinetLeak | None:
    leak = await session.get(CabinetLeak, leak_id)
    if leak:
        leak.is_discovered = True
        leak.discovered_by_role = discoverer_role
        await session.flush()
    return leak

