"""
اسکریپت تست خودکار آپدیت شماره ۱۰:
۱. بررسی تعریف و مقادیر ۷ گروه مدیریتی در Settings و .env.example
۲. بررسی ثبت ستون photo_file_id در _COLUMN_MIGRATIONS و مدل ClaimRequest
۳. بررسی Enum گروه AdminGroupType و دیکشنری ADMIN_GROUP_FA
۴. بررسی ثابت‌های کشورگیری VIP (اطلاع‌رسانی چنل @GameOfEarth، شماره کارت و دارنده حساب)
۵. تست متدهای مسیریابی news_service (get_admin_group_id, send_to_admin_group, send_photo_to_admin_group)
۶. تست تفکیک فلوی کشورگیری عادی و VIP در handlers/claim.py:
   - انتخاب کشور عادی: رفتن به ورود نام رئیس‌جمهور
   - انتخاب کشور VIP: هدایت به وضعیت waiting_for_vip_receipt و نمایش متن اطلاع‌رسانی @GameOfEarth و کارت
   - ارسال متن در وضعیت waiting_for_vip_receipt: هشدار به کاربر جهت ارسال عکس
   - ارسال عکس در وضعیت waiting_for_vip_receipt: ثبت در دیتابیس و ارسال به گروه PAYMENT (-1004337037351)
۷. تست تأیید و رد درخواست کشورگیری VIP در handlers/admin.py:
   - تأیید: واگذاری کشور VIP، ویرایش کپشن عکس، ثبت لاگ در MAIN_LOG، بررسی global_freeze
   - رد: تغییر وضعیت به REJECTED، ویرایش کپشن عکس، اطلاع‌رسانی به کاربر
۸. تست هدایت رسید ماهواره اقتصادی به AdminGroupType.PAYMENT
۹. تست هدایت تحریم‌ها، تعرفه‌ها، لوایح و تغییر نظام به AdminGroupType.SANCTION_BILL
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["PYTHONUTF8"] = "1"
os.environ["LOG_GROUP_ID"] = "-1003922948542"
os.environ["SANCTION_BILL_GROUP_ID"] = "-1004474739499"
os.environ["ROLE_ECON_GROUP_ID"] = "-1004359181892"
os.environ["ROLE_ATTACK_GROUP_ID"] = "-1004424329237"
os.environ["ROLE_SABOTAGE_GROUP_ID"] = "-1004317304087"
os.environ["ROLE_SECURITY_GROUP_ID"] = "-1004317826815"
os.environ["PAYMENT_GROUP_ID"] = "-1004337037351"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import Settings, get_settings
from bot.constants import (
    VIP_CLAIM_CARD_HOLDER,
    VIP_CLAIM_CARD_NUMBER,
    VIP_CLAIM_PRICE_INFO,
)
from bot.database.base import Base, _COLUMN_MIGRATIONS
from bot.database.models import BotState, ClaimRequest, Country, User
from bot.database.repositories import claims as claims_repo
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import users as users_repo
from bot.enums import ADMIN_GROUP_FA, AdminGroupType, ClaimStatus
from bot.handlers.admin import cb_vip_claim_approve, cb_vip_claim_reject
from bot.handlers.claim import (
    cb_pick_country,
    msg_vip_receipt_photo,
    msg_vip_receipt_text_warning,
)
from bot.services.news_service import (
    get_admin_group_id,
    send_photo_to_admin_group,
    send_to_admin_group,
)
from bot.states import ClaimForm


async def run_tests() -> None:
    passed = 0
    total = 0

    def assert_check(condition: bool, msg: str) -> None:
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            raise AssertionError(f"Check failed: {msg}")

    print("\n--- بخش ۱: بررسی تنظیمات و گروههای ۷گانه ---")
    st = get_settings()
    assert_check(st.sanction_bill_group_id == -1004474739499, "گروه ۱: SANCTION_BILL_GROUP_ID درست است")
    assert_check(st.log_group_id == -1003922948542, "گروه ۲: LOG_GROUP_ID موجود درست است")
    assert_check(st.role_econ_group_id == -1004359181892, "گروه ۳: ROLE_ECON_GROUP_ID درست است")
    assert_check(st.role_attack_group_id == -1004424329237, "گروه ۴: ROLE_ATTACK_GROUP_ID درست است")
    assert_check(st.role_sabotage_group_id == -1004317304087, "گروه ۵: ROLE_SABOTAGE_GROUP_ID درست است")
    assert_check(st.role_security_group_id == -1004317826815, "گروه ۶: ROLE_SECURITY_GROUP_ID درست است")
    assert_check(st.payment_group_id == -1004337037351, "گروه ۷: PAYMENT_GROUP_ID درست است")

    print("\n--- بخش ۲: بررسی Enum و متادیتا ---")
    assert_check(len(AdminGroupType) == 7, "تعداد گروههای Enum برابر ۷ است")
    assert_check(AdminGroupType.PAYMENT.value == "payment", "مقدار AdminGroupType.PAYMENT درست است")
    assert_check(AdminGroupType.SANCTION_BILL.value == "sanction_bill", "مقدار AdminGroupType.SANCTION_BILL درست است")
    for gt in AdminGroupType:
        assert_check(gt in ADMIN_GROUP_FA, f"نام فارسی گروه {gt.name} در ADMIN_GROUP_FA موجود است")

    print("\n--- بخش ۳: بررسی ثابت‌های کشورگیری VIP ---")
    assert_check("@GameOfEarth" in VIP_CLAIM_PRICE_INFO, "متن قیمت کشورگیری VIP شامل چنل @GameOfEarth است")
    assert_check(VIP_CLAIM_CARD_NUMBER == "6219861843148577", "شماره کارت رضائی درست است")
    assert_check(VIP_CLAIM_CARD_HOLDER == "رضائی", "نام دارنده حساب درست است")

    print("\n--- بخش ۴: بررسی دیتابیس و مهاجرت ستون photo_file_id ---")
    migration_found = any(m[0] == "claim_requests" and m[1] == "photo_file_id" for m in _COLUMN_MIGRATIONS)
    assert_check(migration_found, "ستون photo_file_id در _COLUMN_MIGRATIONS ثبت شده است")
    assert_check(hasattr(ClaimRequest, "photo_file_id"), "فیلد photo_file_id روی مدل ClaimRequest موجود است")

    print("\n--- بخش ۵: بررسی تابع مپینگ و ارسال گروه‌ها در news_service ---")
    assert_check(get_admin_group_id(AdminGroupType.SANCTION_BILL) == -1004474739499, "مپینگ SANCTION_BILL درست کار می‌کند")
    assert_check(get_admin_group_id(AdminGroupType.PAYMENT) == -1004337037351, "مپینگ PAYMENT درست کار می‌کند")
    assert_check(get_admin_group_id(AdminGroupType.MAIN_LOG) == -1003922948542, "مپینگ MAIN_LOG درست کار می‌کند")

    fake_bot = AsyncMock()
    fake_msg = MagicMock()
    fake_msg.message_id = 999
    fake_bot.send_message.return_value = fake_msg
    fake_bot.send_photo.return_value = fake_msg

    res_txt = await send_to_admin_group(fake_bot, AdminGroupType.SANCTION_BILL, "تست متن")
    assert_check(res_txt is not None, "send_to_admin_group خروجی Message برگرداند")
    fake_bot.send_message.assert_called_with(-1004474739499, "تست متن", reply_markup=None)

    res_photo = await send_photo_to_admin_group(fake_bot, AdminGroupType.PAYMENT, photo="photo123", caption="کپشن رسید")
    assert_check(res_photo is not None, "send_photo_to_admin_group خروجی Message برگرداند")
    fake_bot.send_photo.assert_called_with(-1004337037351, photo="photo123", caption="کپشن رسید", reply_markup=None)

    print("\n--- بخش ۶: راه‌اندازی دیتابیس تست SQLite و سید داده‌ها ---")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        # ساخت وضعیت بات
        state_row = BotState(id=1, global_freeze=False)
        session.add(state_row)

        # ساخت کاربر
        user = User(telegram_id=777, username="vip_player", first_name="Ali")
        session.add(user)

        # ساخت کشور عادی و کشور VIP
        country_normal = Country(
            id=10, name_en="Canada", name_fa="کانادا", flag="🇨🇦",
            region="americas", is_vip=False, is_claimed=False,
        )
        country_vip = Country(
            id=20, name_en="USA", name_fa="ایالات متحده آمریکا", flag="🇺🇸",
            region="americas", is_vip=True, is_claimed=False,
        )
        session.add_all([country_normal, country_vip])
        await session.commit()

    print("\n--- بخش ۷: تست فلوی کشورگیری عادی و VIP در claim.py ---")
    # ۱. تست کلیک روی کشور عادی: باید نام رئیس‌جمهور را بپرسد
    async with session_maker() as session:
        fsm_state = AsyncMock()
        fsm_data = {}

        async def fake_update_data(**kwargs):
            fsm_data.update(kwargs)

        async def fake_get_data():
            return fsm_data

        fsm_state.update_data.side_effect = fake_update_data
        fsm_state.get_data.side_effect = fake_get_data

        call_normal = MagicMock()
        call_normal.data = "claim_pick:10"
        call_normal.answer = AsyncMock()
        call_normal.message = MagicMock()
        call_normal.message.answer = AsyncMock()

        await cb_pick_country(call_normal, fsm_state, session)
        fsm_state.set_state.assert_called_with(ClaimForm.entering_president_name)
        call_normal.message.answer.assert_called()
        assert_check(fsm_data.get("country_id") == 10, "شناسه کشور عادی در state ذخیره شد")

    # ۲. تست کلیک روی کشور VIP: باید وارد waiting_for_vip_receipt شود و اطلاعات کارت و @GameOfEarth نمایش داده شود
    async with session_maker() as session:
        fsm_state = AsyncMock()
        fsm_data = {}
        fsm_state.update_data.side_effect = fake_update_data
        fsm_state.get_data.side_effect = fake_get_data

        call_vip = MagicMock()
        call_vip.data = "claim_pick:20"
        call_vip.answer = AsyncMock()
        call_vip.message = MagicMock()
        call_vip.message.answer = AsyncMock()

        await cb_pick_country(call_vip, fsm_state, session)
        fsm_state.set_state.assert_called_with(ClaimForm.waiting_for_vip_receipt)
        vip_msg_text = call_vip.message.answer.call_args[0][0]
        assert_check("@GameOfEarth" in vip_msg_text, "پیام انتخاب کشور VIP شامل آدرس کانال @GameOfEarth است")
        assert_check("6219861843148577" in vip_msg_text, "پیام انتخاب کشور VIP شامل شماره کارت است")
        assert_check("رضائی" in vip_msg_text, "پیام انتخاب کشور VIP شامل نام رضائی است")
        assert_check(fsm_data.get("country_id") == 20, "شناسه کشور VIP در state ذخیره شد")

    # ۳. تست ارسال متن در وضعیت waiting_for_vip_receipt: هشدار ارسال تصویر
    msg_text_only = MagicMock()
    msg_text_only.answer = AsyncMock()
    await msg_vip_receipt_text_warning(msg_text_only)
    warn_text = msg_text_only.answer.call_args[0][0]
    assert_check("تصویر رسید" in warn_text, "هشدار ارسال عکس به کاربر نمایش داده شد")

    # ۴. تست ارسال عکس فیش کشور VIP: ثبت در دیتابیس و ارسال به گروه PAYMENT
    async with session_maker() as session:
        fsm_state = AsyncMock()
        fsm_data = {"country_id": 20}
        fsm_state.get_data.side_effect = fake_get_data
        fsm_state.clear = AsyncMock()

        msg_photo = MagicMock()
        msg_photo.from_user.id = 777
        msg_photo.from_user.username = "vip_player"
        msg_photo.from_user.first_name = "Ali"
        fake_photo_size = MagicMock()
        fake_photo_size.file_id = "receipt_telegram_file_id_999"
        msg_photo.photo = [fake_photo_size]
        msg_photo.answer = AsyncMock()

        user_obj = await users_repo.get_user(session, 777)

        with patch("bot.handlers.claim.send_photo_to_admin_group", new_callable=AsyncMock) as mock_send_photo:
            await msg_vip_receipt_photo(msg_photo, fsm_state, session, user_obj)
            await session.commit()

            # بررسی ارسال به گروه PAYMENT
            mock_send_photo.assert_called_once()
            args, kwargs = mock_send_photo.call_args
            assert_check(args[1] == AdminGroupType.PAYMENT, "تصویر رسید به گروه AdminGroupType.PAYMENT فرستاده شد")
            assert_check(kwargs.get("photo") == "receipt_telegram_file_id_999", "شناسه عکس فیش صحیح است")
            assert_check("@GameOfEarth" in kwargs.get("caption", ""), "کپشن عکس فیش شامل @GameOfEarth است")

            # بررسی ذخیره رکورد در دیتابیس
            claim_rec = await claims_repo.get_pending_for_user(session, 777)
            assert_check(claim_rec is not None, "درخواست ClaimRequest در دیتابیس ساخته شد")
            assert_check(claim_rec.country_id == 20, "درخواست برای کشور VIP شماره ۲۰ است")
            assert_check(claim_rec.photo_file_id == "receipt_telegram_file_id_999", "شناسه عکس در ClaimRequest ذخیره شد")
            assert_check(claim_rec.status == ClaimStatus.PENDING, "وضعیت درخواست PENDING است")
            vip_claim_id = claim_rec.id

    print("\n--- بخش ۸: تست تأیید و رد درخواست کشورگیری VIP در admin.py ---")
    # ۱. تست تأیید توسط ادمین در گروه پرداختی‌ها
    async with session_maker() as session:
        admin_call = MagicMock()
        admin_call.from_user.id = 111  # مالک در Settings
        admin_call.from_user.full_name = "Admin Owner"
        admin_call.data = f"vip_claim_approve:{vip_claim_id}"
        admin_call.answer = AsyncMock()
        admin_call.message = MagicMock()
        admin_call.message.caption = "کپشن اولیه رسید"
        admin_call.message.edit_caption = AsyncMock()

        admin_db_user = await users_repo.get_user(session, 777)

        with patch("bot.handlers.admin.send_to_admin_group", new_callable=AsyncMock) as mock_log, \
             patch("bot.services.media.send_photo_news", new_callable=AsyncMock) as mock_welcome:
            await cb_vip_claim_approve(admin_call, session, admin_db_user)

            # بررسی واگذاری کشور
            c_vip = await countries_repo.get_country(session, 20)
            assert_check(c_vip.is_claimed is True, "کشور VIP به وضعیت claimed تغییر یافت")
            assert_check(c_vip.owner_user_id == 777, "مالکیت کشور به کاربر ۷۷۷ واگذار شد")

            # بررسی تغییر وضعیت claim
            c_req = await claims_repo.get_claim(session, vip_claim_id)
            assert_check(c_req.status == ClaimStatus.APPROVED, "وضعیت درخواست به APPROVED تغییر یافت")

            # بررسی ویرایش کپشن در گروه پرداختی‌ها
            admin_call.message.edit_caption.assert_called_once()
            caption_updated = admin_call.message.edit_caption.call_args[1]["caption"]
            assert_check("تأیید شد" in caption_updated, "کپشن عکس در گروه پرداختی‌ها ویرایش و تایید شد")

            # بررسی ارسال لاگ به MAIN_LOG
            mock_log.assert_called_once()
            assert_check(mock_log.call_args[0][1] == AdminGroupType.MAIN_LOG, "لاگ واگذاری VIP به MAIN_LOG ارسال شد")

            # بررسی ارسال پیام خوش‌آمد به بازیکن
            mock_welcome.assert_called_once()
            assert_check(mock_welcome.call_args[0][1] == 777, "پیام تبریک و ورود به پنل به کاربر ارسال شد")

    # ۲. تست انجماد سراسری (global_freeze): اگر فعال باشد، کاربر پس از دریافت VIP معلق می‌شود
    async with session_maker() as session:
        # فعالسازی global_freeze
        st_row = (await session.execute(select(BotState))).scalar_one()
        st_row.global_freeze = True

        # کاربر جدید و کشور VIP آزاد
        user2 = User(telegram_id=888, username="freeze_player", first_name="Reza")
        c_vip2 = Country(id=30, name_en="Russia", name_fa="روسیه", flag="🇷🇺", region="europe", is_vip=True, is_claimed=False)
        session.add_all([user2, c_vip2])
        await session.commit()

        claim2 = await claims_repo.create_claim(session, 888, 30, "Reza", None, "file_photo_2")
        await session.commit()

        admin_call2 = MagicMock()
        admin_call2.from_user.id = 111
        admin_call2.from_user.full_name = "Super Admin"
        admin_call2.data = f"vip_claim_approve:{claim2.id}"
        admin_call2.answer = AsyncMock()
        admin_call2.message = MagicMock()
        admin_call2.message.caption = "کپشن فیش دوم"
        admin_call2.message.edit_caption = AsyncMock()

        with patch("bot.handlers.admin.send_to_admin_group", new_callable=AsyncMock), \
             patch("bot.loader.bot.send_message", new_callable=AsyncMock) as mock_send_freeze_msg:
            await cb_vip_claim_approve(admin_call2, session, user2)

            u2_reloaded = await users_repo.get_user(session, 888)
            assert_check(u2_reloaded.is_suspended is True, "کاربر به دلیل global_freeze خودکار معلق (is_suspended=True) شد")
            mock_send_freeze_msg.assert_called()
            assert_check("معلق" in mock_send_freeze_msg.call_args[0][1], "پیام تعلیق انجماد به بازیکن ارسال شد")

    # ۳. تست رد درخواست کشورگیری VIP (vip_claim_reject)
    async with session_maker() as session:
        user3 = User(telegram_id=999, username="rejected_player", first_name="Kaveh")
        c_vip3 = Country(id=40, name_en="China", name_fa="چین", flag="🇨🇳", region="east_asia", is_vip=True, is_claimed=False)
        session.add_all([user3, c_vip3])
        await session.commit()

        claim3 = await claims_repo.create_claim(session, 999, 40, "Kaveh", None, "file_photo_3")
        await session.commit()

        admin_reject_call = MagicMock()
        admin_reject_call.from_user.id = 111
        admin_reject_call.from_user.full_name = "Finance Admin"
        admin_reject_call.data = f"vip_claim_reject:{claim3.id}"
        admin_reject_call.answer = AsyncMock()
        admin_reject_call.message = MagicMock()
        admin_reject_call.message.caption = "کپشن فیش ردشده"
        admin_reject_call.message.edit_caption = AsyncMock()

        with patch("bot.loader.bot.send_message", new_callable=AsyncMock) as mock_reject_user_msg:
            await cb_vip_claim_reject(admin_reject_call, session)

            claim3_reloaded = await claims_repo.get_claim(session, claim3.id)
            assert_check(claim3_reloaded.status == ClaimStatus.REJECTED, "وضعیت درخواست به REJECTED تغییر یافت")

            c_vip3_reloaded = await countries_repo.get_country(session, 40)
            assert_check(c_vip3_reloaded.is_claimed is False, "کشور همچنان آزاد (is_claimed=False) باقی ماند")

            admin_reject_call.message.edit_caption.assert_called_once()
            assert_check("رد شد" in admin_reject_call.message.edit_caption.call_args[1]["caption"], "کپشن عکس در گروه پرداختی‌ها به رد شد تغییر کرد")

            mock_reject_user_msg.assert_called_once()
            assert_check(mock_reject_user_msg.call_args[0][0] == 999, "پیام رد درخواست به کاربر ارسال شد")

    await engine.dispose()

    print("\n" + "=" * 60)
    print(f"🎉 کلیه تست‌های آپدیت شماره ۱۰ با موفقیت پاس شدند! ({passed}/{total})")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
