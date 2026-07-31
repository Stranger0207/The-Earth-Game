"""لایه‌ی دسترسی داده برای برنامه‌ی هسته‌ای (v1.10.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import (
    NuclearFacilityStatus,
    NuclearFacilityType,
    NuclearTechType,
    WarheadStatus,
)
from ..models.nuclear import (
    NuclearFacility,
    NuclearInspection,
    NuclearProgram,
    NuclearTech,
    NuclearTest,
    NuclearWarhead,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  برنامه‌ی هسته‌ای
# ============================================================


async def get_program(session: AsyncSession, country_id: int) -> NuclearProgram | None:
    """برنامه‌ی هسته‌ای یک کشور (یا None اگر آغاز نشده باشد)."""
    stmt = select(NuclearProgram).where(NuclearProgram.country_id == country_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def create_program(session: AsyncSession, country_id: int) -> NuclearProgram:
    """ساخت ردیف برنامه‌ی هسته‌ای برای یک کشور."""
    program = NuclearProgram(country_id=country_id)
    session.add(program)
    await session.flush()
    return program


async def list_active_programs(session: AsyncSession) -> Sequence[NuclearProgram]:
    """همه‌ی برنامه‌های هسته‌ای آغازشده (برای پردازش زمان‌بند)."""
    stmt = select(NuclearProgram).where(NuclearProgram.phase > 0)
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_discovered_programs(session: AsyncSession) -> Sequence[NuclearProgram]:
    """برنامه‌های افشاشده (برای گزارش آژانس و امکان تحریم)."""
    stmt = select(NuclearProgram).where(NuclearProgram.is_discovered == True)  # noqa: E712
    res = await session.execute(stmt)
    return res.scalars().all()


# ============================================================
#  فناوری‌ها
# ============================================================


async def get_tech(
    session: AsyncSession, country_id: int, tech_type: NuclearTechType | str
) -> NuclearTech | None:
    """رکورد یک فناوری برای یک کشور (در حال تحقیق یا تکمیل‌شده)."""
    value = tech_type.value if isinstance(tech_type, NuclearTechType) else tech_type
    stmt = select(NuclearTech).where(
        NuclearTech.country_id == country_id, NuclearTech.tech_type == value
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_techs(session: AsyncSession, country_id: int) -> Sequence[NuclearTech]:
    """فهرست همه‌ی فناوری‌های یک کشور."""
    stmt = select(NuclearTech).where(NuclearTech.country_id == country_id)
    res = await session.execute(stmt)
    return res.scalars().all()


async def has_tech(
    session: AsyncSession, country_id: int, tech_type: NuclearTechType | str
) -> bool:
    """آیا فناوری موردنظر تکمیل شده است؟"""
    tech = await get_tech(session, country_id, tech_type)
    return tech is not None and tech.is_done


async def create_tech(session: AsyncSession, tech: NuclearTech) -> NuclearTech:
    """ثبت شروع تحقیق یک فناوری."""
    session.add(tech)
    await session.flush()
    return tech


async def list_pending_techs(session: AsyncSession) -> Sequence[NuclearTech]:
    """فناوری‌هایی که تحقیق‌شان تمام نشده (برای زمان‌بند)."""
    stmt = select(NuclearTech).where(NuclearTech.is_done == False)  # noqa: E712
    res = await session.execute(stmt)
    return res.scalars().all()


# ============================================================
#  تأسیسات هسته‌ای
# ============================================================


async def create_facility(
    session: AsyncSession, facility: NuclearFacility
) -> NuclearFacility:
    """ثبت یک تأسیسات هسته‌ای جدید."""
    session.add(facility)
    await session.flush()
    return facility


async def get_facility(
    session: AsyncSession, facility_id: int
) -> NuclearFacility | None:
    """دریافت یک تأسیسات با شناسه."""
    stmt = select(NuclearFacility).where(NuclearFacility.id == facility_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_facilities(
    session: AsyncSession, country_id: int
) -> Sequence[NuclearFacility]:
    """همه‌ی تأسیسات هسته‌ای یک کشور (به‌جز نابودشده‌ها)."""
    stmt = (
        select(NuclearFacility)
        .where(
            NuclearFacility.country_id == country_id,
            NuclearFacility.status != NuclearFacilityStatus.DESTROYED.value,
        )
        .order_by(NuclearFacility.id)
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_active_facilities(
    session: AsyncSession, country_id: int, facility_type: NuclearFacilityType | str
) -> Sequence[NuclearFacility]:
    """تأسیسات فعال یا آسیب‌دیده‌ی یک نوع مشخص (بازدهی دارند)."""
    value = (
        facility_type.value
        if isinstance(facility_type, NuclearFacilityType)
        else facility_type
    )
    stmt = select(NuclearFacility).where(
        NuclearFacility.country_id == country_id,
        NuclearFacility.facility_type == value,
        NuclearFacility.status.in_(
            [NuclearFacilityStatus.ACTIVE.value, NuclearFacilityStatus.DAMAGED.value]
        ),
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def count_facilities_by_type(
    session: AsyncSession, country_id: int, facility_type: NuclearFacilityType | str
) -> int:
    """تعداد تأسیسات یک نوع (برای سقف تعداد) — نابودشده‌ها شمرده نمی‌شوند."""
    value = (
        facility_type.value
        if isinstance(facility_type, NuclearFacilityType)
        else facility_type
    )
    stmt = select(func.count(NuclearFacility.id)).where(
        NuclearFacility.country_id == country_id,
        NuclearFacility.facility_type == value,
        NuclearFacility.status != NuclearFacilityStatus.DESTROYED.value,
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def count_builds_since(
    session: AsyncSession, country_id: int, hours: float
) -> int:
    """تعداد تأسیسات هسته‌ای ساخته‌شده در پنجره‌ی زمانی اخیر (سقف ساخت)."""
    since = _utcnow() - timedelta(hours=hours)
    stmt = select(func.count(NuclearFacility.id)).where(
        NuclearFacility.country_id == country_id,
        NuclearFacility.created_at >= since,
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def list_building_facilities(session: AsyncSession) -> Sequence[NuclearFacility]:
    """تأسیساتی که در حال ساخت هستند (برای زمان‌بند)."""
    stmt = select(NuclearFacility).where(
        NuclearFacility.status == NuclearFacilityStatus.BUILDING.value
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def enrichment_capacity(session: AsyncSession, country_id: int) -> int:
    """ظرفیت کل سانتریفیوژ بر اساس سالن‌های غنی‌سازی فعال."""
    from ...constants import ENRICHMENT_HALL_CENTRIFUGE_CAPACITY

    halls = await list_active_facilities(
        session, country_id, NuclearFacilityType.ENRICHMENT_HALL
    )
    # سالن آسیب‌دیده ظرفیتش به نسبت سلامت سازه کاهش می‌یابد
    total = 0.0
    for hall in halls:
        total += ENRICHMENT_HALL_CENTRIFUGE_CAPACITY * (hall.integrity_pct / 100.0)
    return int(total)


# ============================================================
#  کلاهک‌ها
# ============================================================


async def create_warhead(
    session: AsyncSession, warhead: NuclearWarhead
) -> NuclearWarhead:
    """ثبت شروع مونتاژ یک کلاهک."""
    session.add(warhead)
    await session.flush()
    return warhead


async def get_warhead(session: AsyncSession, warhead_id: int) -> NuclearWarhead | None:
    """دریافت یک کلاهک با شناسه."""
    stmt = select(NuclearWarhead).where(NuclearWarhead.id == warhead_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_warheads(
    session: AsyncSession, country_id: int
) -> Sequence[NuclearWarhead]:
    """زرادخانه‌ی یک کشور (کلاهک‌های مصرف‌نشده)."""
    stmt = (
        select(NuclearWarhead)
        .where(
            NuclearWarhead.country_id == country_id,
            NuclearWarhead.status != WarheadStatus.TESTED.value,
        )
        .order_by(NuclearWarhead.id)
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def count_ready_warheads(session: AsyncSession, country_id: int) -> int:
    """تعداد کلاهک‌های آماده (مونتاژشده یا نصب‌شده) — پایه‌ی بازدارندگی."""
    stmt = select(func.count(NuclearWarhead.id)).where(
        NuclearWarhead.country_id == country_id,
        NuclearWarhead.status.in_(
            [WarheadStatus.ASSEMBLED.value, WarheadStatus.MOUNTED.value]
        ),
    )
    res = await session.execute(stmt)
    return res.scalar() or 0


async def list_assembling_warheads(session: AsyncSession) -> Sequence[NuclearWarhead]:
    """کلاهک‌های در حال مونتاژ (برای زمان‌بند)."""
    stmt = select(NuclearWarhead).where(
        NuclearWarhead.status == WarheadStatus.ASSEMBLING.value
    )
    res = await session.execute(stmt)
    return res.scalars().all()


# ============================================================
#  آزمایش هسته‌ای
# ============================================================


async def create_test(session: AsyncSession, test: NuclearTest) -> NuclearTest:
    """ثبت یک آزمایش هسته‌ای."""
    session.add(test)
    await session.flush()
    return test


async def list_pending_tests(session: AsyncSession) -> Sequence[NuclearTest]:
    """آزمایش‌های در انتظار اجرا (برای زمان‌بند)."""
    stmt = select(NuclearTest).where(NuclearTest.status == "pending")
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_tests(session: AsyncSession, country_id: int) -> Sequence[NuclearTest]:
    """تاریخ آزمایش‌های هسته‌ای یک کشور."""
    stmt = (
        select(NuclearTest)
        .where(NuclearTest.country_id == country_id)
        .order_by(NuclearTest.id.desc())
    )
    res = await session.execute(stmt)
    return res.scalars().all()


# ============================================================
#  بازرسی بین‌المللی
# ============================================================


async def create_inspection(
    session: AsyncSession, inspection: NuclearInspection
) -> NuclearInspection:
    """ثبت درخواست بازرسی."""
    session.add(inspection)
    await session.flush()
    return inspection


async def get_inspection(
    session: AsyncSession, inspection_id: int
) -> NuclearInspection | None:
    """دریافت یک درخواست بازرسی."""
    stmt = select(NuclearInspection).where(NuclearInspection.id == inspection_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_pending_inspections(
    session: AsyncSession, target_id: int
) -> Sequence[NuclearInspection]:
    """درخواست‌های بازرسی بی‌پاسخ روی یک کشور."""
    stmt = select(NuclearInspection).where(
        NuclearInspection.target_id == target_id,
        NuclearInspection.status == "pending",
    )
    res = await session.execute(stmt)
    return res.scalars().all()
