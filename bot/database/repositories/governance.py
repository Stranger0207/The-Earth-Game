"""لایه‌ی دسترسی داده برای سیستم حاکمیت (v1.10.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.governance import Law, Protest, VisaRequirement


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  اعتراضات
# ============================================================

async def create_protest(
    session: AsyncSession,
    country_id: int,
    protest_type: str,
    title: str,
    description: str = "",
    severity: float = 5.0,
) -> Protest:
    """ساخت یک اعتراض جدید."""
    p = Protest(
        country_id=country_id,
        protest_type=protest_type,
        title=title,
        description=description,
        severity=severity,
        status="active",
    )
    session.add(p)
    await session.flush()
    return p


async def get_active_protests(session: AsyncSession, country_id: int) -> list[Protest]:
    """فهرست اعتراضات فعال یک کشور."""
    q = (
        select(Protest)
        .where(Protest.country_id == country_id, Protest.status == "active")
        .order_by(Protest.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def get_all_protests(session: AsyncSession, country_id: int) -> list[Protest]:
    """همه‌ی اعتراضات یک کشور (فعال و غیرفعال)."""
    q = (
        select(Protest)
        .where(Protest.country_id == country_id)
        .order_by(Protest.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def get_protest_by_id(session: AsyncSession, protest_id: int) -> Protest | None:
    return await session.get(Protest, protest_id)


async def update_protest_status(
    session: AsyncSession,
    protest_id: int,
    status: str,
    result_text: str | None = None,
) -> Protest | None:
    """تغییر وضعیت اعتراض."""
    p = await session.get(Protest, protest_id)
    if p is None:
        return None
    p.status = status
    p.handled_at = _utcnow()
    if result_text is not None:
        p.result_text = result_text
    await session.flush()
    return p


async def count_active_protests(session: AsyncSession, country_id: int) -> int:
    """تعداد اعتراضات فعال."""
    q = select(func.count()).select_from(Protest).where(
        Protest.country_id == country_id, Protest.status == "active"
    )
    return (await session.execute(q)).scalar() or 0


async def get_all_active_protests_all_countries(session: AsyncSession) -> list[Protest]:
    """همه‌ی اعتراضات فعال در تمام کشورها (برای scheduler)."""
    q = select(Protest).where(Protest.status == "active")
    return list((await session.execute(q)).scalars().all())


# ============================================================
#  قوانین / لوایح
# ============================================================

async def create_law(
    session: AsyncSession,
    country_id: int,
    title: str,
    body: str,
    law_type: str = "custom",
) -> Law:
    """ساخت لایحه‌ی جدید (به‌صورت پیش‌فرض در مجلس)."""
    law = Law(
        country_id=country_id,
        title=title,
        body=body,
        law_type=law_type,
        status="in_parliament",
    )
    session.add(law)
    await session.flush()
    return law


async def get_laws(session: AsyncSession, country_id: int) -> list[Law]:
    """فهرست لوایح یک کشور (جدیدترین اول)."""
    q = (
        select(Law)
        .where(Law.country_id == country_id)
        .order_by(Law.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def get_pending_laws(session: AsyncSession, country_id: int) -> list[Law]:
    """لوایح در انتظار رأی مجلس."""
    q = (
        select(Law)
        .where(Law.country_id == country_id, Law.status == "in_parliament")
        .order_by(Law.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def count_laws_by_country_since(
    session: AsyncSession, country_id: int, since_dt: datetime, exclude_rejected: bool = True
) -> int:
    """شمارش لوایح ثبت‌شده یک کشور از یک تاریخ مشخص (به‌جز لوایح ردشده)."""
    q = select(func.count(Law.id)).where(
        Law.country_id == country_id,
        Law.created_at >= since_dt,
    )
    if exclude_rejected:
        q = q.where(Law.status != "rejected")
    res = await session.execute(q)
    return res.scalar_one() or 0


async def get_earliest_law_since(
    session: AsyncSession, country_id: int, since_dt: datetime, exclude_rejected: bool = True
) -> Law | None:
    """قدیمی‌ترین لایحه در پنجره زمانی جهت محاسبه زمان آزادسازی سهمیه بعدی."""
    q = (
        select(Law)
        .where(Law.country_id == country_id, Law.created_at >= since_dt)
    )
    if exclude_rejected:
        q = q.where(Law.status != "rejected")
    q = q.order_by(Law.created_at.asc()).limit(1)
    res = await session.execute(q)
    return res.scalars().first()


async def get_law_by_id(session: AsyncSession, law_id: int) -> Law | None:
    return await session.get(Law, law_id)


async def vote_law(
    session: AsyncSession,
    law_id: int,
    approved: bool,
    vote_result: str = "",
) -> Law | None:
    """ادمین رأی مجلس را اعلام می‌کند."""
    law = await session.get(Law, law_id)
    if law is None:
        return None
    law.status = "approved" if approved else "rejected"
    law.voted_at = _utcnow()
    law.vote_result = vote_result
    await session.flush()
    return law


async def update_law_effects(
    session: AsyncSession,
    law_id: int,
    stability_effect: float | None = None,
    satisfaction_effect: float | None = None,
) -> Law | None:
    """تنظیم یا ویرایش مقادیر اثرات لایحه (ثبات داخلی و رضایت عمومی)."""
    law = await session.get(Law, law_id)
    if law is None:
        return None
    if stability_effect is not None:
        law.stability_effect = float(stability_effect)
    if satisfaction_effect is not None:
        law.satisfaction_effect = float(satisfaction_effect)
    await session.flush()
    return law


async def apply_and_close_law(
    session: AsyncSession,
    law_id: int,
) -> tuple[Law | None, Country | None, float, float]:
    """
    اعمال نهایی و بستن لایحه:
    اثرات تعیین‌شده روی ثبات و رضایت کشور ثبت‌کننده اعمال شده و وضعیت لایحه applied می‌شود.
    خروجی: (law, country, applied_stab_delta, applied_sat_delta)
    """
    from ..models.country import Country
    from ...enums import LawStatus

    law = await session.get(Law, law_id)
    if law is None:
        return None, None, 0.0, 0.0

    country = await session.get(Country, law.country_id)
    if country is None:
        return law, None, 0.0, 0.0

    law.status = LawStatus.APPLIED.value
    law.voted_at = _utcnow()
    law.vote_result = (
        f"تصویب و اعمال نهایی: "
        f"{'+' if law.stability_effect >= 0 else ''}{law.stability_effect:.1f}٪ ثبات | "
        f"{'+' if law.satisfaction_effect >= 0 else ''}{law.satisfaction_effect:.1f}٪ رضایت"
    )

    # اعمال روی کشور با رعایت کف ۰ و سقف ۱۰۰
    cur_stab = float(country.stability or 50.0)
    new_stab = max(0.0, min(100.0, cur_stab + law.stability_effect))
    country.stability = new_stab

    cur_sat = float(country.public_satisfaction or 50.0)
    new_sat = max(0.0, min(100.0, cur_sat + law.satisfaction_effect))
    country.public_satisfaction = new_sat

    await session.flush()
    return law, country, law.stability_effect, law.satisfaction_effect


# ============================================================
#  ویزا
# ============================================================

async def add_visa(
    session: AsyncSession, country_id: int, target_country_id: int
) -> VisaRequirement:
    """افزودن الزام ویزا."""
    v = VisaRequirement(country_id=country_id, target_country_id=target_country_id)
    session.add(v)
    await session.flush()
    return v


async def remove_visa(
    session: AsyncSession, country_id: int, target_country_id: int
) -> bool:
    """حذف ویزا. True اگر حذف شد."""
    q = delete(VisaRequirement).where(
        VisaRequirement.country_id == country_id,
        VisaRequirement.target_country_id == target_country_id,
    )
    result = await session.execute(q)
    await session.flush()
    return result.rowcount > 0


async def get_visa_list(session: AsyncSession, country_id: int) -> list[VisaRequirement]:
    """فهرست ویزاهای وضع‌شده توسط یک کشور."""
    q = (
        select(VisaRequirement)
        .where(VisaRequirement.country_id == country_id)
        .order_by(VisaRequirement.created_at.desc())
    )
    return list((await session.execute(q)).scalars().all())


async def has_visa(
    session: AsyncSession, country_id: int, target_country_id: int
) -> bool:
    """آیا کشور country_id برای target_country_id ویزا وضع کرده؟"""
    q = select(func.count()).select_from(VisaRequirement).where(
        VisaRequirement.country_id == country_id,
        VisaRequirement.target_country_id == target_country_id,
    )
    return ((await session.execute(q)).scalar() or 0) > 0


async def count_visas_against(session: AsyncSession, target_country_id: int) -> int:
    """تعداد ویزاهایی که علیه یک کشور وضع شده (برای محاسبه‌ی تأثیر رضایت)."""
    q = select(func.count()).select_from(VisaRequirement).where(
        VisaRequirement.target_country_id == target_country_id,
    )
    return (await session.execute(q)).scalar() or 0


async def add_visas_bulk(
    session: AsyncSession, country_id: int, target_country_ids: list[int]
) -> int:
    """افزودن ویزای اجباری به صورت دسته‌جمعی برای چندین کشور."""
    if not target_country_ids:
        return 0
    existing = await get_visa_list(session, country_id)
    existing_targets = {v.target_country_id for v in existing}
    new_targets = [tid for tid in target_country_ids if tid not in existing_targets and tid != country_id]
    for tid in new_targets:
        session.add(VisaRequirement(country_id=country_id, target_country_id=tid))
    await session.flush()
    return len(new_targets)


async def remove_all_visas(session: AsyncSession, country_id: int) -> int:
    """حذف تمامی ویزاهای اجباری وضع‌شده توسط این کشور."""
    q = delete(VisaRequirement).where(VisaRequirement.country_id == country_id)
    res = await session.execute(q)
    await session.flush()
    return res.rowcount or 0


async def remove_visas_bulk(
    session: AsyncSession, country_id: int, target_country_ids: list[int]
) -> int:
    """حذف دسته‌جمعی ویزاهای اجباری برای چندین کشور مشخص."""
    if not target_country_ids:
        return 0
    q = delete(VisaRequirement).where(
        VisaRequirement.country_id == country_id,
        VisaRequirement.target_country_id.in_(target_country_ids),
    )
    res = await session.execute(q)
    await session.flush()
    return res.rowcount or 0
