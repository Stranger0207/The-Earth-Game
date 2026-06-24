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
    """تماس فعالی که این کشور در آن درگیر است."""
    result = await session.execute(
        select(PhoneCall).where(
            PhoneCall.status == DiplomacyStatus.ACTIVE,
            or_(
                PhoneCall.caller_country == country_id,
                PhoneCall.callee_country == country_id,
            ),
        )
    )
    return result.scalar_one_or_none()


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
    """دیدار فعالی که این کشور در آن درگیر است."""
    result = await session.execute(
        select(Meeting).where(
            Meeting.status == DiplomacyStatus.ACTIVE,
            or_(
                Meeting.traveler_country == country_id,
                Meeting.host_country == country_id,
            ),
        )
    )
    return result.scalar_one_or_none()


# ------------------------- تحریم -------------------------


async def add_sanction(session: AsyncSession, sanction: Sanction) -> Sanction:
    session.add(sanction)
    await session.flush()
    return sanction


async def list_sanctions_against(
    session: AsyncSession, country_id: int
) -> list[Sanction]:
    """تحریم‌های فعال علیه یک کشور."""
    result = await session.execute(
        select(Sanction).where(
            Sanction.to_country == country_id, Sanction.active.is_(True)
        )
    )
    return list(result.scalars().all())


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
    # به‌عنوان میزبان
    result = await session.execute(
        select(GroupMeeting).where(
            GroupMeeting.status == DiplomacyStatus.ACTIVE,
            GroupMeeting.host_country == country_id,
        )
    )
    gm = result.scalar_one_or_none()
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
    )
    return result.scalar_one_or_none()


async def group_member_country_ids(
    session: AsyncSession, meeting: GroupMeeting
) -> list[int]:
    """فهرست آی‌دی کشورهای حاضر در نشست (میزبان + شرکت‌کننده‌های پذیرفته)."""
    ids = [meeting.host_country]
    participants = await list_group_participants(session, meeting.id)
    ids += [p.country_id for p in participants if p.response == DiplomacyStatus.ACTIVE]
    return ids
