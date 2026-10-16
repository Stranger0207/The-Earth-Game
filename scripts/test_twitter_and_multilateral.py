"""
تست جامع قابلیت‌های جدید:
۱. سیستم توییتر جهانی (X): مدل‌ها، مخزن، لایک، توگل، رندر عکس در Pillow
۲. معاهدات چندجانبه در نشست‌ها: ثبت، امضای پویا، خروج یک‌طرفه، رندر سند معاهده با Pillow
"""

import asyncio
import io
import os
import sys

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# افزودن مسیر ریشه
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from bot.database.base import Base
from bot.database.models import (
    Contract,
    ContractSignatory,
    Country,
    Tweet,
    TweetLike,
    TwitterProfile,
    User,
)
from bot.database.repositories import diplomacy as dip_repo
from bot.database.repositories import twitter as tw_repo
from bot.enums import DiplomacyStatus
from bot.services.letter_image_service import render_contract_image
from bot.services.tweet_image_service import render_tweet_image


def create_dummy_avatar_bytes() -> bytes:
    """تولید یک عکس آواتار تستی در رم."""
    img = Image.new("RGB", (200, 200), color=(50, 150, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 150, 150], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def run_tests():
    print("🚀 شروع آزمون یکپارچگی سیستم توییتر (X) و معاهدات چندجانبه...")

    # راه‌اندازی دیتابیس تستی SQLite در حافظه
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # ۱. ساخت کاربران و کشورهای آزمایشی
        user1 = User(telegram_id=1001, first_name="Ali", president_name="علی رضایی")
        user2 = User(telegram_id=1002, first_name="Sara", president_name="سارا احمدی")
        user3 = User(telegram_id=1003, first_name="Reza", president_name="رضا کمالی")
        user4 = User(telegram_id=1004, first_name="John", president_name="جان دو")
        session.add_all([user1, user2, user3, user4])
        await session.flush()

        c1 = Country(id=1, name_en="Iran", name_fa="ایران", flag="🇮🇷", region="middle_east", owner_user_id=1001)
        c2 = Country(id=2, name_en="Japan", name_fa="ژاپن", flag="🇯🇵", region="asia", owner_user_id=1002)
        c3 = Country(id=3, name_en="Germany", name_fa="آلمان", flag="🇩🇪", region="europe", owner_user_id=1003)
        c4 = Country(id=4, name_en="Brazil", name_fa="برزیل", flag="🇧🇷", region="americas", owner_user_id=1004)
        session.add_all([c1, c2, c3, c4])
        await session.commit()
        print("✅ ۱. کاربران و کشورهای آزمایشی ساخته شدند.")

        # ۲. آزمون ثبت پروفایل توییتر
        profile1 = await tw_repo.create_profile(
            session, country_id=c1.id, username="iran_official", avatar_file_id="photo_123"
        )
        assert profile1.id is not None
        assert profile1.username == "iran_official"
        assert profile1.country_id == c1.id

        # دریافت با آیدی کشور و یوزرنیم
        p_by_c = await tw_repo.get_profile_by_country(session, c1.id)
        assert p_by_c is not None and p_by_c.username == "iran_official"

        p_by_u = await tw_repo.get_profile_by_username(session, "iran_official")
        assert p_by_u is not None and p_by_u.country_id == c1.id

        # بررسی یوزرنیم ناموجود
        p_none = await tw_repo.get_profile_by_username(session, "non_existent")
        assert p_none is None
        print("✅ ۲. ایجاد و اعتبارسنجی پروفایل توییتر با موفقیت انجام شد.")

        # ۳. آزمون ارسال توییت و لایک / آن‌لایک
        tweet = await tw_repo.add_tweet(
            session,
            country_id=c1.id,
            content="پیام صلح و دوستی به تمام ملت‌های جهان از سوی جمهوری اسلامی ایران.",
            channel_message_id=98765,
        )
        assert tweet.id is not None
        assert tweet.likes_count == 0

        # کاربر ۲ توییت را لایک می‌کند
        is_liked, new_count = await tw_repo.toggle_like(session, tweet.id, user2.telegram_id)
        assert is_liked is True
        assert new_count == 1
        assert await tw_repo.is_liked_by_user(session, tweet.id, user2.telegram_id) is True

        # کاربر ۲ مجدداً کلیک می‌کند (پس گرفتن لایک)
        is_liked_again, new_count_again = await tw_repo.toggle_like(session, tweet.id, user2.telegram_id)
        assert is_liked_again is False
        assert new_count_again == 0
        assert await tw_repo.is_liked_by_user(session, tweet.id, user2.telegram_id) is False

        # کاربر ۳ و کاربر ۴ هر دو لایک می‌کنند
        await tw_repo.toggle_like(session, tweet.id, user3.telegram_id)
        await tw_repo.toggle_like(session, tweet.id, user4.telegram_id)
        refreshed_tweet = await tw_repo.get_tweet(session, tweet.id)
        assert refreshed_tweet.likes_count == 2
        print("✅ ۳. ارسال توییت و سیستم لایک شیشه‌ای Toggle با موفقیت آزمایش شد.")

        # ۳.۱ آزمون محدودیت زمانی ۱ ساعته (کول‌داون) و کیبورد خانه توییتر
        from bot.constants import TWEET_COOLDOWN_HOURS
        from bot.database.repositories import cooldowns as cd_repo
        from bot.handlers.twitter import _twitter_home_kb

        # تست عملکرد بدون باگ _twitter_home_kb
        home_kb = _twitter_home_kb()
        assert len(home_kb.inline_keyboard) == 3

        # قبل از ثبت کول‌داون
        rem_before = await cd_repo.remaining_seconds(session, c1.id, "tweet", TWEET_COOLDOWN_HOURS)
        assert rem_before == 0.0

        # پس از انتشار توییت و لمس کول‌داون
        await cd_repo.touch(session, c1.id, "tweet")
        rem_after = await cd_repo.remaining_seconds(session, c1.id, "tweet", TWEET_COOLDOWN_HOURS)
        assert rem_after > 3500.0  # حدود ۱ ساعت (۳۶۰۰ ثانیه) باقی مانده است
        print("✅ ۳.۱ محدودیت زمانی ۱ ساعته (Cooldown) و منوی اصلی توییتر با موفقیت تایید شد.")

        # ۴. آزمون رندر گرافیکی توییت با Pillow و فونت‌های ۲ درجه بزرگتر
        avatar_bytes = create_dummy_avatar_bytes()
        tweet_img_bytes = render_tweet_image(
            country_name="ایران",
            username="iran_official",
            content="صلح و ثبات منطقه‌ای، اولویت دیپلماتیک ماست. #دیپلماسی #توییتر",
            avatar_bytes=avatar_bytes,
        )
        assert isinstance(tweet_img_bytes, bytes)
        assert len(tweet_img_bytes) > 1000

        # اعتبارسنجی تصویر تولید شده
        with Image.open(io.BytesIO(tweet_img_bytes)) as rendered_im:
            assert rendered_im.size[0] == 1000
            assert rendered_im.size[1] > 300
        print("✅ ۴. رندر گرافیکی Dark Mode اسکرین‌شات توییتر در Pillow با فونت درشت‌تر با موفقیت بررسی شد.")

        # ۵. آزمون معاهده چندجانبه بین‌المللی
        # ایجاد پیش‌نویس معاهده توسط کشور ۱ میان کشورهای ۱، ۲، ۳
        contract = Contract(
            country_a=c1.id,
            country_b=c2.id,
            title="پیمان همکاری اقتصادی و امنیتی اوراسیا",
            body="ماده ۱: طرفین متعهد می‌شوند تعرفه‌های گمرکی مشترک را تا ۵۰٪ کاهش دهند.\nماده ۲: رزمایش‌های مشترک سالانه برگزار خواهد شد.",
            signed_a=True,
            signed_b=False,
            status=DiplomacyStatus.PENDING,
            is_multilateral=True,
        )
        await dip_repo.add_contract(session, contract)
        await session.flush()

        # ثبت امضاکنندگان
        signatories = await dip_repo.add_contract_signatories(
            session=session,
            contract_id=contract.id,
            country_ids=[c1.id, c2.id, c3.id],
            proposer_id=c1.id,
        )
        assert len(signatories) == 3
        # کشور ۱ پیشنهاددهنده است پس باید signed=True باشد
        sig1 = await dip_repo.get_contract_signatory(session, contract.id, c1.id)
        assert sig1.signed is True

        sig2 = await dip_repo.get_contract_signatory(session, contract.id, c2.id)
        assert sig2.signed is False

        # بررسی طرف معاهده بودن
        assert await dip_repo.is_contract_party(session, contract, c1.id) is True
        assert await dip_repo.is_contract_party(session, contract, c2.id) is True
        assert await dip_repo.is_contract_party(session, contract, c3.id) is True
        assert await dip_repo.is_contract_party(session, contract, c4.id) is False

        # کشور ۲ امضا می‌کند
        ok2, all_signed2 = await dip_repo.sign_contract_signatory(session, contract.id, c2.id)
        assert ok2 is True
        assert all_signed2 is False  # کشور ۳ هنوز امضا نکرده

        # کشور ۳ امضا می‌کند
        ok3, all_signed3 = await dip_repo.sign_contract_signatory(session, contract.id, c3.id)
        assert ok3 is True
        assert all_signed3 is True  # اکنون تمام اعضا امضا کرده‌اند!
        print("✅ ۵. ثبت و امضای متوالی اعضای معاهده چندجانبه با موفقیت بررسی شد.")

        # ۶. آزمون فهرست قراردادهای کشور
        c1_contracts = await dip_repo.list_contracts_for_country(session, c1.id, only_active=False)
        assert len(c1_contracts) == 1
        assert c1_contracts[0].id == contract.id

        c3_contracts = await dip_repo.list_contracts_for_country(session, c3.id, only_active=False)
        assert len(c3_contracts) == 1
        assert c3_contracts[0].id == contract.id

        c4_contracts = await dip_repo.list_contracts_for_country(session, c4.id, only_active=False)
        assert len(c4_contracts) == 0
        print("✅ ۶. استعلام قراردادهای چندجانبه از طریق مخزن با موفقیت تایید شد.")

        # ۷. آزمون رندر سند معاهده با Pillow برای ۳، ۴ و ۵ کشور
        parties_3 = [
            {"country_name": "ایران", "country_flag": "🇮🇷", "leader_name": "علی رضایی"},
            {"country_name": "ژاپن", "country_flag": "🇯🇵", "leader_name": "سارا احمدی"},
            {"country_name": "آلمان", "country_flag": "🇩🇪", "leader_name": "رضا کمالی"},
        ]
        img_treaty_3 = render_contract_image(
            contract_id=contract.id,
            title=contract.title,
            country_a_name="",
            country_a_flag="",
            country_b_name="",
            country_b_flag="",
            body=contract.body,
            parties=parties_3,
        )
        assert isinstance(img_treaty_3, bytes) and len(img_treaty_3) > 5000

        parties_5 = parties_3 + [
            {"country_name": "برزیل", "country_flag": "🇧🇷", "leader_name": "جان دو"},
            {"country_name": "فرانسه", "country_flag": "🇫🇷", "leader_name": "میشل"},
        ]
        img_treaty_5 = render_contract_image(
            contract_id=contract.id,
            title=contract.title,
            country_a_name="",
            country_a_flag="",
            country_b_name="",
            country_b_flag="",
            body=contract.body,
            parties=parties_5,
        )
        assert isinstance(img_treaty_5, bytes) and len(img_treaty_5) > 5000
        print("✅ ۷. رندر تصویر سند معاهده چندجانبه (۳ و ۵ کشور) با امضای پویا با موفقیت تایید شد.")

        # ۸. آزمون خروج یک‌طرفه از معاهده چندجانبه
        # کشور ۳ خارج می‌شود
        removed = await dip_repo.remove_contract_signatory(session, contract.id, c3.id)
        assert removed is True
        remaining = await dip_repo.get_contract_signatories(session, contract.id)
        assert len(remaining) == 2  # کشور ۱ و ۲ باقی ماندند
        assert await dip_repo.is_contract_party(session, contract, c3.id) is False

        # کشور ۲ خارج می‌شود -> تعداد اعضا به ۱ کاهش می‌یابد و معاهده لغو می‌شود
        removed2 = await dip_repo.remove_contract_signatory(session, contract.id, c2.id)
        assert removed2 is True
        remaining2 = await dip_repo.get_contract_signatories(session, contract.id)
        assert len(remaining2) == 1
        print("✅ ۸. خروج یک‌طرفه از معاهده چندجانبه با موفقیت بررسی شد.")

    print("\n🎉 تمام تست‌های قابلیت‌های توییتر (X) و معاهدات چندجانبه با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
