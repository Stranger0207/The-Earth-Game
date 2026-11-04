"""
تست‌های جامع قفل دسترسی گروه‌ها (v2.12.0):
۱. بررسی شناسایی چت‌های داخلی (is_internal_chat و get_internal_chat_ids).
۲. ارزیابی دسترسی (evaluate_group_access): چت خصوصی، گروه معمولی، گروه داخلی، ادمین ناشناس، sender_chat.
۳. رفتار GroupAccessMiddleware روی Message، CallbackQuery، EditedMessage و عدم ثبت در جدول users.
۴. کال‌بک غیرمجاز: اجرای call.answer() خالی و توقف پردازش.
۵. هندلر my_chat_member: ارسال لاگ و خروج خودکار (leave_chat) و اثر تاگل AUTO_LEAVE_UNAUTHORIZED_GROUPS.
۶. کانال‌ها و عدم تداخل با channel_post.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# تنظیم متغیرهای محیطی آزمایشی
os.environ["BOT_TOKEN"] = "123456:TEST_ACCESS_GUARD"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["LOG_GROUP_ID"] = "-100111222333"
os.environ["ROLE_SECURITY_GROUP_ID"] = "-1004317826815"
os.environ["ROLE_ATTACK_GROUP_ID"] = "-1004424329237"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import add_dynamic_admin, get_settings
from bot.database.base import Base
from bot.database.models import User
from bot.database.repositories import users as users_repo
from bot.handlers.group_guard import on_my_chat_member_updated
from bot.middlewares.group_access import GroupAccessMiddleware
from bot.middlewares.user import UserMiddleware
from bot.utils.chat_access import (
    TELEGRAM_ANONYMOUS_BOT_ID,
    evaluate_group_access,
    get_internal_chat_ids,
    is_internal_chat,
)

_passed = 0
_failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passed
    if condition:
        _passed += 1
        print(f"  ✅ {label}")
    else:
        _failed.append(f"{label} — {detail}")
        print(f"  ❌ {label} — {detail}")


def make_mock_user(uid: int, username: str = "testuser", full_name: str = "Test User"):
    user = MagicMock()
    user.id = uid
    user.username = username
    user.first_name = "Test"
    user.full_name = full_name
    return user


def make_mock_chat(cid: int, chat_type: str = "supergroup", title: str = "Test Chat"):
    chat = MagicMock()
    chat.id = cid
    chat.type = chat_type
    chat.title = title
    return chat


async def run_tests() -> None:
    print("\n🔍 شروع تست‌های سیستم قفل دسترسی گروه‌ها (v2.12.0)...")
    settings = get_settings()

    # ۱) تست شناسایی چت‌های داخلی
    print("\n[بخش ۱] بررسی شناسایی چت‌های داخلی (Internal Chats)")
    internal_ids = get_internal_chat_ids()
    check("LOG_GROUP_ID در چت‌های داخلی است", -100111222333 in internal_ids)
    check("ROLE_SECURITY_GROUP_ID در چت‌های داخلی است", -1004317826815 in internal_ids)
    check("ROLE_ATTACK_GROUP_ID در چت‌های داخلی است", -1004424329237 in internal_ids)
    check("is_internal_chat برای شناسه معتبر کار می‌کند", is_internal_chat(-100111222333))
    check("is_internal_chat برای رشته عددی کار می‌کند", is_internal_chat("-100111222333"))
    check("is_internal_chat برای گروه متفرقه False است", not is_internal_chat(-100999999999))
    check("is_internal_chat برای None بدون خطا False است", not is_internal_chat(None))

    # ۲) تست ارزیابی دسترسی (evaluate_group_access)
    print("\n[بخش ۲] ارزیابی دسترسی (evaluate_group_access)")
    private_chat = make_mock_chat(111, chat_type="private")
    channel_chat = make_mock_chat(-100123456, chat_type="channel")
    regular_group = make_mock_chat(-100999999, chat_type="supergroup")
    internal_group = make_mock_chat(-100111222333, chat_type="supergroup")

    owner = make_mock_user(111, username="owner", full_name="Game Owner")
    admin = make_mock_user(222, username="admin", full_name="Game Admin")
    stranger = make_mock_user(333, username="stranger", full_name="Random Guy")
    anon_bot = make_mock_user(TELEGRAM_ANONYMOUS_BOT_ID, username="GroupAnonymousBot")

    # چت خصوصی
    check("پیوی: مالک مجاز است", evaluate_group_access(private_chat, owner))
    check("پیوی: ادمین مجاز است", evaluate_group_access(private_chat, admin))
    check("پیوی: کاربر عادی مجاز است", evaluate_group_access(private_chat, stranger))

    # کانال
    check("کانال: دسترسی مسدود نمی‌شود", evaluate_group_access(channel_chat, stranger))

    # گروه متفرقه
    check("گروه معمولی: مالک مجاز است", evaluate_group_access(regular_group, owner))
    check("گروه معمولی: ادمین غیرمالک مسدود است (DROP)", not evaluate_group_access(regular_group, admin))
    check("گروه معمولی: غریبه مسدود است (DROP)", not evaluate_group_access(regular_group, stranger))
    check("گروه معمولی: ادمین ناشناس تلگرام مسدود است", not evaluate_group_access(regular_group, anon_bot))
    check(
        "گروه معمولی: ارسال با sender_chat مسدود است",
        not evaluate_group_access(regular_group, owner, sender_chat=make_mock_chat(-100555)),
    )
    check("گروه معمولی: from_user خالی مسدود است", not evaluate_group_access(regular_group, None))

    # گروه داخلی
    check("گروه داخلی: مالک مجاز است", evaluate_group_access(internal_group, owner))
    check("گروه داخلی: ادمین مجاز است", evaluate_group_access(internal_group, admin))
    check("گروه داخلی: غریبه مسدود است", not evaluate_group_access(internal_group, stranger))
    check("گروه داخلی: ادمین ناشناس مسدود است", not evaluate_group_access(internal_group, anon_bot))

    # ادمین پویا در گروه داخلی
    add_dynamic_admin(444)
    dynamic_admin = make_mock_user(444, username="dynamic_admin")
    check("گروه داخلی: ادمین پویا مجاز است", evaluate_group_access(internal_group, dynamic_admin))
    check("گروه معمولی: ادمین پویا غیرمالک مسدود است", not evaluate_group_access(regular_group, dynamic_admin))

    # ۳) تست میدلور بیرونی GroupAccessMiddleware
    print("\n[بخش ۳] عملکرد میدلور GroupAccessMiddleware")
    middleware = GroupAccessMiddleware()
    handler_mock = AsyncMock(return_value="handler_executed")

    # تست ۱: پیام چت خصوصی
    msg_private = MagicMock()
    msg_private.chat = private_chat
    msg_private.from_user = stranger
    msg_private.sender_chat = None
    res = await middleware(handler_mock, msg_private, {"event_chat": private_chat, "event_from_user": stranger})
    check("میدلور در پیوی هندلر را صدا می‌زند", res == "handler_executed")
    handler_mock.reset_mock()

    # تست ۲: پیام در گروه معمولی از کاربر غریبه
    msg_group_stranger = MagicMock()
    msg_group_stranger.chat = regular_group
    msg_group_stranger.from_user = stranger
    msg_group_stranger.sender_chat = None
    res = await middleware(
        handler_mock,
        msg_group_stranger,
        {"event_chat": regular_group, "event_from_user": stranger},
    )
    check("میدلور در گروه متفرقه پیام غریبه را بیصدا DROP می‌کند", res is None)
    check("هندلر برای پیام غریبه صدا زده نشد", not handler_mock.called)
    handler_mock.reset_mock()

    # تست ۳: پیام در گروه معمولی از مالک
    msg_group_owner = MagicMock()
    msg_group_owner.chat = regular_group
    msg_group_owner.from_user = owner
    msg_group_owner.sender_chat = None
    res = await middleware(
        handler_mock,
        msg_group_owner,
        {"event_chat": regular_group, "event_from_user": owner},
    )
    check("میدلور پیام مالک در گروه را اجرا می‌کند", res == "handler_executed")
    handler_mock.reset_mock()

    # تست ۴: کال‌بک در گروه از کاربر غریبه (باید call.answer خالی بزند و return None)
    call_group_stranger = MagicMock()
    call_group_stranger.data = "test_btn"
    call_group_stranger.message = MagicMock()
    call_group_stranger.message.chat = regular_group
    call_group_stranger.from_user = stranger
    call_group_stranger.sender_chat = None
    call_group_stranger.answer = AsyncMock()

    res = await middleware(
        handler_mock,
        call_group_stranger,
        {"event_chat": regular_group, "event_from_user": stranger},
    )
    check("کال‌بک غیرمجاز DROP شد", res is None)
    check("کال‌بک غیرمجاز answer خالی دریافت کرد تا لودینگ نماند", call_group_stranger.answer.called)
    call_args = call_group_stranger.answer.call_args[0] if call_group_stranger.answer.call_args else ()
    check("متن answer کال‌بک خالی است", call_args == () or call_args == ("",))
    check("هندلر برای کال‌بک غیرمجاز اجرا نشد", not handler_mock.called)
    handler_mock.reset_mock()

    # تست ۵: ادیت پیام در گروه معمولی توسط غریبه
    edited_msg = MagicMock()
    edited_msg.chat = regular_group
    edited_msg.from_user = stranger
    edited_msg.sender_chat = None
    res = await middleware(
        handler_mock,
        edited_msg,
        {"event_chat": regular_group, "event_from_user": stranger},
    )
    check("edited_message از غریبه DROP شد", res is None)
    check("هندلر برای ادیت غریبه اجرا نشد", not handler_mock.called)
    handler_mock.reset_mock()

    # ۴) تست عدم ثبت کاربر در دیتابیس (عدم نفوذ غریبه به جدول users)
    print("\n[بخش ۴] بررسی عدم ثبت کاربر غریبه در دیتابیس")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    user_mw = UserMiddleware()
    async with session_factory() as session:
        # شبیه‌سازی زنجیره میدلور: GroupAccessMiddleware → UserMiddleware
        async def full_pipeline(event, data):
            async def call_user_mw(ev, dt):
                return await user_mw(handler_mock, ev, dt)
            return await middleware(call_user_mw, event, data)

        stranger_new = make_mock_user(987654, username="stranger_new")
        msg_foreign = MagicMock()
        msg_foreign.chat = regular_group
        msg_foreign.from_user = stranger_new
        msg_foreign.sender_chat = None

        data_dict = {
            "session": session,
            "event_chat": regular_group,
            "event_from_user": stranger_new,
        }

        res = await full_pipeline(msg_foreign, data_dict)
        check("پایپلاین برای غریبه مسدود شد", res is None)

        # اطمینان از اینکه کاربر در دیتابیس ثبت نشده است
        db_user = await users_repo.get_user(session, 987654)
        check("کاربر غریبه با حرف زدن در گروه وارد دیتابیس نشد", db_user is None)

    # ۵) تست هندلر my_chat_member
    print("\n[بخش ۵] تست هندلر my_chat_member و خروج خودکار")
    mock_bot = AsyncMock()

    # ۵.۱ افزودن به گروه معمولی توسط غریبه با AUTO_LEAVE=True
    event_add_stranger = MagicMock()
    event_add_stranger.chat = regular_group
    event_add_stranger.old_chat_member.status = "left"
    event_add_stranger.new_chat_member.status = "member"
    event_add_stranger.from_user = stranger

    with patch("bot.handlers.group_guard.send_log", new_callable=AsyncMock) as mock_send_log:
        await on_my_chat_member_updated(event_add_stranger, mock_bot)
        check("لاگ ارسال شد", mock_send_log.called)
        check("ربات از گروه غیرمجاز لفت داد (leave_chat)", mock_bot.leave_chat.called)
        check("leave_chat با chat.id صحیح فراخوانی شد", mock_bot.leave_chat.call_args[0][0] == regular_group.id)

    mock_bot.reset_mock()

    # ۵.۲ افزودن به گروه معمولی توسط مالک
    event_add_owner = MagicMock()
    event_add_owner.chat = regular_group
    event_add_owner.old_chat_member.status = "left"
    event_add_owner.new_chat_member.status = "member"
    event_add_owner.from_user = owner

    with patch("bot.handlers.group_guard.send_log", new_callable=AsyncMock) as mock_send_log:
        await on_my_chat_member_updated(event_add_owner, mock_bot)
        check("لاگ برای مالک ارسال شد", mock_send_log.called)
        check("ربات از گروه مالک لفت نداد", not mock_bot.leave_chat.called)

    mock_bot.reset_mock()

    # ۵.۳ افزودن به گروه داخلی توسط ادمین
    event_add_admin_internal = MagicMock()
    event_add_admin_internal.chat = internal_group
    event_add_admin_internal.old_chat_member.status = "left"
    event_add_admin_internal.new_chat_member.status = "administrator"
    event_add_admin_internal.from_user = admin

    with patch("bot.handlers.group_guard.send_log", new_callable=AsyncMock) as mock_send_log:
        await on_my_chat_member_updated(event_add_admin_internal, mock_bot)
        check("لاگ برای افزودن به گروه داخلی ارسال شد", mock_send_log.called)
        check("ربات از گروه داخلی لفت نداد", not mock_bot.leave_chat.called)

    mock_bot.reset_mock()

    # ۵.۴ اثر تاگل AUTO_LEAVE_UNAUTHORIZED_GROUPS = False
    with patch("bot.handlers.group_guard.AUTO_LEAVE_UNAUTHORIZED_GROUPS", False):
        with patch("bot.handlers.group_guard.send_log", new_callable=AsyncMock) as mock_send_log:
            await on_my_chat_member_updated(event_add_stranger, mock_bot)
            check("با خاموش بودن AUTO_LEAVE لاگ ارسال شد", mock_send_log.called)
            check("با خاموش بودن AUTO_LEAVE ربات لفت نداد", not mock_bot.leave_chat.called)

    mock_bot.reset_mock()

    # ۵.۵ حذف ربات از گروه (is_leaving)
    event_remove = MagicMock()
    event_remove.chat = regular_group
    event_remove.old_chat_member.status = "member"
    event_remove.new_chat_member.status = "kicked"
    event_remove.from_user = stranger

    with patch("bot.handlers.group_guard.send_log", new_callable=AsyncMock) as mock_send_log:
        await on_my_chat_member_updated(event_remove, mock_bot)
        check("لاگ حذف از گروه ارسال شد", mock_send_log.called)
        check("در رویداد خروج leave_chat صدا زده نشد", not mock_bot.leave_chat.called)

    print("\n" + "=" * 50)
    print(f"📊 نتیجه نهایی تست‌ها: {_passed} تست موفق، {len(_failed)} خطا.")
    if _failed:
        print("❌ موارد شکست‌خورده:")
        for f in _failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("🎉 تمامی تست‌های قفل دسترسی گروه‌ها با موفقیت پاس شدند.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_tests())
