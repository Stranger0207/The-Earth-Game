"""توابع دسترسی داده برای دیپلماسی (قرارداد، تماس، دیدار، تحریم)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import DiplomacyStatus
from ..models import (
    Contract,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    PhoneCall,
    PhoneCallMessage,
    Sanction,
)

# ------------------------- قراردادها -------------------------


async def add_contract(session: AsyncSession, contract: Contract) -> Contract:
    session.add(contract)
    await session.flush()
    return contract


async def get_contract(session: AsyncSession, contract_id: int) -> Contract | None:
    return await session.get(Contract, contract_id)


async def list_contracts_for_country(
    session: AsyncSession, country_id: int, only_active: bool = True
) -> list[Contract]:
    """فهرست قراردادهای یک کشور (به‌عنوان طرف اول یا دوم)."""
    stmt = select(Contract).where(
        or_(Contract.country_a == country_id, Contract.country_b == country_id)
    )
    if only_active:
        stmt = stmt.where(Contract.status == DiplomacyStatus.ACTIVE)
    result = await session.execute(stmt.order_by(Contract.created_at.desc()))
    return list(result.scalars().all())


# ------------------------- تماس تلفنی -------------------------


async def add_call(session: AsyncSession, call: PhoneCall) -> PhoneCall:
    session.add(call)
    await session.flush()
    return call


async def get_call(session: AsyncSession, call_id: int) -> PhoneCall | None:
    return await session.get(PhoneCall, call_id)


async def get_active_call_for_country(
    session: AsyncSession, country_id: int
) -> PhoneCall | None:
    """تماس فعالی که این کشور در آن درگیر است (در صورت چند مورد، جدیدترین)."""
    # نکته: به‌جای scalar_one_or_none از first استفاده می‌کنیم تا اگر به هر دلیل
    # بیش از یک تماس فعال برای یک کشور وجود داشته باشد، به‌جای کرش، جدیدترین برگردد.
    result = await session.execute(
        select(PhoneCall)
        .where(
            PhoneCall.status == DiplomacyStatus.ACTIVE,
            or_(
                PhoneCall.caller_country == country_id,
                PhoneCall.callee_country == country_id,
            ),
        )
        .order_by(PhoneCall.id.desc())
    )
    return result.scalars().first()


async def add_call_message(
    session: AsyncSession, call_id: int, sender_country: int, text: str
) -> PhoneCallMessage:
    msg = PhoneCallMessage(
        call_id=call_id, sender_country=sender_country, text=text
    )
    session.add(msg)
    await session.flush()
    return msg


# ------------------------- دیدار حضوری -------------------------


async def add_meeting(session: AsyncSession, meeting: Meeting) -> Meeting:
    session.add(meeting)
    await session.flush()
    return meeting


async def get_meeting(session: AsyncSession, meeting_id: int) -> Meeting | None:
    return await session.get(Meeting, meeting_id)


async def get_active_meeting_for_country(
    session: AsyncSession, country_id: int
) -> Meeting | None:
    """دیدار فعالی که این کشور در آن درگیر است (در صورت چند مورد، جدیدترین)."""
    # نکته: first به‌جای scalar_one_or_none تا چند دیدار فعالِ هم‌زمان کرش ندهد.
    result = await session.execute(
        select(Meeting)
        .where(
            Meeting.status == DiplomacyStatus.ACTIVE,
            or_(
                Meeting.traveler_country == country_id,
                Meeting.host_country == country_id,
            ),
        )
        .order_by(Meeting.id.desc())
    )
    return result.scalars().first()


# ------------------------- تحریم -------------------------


async def add_sanction(session: AsyncSession, sanction: Sanction) -> Sanction:
    session.add(sanction)
    await session.flush()
    return sanction


async def list_sanctions_against(
    session: AsyncSession, country_id: int
) -> list[Sanction]:
    """تحریم‌های فعال علیه یک کشور (دیگران مرا تحریم کرده‌اند)."""
    result = await session.execute(
        select(Sanction).where(
            Sanction.to_country == country_id, Sanction.active.is_(True)
        )
    )
    return list(result.scalars().all())


async def list_sanctions_by(
    session: AsyncSession, country_id: int
) -> list[Sanction]:
    """تحریم‌های فعالی که این کشور وضع کرده است (v1.7)."""
    result = await session.execute(
        select(Sanction).where(
            Sanction.from_country == country_id, Sanction.active.is_(True)
        )
    )
    return list(result.scalars().all())


async def get_sanction(session: AsyncSession, sanction_id: int) -> Sanction | None:
    return await session.get(Sanction, sanction_id)


async def deactivate_sanction(session: AsyncSession, sanction_id: int) -> Sanction | None:
    """لغو (غیرفعال‌سازی) یک تحریم (v1.7)."""
    sanction = await session.get(Sanction, sanction_id)
    if sanction is not None:
        sanction.active = False
    return sanction


# ------------------------- دیدار چندجانبه -------------------------


async def add_group_meeting(
    session: AsyncSession, meeting: GroupMeeting
) -> GroupMeeting:
    session.add(meeting)
    await session.flush()
    return meeting


async def get_group_meeting(
    session: AsyncSession, meeting_id: int
) -> GroupMeeting | None:
    return await session.get(GroupMeeting, meeting_id)


async def add_group_participant(
    session: AsyncSession, meeting_id: int, country_id: int
) -> GroupMeetingParticipant:
    participant = GroupMeetingParticipant(
        meeting_id=meeting_id, country_id=country_id
    )
    session.add(participant)
    await session.flush()
    return participant


async def list_group_participants(
    session: AsyncSession, meeting_id: int
) -> list[GroupMeetingParticipant]:
    result = await session.execute(
        select(GroupMeetingParticipant).where(
            GroupMeetingParticipant.meeting_id == meeting_id
        )
    )
    return list(result.scalars().all())


async def get_group_participant(
    session: AsyncSession, meeting_id: int, country_id: int
) -> GroupMeetingParticipant | None:
    result = await session.execute(
        select(GroupMeetingParticipant).where(
            GroupMeetingParticipant.meeting_id == meeting_id,
            GroupMeetingParticipant.country_id == country_id,
        )
    )
    return result.scalar_one_or_none()


async def get_active_group_meeting_for_country(
    session: AsyncSession, country_id: int
) -> GroupMeeting | None:
    """نشست چندجانبه‌ی فعالی که این کشور (میزبان یا شرکت‌کننده‌ی پذیرفته) در آن حضور دارد."""
    # نکته: first به‌جای scalar_one_or_none تا چند نشست فعالِ هم‌زمان کرش ندهد.
    # به‌عنوان میزبان
    result = await session.execute(
        select(GroupMeeting)
        .where(
            GroupMeeting.status == DiplomacyStatus.ACTIVE,
            GroupMeeting.host_country == country_id,
        )
        .order_by(GroupMeeting.id.desc())
    )
    gm = result.scalars().first()
    if gm is not None:
        return gm
    # به‌عنوان شرکت‌کننده‌ی پذیرفته
    result = await session.execute(
        select(GroupMeeting)
        .join(GroupMeetingParticipant, GroupMeetingParticipant.meeting_id == GroupMeeting.id)
        .where(
            GroupMeeting.status == DiplomacyStatus.ACTIVE,
            GroupMeetingParticipant.country_id == country_id,
            GroupMeetingParticipant.response == DiplomacyStatus.ACTIVE,
        )
        .order_by(GroupMeeting.id.desc())
    )
    return result.scalars().first()


async def get_committed_group_meeting_for_country(
    session: AsyncSession, country_id: int
) -> GroupMeeting | None:
    """
    نشست چندجانبه‌ای که کشور به آن «متعهد» است حتی اگر هنوز رسماً ACTIVE نشده باشد:
    شرکت‌کننده‌ای که دعوت را پذیرفته (response=ACTIVE) و در حال سفر به میزبان است،
    در نشستی که هنوز پایان/لغو نشده (PENDING یا ACTIVE). (v1.9 — جلوگیری از پذیرش سفر دوم در پرواز)
    """
    result = await session.execute(
        select(GroupMeeting)
        .join(GroupMeetingParticipant, GroupMeetingParticipant.meeting_id == GroupMeeting.id)
        .where(
            GroupMeeting.status.in_([DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE]),
            GroupMeetingParticipant.country_id == country_id,
            GroupMeetingParticipant.response == DiplomacyStatus.ACTIVE,
        )
        .order_by(GroupMeeting.id.desc())
    )
    return result.scalars().first()


async def get_active_engagement_label(
    session: AsyncSession, country_id: int
) -> str | None:
    """
    اگر کشور در یک تماس/دیدار/نشست فعال یا در حال سفر به نشست درگیر باشد، توضیح فارسی آن را
    برمی‌گرداند؛ در غیر این صورت None. مبنای «سیستم انحصار»: یک کشور هم‌زمان فقط یک نشست فعال دارد.
    """
    if await get_active_call_for_country(session, country_id) is not None:
        return "یک تماس تلفنی فعال"
    if await get_active_meeting_for_country(session, country_id) is not None:
        return "یک دیدار حضوری فعال"
    if await get_active_group_meeting_for_country(session, country_id) is not None:
        return "یک نشست چندجانبه‌ی فعال"
    # شرکت‌کننده‌ای که نشست چندجانبه را پذیرفته و در حال سفر است (نشست هنوز PENDING)
    if await get_committed_group_meeting_for_country(session, country_id) is not None:
        return "یک نشست چندجانبه‌ی در حال سفر/برگزاری"
    return None


async def group_member_country_ids(
    session: AsyncSession, meeting: GroupMeeting
) -> list[int]:
    """فهرست آی‌دی کشورهای حاضر در نشست (میزبان + شرکت‌کننده‌های پذیرفته)."""
    ids = [meeting.host_country]
    participants = await list_group_participants(session, meeting.id)
    ids += [p.country_id for p in participants if p.response == DiplomacyStatus.ACTIVE]
    return ids
