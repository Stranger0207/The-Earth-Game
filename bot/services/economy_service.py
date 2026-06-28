"""
منطق اقتصاد: احداث تأسیسات و اثر آن بر شاخص‌ها، و آماده‌سازی فروش ذخیره.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    FACILITY_COST_USD,
    FACILITY_ECON_POWER_GAIN,
    FACILITY_INFLATION_DROP,
    FACILITY_SATISFACTION_GAIN,
    FACILITY_UNEMPLOYMENT_DROP,
    GAS_PLATFORM_OUTPUT_PER_24H,
    GOLD_MINE_YIELD_KG_PER_24H,
    MINE_YIELD_PER_24H,
    OIL_PLATFORM_OUTPUT_PER_24H,
    SALE_BUYER_INFLATION_DELTA,
    SALE_SELLER_ECON_POWER_GAIN,
    SALE_SELLER_INFLATION_DELTA,
    STEEL_FACTORY_IRON_INTAKE_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from ..database.models import Country, Facility
from ..database.repositories import countries as countries_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import FacilityType, ResourceType


class EconomyError(Exception):
    """خطای منطقی اقتصاد (بودجه ناکافی، عدم امکان استخراج و ...)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _facility_yield(facility_type: FacilityType, resource: str | None) -> tuple[float, str | None, float]:
    """
    بازدهی، منبع خروجی و مصرف ورودی یک تأسیسات را برمی‌گرداند.
    خروجی: (yield_amount, output_resource, intake_amount)
    """
    if facility_type == FacilityType.MINE:
        rtype = ResourceType(resource)
        if rtype == ResourceType.GOLD:
            return GOLD_MINE_YIELD_KG_PER_24H, resource, 0.0
        return MINE_YIELD_PER_24H.get(rtype, 0.0), resource, 0.0
    if facility_type == FacilityType.STEEL_FACTORY:
        return STEEL_FACTORY_OUTPUT_PER_24H, ResourceType.STEEL.value, STEEL_FACTORY_IRON_INTAKE_PER_24H
    if facility_type == FacilityType.OIL_PLATFORM:
        return OIL_PLATFORM_OUTPUT_PER_24H, ResourceType.OIL.value, 0.0
    if facility_type == FacilityType.GAS_PLATFORM:
        return GAS_PLATFORM_OUTPUT_PER_24H, ResourceType.GAS.value, 0.0
    return 0.0, None, 0.0


def _required_resource_for_facility(
    facility_type: FacilityType, resource: str | None
) -> ResourceType | None:
    """منبعی که برای ساخت این تأسیسات باید قابل‌استخراج باشد را برمی‌گرداند."""
    if facility_type == FacilityType.MINE:
        return ResourceType(resource) if resource else None
    if facility_type == FacilityType.OIL_PLATFORM:
        return ResourceType.OIL
    if facility_type == FacilityType.GAS_PLATFORM:
        return ResourceType.GAS
    # کارخانه فولاد نیازی به مجوز استخراج ندارد (از آهن می‌سازد)
    return None


async def build_facility(
    session: AsyncSession,
    country: Country,
    facility_type: FacilityType,
    resource: str | None,
    location: str,
) -> Facility:
    """
    احداث یک تأسیسات: بررسی بودجه و امکان استخراج، کسر هزینه، ساخت رکورد و اثر بر شاخص‌ها.
    در صورت خطا EconomyError پرتاب می‌شود.
    """
    cost = FACILITY_COST_USD[facility_type]
    if country.budget < cost:
        raise EconomyError(
            f"بودجه‌ی کافی ندارید. هزینه‌ی این تأسیسات {cost:,} دلار است."
        )

    # بررسی امکان استخراج منبع (پلی‌بوک: مثلاً آذربایجان نمی‌تواند سکوی نفتی بسازد)
    required = _required_resource_for_facility(facility_type, resource)
    if required is not None:
        reserve = await reserves_repo.get_reserve(session, country.id, required)
        if reserve is None or not reserve.can_extract:
            raise EconomyError(
                "کشور شما امکان استخراج این منبع را ندارد."
            )

    yield_amount, output_resource, intake = _facility_yield(facility_type, resource)

    # کسر هزینه از بودجه
    country.budget -= cost

    facility = Facility(
        country_id=country.id,
        type=facility_type.value,
        resource=output_resource,
        location=location,
        budget=cost,
        yield_amount=yield_amount,
        yield_interval_h=24,
        intake_amount=intake,
        active=True,
        last_yield_at=_utcnow(),
    )
    session.add(facility)

    # اثر مثبت بر شاخص‌های اقتصادی (مدل ساده)
    country.unemployment = max(0.0, country.unemployment - FACILITY_UNEMPLOYMENT_DROP)
    country.public_satisfaction = min(
        100.0, country.public_satisfaction + FACILITY_SATISFACTION_GAIN
    )
    country.economic_power = min(
        100.0, country.economic_power + FACILITY_ECON_POWER_GAIN
    )
    # افزایش تولید داخلی → کاهش تورم و رشد مثبت (v1.5)
    country.inflation = max(0.0, country.inflation - FACILITY_INFLATION_DROP)
    country.growth = "up"

    await session.flush()
    return facility


