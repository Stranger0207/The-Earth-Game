"""
تست خودکار جامع رفع باگ دکمه تایید رول و تعیین بازدهی در پنل /roles
و اعتبارسنجی عدم وجود ارورهای CallbackQuery منجمد و AdminGroupType.
"""

import asyncio
import datetime
from datetime import timezone
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage, StorageKey
from aiogram.types import CallbackQuery, Chat, Message, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import add_dynamic_owner, get_settings
from bot.database.base import Base
from bot.database.models import Country, EconomicProject, User as DBUser
from bot.database.repositories import economic_projects as proj_repo
from bot.enums import AdminGroupType, EconomicProjectStatus
from bot.handlers.admin_roles import cb_roles_admin_econ_view
from bot.handlers.economic_projects import (
    cb_admin_approve_router,
    cb_admin_reject_router,
    cb_adm_confirm,
    cb_cfg_cash,
    cb_cfg_ycash,
    cb_grp_approve_menu,
    cb_grp_cancel,
    cb_set_cash_custom,
    cb_set_ycash,
    cb_set_ycash_custom,
    msg_custom_cash,
    msg_custom_yield,
)
from bot.loader import bot
from bot.services import news_service


def _make_msg(chat_id: int, text: str = "Test") -> Message:
    now = datetime.datetime.now(timezone.utc)
    chat = Chat(id=chat_id, type="private")
    msg = Message.model_construct(
        message_id=100,
        date=now,
        chat=chat,
        text=text,
        photo=None,
        document=None,
    )
    object.__setattr__(msg, "edit_text", AsyncMock())
    object.__setattr__(msg, "edit_reply_markup", AsyncMock())
    object.__setattr__(msg, "answer", AsyncMock())
    object.__setattr__(msg, "reply", AsyncMock())
    object.__setattr__(msg, "delete", AsyncMock())
    return msg


def _make_call(user_id: int, data: str, msg: Message) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name="Admin", username="admin_user")
    call = CallbackQuery.model_construct(
        id="call_test_1",
        from_user=user,
        chat_instance="inst_1",
        message=msg,
        data=data,
    )
    object.__setattr__(call, "answer", AsyncMock())
    return call


