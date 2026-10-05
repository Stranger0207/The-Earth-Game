"""مدل مزایده منابع طبیعی و پیشنهادات قیمت (v2.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ...enums import AuctionStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Auction(Base):
    """
    مزایده یک منبع طبیعی توسط کشور فروشنده.
    منبع تا پایان مزایده در انبار فروشنده رزرو می‌شود.
    در پایان، برنده با بالاترین پیشنهاد، منبع را از طریق محموله WTO دریافت می‌کند.
    """

    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    resource: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    base_price: Mapped[float] = mapped_column(Float, nullable=False)  # دلار

    highest_bid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    highest_bidder_country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id"), nullable=True
    )

    # آی‌دی پیام ارسال‌شده در کانال اخبار اقتصاد برای ویرایش نتیجه
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), default=AuctionStatus.ACTIVE, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    bids: Mapped[list["AuctionBid"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Auction #{self.id} seller={self.seller_country_id} res={self.resource} amount={self.amount} status={self.status}>"


class AuctionBid(Base):
    """یک پیشنهاد ثبت‌شده در مزایده توسط خریدار به همراه کارمزد شرکت در مزایده."""

    __tablename__ = "auction_bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auction_id: Mapped[int] = mapped_column(
        ForeignKey("auctions.id"), nullable=False, index=True
    )
    bidder_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    amount: Mapped[float] = mapped_column(Float, nullable=False)  # مبلغ پیشنهادی
    entry_fee: Mapped[float] = mapped_column(
        Float, default=200_000_000.0, nullable=False
    )  # ۲۰۰ میلیون دلار کسر و سوزانده شده

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    auction: Mapped["Auction"] = relationship(back_populates="bids")

    def __repr__(self) -> str:
        return f"<AuctionBid #{self.id} auc={self.auction_id} bidder={self.bidder_country_id} amount={self.amount}>"
