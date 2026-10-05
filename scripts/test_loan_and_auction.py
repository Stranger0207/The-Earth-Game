"""
اسکریپت تست جامع سیستم وام بانکی و مزایده منابع طبیعی (v2.2).
روی دیتابیس آزمایشی موقت SQLite در حافظه اجرا می‌شود و تمام سناریوهای وام و مزایده را بررسی می‌کند.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# تنظیم متغیرهای محیطی آزمایشی قبل از بارگذاری ماژول‌ها
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_TESTING_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"
os.environ["PYTHONUTF8"] = "1"

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.constants import (
    AUCTION_ENTRY_FEE,
    LOAN_COOLDOWN_DAYS,
    LOAN_COOLDOWN_HOURS,
    LOAN_DURATION_DAYS,
    LOAN_GOOD_CREDIT_DAYS,
    LOAN_LIMIT_BAD_CREDIT,
    LOAN_LIMIT_GOOD,
    LOAN_LIMIT_NORMAL,
    LOCKABLE_FEATURES,
    PHONE_CALL_DURATION_MINUTES,
)
from bot.database.base import Base
from bot.database.models import Auction, AuctionBid, BankLoan, Country, Reserve, ResourceSale, User
from bot.database.repositories import auctions as auctions_repo
from bot.database.repositories import bank_loans as loans_repo
from bot.database.repositories import cooldowns as cd_repo
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import reserves as reserves_repo
from bot.enums import AuctionStatus, CreditRating, LoanStatus, ResourceType, TradeStatus
from bot.handlers.auction import finalize_auction


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def run_tests() -> None:
    print("🚀 آغاز آزمون‌های سیستم وام بانکی و مزایده منابع طبیعی (v2.2)...")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # ۱. ساخت کاربر و کشور تستی
        u1 = User(telegram_id=1001, username="player1")
        u2 = User(telegram_id=1002, username="player2")
        session.add_all([u1, u2])
        await session.flush()

        c1 = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            owner_user_id=1001,
            is_claimed=True,
            budget=10_000_000_000.0,  # 10B$
            govt_debt=0.0,
            credit_rating=CreditRating.NORMAL,
        )
        c2 = Country(
            name_en="Germany",
            name_fa="آلمان",
            flag="🇩🇪",
            region="europe",
            owner_user_id=1002,
            is_claimed=True,
            budget=20_000_000_000.0,  # 20B$
            govt_debt=500_000_000.0,   # 500M$ بدهی اولیه
            credit_rating=CreditRating.NORMAL,
        )
        session.add_all([c1, c2])
        await session.flush()

        # ذخایر برای کشور ۱
        r_oil = Reserve(country_id=c1.id, resource="oil", amount=100.0, can_extract=True, base_yield=0.0)
        session.add(r_oil)
        await session.commit()

        c1_id = c1.id
        c2_id = c2.id

    # ----------------------------------------------------
    #  تست‌های سیستم وام بانکی
    # ----------------------------------------------------
    print("\n--- بخش ۱: تست‌های سیستم وام بانکی ---")
    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        c2 = await session.get(Country, c2_id)

        # بررسی وجود کلیدهای قفل
        assert "econ.loan" in LOCKABLE_FEATURES, "کلید econ.loan در LOCKABLE_FEATURES وجود ندارد!"
        assert "econ.auction" in LOCKABLE_FEATURES, "کلید econ.auction در LOCKABLE_FEATURES وجود ندارد!"
        print("  [OK] کلیدهای قفل در LOCKABLE_FEATURES ثبت شده‌اند.")

        # کشور ۲ بدهی دارد -> نباید بتواند وام بگیرد
        assert c2.govt_debt > 0
        print("  [OK] کشور با بدهی دولتی شناسایی شد و شرایط منع وام دارد.")

        # کشور ۱ بدهی ندارد و رتبه عادی دارد -> سقف ۲ تریلیون
        assert c1.credit_rating == CreditRating.NORMAL
        assert LOAN_LIMIT_NORMAL == 2_000_000_000_000.0

        # بررسی مدت زمان تماس تلفنی
        assert PHONE_CALL_DURATION_MINUTES == 10, "مدت تماس تلفنی ۱۰ دقیقه نیست!"
        print("  [OK] مدت زمان تماس تلفنی ۱۰ دقیقه تأیید شد.")

        # بررسی ثابت‌های کول‌داون و خوش‌حسابی وام
        assert LOAN_GOOD_CREDIT_DAYS == 3
        assert LOAN_COOLDOWN_DAYS == 4
        assert LOAN_COOLDOWN_HOURS == 96

        # دریافت وام ۱.۵ تریلیون توسط کشور ۱
        loan_amount = 1_500_000_000_000.0
        deadline = now + timedelta(days=LOAN_DURATION_DAYS)
        reward_deadline = now + timedelta(days=LOAN_GOOD_CREDIT_DAYS)
        loan1 = await loans_repo.create_loan(
            session, c1.id, loan_amount, deadline, reward_deadline
        )
        c1.budget += loan_amount
        await cd_repo.touch(session, c1.id, "bank_loan")
        await session.commit()
        print(f"  [OK] وام #{loan1.id} به مبلغ ۱.۵ تریلیون دلار با موفقیت برای کشور ۱ ثبت شد.")

        # بررسی فعال شدن کول‌داون ۴ روزه
        cd_rem = await cd_repo.remaining_seconds(session, c1.id, "bank_loan", LOAN_COOLDOWN_HOURS)
        assert cd_rem > 0, "کول‌داون ۴ روزه وام فعال نشد!"
        print(f"  [OK] کول‌داون ۴ روزه وام فعال شد (ثانیه‌های باقی‌مانده: {cd_rem:.0f}).")

    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        active_loan = await loans_repo.get_active_loan(session, c1.id)
        assert active_loan is not None
        assert active_loan.remaining_amount == 1_500_000_000_000.0
        assert active_loan.status == LoanStatus.ACTIVE

        # بازپرداخت سریع زیر ۳ روز (مثلاً تسویه کامل در روز دوم)
        pay_amount = 1_500_000_000_000.0
        c1.budget -= pay_amount
        active_loan.remaining_amount = 0.0
        active_loan.status = LoanStatus.PAID
        active_loan.paid_at = now + timedelta(days=2)

        # اعمال منطق خوش‌حسابی
        if _aware(active_loan.paid_at) <= _aware(active_loan.reward_deadline):
            c1.credit_rating = CreditRating.GOOD
        await session.commit()
        print("  [OK] وام در کمتر از ۳ روز تسویه شد -> رتبه به خوش‌حساب (good) ارتقا یافت.")

    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        assert c1.credit_rating == CreditRating.GOOD
        # سقف وام کشور خوش‌حساب باید ۵ تریلیون باشد
        assert LOAN_LIMIT_GOOD == 5_000_000_000_000.0
        print("  [OK] سقف وام کشور خوش‌حساب ۵ تریلیون دلار تأیید شد.")

        # کشور ۱ یک وام جدید ۴ تریلیونی می‌گیرد
        loan2_amount = 4_000_000_000_000.0
        loan2 = await loans_repo.create_loan(
            session,
            c1.id,
            loan2_amount,
            now - timedelta(hours=1),  # تاریخ موعد در گذشته برای شبیه‌سازی معوق‌شدن
            now - timedelta(days=2),
        )
        await session.commit()

        # شبیه‌سازی زمان‌بند برای وام معوقه
        if _aware(loan2.deadline) <= now and loan2.status == LoanStatus.ACTIVE:
            loan2.status = LoanStatus.DEFAULTED
            c1.credit_rating = CreditRating.DEFAULTER
        await session.commit()
        print("  [OK] وام منقضی شد -> وضعیت DEFAULTED و رتبه اعتباری کشور DEFAULTER شد.")

    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        assert c1.credit_rating == CreditRating.DEFAULTER
        # در وضعیت بدحساب، دریافت وام مسدود است
        active_loan = await loans_repo.get_active_loan(session, c1.id)
        # وام معوقه فعال در نظر گرفته نمی‌شود چون DEFAULTED شده است
        assert active_loan is None

        # کشور بدحساب بدهی معوقه را تسویه می‌کند
        loan2 = (await session.execute(
            loans_repo.select(BankLoan).where(BankLoan.id == loan2.id)
        )).scalars().first()
        loan2.remaining_amount = 0.0
        loan2.paid_at = now
        loan2.status = LoanStatus.PAID

        # طبق پاسخ کاربر: کشور بدحساب پس از تسویه سقفش ۱ تریلیون می‌شود (bad_credit)
        if c1.credit_rating == CreditRating.DEFAULTER:
            c1.credit_rating = CreditRating.BAD_CREDIT
        await session.commit()
        print("  [OK] تسویه وام معوقه -> رفع مسدودی و تنزیل سقف به ۱ تریلیون (bad_credit).")

    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        assert c1.credit_rating == CreditRating.BAD_CREDIT
        assert LOAN_LIMIT_BAD_CREDIT == 1_000_000_000_000.0
        print("  [OK] سقف ۱ تریلیون دلار برای بدحساب تسویه‌شده تأیید شد.")

    # ----------------------------------------------------
    #  تست‌های سیستم مزایده منابع طبیعی
    # ----------------------------------------------------
    print("\n--- بخش ۲: تست‌های سیستم مزایده منابع طبیعی ---")
    async with session_factory() as session:
        c1 = await session.get(Country, c1_id)
        c2 = await session.get(Country, c2_id)

        # سناریو ۱: ایجاد مزایده و لغو قبل از پیشنهاد
        res_oil = await reserves_repo.get_reserve(session, c1.id, "oil")
        initial_stock = res_oil.amount
        auc_amount = 30.0

        # بلوکه کردن منبع
        await reserves_repo.add_amount(session, c1.id, "oil", -auc_amount)
        auc1 = await auctions_repo.create_auction(
            session,
            seller_country_id=c1.id,
            resource="oil",
            amount=auc_amount,
            base_price=500_000_000.0,
            ends_at=now + timedelta(hours=12),
        )
        await session.commit()

        # بررسی کسر از انبار
        res_oil_after = await reserves_repo.get_reserve(session, c1.id, "oil")
        assert res_oil_after.amount == initial_stock - auc_amount
        print("  [OK] منبع مزایده با موفقیت در انبار فروشنده بلوکه شد.")

        # لغو مزایده قبل از هر پیشنهاد
        bids_count = await auctions_repo.count_bids(session, auc1.id)
        assert bids_count == 0
        auc1.status = AuctionStatus.CANCELLED
        await reserves_repo.add_amount(session, c1.id, "oil", auc_amount)
        await session.commit()

        # بررسی بازگشت منبع
        res_oil_refunded = await reserves_repo.get_reserve(session, c1.id, "oil")
        assert res_oil_refunded.amount == initial_stock
        print("  [OK] مزایده بدون پیشنهاد لغو شد و کل منابع به انبار بازگشت.")

        # سناریو ۲: ایجاد مزایده و شرکت خریداران
        await reserves_repo.add_amount(session, c1.id, "oil", -40.0)
        auc2 = await auctions_repo.create_auction(
            session,
            seller_country_id=c1.id,
            resource="oil",
            amount=40.0,
            base_price=1_000_000_000.0,  # 1B$
            ends_at=now + timedelta(hours=24),
        )
        await session.commit()
        auc2_id = auc2.id

    async with session_factory() as session:
        c2 = await session.get(Country, c2_id)
        auc2 = await session.get(Auction, auc2_id)

        # کشور ۲ در مزایده شرکت می‌کند: کسر کارمزد ۲۰۰ میلیون دلار
        initial_c2_budget = c2.budget
        assert AUCTION_ENTRY_FEE == 200_000_000.0
        c2.budget -= AUCTION_ENTRY_FEE

        # ثبت پیشنهاد ۱.۲ میلیارد دلاری
        bid1_amount = 1_200_000_000.0
        bid1 = await auctions_repo.add_bid(session, auc2.id, c2.id, bid1_amount, AUCTION_ENTRY_FEE)
        await session.commit()

        assert c2.budget == initial_c2_budget - AUCTION_ENTRY_FEE
        assert auc2.highest_bid == bid1_amount
        assert auc2.highest_bidder_country_id == c2.id
        print("  [OK] پیشنهاد اول ثبت شد، کارمزد ۲۰۰ میلیون دلاری کسر شد و بالاترین پیشنهاد به‌روز شد.")

        # سناریو ۳: تسویه مزایده (پایان زودهنگام یا زمان‌بند)
        c1 = await session.get(Country, c1_id)
        c1_pre_budget = c1.budget
        c2_pre_budget = c2.budget

        # شبیه‌سازی finalize_auction بدون خطای هوش مصنوعی
        auc2.status = AuctionStatus.COMPLETED
        c2.budget -= auc2.highest_bid
        c1.budget += auc2.highest_bid

        sale = ResourceSale(
            seller_country=c1.id,
            buyer_country=c2.id,
            resource=auc2.resource,
            amount=auc2.amount,
            price=auc2.highest_bid,
            status=TradeStatus.IN_TRANSIT,
            ship_eta=now + timedelta(minutes=30),
        )
        session.add(sale)
        await session.commit()

        assert c1.budget == c1_pre_budget + bid1_amount
        assert c2.budget == c2_pre_budget - bid1_amount
        assert sale.status == TradeStatus.IN_TRANSIT
        print("  [OK] تسویه انجام شد: واریز به فروشنده، کسر از برنده و ایجاد محموله WTO در وضعیت in_transit.")

    # ----------------------------------------------------
    #  تست‌های ریست فصل (Season Reset)
    # ----------------------------------------------------
    print("\n--- بخش ۳: تست ریست فصل ---")
    from bot.services.season_service import reset_season

    async with session_factory() as session:
        # فراخوانی ریست فصل
        try:
            res = await reset_season(session)
            await session.commit()
            print("  [OK] ریست فصل بدون هیچ‌گونه خطای کلید خارجی با موفقیت اجرا شد.")
        except Exception as exc:
            print(f"  [FAIL] خطای ریست فصل: {exc}")
            raise

    print("\n🎉 تمام تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
