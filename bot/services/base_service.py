"""منطق کسب‌وکار پایگاه‌های نظامی."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    MAX_FOREIGN_BASES_PER_HOST,
    MAX_FOREIGN_BASES_PER_OWNER,
    MILITARY_BASE_TYPES,
)
from ..database.models import BaseEquipment, Country, MilitaryBase
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_bases as base_repo


class BaseServiceError(Exception):
    """خطای سرویس پایگاه نظامی."""


async def request_create_base(
    session: AsyncSession,
    owner_country: Country,
    host_country: Country,
    base_type: str,
    name: str,
    location: str,
) -> tuple[MilitaryBase, bool]:
    """
    درخواست احداث پایگاه نظامی.
    اگر کشور میزبان خودش باشد -> مستقیماً active می‌شود.
    اگر کشور دیگری باشد -> وضعیت pending قرار می‌گیرد و منتظر تأیید میزبان می‌ماند.

    خروجی: (پایگاه ساخته شده، آیا مستقیماً فعال شد؟)
    """
    if not owner_country.is_vip:
        raise BaseServiceError("فقط کشورهای VIP می‌توانند پایگاه نظامی احداث کنند.")

    if base_type not in MILITARY_BASE_TYPES:
        raise BaseServiceError("نوع پایگاه نامعتبر است.")

    type_name_fa, cost_usd, capacity = MILITARY_BASE_TYPES[base_type]

    if owner_country.budget < cost_usd:
        raise BaseServiceError(f"بودجه کافی نیست. هزینه ساخت {cost_usd:,.0f} دلار است.")

    is_foreign = owner_country.id != host_country.id

    if is_foreign:
        owner_foreign_count = await base_repo.count_foreign_bases_by_owner(
            session, owner_country.id
        )
        if owner_foreign_count >= MAX_FOREIGN_BASES_PER_OWNER:
            raise BaseServiceError(
                f"شما حداکثر می‌توانید {MAX_FOREIGN_BASES_PER_OWNER} پایگاه خارجی داشته باشید."
            )

        host_foreign_count = await base_repo.count_foreign_bases_in_host(
            session, host_country.id
        )
        if host_foreign_count >= MAX_FOREIGN_BASES_PER_HOST:
            raise BaseServiceError(
                f"کشور {host_country.name_fa} حداکثر گنجایش {MAX_FOREIGN_BASES_PER_HOST} پایگاه خارجی را دارد."
            )

    # کسر هزینه بودجه
    owner_country.budget -= cost_usd

    status = "active" if not is_foreign else "pending"
    host_approved = not is_foreign

    base = MilitaryBase(
        owner_country_id=owner_country.id,
        host_country_id=host_country.id,
        base_type=base_type,
        name=name,
        location=location,
        status=status,
        host_approved=host_approved,
        capacity=capacity,
        cost_usd=cost_usd,
    )

    base = await base_repo.create_base(session, base)
    return base, host_approved


async def approve_base_request(
    session: AsyncSession, base_id: int, host_country_id: int
) -> MilitaryBase:
    """تأیید درخواست احداث پایگاه توسط کشور میزبان."""
    base = await base_repo.get_base(session, base_id)
    if not base or base.host_country_id != host_country_id:
        raise BaseServiceError("درخواست پایگاه یافت نشد.")

    if base.status != "pending":
        raise BaseServiceError("این درخواست قبلاً تعیین تکلیف شده است.")

    base.status = "active"
    base.host_approved = True
    await session.flush()
    return base


async def reject_base_request(
    session: AsyncSession, base_id: int, host_country_id: int
) -> MilitaryBase:
    """رد درخواست احداث پایگاه توسط کشور میزبان (بازگشت هزینه)."""
    base = await base_repo.get_base(session, base_id)
    if not base or base.host_country_id != host_country_id:
        raise BaseServiceError("درخواست پایگاه یافت نشد.")

    if base.status != "pending":
        raise BaseServiceError("این درخواست قبلاً تعیین تکلیف شده است.")

    # بازگشت بودجه به سازنده
    owner = await countries_repo.get_country(session, base.owner_country_id)
    if owner:
        owner.budget += base.cost_usd

    base.status = "rejected"
    await session.flush()
    return base


async def transfer_equipment_to_base(
    session: AsyncSession,
    owner_country_id: int,
    base_id: int,
    asset_name: str,
    count: int,
) -> BaseEquipment:
    """انتقال تجهیزات از موجودی اصلی کشور به پایگاه نظامی."""
    base = await base_repo.get_base(session, base_id)
    if not base or base.owner_country_id != owner_country_id or base.status != "active":
        raise BaseServiceError("پایگاه فعال معتبر یافت نشد.")

    asset = await mil_repo.get_asset_by_name(session, owner_country_id, asset_name)
    if not asset or asset.count < count:
        raise BaseServiceError("موجودی این تجهیزات در کشور شما کافی نیست.")

    # بررسی ظرفیت پایگاه
    current_total = sum(eq.count for eq in base.equipments)
    if current_total + count > base.capacity:
        raise BaseServiceError(
            f"ظرفیت پایگاه کافی نیست! (موجود: {current_total}/{base.capacity})"
        )

    # کسر از موجودی کشور
    await mil_repo.reduce_count(session, owner_country_id, asset_name, count)

    # افزودن به پایگاه
    eq = await base_repo.add_base_equipment(
        session, base_id, asset_name, asset.branch, count
    )
    return eq


async def return_equipment_from_base(
    session: AsyncSession,
    owner_country_id: int,
    base_id: int,
    asset_name: str,
    count: int,
) -> None:
    """بازگرداندن تجهیزات از پایگاه به موجودی اصلی کشور."""
    base = await base_repo.get_base(session, base_id)
    if not base or base.owner_country_id != owner_country_id:
        raise BaseServiceError("پایگاه یافت نشد.")

    success = await base_repo.reduce_base_equipment(session, base_id, asset_name, count)
    if not success:
        raise BaseServiceError("موجودی تجهیزات در این پایگاه کافی نیست.")

    # افزودن مجدد به کشور
    asset = await mil_repo.get_asset_by_name(session, owner_country_id, asset_name)
    if asset:
        asset.count += count
    else:
        # اگر رکورد قبلاً پاک شده بود، دوباره اضافه می‌شود
        from ..database.models import MilitaryAsset
        new_asset = MilitaryAsset(
            country_id=owner_country_id,
            branch="نظامی",
            category="عمومی",
            name=asset_name,
            unit="عدد",
            count=count,
        )
        session.add(new_asset)
    await session.flush()


async def destroy_or_delete_base(
    session: AsyncSession, owner_country_id: int, base_id: int
) -> None:
    """تخریب/تخلیه کامل پایگاه و بازگشت تجهیزات به کشور."""
    base = await base_repo.get_base(session, base_id)
    if not base or base.owner_country_id != owner_country_id:
        raise BaseServiceError("پایگاه یافت نشد.")

    # بازگرداندن تمام تجهیزات موجود در پایگاه به دیتابیس کشور
    for eq in base.equipments:
        if eq.count > 0:
            asset = await mil_repo.get_asset_by_name(session, owner_country_id, eq.asset_name)
            if asset:
                asset.count += eq.count

    await base_repo.delete_base(session, base_id)