async def build_joint_facility(
    session: AsyncSession,
    initiator: Country,
    partner: Country,
    facility_type: FacilityType,
    resource: str | None,
    location: str,
    partner_percent: float,
) -> Facility:
    """
    احداث تأسیسات مشترک (v1.9): هزینه بین سازنده و شریک به نسبت درصد تقسیم می‌شود
    (سهم شریک = partner_percent٪، سهم سازنده = بقیه). بازدهی هم با همان نسبت در زمان‌بند
    بین دو کشور تقسیم می‌شود. در صورت خطا EconomyError پرتاب می‌شود.
    """
    cost = FACILITY_COST_USD[facility_type]
    partner_share = cost * (partner_percent / 100.0)
    owner_share = cost - partner_share

    if initiator.budget < owner_share:
        raise EconomyError(f"بودجه‌ی شما کافی نیست. سهم شما {owner_share:,.0f} دلار است.")
    if partner.budget < partner_share:
        raise EconomyError("بودجه‌ی شریک کافی نیست.")

    # بررسی امکان استخراج منبع برای کشور سازنده (محل احداث در کشور سازنده است)
    required = _required_resource_for_facility(facility_type, resource)
    if required is not None:
        reserve = await reserves_repo.get_reserve(session, initiator.id, required)
        if reserve is None or not reserve.can_extract:
            raise EconomyError("کشور سازنده امکان استخراج این منبع را ندارد.")

    yield_amount, output_resource, intake = _facility_yield(facility_type, resource)

    initiator.budget -= owner_share
    partner.budget -= partner_share

    facility = Facility(
        country_id=initiator.id,
        type=facility_type.value,
        resource=output_resource,
        location=location,
        budget=cost,
        yield_amount=yield_amount,
        yield_interval_h=24,
        intake_amount=intake,
        active=True,
        partner_country=partner.id,
        partner_percent=partner_percent,
        last_yield_at=_utcnow(),
    )
    session.add(facility)

    # اثر مثبت اقتصادی (برای کشور سازنده)
    initiator.unemployment = max(0.0, initiator.unemployment - FACILITY_UNEMPLOYMENT_DROP)
    initiator.public_satisfaction = min(100.0, initiator.public_satisfaction + FACILITY_SATISFACTION_GAIN)
    initiator.economic_power = min(100.0, initiator.economic_power + FACILITY_ECON_POWER_GAIN)
    initiator.inflation = max(0.0, initiator.inflation - FACILITY_INFLATION_DROP)
    initiator.growth = "up"

    await session.flush()
    return facility


async def transfer_sale(
    session: AsyncSession,
    seller_id: int,
    buyer_id: int,
    resource: str,
    amount: float,
    price: float,
) -> dict:
    """
    اجرای مالی فروش: کسر منبع از فروشنده، کسر پول از خریدار، افزودن پول به فروشنده.
    در صورت وجود تعرفه‌ی آمریکا روی فروشنده، درصدی از مبلغ کسر و به خزانه‌ی آمریکا واریز می‌شود.
    دیکشنری حاوی اطلاعات تعرفه (مبلغ عوارض و خالص دریافتی فروشنده) برمی‌گرداند.
    (افزودن منبع به خریدار پس از رسیدن محموله توسط زمان‌بند انجام می‌شود.)
    """
    from ..database.repositories import tariff as tariff_repo  # جلوگیری از import حلقوی

    seller = await countries_repo.get_country(session, seller_id)
    buyer = await countries_repo.get_country(session, buyer_id)
    if seller is None or buyer is None:
        raise EconomyError("کشور یافت نشد.")

    if not await reserves_repo.has_enough(session, seller_id, resource, amount):
        raise EconomyError("موجودی منبع فروشنده کافی نیست.")
    if buyer.budget < price:
        raise EconomyError("بودجه‌ی خریدار کافی نیست.")

    await reserves_repo.add_amount(session, seller_id, resource, -amount)
    buyer.budget -= price

    # --- اعمال تعرفه‌ی آمریکا روی فروشنده (v1.5) ---
    duty = 0.0
    tariff = await tariff_repo.get_tariff(session, seller_id)
    if tariff is not None and tariff.percent > 0 and seller.name_en != "USA":
        usa = await countries_repo.get_country_by_name(session, "USA")
        if usa is not None and usa.id != seller_id:
            duty = price * (tariff.percent / 100.0)
            usa.budget += duty
            usa.international_duties += duty

    # فروشنده فقط مبلغ باقی‌مانده پس از کسر تعرفه را دریافت می‌کند
    seller.budget += price - duty

    # --- اثر اقتصادی تجارت بر تورم دو طرف (v1.5) ---
    # فروشنده: عرضه‌ی داخلی کم، تقاضا بالا → تورم بالا؛ ولی درآمد ارزی اقتصاد را کمی تقویت می‌کند
    seller.inflation = max(0.0, seller.inflation + SALE_SELLER_INFLATION_DELTA)
    seller.economic_power = min(100.0, seller.economic_power + SALE_SELLER_ECON_POWER_GAIN)
    # خریدار: عرضه‌ی داخلی بالا → تورم پایین
    buyer.inflation = max(0.0, buyer.inflation + SALE_BUYER_INFLATION_DELTA)

    return {"duty": duty, "net_to_seller": price - duty, "tariff_percent": tariff.percent if tariff else 0}
