"""لایه‌ی دسترسی داده برای نرخ‌های لحظه‌ای بازار جهانی (آپدیت شماره ۴)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.market_price import MarketPrice


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_all_market_prices(session: AsyncSession) -> list[MarketPrice]:
    """دریافت لیست تمام رکوردهای نرخ بازار جهانی."""
    stmt = select(MarketPrice).order_by(MarketPrice.resource)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_market_price(session: AsyncSession, resource: str) -> MarketPrice | None:
    """دریافت رکورد نرخ یک منبع خاص."""
    stmt = select(MarketPrice).where(MarketPrice.resource == resource)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def save_market_price(
    session: AsyncSession,
    resource: str,
    base_price: float,
    current_price: float,
    previous_price: float,
    change_pct: float,
    trend: str,
    last_reason_code: str,
    last_reason_text: str,
    updated_at: datetime | None = None,
) -> MarketPrice:
    """ایجاد یا به‌روزرسانی نرخ یک ذخیره."""
    mp = await get_market_price(session, resource)
    if mp is None:
        mp = MarketPrice(
            resource=resource,
            base_price=base_price,
            current_price=current_price,
            previous_price=previous_price,
            change_pct=change_pct,
            trend=trend,
            last_reason_code=last_reason_code,
            last_reason_text=last_reason_text,
            updated_at=updated_at or _utcnow(),
        )
        session.add(mp)
    else:
        mp.base_price = base_price
        mp.current_price = current_price
        mp.previous_price = previous_price
        mp.change_pct = change_pct
        mp.trend = trend
        mp.last_reason_code = last_reason_code
        mp.last_reason_text = last_reason_text
        mp.updated_at = updated_at or _utcnow()

    await session.flush()
    return mp


async def reset_all_market_prices(
    session: AsyncSession,
    base_prices: dict[str, float],
    reason_code: str = "SEASON_RESET",
    reason_text: str = "آغاز فصل جدید و بازنشانی بازار جهانی به نرخ پایه",
) -> int:
    """بازنشانی کلیه قیمت‌های ذخایر به نرخ پایه و صفر کردن روندها (مخصوص ریست فصل)."""
    now = _utcnow()
    count = 0
    for res_name, bprice in base_prices.items():
        await save_market_price(
            session=session,
            resource=res_name,
            base_price=bprice,
            current_price=bprice,
            previous_price=bprice,
            change_pct=0.0,
            trend="STABLE",
            last_reason_code=reason_code,
            last_reason_text=reason_text,
            updated_at=now,
        )
        count += 1
    return count
