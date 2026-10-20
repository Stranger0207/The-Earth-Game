"""
تست بررسی رفع باگ پذیرش دعوت سازمان ملل، پرواز به نیویورک و نمایش در پنل گاد مود.
"""

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, r"c:\Users\ARASH\earth_game_bot")

from bot.database.base import async_session_factory
from bot.database.models import Country, User
from bot.database.models.united_nations import UNAssemblyParticipant, UNAssemblySession
from bot.database.repositories import united_nations as un_repo
from bot.handlers.godmode import cb_arrive_now
from bot.handlers.united_nations import cb_asmb_fly
from sqlalchemy import delete, select


async def run_test():
    print("=== شروع تست رفع باگ پرواز مجمع عمومی سازمان ملل ===")

    async with async_session_factory() as session:
        # ۱. آماده‌سازی کشور و کاربر چین
        china = (await session.execute(select(Country).where(Country.name_en == "China"))).scalars().first()
        assert china is not None, "کشور چین پیدا نشد!"

        # ساخت یا یافتن کاربر مالک چین
        test_user = (await session.execute(select(User).where(User.telegram_id == 999999123))).scalars().first()
        if not test_user:
            test_user = User(
                telegram_id=999999123,
                username="test_china_president",
                first_name="China Leader",
            )
            session.add(test_user)
            await session.flush()

        china.owner_user_id = test_user.telegram_id
        china.is_claimed = True
        await session.flush()

        # ۲. ایجاد یک اجلاس مجمع عمومی
        # پاک‌سازی شرکت‌کنندگان قبلی
        await session.execute(delete(UNAssemblyParticipant).where(UNAssemblyParticipant.country_id == china.id))
        session_obj = UNAssemblySession(
            session_number=88,
            status="pending",
            title="اجلاس مجمع عمومی آزمایشی",
            started_at=datetime.now(timezone.utc),
        )
        session.add(session_obj)
        await session.flush()
        session_id = session_obj.id
        await session.commit()
        print(f"✅ اجلاس آزمایشی با شناسه #{session_id} ایجاد شد.")

    # ۳. تست اجرای هندلر cb_asmb_fly
    async with async_session_factory() as session:
        # ساخت Mock CallbackQuery
        call = AsyncMock()
        call.data = f"asmb_fly:{session_id}"
        call.from_user = MagicMock(id=test_user.telegram_id)
        call.message = AsyncMock()
        call.message.edit_text = AsyncMock()

        # اجرای هندلر
        print("در حال اجرای cb_asmb_fly...")
        await cb_asmb_fly(call, session, test_user)
        await session.commit()
        print("✅ cb_asmb_fly بدون خطا اجرا شد و commit گردید!")

    # ۴. بررسی ذخیره‌سازی پرواز در دیتابیس
    async with async_session_factory() as session:
        part = await un_repo.get_participant(session, session_id, china.id)
        assert part is not None, "شرکت‌کننده در دیتابیس ذخیره نشد!"
        assert part.status == "in_flight", f"وضعیت پرواز نادرست است: {part.status}"
        print(f"✅ شرکت‌کننده در دیتابیس ثبت شد با وضعیت '{part.status}' و شناسه #{part.id}")

        # ۵. بررسی رویت پرواز در پنل گاد مود (کد موجود در god:flights)
        un_participants = (await session.execute(
            select(UNAssemblyParticipant).where(UNAssemblyParticipant.status == "in_flight")
        )).scalars().all()
        found_in_god = any(p.id == part.id for p in un_participants)
        assert found_in_god, "پرواز در لیست پروازهای گاد مود مشاهده نشد!"
        print("✅ پرواز در لیست پروازهای پنل گاد مود (god:flights) با موفقیت رویت شد!")

        # ۶. تست رساندن فوری پرواز از پنل گاد مود (garrive:unasmb)
        god_call = AsyncMock()
        god_call.data = f"garrive:unasmb:{part.id}"
        god_call.from_user = MagicMock(id=8645723547)  # ادمین مجاز
        god_call.message = AsyncMock()

        print("در حال تست رساندن فوری پرواز با cb_arrive_now...")
        await cb_arrive_now(god_call, session)
        await session.commit()

    # ۷. بررسی وضعیت نهایی پس از فرود آمدن
    async with async_session_factory() as session:
        part_after = await un_repo.get_participant(session, session_id, china.id)
        assert part_after.status == "in_new_york", f"پرواز فرود نیامد! وضعیت فعلی: {part_after.status}"
        print(f"✅ پرواز با موفقیت در نیویورک فرود آمد! وضعیت نهایی: {part_after.status}")

        # ۸. پاک‌سازی داده‌های تست
        await session.execute(delete(UNAssemblyParticipant).where(UNAssemblyParticipant.session_id == session_id))
        await session.execute(delete(UNAssemblySession).where(UNAssemblySession.id == session_id))
        await session.commit()
        print("✅ داده‌های تست با موفقیت پاک‌سازی شدند.")

    print("\n🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_test())
