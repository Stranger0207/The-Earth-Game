"""
ریپازیتوری سازمان ملل متحد (UN)، مجمع عمومی، صف سخنرانی، دیوان بین‌المللی دادگستری (ICJ) و قطعنامه‌ها.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.united_nations import (
    CourtParty,
    InternationalCourtCase,
    UNAssemblyParticipant,
    UNAssemblySession,
    UNResolution,
    UNResolutionVote,
    UNSpeechQueue,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  اجلاس مجمع عمومی (UN General Assembly)
# ============================================================


async def get_active_session(session: AsyncSession) -> UNAssemblySession | None:
    """دریافت جلسه فعال یا در انتظار مجمع عمومی (در هر زمان حداکثر یک اجلاس فعال)."""
    res = await session.execute(
        select(UNAssemblySession)
        .where(UNAssemblySession.status.in_(["pending", "active"]))
        .order_by(UNAssemblySession.id.desc())
        .limit(1)
    )
    return res.scalars().first()


async def get_session(session: AsyncSession, session_id: int) -> UNAssemblySession | None:
    """دریافت مشخصات یک جلسه با شناسه."""
    return await session.get(UNAssemblySession, session_id)


async def get_latest_session(session: AsyncSession) -> UNAssemblySession | None:
    """دریافت آخرین جلسه مجمع عمومی بدون در نظر گرفتن وضعیت."""
    res = await session.execute(
        select(UNAssemblySession).order_by(UNAssemblySession.id.desc()).limit(1)
    )
    return res.scalars().first()


async def create_session(
    session: AsyncSession, un_session: UNAssemblySession
) -> UNAssemblySession:
    """ایجاد یک دوره‌ی جدید اجلاس مجمع عمومی."""
    session.add(un_session)
    await session.flush()
    return un_session


async def close_session(session: AsyncSession, session_id: int) -> None:
    """پایان دادن رسمی به اجلاس سالانه مجمع عمومی."""
    s = await get_session(session, session_id)
    if s:
        s.status = "closed"
        s.ended_at = _utcnow()
        s.current_speaker_country_id = None
        s.speech_ends_at = None
        s.voting_active = False

        parts = await list_participants(session, session_id)
        for p in parts:
            if p.status == "in_flight":
                p.status = "left"
            elif p.status == "inside_hall":
                p.status = "in_new_york"

        await session.flush()


# ============================================================
#  مشارکت‌کنندگان و حضور در نیویورک / تالار مجمع
# ============================================================


async def add_participant(
    session: AsyncSession, participant: UNAssemblyParticipant
) -> UNAssemblyParticipant:
    """افزودن یا بازنشانی مشارکت‌کننده در جلسه مجمع."""
    existing = await get_participant(session, participant.session_id, participant.country_id)
    if existing:
        existing.status = participant.status
        if participant.travel_eta is not None:
            existing.travel_eta = participant.travel_eta
        if participant.joined_hall_at is not None:
            existing.joined_hall_at = participant.joined_hall_at
        if participant.walkout is not None:
            existing.walkout = participant.walkout
        await session.flush()
        return existing
    session.add(participant)
    await session.flush()
    return participant


async def get_participant(
    session: AsyncSession, session_id: int, country_id: int
) -> UNAssemblyParticipant | None:
    """دریافت اطلاعات حضور یک کشور در یک جلسه خاص."""
    res = await session.execute(
        select(UNAssemblyParticipant).where(
            UNAssemblyParticipant.session_id == session_id,
            UNAssemblyParticipant.country_id == country_id,
        )
    )
    return res.scalars().first()


async def get_active_participant_for_country(
    session: AsyncSession, country_id: int
) -> UNAssemblyParticipant | None:
    """بررسی اینکه آیا کشور هم‌اکنون در پرواز، در نیویورک یا داخل تالار است یا خیر."""
    active_s = await get_active_session(session)
    if not active_s:
        return None
    res = await session.execute(
        select(UNAssemblyParticipant).where(
            UNAssemblyParticipant.session_id == active_s.id,
            UNAssemblyParticipant.country_id == country_id,
            UNAssemblyParticipant.status.in_(["in_flight", "in_new_york", "inside_hall"]),
        )
    )
    return res.scalars().first()


async def list_participants(
    session: AsyncSession, session_id: int
) -> list[UNAssemblyParticipant]:
    """لیست تمام شرکت‌کنندگان یک جلسه مجمع."""
    res = await session.execute(
        select(UNAssemblyParticipant).where(
            UNAssemblyParticipant.session_id == session_id
        )
    )
    return list(res.scalars().all())


async def list_participants_by_status(
    session: AsyncSession, session_id: int, status: str
) -> list[UNAssemblyParticipant]:
    """لیست شرکت‌کنندگان بر اساس موقعیت مکانی (مثلاً inside_hall)."""
    res = await session.execute(
        select(UNAssemblyParticipant).where(
            UNAssemblyParticipant.session_id == session_id,
            UNAssemblyParticipant.status == status,
        )
    )
    return list(res.scalars().all())


# ============================================================
#  صف سخنرانی ۵ دقیقه‌ای (Speech Queue)
# ============================================================


async def add_speech_request(
    session: AsyncSession, queue_item: UNSpeechQueue
) -> UNSpeechQueue:
    """افزودن کشور به انتهای صف سخنرانی تالار مجمع عمومی."""
    # اگر قبلاً در وضعیت waiting یا speaking بوده باشد، دوباره اضافه نمی‌شود
    existing = await session.execute(
        select(UNSpeechQueue).where(
            UNSpeechQueue.session_id == queue_item.session_id,
            UNSpeechQueue.country_id == queue_item.country_id,
            UNSpeechQueue.status.in_(["waiting", "speaking"]),
        )
    )
    ex = existing.scalars().first()
    if ex:
        return ex
    session.add(queue_item)
    await session.flush()
    return queue_item


async def get_next_speaker(
    session: AsyncSession, session_id: int
) -> UNSpeechQueue | None:
    """دریافت نفر بعدی در صف سخنرانی بر اساس زمان ثبت اعلام حضور (FIFO)."""
    res = await session.execute(
        select(UNSpeechQueue)
        .where(
            UNSpeechQueue.session_id == session_id,
            UNSpeechQueue.status == "waiting",
        )
        .order_by(UNSpeechQueue.requested_at.asc())
        .limit(1)
    )
    return res.scalars().first()


async def get_speech_queue(
    session: AsyncSession, session_id: int
) -> list[UNSpeechQueue]:
    """دریافت کل صف سخنرانی در انتظار."""
    res = await session.execute(
        select(UNSpeechQueue)
        .where(
            UNSpeechQueue.session_id == session_id,
            UNSpeechQueue.status == "waiting",
        )
        .order_by(UNSpeechQueue.requested_at.asc())
    )
    return list(res.scalars().all())


async def get_active_speech(
    session: AsyncSession, session_id: int
) -> UNSpeechQueue | None:
    """سخنرانی فعلی که تریبون در اختیار اوست."""
    res = await session.execute(
        select(UNSpeechQueue)
        .where(
            UNSpeechQueue.session_id == session_id,
            UNSpeechQueue.status == "speaking",
        )
        .limit(1)
    )
    return res.scalars().first()


async def append_speech_transcript(
    session: AsyncSession, queue_id: int, text: str
) -> None:
    """افزودن متن/کپشن جدید سخنران به رونوشت کامل سخنرانی جهت تحلیل هوش مصنوعی."""
    q = await session.get(UNSpeechQueue, queue_id)
    if q:
        sep = "\n" if q.speech_transcript else ""
        q.speech_transcript = f"{q.speech_transcript}{sep}{text}".strip()
        await session.flush()


async def set_speaker_done(session: AsyncSession, queue_id: int) -> None:
    """پایان یافتن نوبت سخنرانی یک کشور."""
    q = await session.get(UNSpeechQueue, queue_id)
    if q:
        q.status = "done"
        q.ends_at = _utcnow()
        await session.flush()


# ============================================================
#  دیوان بین‌المللی دادگستری (دادگاه لاهه - ICJ)
# ============================================================


async def create_court_case(
    session: AsyncSession, case: InternationalCourtCase
) -> InternationalCourtCase:
    """ثبت دادخواست جدید در دیوان دادگستری."""
    session.add(case)
    await session.flush()
    return case


async def get_court_case(
    session: AsyncSession, case_id: int
) -> InternationalCourtCase | None:
    """دریافت پرونده با شناسه عددی."""
    return await session.get(InternationalCourtCase, case_id)


async def get_court_case_by_number(
    session: AsyncSession, case_num: str
) -> InternationalCourtCase | None:
    """دریافت پرونده با شماره یکتای پرونده."""
    res = await session.execute(
        select(InternationalCourtCase).where(InternationalCourtCase.case_number == case_num)
    )
    return res.scalars().first()


async def list_court_cases(
    session: AsyncSession, status: str | None = None
) -> list[InternationalCourtCase]:
    """فهرست پرونده‌های دادگاه."""
    stmt = select(InternationalCourtCase).order_by(InternationalCourtCase.id.desc())
    if status:
        stmt = stmt.where(InternationalCourtCase.status == status)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_cases_for_country(
    session: AsyncSession, country_id: int
) -> list[InternationalCourtCase]:
    """فهرست پرونده‌هایی که یک کشور در آن‌ها شاکی یا متهم است."""
    res = await session.execute(
        select(InternationalCourtCase)
        .where(
            or_(
                InternationalCourtCase.claimant_country_id == country_id,
                InternationalCourtCase.defendant_country_id == country_id,
            )
        )
        .order_by(InternationalCourtCase.id.desc())
    )
    return list(res.scalars().all())


async def add_court_party(
    session: AsyncSession, party: CourtParty
) -> CourtParty:
    """افزودن طرف پرونده (شاکی، متهم یا شاهد)."""
    existing = await get_court_party(session, party.case_id, party.country_id)
    if existing:
        existing.role = party.role
        existing.can_speak = party.can_speak
        await session.flush()
        return existing
    session.add(party)
    await session.flush()
    return party


async def list_court_parties(
    session: AsyncSession, case_id: int
) -> list[CourtParty]:
    """فهرست تمام طرف‌های احضارشده در یک دادگاه."""
    res = await session.execute(
        select(CourtParty).where(CourtParty.case_id == case_id)
    )
    return list(res.scalars().all())


async def get_court_party(
    session: AsyncSession, case_id: int, country_id: int
) -> CourtParty | None:
    """دریافت مشخصات حضور یک کشور در پرونده دادگاه."""
    res = await session.execute(
        select(CourtParty).where(
            CourtParty.case_id == case_id,
            CourtParty.country_id == country_id,
        )
    )
    return res.scalars().first()


async def get_active_case_for_party(
    session: AsyncSession, country_id: int
) -> tuple[InternationalCourtCase, CourtParty] | None:
    """بررسی اینکه آیا این کشور در یک دادگاه فعالِ در حال محاکمه حضور دارد یا خیر."""
    res = await session.execute(
        select(InternationalCourtCase, CourtParty)
        .join(CourtParty, InternationalCourtCase.id == CourtParty.case_id)
        .where(
            InternationalCourtCase.status == "trial",
            CourtParty.country_id == country_id,
        )
    )
    row = res.first()
    if row:
        return row[0], row[1]
    return None


# ============================================================
#  قطعنامه‌ها و رای‌گیری جهانی (UN Resolutions)
# ============================================================


async def create_resolution(
    session: AsyncSession, res: UNResolution
) -> UNResolution:
    """ثبت قطعنامه جدید برای رای‌گیری جهانی."""
    session.add(res)
    await session.flush()
    return res


async def get_resolution(
    session: AsyncSession, res_id: int
) -> UNResolution | None:
    """دریافت قطعنامه با شناسه."""
    return await session.get(UNResolution, res_id)


async def list_resolutions(
    session: AsyncSession, status: str | None = None
) -> list[UNResolution]:
    """فهرست قطعنامه‌ها."""
    stmt = select(UNResolution).order_by(UNResolution.id.desc())
    if status:
        stmt = stmt.where(UNResolution.status == status)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def cast_resolution_vote(
    session: AsyncSession, res_id: int, country_id: int, vote: str
) -> UNResolutionVote:
    """ثبت یا تغییر رای کشور به یک قطعنامه."""
    res = await session.execute(
        select(UNResolutionVote).where(
            UNResolutionVote.resolution_id == res_id,
            UNResolutionVote.country_id == country_id,
        )
    )
    v = res.scalars().first()
    if v:
        v.vote = vote
        v.voted_at = _utcnow()
    else:
        v = UNResolutionVote(
            resolution_id=res_id,
            country_id=country_id,
            vote=vote,
        )
        session.add(v)
    await session.flush()
    return v


async def get_resolution_votes(
    session: AsyncSession, res_id: int
) -> dict[str, int]:
    """شمارش آرای ماخوذه برای یک قطعنامه (موافق، مخالف، ممتنع)."""
    res = await session.execute(
        select(UNResolutionVote.vote, func.count(UNResolutionVote.id))
        .where(UNResolutionVote.resolution_id == res_id)
        .group_by(UNResolutionVote.vote)
    )
    counts = {"yes": 0, "no": 0, "abstain": 0}
    for vote, cnt in res.all():
        if vote in counts:
            counts[vote] = cnt
    return counts