async def run_tests():
    passed = 0
    failed = 0

    def assert_true(cond: bool, desc: str):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✅ {desc}")
        else:
            failed += 1
            print(f"  ❌ {desc} (شرط برقرار نبود)")

    def assert_eq(actual, expected, desc: str):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
            print(f"  ✅ {desc}")
        else:
            failed += 1
            print(f"  ❌ {desc} | انتظار: {expected} ولی دریافت شد: {actual}")

    print("=" * 65)
    print("🚀 آزمون جامع رفع باگ تایید رول اقتصادی و تعیین بازدهی در /roles")
    print("=" * 65)

    # -------------------------------------------------------------
    # ۱. بررسی Enums و اسامی مستعار AdminGroupType
    # -------------------------------------------------------------
    print("\n📌 بخش ۱: بررسی تعریف و اسامی مستعار AdminGroupType:")
    assert_true(hasattr(AdminGroupType, "ROLE_ECON"), "AdminGroupType دارای عضو ROLE_ECON است")
    assert_true(hasattr(AdminGroupType, "ECONOMIC_PROJECTS"), "AdminGroupType دارای نام مستعار ECONOMIC_PROJECTS است")
    assert_eq(AdminGroupType.ECONOMIC_PROJECTS, AdminGroupType.ROLE_ECON, "ECONOMIC_PROJECTS معادل ROLE_ECON است")
    assert_true(hasattr(AdminGroupType, "MILITARY_ROLES"), "AdminGroupType دارای نام مستعار MILITARY_ROLES است")
    assert_eq(AdminGroupType.MILITARY_ROLES, AdminGroupType.ROLE_ATTACK, "MILITARY_ROLES معادل ROLE_ATTACK است")

    # -------------------------------------------------------------
    # ۲. راه‌اندازی دیتابیس درون‌حافظه‌ای
    # -------------------------------------------------------------
    print("\n📌 بخش ۲: راه‌اندازی دیتابیس و محیط تست ایزوله:")
    add_dynamic_owner(111)
    settings = get_settings()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        u_admin = DBUser(telegram_id=111, username="admin_user", first_name="Admin", is_admin=True, is_owner=True)
        u_player = DBUser(telegram_id=222, username="player_user", first_name="Player")
        c = Country(id=1, name_fa="ایران", name_en="Iran", flag="🇮🇷", region="middle_east", budget=1000.0, owner_user_id=222)
        p = EconomicProject(
            id=1,
            country_id=1,
            title="پروژه پتروشیمی خلیج فارس",
            proposed_budget=200.0,
            status=EconomicProjectStatus.PENDING_REVIEW.value,
            page_1="احداث مجتمع پتروشیمی جهت صادرات...",
        )
        session.add_all([u_admin, u_player, c, p])
        await session.commit()

    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    news_service.send_log = AsyncMock()
    storage = MemoryStorage()
    fsm_key = StorageKey(bot_id=1, chat_id=111, user_id=111)
    fsm_ctx = FSMContext(storage=storage, key=fsm_key)

    # -------------------------------------------------------------
    # ۳. تست منوی مشاهده رول در /roles و دکمه‌های اصلاح‌شده
    # -------------------------------------------------------------
    print("\n📌 بخش ۳: تست مشاهده رول اقتصادی در /roles و دکمه تایید/بازدهی:")
    async with Session() as session:
        db_user = await session.get(DBUser, 111)
        msg = _make_msg(111, text="نقشه‌های پنل")
        call = _make_call(111, "roles_admin:econ_v:1:1", msg)

        await cb_roles_admin_econ_view(call, session, db_user)

        assert_true(msg.edit_text.called, "پیام رول اقتصادی رندر گردید")
        call_args = msg.edit_text.call_args
        reply_markup = call_args[1].get("reply_markup") or call_args[0][1]
        buttons_map = {b.callback_data: b.text for row in reply_markup.inline_keyboard for b in row}

        assert_true("ep_grp_approve:1:panel" in buttons_map, "دکمه مستقیم تایید و بازدهی با پسوند :panel وجود دارد")
        assert_true("تایید رول و تعیین بازدهی" in buttons_map["ep_grp_approve:1:panel"], "عنوان دکمه به «تایید رول و تعیین بازدهی» تنظیم شده است")
        assert_true("ep_grp_reject:1:panel" in buttons_map, "دکمه رد رول با پسوند :panel وجود دارد")

    # -------------------------------------------------------------
    # ۴. تست کلیک روی دکمه «تایید رول و تعیین بازدهی»
    # -------------------------------------------------------------
    print("\n📌 بخش ۴: تست کلیک روی «تایید رول و تعیین بازدهی»:")
    async with Session() as session:
        msg = _make_msg(111, text="متن رول")
        call = _make_call(111, "ep_grp_approve:1:panel", msg)

        await cb_grp_approve_menu(call, session, fsm_ctx)

        assert_true(msg.edit_reply_markup.called, "کیبورد تنظیمات بازدهی و هزینه‌ها باز شد")
        kb = msg.edit_reply_markup.call_args[1]["reply_markup"]
        btn_data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert_true("ep_cfg_cash:1:panel" in btn_data, "دکمه تنظیم هزینه دلاری با پسوند :panel وجود دارد")
        assert_true("ep_cfg_ycash:1:panel" in btn_data, "دکمه تنظیم سود نقدی ۷۲ساعته با پسوند :panel وجود دارد")
        assert_true("ep_adm_confirm:1:panel" in btn_data, "دکمه صدور تاییدیه نهایی با پسوند :panel وجود دارد")

    # -------------------------------------------------------------
    # ۵. تست روتینگ سازگاری ep_admin_approve و ep_admin_reject
    # -------------------------------------------------------------
    print("\n📌 بخش ۵: تست سازگاری فراخوانی‌های قدیمی ep_admin_approve / ep_admin_reject:")
    async with Session() as session:
        msg1 = _make_msg(111, text="متن رول")
        call1 = _make_call(111, "ep_admin_approve:1", msg1)
        # این فراخوانی نباید با ValidationError منجمد متوقف شود
        await cb_admin_approve_router(call1, session, fsm_ctx)
        assert_true(msg1.edit_reply_markup.called, "فراخوانی ep_admin_approve بدون خطای مدل منجمد به منوی تایید هدایت شد")

        msg2 = _make_msg(111, text="متن رول")
        call2 = _make_call(111, "ep_admin_reject:1", msg2)
        await cb_admin_reject_router(call2, fsm_ctx)
        assert_true(msg2.edit_reply_markup.called, "فراخوانی ep_admin_reject بدون خطای مدل منجمد به دلایل رد هدایت شد")

    # -------------------------------------------------------------
    # ۶. تست تنظیم سود سریع (مثلاً ۲۰٪ بودجه = ۴۰M)
    # -------------------------------------------------------------
    print("\n📌 بخش ۶: تست انتخاب گزینه‌های سریع سود بازدهی:")
    async with Session() as session:
        msg = _make_msg(111, text="تنظیم سود")
        call = _make_call(111, "ep_set_ycash:1:40.0:panel", msg)

        await cb_set_ycash(call, session)

        proj = await proj_repo.get_project(session, 1)
        assert_eq(proj.yield_cash_72h, 40.0, "سود ۷۲ ساعته روی ۴۰ میلیون دلار تنظیم شد")

    # -------------------------------------------------------------
    # ۷. تست ورود سود دستی در مود پنل (is_panel = True)
    # -------------------------------------------------------------
    print("\n📌 بخش ۷: تست ورود دستی سود با FSM در مود پنل:")
    async with Session() as session:
        msg = _make_msg(111, text="درخواست ورود سود")
        call = _make_call(111, "ep_set_ycash_custom:1:panel", msg)

        await cb_set_ycash_custom(call, fsm_ctx)

        state_name = await fsm_ctx.get_state()
        assert_true("entering_custom_yield" in str(state_name), "استیت به entering_custom_yield تغییر یافت")

        state_data = await fsm_ctx.get_data()
        assert_true(state_data.get("is_panel") is True, "متغیر is_panel در استیت ذخیره گردید")

        text_msg = _make_msg(111, text="35M")
        await msg_custom_yield(text_msg, fsm_ctx, session)

        proj = await proj_repo.get_project(session, 1)
        assert_eq(proj.yield_cash_72h, 35_000_000.0, "سود نقدی دستی ۳۵ میلیون دلار با موفقیت اعمال شد")

    # -------------------------------------------------------------
    # ۸. تست تایید نهایی و صدور افتتاح در پنل /roles (cb_adm_confirm)
    # -------------------------------------------------------------
    print("\n📌 بخش ۸: تست تایید نهایی، افتتاح و ثبت بازدهی بدون خطای AdminGroupType:")
    async with Session() as session:
        msg = _make_msg(111, text="تایید نهایی")
        call = _make_call(111, "ep_adm_confirm:1:panel", msg)

        await cb_adm_confirm(call, session)

        proj = await proj_repo.get_project(session, 1)
        assert_eq(proj.status, EconomicProjectStatus.ACTIVE.value, "پروژه با موفقیت فعال (ACTIVE) گردید")

        c = await session.get(Country, 1)
        assert_eq(c.budget, 800.0, "هزینه افتتاح (۲۰۰M) از بودجه کشور کسر شد (بودجه جدید: ۸۰۰M)")
        assert_true(bot.send_message.called, "پیام تبریک افتتاح و ثبت بازدهی به پیوی بازیکن ارسال شد")

    # -------------------------------------------------------------
    # ۹. تست انصراف در مود پنل و وجود دکمه بازگشت به رول
    # -------------------------------------------------------------
    print("\n📌 بخش ۹: تست دکمه انصراف در مود پنل:")
    async with Session() as session:
        msg = _make_msg(111, text="انصراف")
        call = _make_call(111, "ep_grp_cancel:1:panel", msg)

        await cb_grp_cancel(call, session, fsm_ctx)

        call_args = msg.edit_text.call_args or msg.answer.call_args
        reply_markup = call_args[1].get("reply_markup") or call_args[0][1]
        buttons_cbs = [b.callback_data for row in reply_markup.inline_keyboard for b in row]
        assert_true("roles_admin:econ_v:1:1" in buttons_cbs, "دکمه بازگشت به رول اقتصادی در پیام انصراف تعبیه شده است")

    print("\n" + "=" * 65)
    print(f"🏁 نتیجه نهایی: {passed} آزمون موفق | {failed} آزمون ناموفق")
    print("=" * 65)

    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
