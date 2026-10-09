"""تست جامع گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

import asyncio
import os

os.environ["BOT_TOKEN"] = "123456:ABC-test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"

from bot.database.base import async_session_factory, init_db
from bot.database.models import User
from bot.database.repositories import cabinet as cabinet_repo, users as users_repo
from bot.enums import CabinetRole
from bot.services.cabinet_service import can_access_domain, perform_doge_audit, set_defcon_level, get_defcon_level


async def run_tests():
    print("🚀 در حال اجرای تست‌های گیم‌مود مقاماتی...")
    await init_db()

    async with async_session_factory() as session:
        # ۱. ساخت کاربر نمونه
        user1 = await users_repo.get_or_create_user(session, telegram_id=9901, username="player_trump", first_name="Donald")
        user2 = await users_repo.get_or_create_user(session, telegram_id=9902, username="player_bessent", first_name="Scott")
        user3 = await users_repo.get_or_create_user(session, telegram_id=9903, username="player_rubio", first_name="Marco")
        await session.commit()

        # ۲. مقداردهی اولیه ۱۵ مقام
        members = await cabinet_repo.list_members(session)
        assert len(members) == 15, f"Expected 15 cabinet roles, got {len(members)}"
        print(f"✅ تست ۱: هر ۱۵ سمت فدرال با موفقیت ایجاد و لیست شدند.")

        # ۳. تصدی سمت (Claim)
        ok_claim1 = await cabinet_repo.claim_member_role(session, CabinetRole.PRESIDENT.value, user1.telegram_id)
        assert ok_claim1 is True, "Trump should be able to claim President role"
        ok_claim2 = await cabinet_repo.claim_member_role(session, CabinetRole.TREASURY_SECRETARY.value, user2.telegram_id)
        assert ok_claim2 is True, "Bessent should be able to claim Treasury role"
        ok_claim3 = await cabinet_repo.claim_member_role(session, CabinetRole.SECRETARY_STATE.value, user3.telegram_id)
        assert ok_claim3 is True, "Rubio should be able to claim State role"

        # جلوگیری از تصدی سمت اشغال‌شده
        ok_dup = await cabinet_repo.claim_member_role(session, CabinetRole.PRESIDENT.value, 9999)
        assert ok_dup is False, "Occupied role should not be claimable"
        print("✅ تست ۲: تصدی سمت‌ها و جلوگیری از اشغال همزمان به درستی بررسی شد.")

        # ۴. تست تفکیک دسترسی به حوزه‌های اطلاعاتی (Compartmentalization)
        assert can_access_domain(CabinetRole.PRESIDENT.value, "economy") is True
        assert can_access_domain(CabinetRole.TREASURY_SECRETARY.value, "economy") is True
        assert can_access_domain(CabinetRole.SECRETARY_STATE.value, "economy") is False, "Rubio should not directly view economy"
        assert can_access_domain(CabinetRole.SECRETARY_STATE.value, "diplomacy") is True
        print("✅ تست ۳: تفکیک دسترسی به حوزه‌های اطلاعاتی با موفقیت تایید شد.")

        # ۵. تست مکاتبات و استعلامات
        memo = await cabinet_repo.create_memo(
            session,
            sender_role="president",
            recipient_role="all",
            sender_user_id=user1.telegram_id,
            subject="فرمان اول",
            body="جلسه کابینه راس ساعت ۸",
        )
        inbox = await cabinet_repo.list_memos_for_role(session, "treasury_secretary")
        assert len(inbox) >= 1
        print("✅ تست ۴: ثبت و دریافت یادداشت‌های درون‌سازمانی با موفقیت انجام شد.")

        # ۶. تست استعلام اطلاعات
        inquiry = await cabinet_repo.create_inquiry(
            session,
            from_role="secretary_state",
            to_role="treasury_secretary",
            sender_user_id=user3.telegram_id,
            topic="بودجه ماموریت خارجی",
            question="آیا بودجه سفر تایید است؟",
        )
        assert inquiry.status == "pending"
        ans_ok = await cabinet_repo.answer_inquiry(session, inquiry.id, "بله، ۱۰۰ میلیون دلار تخصیص یافت.")
        assert ans_ok is True
        updated_inq = await cabinet_repo.get_inquiry(session, inquiry.id)
        assert updated_inq.status == "answered"
        print("✅ تست ۵: چرخه ارسال و پاسخ استعلام اطلاعات رسمی تایید شد.")

        # ۷. تست ممیزی DOGE و DEFCON
        audit = perform_doge_audit("treasury_secretary")
        assert audit["savings"] > 0
        set_defcon_level(2)
        assert get_defcon_level() == 2
        print("✅ تست ۶: محاسبات ممیزی DOGE و سطح DEFCON به درستی عمل کردند.")

        # ۸. تست استعفا
        vac_ok = await cabinet_repo.vacate_member_role(session, CabinetRole.PRESIDENT.value)
        assert vac_ok is True
        pres = await cabinet_repo.get_member_by_role(session, CabinetRole.PRESIDENT.value)
        assert pres.user_id is None
        print("✅ تست ۷: استعفا و آزادسازی سمت فدرال با موفقیت تایید شد.")

        await session.commit()

    print("🎉 تمام تست‌های گیم‌مود مقاماتی با موفقیت ۱۰۰٪ سپری شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
