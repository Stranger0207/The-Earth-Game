"""توابع دسترسی داده برای سیستم مزایده منابع طبیعی (v2.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...enums import AuctionStatus
from ..models import Auction, AuctionBid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_auction(
    session: AsyncSession,
    seller_country_id: int,
    resource: str,
    amount: float,
    base_price: float,
    ends_at: datetime,
) -> Auction:
    """ایجاد مزایده جدید."""
    auction = Auction(
        seller_country_id=seller_country_id,
        resource=resource,
        amount=amount,
        base_price=base_price,
        highest_bid=0.0,
        highest_bidder_country_id=None,
        status=AuctionStatus.ACTIVE,
        created_at=_utcnow(),
        ends_at=ends_at,
    )
    session.add(auction)
    await session.flush()
    return auction


async def get_auction(session: AsyncSession, auction_id: int) -> Auction | None:
    """دریافت یک مزایده بر اساس شناسه."""
    result = await session.execute(
        select(Auction)
        .options(selectinload(Auction.bids))
        .where(Auction.id == auction_id)
    )
    return result.scalars().first()


async def list_active_auctions(session: AsyncSession) -> list[Auction]:
    """فهرست تمام مزایده‌های فعال."""
    result = await session.execute(
        select(Auction)
        .where(Auction.status == AuctionStatus.ACTIVE)
        .order_by(Auction.ends_at.asc())
    )
    return list(result.scalars().all())


async def list_seller_auctions(
    session: AsyncSession, seller_country_id: int, active_only: bool = True
) -> list[Auction]:
    """فهرست مزایده‌های یک فروشنده."""
    stmt = select(Auction).where(Auction.seller_country_id == seller_country_id)
    if active_only:
        stmt = stmt.where(Auction.status == AuctionStatus.ACTIVE)
    stmt = stmt.order_by(Auction.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_bid(
    session: AsyncSession,
    auction_id: int,
    bidder_country_id: int,
    amount: float,
    entry_fee: float = 200_000_000.0,
) -> AuctionBid:
    """ثبت یک پیشنهاد قیمت جدید در مزایده."""
    bid = AuctionBid(
        auction_id=auction_id,
        bidder_country_id=bidder_country_id,
        amount=amount,
        entry_fee=entry_fee,
        created_at=_utcnow(),
    )
    session.add(bid)

    # به‌روزرسانی بالاترین پیشنهاد در خود مزایده
    auction = await session.get(Auction, auction_id)
    if auction:
        auction.highest_bid = amount
        auction.highest_bidder_country_id = bidder_country_id

    await session.flush()
    return bid


async def count_bids(session: AsyncSession, auction_id: int) -> int:
    """تعداد پیشنهادات ثبت‌شده در یک مزایده."""
    result = await session.execute(
        select(func.count(AuctionBid.id)).where(AuctionBid.auction_id == auction_id)
    )
    return result.scalar() or 0


async def list_bids(session: AsyncSession, auction_id: int) -> list[AuctionBid]:
    """فهرست پیشنهادات یک مزایده به ترتیب بیشترین مبلغ."""
    result = await session.execute(
        select(AuctionBid)
        .where(AuctionBid.auction_id == auction_id)
        .order_by(AuctionBid.amount.desc(), AuctionBid.id.desc())
    )
    return list(result.scalars().all())
