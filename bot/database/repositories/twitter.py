"""توابع دسترسی داده برای سیستم توییتر جهانی (X)."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Tweet, TweetLike, TwitterProfile


async def get_profile_by_country(
    session: AsyncSession, country_id: int
) -> TwitterProfile | None:
    """یافتن پروفایل توییتر یک کشور با استفاده از شناسه کشور."""
    result = await session.execute(
        select(TwitterProfile).where(TwitterProfile.country_id == country_id)
    )
    return result.scalar_one_or_none()


async def get_profile_by_username(
    session: AsyncSession, username: str
) -> TwitterProfile | None:
    """یافتن پروفایل توییتر بر اساس یوزرنیم (حساس نبودن به بزرگی/کوچکی حروف)."""
    clean_username = username.strip().lstrip("@").lower()
    result = await session.execute(
        select(TwitterProfile).where(func.lower(TwitterProfile.username) == clean_username)
    )
    return result.scalar_one_or_none()


async def create_profile(
    session: AsyncSession,
    country_id: int,
    username: str,
    avatar_file_id: str,
) -> TwitterProfile:
    """ایجاد و ذخیره پروفایل توییتر جدید برای کشور."""
    clean_username = username.strip().lstrip("@").lower()
    profile = TwitterProfile(
        country_id=country_id,
        username=clean_username,
        avatar_file_id=avatar_file_id,
    )
    session.add(profile)
    await session.flush()
    return profile


async def add_tweet(
    session: AsyncSession,
    country_id: int,
    content: str,
    channel_message_id: int | None = None,
) -> Tweet:
    """ثبت توییت جدید در دیتابیس."""
    tweet = Tweet(
        country_id=country_id,
        content=content,
        channel_message_id=channel_message_id,
        likes_count=0,
    )
    session.add(tweet)
    await session.flush()
    return tweet


async def get_tweet(session: AsyncSession, tweet_id: int) -> Tweet | None:
    """یافتن یک توییت با شناسه عددی."""
    return await session.get(Tweet, tweet_id)


async def list_tweets_by_country(
    session: AsyncSession, country_id: int, limit: int = 10
) -> list[Tweet]:
    """فهرست آخرین توییت‌های یک کشور (جدیدترین اول)."""
    result = await session.execute(
        select(Tweet)
        .where(Tweet.country_id == country_id)
        .order_by(Tweet.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_tweets_by_country(session: AsyncSession, country_id: int) -> int:
    """شمارش کل توییت‌های ارسالی یک کشور در این فصل."""
    result = await session.execute(
        select(func.count(Tweet.id)).where(Tweet.country_id == country_id)
    )
    return result.scalar_one() or 0


async def is_liked_by_user(
    session: AsyncSession, tweet_id: int, user_id: int
) -> bool:
    """بررسی اینکه آیا کاربر تلگرام این توییت را لایک کرده است یا خیر."""
    result = await session.execute(
        select(TweetLike).where(
            TweetLike.tweet_id == tweet_id, TweetLike.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is not None


async def toggle_like(
    session: AsyncSession, tweet_id: int, user_id: int
) -> tuple[bool, int]:
    """
    ثبت یا پس گرفتن لایک (Toggle).
    خروجی: (is_liked: bool, new_likes_count: int)
    """
    tweet = await session.get(Tweet, tweet_id)
    if tweet is None:
        return False, 0

    existing_like = await session.execute(
        select(TweetLike).where(
            TweetLike.tweet_id == tweet_id, TweetLike.user_id == user_id
        )
    )
    like_obj = existing_like.scalar_one_or_none()

    if like_obj is not None:
        # کاربر قبلاً لایک کرده بود -> حذف لایک
        await session.delete(like_obj)
        tweet.likes_count = max(0, tweet.likes_count - 1)
        await session.flush()
        return False, tweet.likes_count
    else:
        # لایک جدید
        new_like = TweetLike(tweet_id=tweet_id, user_id=user_id)
        session.add(new_like)
        tweet.likes_count += 1
        await session.flush()
        return True, tweet.likes_count
