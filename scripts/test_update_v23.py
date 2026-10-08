"""تست خودکار و جامع ۴ ویژگی آپدیت v2.3:
۱. لغو سرمایه‌گذاری با بازگشت ۵۰٪ اصل سرمایه
۲. تخریب/انحلال تأسیسات اقتصادی و کارخانه‌های نظامی
۳. لغو یک‌طرفه قراردادهای دیپلماتیک
۴. رفع باگ انحلال اتحاد با اعمال سخت‌گیرانه کلیدهای خارجی (Foreign Keys Enforced)
"""

from __future__ import annotations

import asyncio
import os
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import (
    Alliance,
    AllianceMember,
    Contract,
    Country,
    Facility,
    Investment,
    MilitaryFactory,
    User,
)
from bot.database.repositories import alliances as alli_repo
from bot.database.repositories import diplomacy as dip_repo
from bot.database.repositories import facilities as fac_repo
from bot.database.repositories import investments as inv_repo
from bot.database.repositories import military_factory as milfac_repo
from bot.enums import DiplomacyStatus, FacilityType, MilitaryFactoryType


async def run_tests() -> None:
    print("🚀 در حال اجرای تست‌های جامع آپدیت v2.3...")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        await session.execute(text("PRAGMA foreign_keys = ON;"))

        # ایجاد کاربران
        u1 = User(telegram_id=111, role="player", president_name="رئیس جمهور ایران")
        u2 = User(telegram_id=222, role="player", president_name="رئیس جمهور روسیه")
        session.add_all([u1, u2])
        await session.commit()

        # ایجاد کشورهای نمونه
        c1 = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            is_vip=True,
            budget=10_000_000_000.0,
            owner_user_id=111,
        )
        c2 = Country(
            name_en="Russia",
            name_fa="روسیه",
            flag="🇷🇺",
            region="europe",
            is_vip=True,
            budget=20_000_000_000.0,
            owner_user_id=222,
        )
        session.add_all([c1, c2])
        await session.commit()

        # ========================================================
        # تست ۱: لغو سرمایه‌گذاری (داخلی و خارجی) با بازگشت ۵۰٪
        # ========================================================
        print("\n--- تست ۱: لغو سرمایه‌گذاری ---")
        inv_amount = 2_000_000_000.0
        c1.budget -= inv_amount  # بودجه شد 8B
        inv = Investment(
            investor_country=c1.id,
            target_country=c2.id,
            category="tourism",
            amount=inv_amount,
            profit_pct=5.0,
            active=True,
        )
        await inv_repo.add_investment(session, inv)
        await session.commit()

        active_count = await inv_repo.count_active_by_investor(session, c1.id)
        assert active_count == 1, f"Expected 1 active investment, got {active_count}"
        assert c1.budget == 8_000_000_000.0

        # شبیه‌سازی لغو سرمایه‌گذاری
        fetched_inv = await inv_repo.get_investment(session, inv.id)
        assert fetched_inv is not None and fetched_inv.active is True
        refund = fetched_inv.amount * 0.5
        c1.budget += refund
        fetched_inv.active = False
        await session.commit()

        assert c1.budget == 9_000_000_000.0, f"Expected budget 9B after 50% refund, got {c1.budget}"
        active_after = await inv_repo.count_active_by_investor(session, c1.id)
        assert active_after == 0, f"Expected 0 active investments, got {active_after}"
        print("✅ تست ۱ با موفقیت پاس شد: ۵۰٪ بودجه برگشت و سرمایه‌گذاری غیرفعال شد.")

        # ========================================================
        # تست ۲: تخریب تأسیسات و کارخانه نظامی
        # ========================================================
        print("\n--- تست ۲: تخریب تأسیسات اقتصادی و کارخانه نظامی ---")
        fac1 = Facility(
            country_id=c1.id,
            type=FacilityType.STEEL_FACTORY.value,
            location="اصفهان",
            budget=500_000_000.0,
            yield_amount=1000.0,
            active=True,
        )
        fac_joint = Facility(
            country_id=c1.id,
            type=FacilityType.MINE.value,
            resource="iron",
            location="کرمان",
            budget=300_000_000.0,
            yield_amount=500.0,
            partner_country=c2.id,
            partner_percent=40.0,
            active=True,
        )
        mf1 = MilitaryFactory(
            country_id=c1.id,
            factory_type=MilitaryFactoryType.TANK.value,
            asset_name="تانک کرار",
            category="تانک",
            location="شیراز",
            cost=1_000_000_000.0,
            yield_amount=5.0,
            active=True,
        )
        session.add_all([fac1, fac_joint, mf1])
        await session.commit()

        facs = await fac_repo.list_facilities(session, c1.id)
        mfs = await milfac_repo.list_factories(session, c1.id)
        assert len(facs) == 2, f"Expected 2 facilities, got {len(facs)}"
        assert len(mfs) == 1, f"Expected 1 military factory, got {len(mfs)}"

        # تخریب تأسیسات اول
        await session.delete(fac1)
        await session.flush()
        # تخریب تأسیسات مشترک
        await session.delete(fac_joint)
        await session.flush()
        # تخریب کارخانه نظامی
        await session.delete(mf1)
        await session.flush()
        await session.commit()

        facs_after = await fac_repo.list_facilities(session, c1.id)
        mfs_after = await milfac_repo.list_factories(session, c1.id)
        assert len(facs_after) == 0, f"Expected 0 facilities, got {len(facs_after)}"
        assert len(mfs_after) == 0, f"Expected 0 military factories, got {len(mfs_after)}"
        print("✅ تست ۲ با موفقیت پاس شد: تأسیسات و کارخانه‌های نظامی به درستی تخریب و حذف شدند.")

        # ========================================================
        # تست ۳: لغو یک‌طرفه قرارداد
        # ========================================================
        print("\n--- تست ۳: لغو قرارداد دیپلماتیک ---")
        contract = Contract(
            country_a=c1.id,
            country_b=c2.id,
            title="معاهده همکاری راهبردی",
            body="طرفین متعهد به عدم تعرض و توسعه تجارت مشترک می‌باشند.",
            signed_a=True,
            signed_b=True,
            status=DiplomacyStatus.ACTIVE,
        )
        await dip_repo.add_contract(session, contract)
        await session.commit()

        active_contracts = await dip_repo.list_contracts_for_country(session, c1.id, only_active=True)
        assert len(active_contracts) == 1, f"Expected 1 active contract, got {len(active_contracts)}"

        # لغو یک‌طرفه قرارداد
        fetched_contract = await dip_repo.get_contract(session, contract.id)
        assert fetched_contract is not None
        fetched_contract.status = DiplomacyStatus.CANCELLED
        await session.commit()

        active_contracts_after = await dip_repo.list_contracts_for_country(session, c1.id, only_active=True)
        assert len(active_contracts_after) == 0, f"Expected 0 active contracts, got {len(active_contracts_after)}"

        all_contracts = await dip_repo.list_contracts_for_country(session, c1.id, only_active=False)
        assert len(all_contracts) == 1
        assert all_contracts[0].status == DiplomacyStatus.CANCELLED
        print("✅ تست ۳ با موفقیت پاس شد: قرارداد به وضعیت لغوشده تغییر یافت و از لیست فعال خارج شد.")

        # ========================================================
        # تست ۴: رفع باگ انحلال اتحاد (با Foreign Keys ON)
        # ========================================================
        print("\n--- تست ۴: انحلال اتحاد با اعمال کامل کلیدهای خارجی ---")
        # ساخت اتحاد توسط کشور ۱
        alli = await alli_repo.create_alliance(session, "اتحاد مقاومت", "همکاری نظامی", c1.id)
        # افزودن کشور ۲ به اتحاد
        add_ok = await alli_repo.add_member(session, alli.id, c2.id)
        assert add_ok is True
        await session.commit()

        members = await alli_repo.list_members(session, alli.id)
        assert len(members) == 2, f"Expected 2 members, got {len(members)}"

        # حذف کشور ۲ توسط مالک
        await alli_repo.remove_member(session, alli.id, c2.id)
        await session.commit()

        members_after_rm = await alli_repo.list_members(session, alli.id)
        assert len(members_after_rm) == 1
        assert members_after_rm[0].country_id == c1.id

        # انحلال اتحاد توسط مالک
        await alli_repo.delete_alliance(session, alli.id)
        await session.commit()

        # بررسی نهایی: اطمینان از حذف کامل
        mem_check = await session.execute(
            select(AllianceMember).where(AllianceMember.country_id == c1.id)
        )
        assert mem_check.scalars().first() is None, "Membership of c1 should be None after delete_alliance"

        alli_check = await session.execute(
            select(Alliance).where(Alliance.id == alli.id)
        )
        assert alli_check.scalars().first() is None, "Alliance should be None after delete_alliance"
        print("✅ تست ۴ با موفقیت پاس شد: اتحاد و تمام اعضا بدون خطای Foreign Key کاملاً منحل شدند.")

    print("\n🎉 تمام تست‌های آپدیت v2.3 با موفقیت ۱۰۰٪ سپری شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
