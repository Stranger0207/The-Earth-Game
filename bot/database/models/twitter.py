"""مدل‌های سیستم توییتر جهانی (X): پروفایل کشور، توییت‌ها و لایک‌ها."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TwitterProfile(Base):
    """
    پروفایل رسمی توییتر یک کشور در فصل جاری.
    هر کشور حداکثر یک پروفایل با نام کاربری و عکس مشخص دارد.
    """

    __tablename__ = "twitter_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, unique=True, index=True
    )
    # نام کاربری بدون @ (تنها حروف انگلیسی، ارقام و آندرلاین)
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # فایل آیدی تصویر پروفایل در تلگرام
    avatar_file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<TwitterProfile country={self.country_id} @{self.username}>"


class Tweet(Base):
    """یک توییت رسمی ارسال‌شده توسط کشور در کانال توییتر جهانی."""

    __tablename__ = "tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    # متن توییت (حداکثر ۲۸۰ کاراکتر)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # آیدی پیام ارسال‌شده در کانال رسمی توییتر
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # شمارنده لایک‌های توییت
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Tweet id={self.id} country={self.country_id} likes={self.likes_count}>"


class TweetLike(Base):
    """ثبت لایک کاربران زیر توییت‌ها در کانال با قید یکتایی (Toggle)."""

    __tablename__ = "tweet_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_id: Mapped[int] = mapped_column(
        ForeignKey("tweets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # آیدی تلگرام کاربر لایک‌کننده
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tweet_id", "user_id", name="uq_tweet_user_like"),
    )

    def __repr__(self) -> str:
        return f"<TweetLike tweet={self.tweet_id} user={self.user_id}>"
