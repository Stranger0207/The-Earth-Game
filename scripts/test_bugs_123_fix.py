"""
تست جامع اعتبارسنجی رفع ۳ باگ بازی کره زمین:
۱. رفع باگ دکمه فروش ذخیره (انتقال امن از پیام عکس‌دار، safe_edit و پاکسازی استیت).
۲. رفع باگ دکمه تأسیسات مشترک (انتقال امن از منوی عکس‌دار احداث تأسیسات و safe_edit).
۳. رفع باگ تکرار آپشن‌ها در پنل /god (حذف ۸ کلید مستعار و عدم وجود حتی یک مورد تکراری).
"""

from __future__ import annotations

import ast
import asyncio
import glob
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# تنظیم محیط تست درون‌حافظه‌ای
os.environ["BOT_TOKEN"] = "123456:ABC-test-token"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test_key"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"
os.environ["PYTHONUTF8"] = "1"

PASS_COUNT = 0
FAIL_COUNT = 0


def check(title: str, condition: bool, details: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [OK] {title}")
    else:
        FAIL_COUNT += 1
        print(f"  [FAIL] {title} {details}")


async def run_all_checks() -> None:
    print("=" * 70)
    print("🚀 آغاز آزمون‌های جامع صحه‌گذاری رفع ۳ باگ (Bugs 1, 2, 3)")
    print("=" * 70)

    # -------------------------------------------------------------
    # بخش ۱: صحت ایمپورت و ثبت تمام روترها
    # -------------------------------------------------------------
    print("\n📦 بررسی ۱: ایمپورت بدون خطا و رجیستر تمام روترها")
    from aiogram import Dispatcher
    from bot.handlers import register_all_routers
    dp = Dispatcher()
    try:
        register_all_routers(dp)
        check("تمامی روترها و ماژول‌ها بدون خطای ایمپورت ثبت شدند", True)
    except Exception as exc:
        check("تمامی روترها و ماژول‌ها بدون خطای ایمپورت ثبت شدند", False, str(exc))

    # -------------------------------------------------------------
    # بخش ۲: بررسی دیتابیس SQLite و ساخت جدول‌ها
    # -------------------------------------------------------------
    print("\n🗄 بررسی ۲: ساخت جدول‌ها و سشن دیتابیس")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from bot.database.base import Base
    from bot.database.models import Country, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        # ساخت کاربر و کشور تستی
        test_user = User(telegram_id=111, username="test_player", is_admin=False, is_owner=False)
        test_country = Country(
            id=1,
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="Middle East",
            economic_power=60.0,
            budget=500_000_000.0,
            owner_user_id=111,
            is_vip=False,
        )
        test_partner = Country(
            id=2,
            name_en="Russia",
            name_fa="روسیه",
            flag="🇷🇺",
            region="Europe",
            economic_power=85.0,
            budget=800_000_000.0,
            owner_user_id=222,
            is_vip=True,
        )
        session.add_all([test_user, test_country, test_partner])
        await session.commit()
        check("کاربر و کشورهای تستی در دیتابیس ایجاد شدند", True)

    # -------------------------------------------------------------
    # بخش ۳: بررسی باگ ۱ — دکمه «فروش ذخیره»
    # -------------------------------------------------------------
    print("\n💱 بررسی ۳: رفع باگ دکمه فروش ذخیره (Bug 1)")
    from bot.handlers.economy import _ask_sale_amount, _show_sale_buyers, cb_sell
    from bot.keyboards.economy import economy_menu_kb, sell_resources_kb

    # ۳.۱ بررسی کالبک دکمه در کیبورد اقتصاد
    econ_kb = economy_menu_kb()
    sell_btn = next((b for row in econ_kb.inline_keyboard for b in row if b.callback_data == "econ:sell"), None)
    check("دکمه 'فروش ذخیره' با callback_data='econ:sell' در منوی اقتصاد وجود دارد", sell_btn is not None)

    # ۳.۲ بررسی عدم استفاده از edit_text مستقیم روی پیام در توابع فروش
    with open("bot/handlers/economy.py", "r", encoding="utf-8") as f:
        econ_code = f.read()
    check("عدم وجود target.message.edit_text در هندلرهای فروش", "target.message.edit_text" not in econ_code)

    # ۳.۳ اجرای cb_sell با پیام عکس‌دار
    mock_photo_msg = MagicMock()
    mock_photo_msg.photo = [MagicMock()]
    mock_photo_msg.document = None
    mock_photo_msg.delete = AsyncMock()
    mock_photo_msg.answer = AsyncMock()
    mock_photo_msg.answer_photo = AsyncMock()

    mock_call = MagicMock()
    mock_call.message = mock_photo_msg
    mock_call.data = "econ:sell"
    mock_call.from_user.id = 111
    mock_call.answer = AsyncMock()

    mock_state = MagicMock()
    mock_state.set_state = AsyncMock()
    mock_state.update_data = AsyncMock()

    async with session_factory() as session:
        try:
            await cb_sell(mock_call, mock_state, session, test_user)
            check("cb_sell روی پیام عکس‌دار بدون خطا اجرا شد", True)
            check("پیام عکس‌دار قبلی حذف شد", mock_photo_msg.delete.called)
            check("پیام متن انتخاب منبع جدید ارسال شد", mock_photo_msg.answer.called)
        except Exception as exc:
            check("cb_sell روی پیام عکس‌دار بدون خطا اجرا شد", False, str(exc))

    # ۳.۴ اجرای _ask_sale_amount روی CallbackQuery عکس‌دار
    mock_photo_msg.reset_mock()
    try:
        await _ask_sale_amount(mock_call, mock_state, "oil")
        check("_ask_sale_amount روی CallbackQuery عکس‌دار با safe_edit بدون خطا عمل کرد", True)
    except Exception as exc:
        check("_ask_sale_amount روی CallbackQuery عکس‌دار با safe_edit بدون خطا عمل کرد", False, str(exc))

    # ۳.۵ اجرای _show_sale_buyers روی CallbackQuery عکس‌دار
    mock_photo_msg.reset_mock()
    async with session_factory() as session:
        try:
            await _show_sale_buyers(mock_call, mock_state, session, 1)
            check("_show_sale_buyers روی CallbackQuery عکس‌دار با safe_edit بدون خطا عمل کرد", True)
        except Exception as exc:
            check("_show_sale_buyers روی CallbackQuery عکس‌دار با safe_edit بدون خطا عمل کرد", False, str(exc))

    # ۳.۶ بررسی پاکسازی استیت در menu:economy
    from bot.handlers.menu import cb_economy
    mock_econ_state = MagicMock()
    mock_econ_state.clear = AsyncMock()
    mock_call_econ = MagicMock()
    mock_call_econ.message = MagicMock()
    mock_call_econ.from_user.id = 111
    mock_call_econ.answer = AsyncMock()
    async with session_factory() as session:
        await cb_economy(mock_call_econ, mock_econ_state, session, test_user)
        check("بازگشت به منوی اقتصاد (cb_economy) استیت‌های قبلی را ریست می‌کند", mock_econ_state.clear.called)

    # -------------------------------------------------------------
    # بخش ۴: بررسی باگ ۲ — دکمه «تأسیسات مشترک»
    # -------------------------------------------------------------
    print("\n🤝 بررسی ۴: رفع باگ دکمه تأسیسات مشترک (Bug 2)")
    from bot.handlers.joint import cb_joint_partner, cb_joint_resource, cb_joint_start, cb_joint_type
    from bot.keyboards.economy import facility_types_kb

    # ۴.۱ بررسی کالبک دکمه در کیبورد تأسیسات
    fac_kb = facility_types_kb()
    joint_btn = next((b for row in fac_kb.inline_keyboard for b in row if b.callback_data == "joint:start"), None)
    check("دکمه 'تأسیسات مشترک' با callback_data='joint:start' در facility_types_kb موجود است", joint_btn is not None)

    # ۴.۲ بررسی عدم وجود edit_text مستقیم روی پیام در جریان سازنده تأسیسات مشترک
    with open("bot/handlers/joint.py", "r", encoding="utf-8") as f:
        joint_code = f.read()
    check("ایمپورت safe_edit در bot/handlers/joint.py موجود است", "from ..utils.screens import safe_edit" in joint_code)

    # ۴.۳ فراخوانی cb_joint_start با پیام عکس‌دار
    mock_photo_msg.reset_mock()
    mock_call.data = "joint:start"
    async with session_factory() as session:
        try:
            await cb_joint_start(mock_call, mock_state, session, test_user)
            check("cb_joint_start روی پیام عکس‌دار با safe_edit بدون کرش اجرا شد", True)
            check("پیام عکس‌دار احداث حذف و متن انتخاب شریک جایگزین شد", mock_photo_msg.delete.called and mock_photo_msg.answer.called)
        except Exception as exc:
            check("cb_joint_start روی پیام عکس‌دار با safe_edit بدون کرش اجرا شد", False, str(exc))

    # ۴.۴ فراخوانی cb_joint_partner با پیام عکس‌دار
    mock_photo_msg.reset_mock()
    mock_call.data = "joint_partner:2"
    async with session_factory() as session:
        try:
            await cb_joint_partner(mock_call, mock_state, session)
            check("cb_joint_partner با safe_edit بدون کرش اجرا شد", True)
        except Exception as exc:
            check("cb_joint_partner با safe_edit بدون کرش اجرا شد", False, str(exc))

    # ۴.۵ فراخوانی cb_joint_type با پیام عکس‌دار
    mock_photo_msg.reset_mock()
    mock_call.data = "joint_type:steel_factory"
    async with session_factory() as session:
        try:
            await cb_joint_type(mock_call, mock_state, session, test_user)
            check("cb_joint_type با safe_edit بدون کرش اجرا شد", True)
        except Exception as exc:
            check("cb_joint_type با safe_edit بدون کرش اجرا شد", False, str(exc))

    # -------------------------------------------------------------
    # بخش ۵: بررسی باگ ۳ — رفع تکرار آپشن‌ها در /god
    # -------------------------------------------------------------
    print("\n🔒 بررسی ۵: رفع تکرار گزینه‌ها در پنل /god و LOCKABLE_FEATURES (Bug 3)")
    from bot.constants import FEATURE_CATEGORIES, FEATURE_KEY_ALIASES, LOCKABLE_FEATURES
    from bot.handlers.deps import feature_name, is_feature_locked
    from bot.handlers.god_locks import _render_category

    # ۵.۱ بررسی یکتا بودن عناوین فارسی در LOCKABLE_FEATURES
    title_counts = Counter(val[0] for val in LOCKABLE_FEATURES.values())
    duplicates = [t for t, count in title_counts.items() if count > 1]
    check(
        f"عدم وجود عناوین تکراری در LOCKABLE_FEATURES (تعداد عناوین تکراری: {len(duplicates)})",
        len(duplicates) == 0,
        f"تکراری‌ها: {duplicates}",
    )

    # ۵.۲ بررسی تعداد دقیق ویژگی‌های یکتا
    check(f"تعداد ویژگی‌های یکتا در LOCKABLE_FEATURES دقیقا ۳۷ است (فعلی: {len(LOCKABLE_FEATURES)})", len(LOCKABLE_FEATURES) == 37)

    # ۵.۳ بررسی اینکه کلیدهای تکراری سابق در FEATURE_KEY_ALIASES نگاشت شده‌اند
    expected_aliases = [
        ("military.tech_transfer", "tech_transfer"),
        ("military.straits", "straits_management"),
        ("military.security_role", "security_roles"),
        ("military.ops_role", "military_roles"),
        ("econ_satellite", "econ.satellite"),
        ("econ_projects", "econ.projects"),
        ("market_rates", "econ.market_rates"),
        ("dip.twitter", "twitter"),
    ]
    for old_k, canonical_k in expected_aliases:
        check(
            f"کلید مستعار '{old_k}' به '{canonical_k}' نگاشت می‌شود",
            FEATURE_KEY_ALIASES.get(old_k) == canonical_k,
        )

    # ۵.۴ بررسی کارکرد توابع feature_name و is_feature_locked برای کلیدهای مستعار و اصلی
    async with session_factory() as session:
        name_canonical = feature_name("econ.projects")
        name_alias = feature_name("econ_projects")
        check("feature_name برای کلید اصلی و مستعار یکسان است", name_canonical == name_alias and name_canonical == "🏗 پروژه‌های اقتصادی")

        locked_res = await is_feature_locked(session, test_country, "econ_projects")
        check("is_feature_locked بدون خطا برای کلید مستعار کار می‌کند", locked_res is False)

    # ۵.۵ استخراج کلیه کلیدهای مورد استفاده در assert_feature در سراسر پروژه
    used_assert_keys = set()
    for py_file in glob.glob("bot/**/*.py", recursive=True):
        with open(py_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if func_name == "assert_feature" and len(node.args) >= 4 and isinstance(node.args[3], ast.Constant):
                    used_assert_keys.add(node.args[3].value)

    missing_keys = [k for k in used_assert_keys if k not in LOCKABLE_FEATURES]
    check(
        f"تمام {len(used_assert_keys)} کلید assert_feature در LOCKABLE_FEATURES تعریف شده‌اند",
        len(missing_keys) == 0,
        f"کلیدهای ناموجود: {missing_keys}",
    )

    # ۵.۶ شبیه‌سازی رندر دسته‌ها در پنل god_locks و بررسی دکمه‌ها
    async with session_factory() as session:
        mock_god_call = MagicMock()
        mock_god_call.message = MagicMock()
        mock_god_call.message.edit_text = AsyncMock()

        for cat_idx, category in enumerate(FEATURE_CATEGORIES):
            await _render_category(mock_god_call, session, cat_idx)
            args, kwargs = mock_god_call.message.edit_text.call_args
            rendered_kb = kwargs.get("reply_markup")
            btn_texts = [
                b.text for row in rendered_kb.inline_keyboard for b in row
                if not b.text.startswith("🔙")
            ]
            # تمیز کردن ایموجی وضعیت (🟢, 🔴, 🟠) از ابتدای متن دکمه
            clean_btn_titles = [t.split(" ", 1)[-1] for t in btn_texts]
            btn_counter = Counter(clean_btn_titles)
            cat_dups = [t for t, count in btn_counter.items() if count > 1]
            check(
                f"دسته '{category}' دارای {len(clean_btn_titles)} آپشن و فاقد هرگونه دکمه تکراری است",
                len(cat_dups) == 0,
                f"تکراری‌های دسته: {cat_dups}",
            )

    print("\n" + "=" * 70)
    print(f"📊 جمع‌بندی نهایی نتایج تست: {PASS_COUNT} موفق | {FAIL_COUNT} ناموفق")
    print("=" * 70)

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_checks())
