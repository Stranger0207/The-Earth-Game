"""اسکریپت تست جامع سیستم فیلتر فحش و کلمات رکیک (Profanity Filter).

تست روی دیتابیس آزمایشی موقت SQLite در حافظه اجرا می‌شود و موارد زیر را اعتبارسنجی می‌کند:
۱. مقداردهی اولیه و بارگذاری کلمات از data/profanity_words.json در کش رم
۲. نرمال‌سازی کامل متن (اعراب، حروف عربی، کشیدگی، تکرار متوالی حروف، نیم‌فاصله)
۳. تشخیص ترفندهای نگارشی (ک.ص.ک.ش، فحششششش، ف_ح_ش)
۴. مصونیت ۱۰۰٪ کلمات سالم نظامی/سیاسی (کشتی، کشور، حمله، ترور، موشک، کشتار، تجاوز، ارتش، کشمیر، سکسکه، عکس، مشکل)
۵. تشخیص دقیق فحش‌های جنسی/ناموسی تک‌کلمه‌ای و عبارات چندکلمه‌ای
۶. عملکرد افزودن و حذف کلمه در دیتابیس و کش آنی
۷. عملکرد خاموش/روشن کردن کل فیلتر (Toggle)
۸. رفتار میدلور: مسدودسازی، حفظ وضعیت FSM، اخطار به کاربر و معافیت کامل ادمین‌ها
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# تنظیم متغیرهای محیطی آزمایشی
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_PROFANITY_TESTS"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Chat, Message, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import BotState, Country, ProfanityWord, User
from bot.middlewares.profanity import ProfanityMiddleware
from bot.services import profanity_service

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


async def run_tests() -> None:
    print("\n🚀 آغاز آزمون‌های جامع فیلتر فحش و کلمات رکیک (Profanity Filter)...\n")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # ساخت bot_state اولیه
        bstate = BotState(id=1, maintenance=False, profanity_filter_enabled=True)
        session.add(bstate)
        await session.commit()

        # ۱. مقداردهی اولیه و بارگذاری کلمات
        print("— آزمون ۱: بارگذاری اولیه کلمات از JSON و مقداردهی کش رم")
        seeded = await profanity_service.ensure_seeded(session)
        check("کلمات اولیه از JSON بارگذاری شدند", seeded > 0, f"تعداد افزوده: {seeded}")

        all_words = await profanity_service.get_all_words(session)
        check("تعداد کلمات ذخیره‌شده حداقل ۸۰ کلمه است", len(all_words) >= 80, f"تعداد: {len(all_words)}")
        check("کش رم فعال و حاوی کلمات است", len(profanity_service._CACHED_WORDS) > 0)

        # ۲. نرمال‌سازی کاراکترها
        print("\n— آزمون ۲: نرمال‌سازی حروف، اعراب و نویسه‌های مخفی")
        n1 = profanity_service.normalize_text("كَلِمَةٌ يَوْمِيَّة")
        check("تبدیل حروف عربی و حذف اعراب موفق بود", n1 == "کلمه یومیه", f"نتیجه: {n1}")

        n2 = profanity_service.normalize_text("فحـش‌هـا\u200cی بی\u200cناموس")
        check("حذف کشیدگی تطویل و نیم‌فاصله‌ها", "فحش" in n2 and "بیناموس" in n2, f"نتیجه: {n2}")

        # ۳. مصونیت کامل کلمات مشروع جنگی، سیاسی و زیررشته‌های حساس
        print("\n— آزمون ۳: عدم تشخیص اشتباه (False Positive) روی واژگان مشروع بازی")
        safe_samples = [
            "کشتی نفتکش ایران به بندر مقصد رسید.",
            "کشور ما در آرامش کامل به سر می‌برد.",
            "دستور حمله نظامی و شلیک موشک به پایگاه دشمن صادر شد.",
            "عملیات ترور هدفمند و نابودی فرمانده تروریست‌ها موفقیت‌آمیز بود.",
            "کشتار بی‌رحمانه غیرنظامیان محکوم است.",
            "تجاوز مرزی نیروهای متخاصم با شکست مواجه شد.",
            "ارتش سرافراز آماده دفاع از مرزها است.",
            "بحران منطقه کشمیر باید از طریق دیپلماتیک حل شود.",
            "سکسکه بازیکن بعد از نوشیدن آب قطع شد.",
            "این عکس هوایی برعکس شده و بررسی آن مشکل دارد.",
            "اشغال اراضی و آغاز جنگ تمام‌عیار در منطقه.",
            "بمب‌گذاری در نزدیکی وزارت خارجه دفع شد.",
        ]
        for s in safe_samples:
            has_bad, bad_w = profanity_service.check_profanity(s)
            check(f"متن سالم بدون خطا تایید شد: «{s[:35]}...»", not has_bad, f"کلمه به اشتباه شناسایی شد: {bad_w}")

        # ۴. تشخیص انواع کلمات رکیک و ترفندهای نگارشی
        print("\n— آزمون ۴: شناسایی دقیق فحش‌های رکیک و ترفندهای دور زدن")
        vulgar_samples = [
            ("تو یک کصکش احمق هستی", "کصکش"),
            ("این قرارداد خیلی تخمی است", "تخمی"),
            ("دیوث فلان فلان شده", "دیوث"),
            ("بی ناموس عوضی", "بی ناموس"),
            ("مادر جنده بی خاصیت", "مادر جنده"),
            ("سیکتیر کن از اینجا", "سیکتیر"),
            ("کیر خر تو این بازی", "کیر خر"),
            ("fuck you bitch", "fuck"),
            # کشیدگی حروف
            ("کصصصصصصصکش", "کصکش"),
            ("جندددددددده", "جنده"),
            ("کیرررررررر", "کیر"),
            # اعراب‌گذاری
            ("کُص‌خُل", "کصخل"),
            ("کِیر خر", "کیر خر"),
            # تقطیع با علائم نگارشی
            ("ک.ص.ک.ش", "کصکش"),
            ("ک_ص_خ_ل", "کصخل"),
            ("ک ص ک ش", "کصکش"),
        ]
        for text_input, expected in vulgar_samples:
            has_bad, bad_w = profanity_service.check_profanity(text_input)
            check(f"فحش شناسایی شد: «{text_input}»", has_bad, f"کشف نشد! انتظار: {expected}")

        # ۵. افزودن و حذف کلمه به صورت دستی
        print("\n— آزمون ۵: افزودن و حذف پویای کلمات در دیتابیس و کش رم")
        test_new_word = "فحش_ساختگی_آزمایشی"
        has_before, _ = profanity_service.check_profanity(f"این یک {test_new_word} است")
        check("کلمه جدید قبل از افزودن در فیلتر نیست", not has_before)

        # افزودن کلمه
        add_ok = await profanity_service.add_word(session, test_new_word, admin_id=111)
        check("افزودن کلمه جدید به دیتابیس موفق بود", add_ok)

        has_after, matched = profanity_service.check_profanity(f"این یک {test_new_word} است")
        check(
            "کلمه جدید بلافاصله در کش فعال شد و شناسایی گردید",
            has_after and matched == profanity_service.normalize_text(test_new_word),
            f"has_after={has_after}, matched={matched}",
        )

        # حذف کلمه
        del_ok = await profanity_service.remove_word(session, test_new_word)
        check("حذف کلمه از دیتابیس و کش موفق بود", del_ok)

        has_after_del, _ = profanity_service.check_profanity(f"این یک {test_new_word} است")
        check("پس از حذف، دیگر شناسایی نمی‌شود", not has_after_del)

        # ۶. خاموش و روشن کردن کل فیلتر
        print("\n— آزمون ۶: تغییر وضعیت سراسری فیلتر فحش (Toggle)")
        check("فیلتر در ابتدا فعال است", profanity_service.is_filter_enabled() is True)

        toggled_off = await profanity_service.toggle_filter(session)
        check("فیلتر با موفقیت خاموش شد", toggled_off is False and profanity_service.is_filter_enabled() is False)

        toggled_on = await profanity_service.toggle_filter(session)
        check("فیلتر با موفقیت مجدداً روشن شد", toggled_on is True and profanity_service.is_filter_enabled() is True)

        # ۷. تست رفتار میدلور (ProfanityMiddleware)
        print("\n— آزمون ۷: رفتار میدلور، مسدودسازی، حفظ FSM و معافیت ادمین")
        middleware = ProfanityMiddleware()
        mock_handler = AsyncMock(return_value="HANDLER_EXECUTED")

        # ساخت FSM Storage شبیه‌سازی‌شده
        storage = MemoryStorage()
        storage_key = StorageKey(bot_id=123, chat_id=999, user_id=999)
        fsm_ctx = FSMContext(storage=storage, key=storage_key)
        await fsm_ctx.set_state("SomeRoleForm:entering_page")
        await fsm_ctx.update_data(page_number=2, draft_title="پروژه تست")

        # الف) پیام حاوی فحش از طرف کاربر عادی (غیرادمین)
        normal_tg_user = TgUser(id=999, is_bot=False, first_name="Ali", username="ali_player")
        fake_chat = Chat(id=999, type="private")
        blocked_msg = MagicMock(spec=Message)
        blocked_msg.text = "متن پیام حاوی کصکش است"
        blocked_msg.caption = None
        blocked_msg.answer = AsyncMock()
        blocked_bot = MagicMock()
        blocked_bot.send_message = AsyncMock()
        blocked_msg.bot = blocked_bot

        data_normal = {
            "session": session,
            "event_from_user": normal_tg_user,
            "state": fsm_ctx,
            "bot": blocked_msg.bot,
        }

        result_normal = await middleware(mock_handler, blocked_msg, data_normal)
        check("میدلور جلوی اجرای هندلر را گرفت", result_normal is None)
        check("هندلر فراخوانی نشد", mock_handler.call_count == 0)
        check("پیام اخطار منشور اخلاقی به کاربر ارسال شد", blocked_msg.answer.call_count == 1)

        # بررسی اینکه وضعیت FSM پاک نشده است
        current_state = await fsm_ctx.get_state()
        state_data = await fsm_ctx.get_data()
        check("وضعیت فرم کاربر (FSM) حفظ شده است", current_state == "SomeRoleForm:entering_page")
        check("داده‌های پیش‌نویس کاربر سالم مانده‌اند", state_data.get("draft_title") == "پروژه تست")

        # ب) پیام سالم از طرف کاربر عادی
        mock_handler.reset_mock()
        clean_msg = MagicMock(spec=Message)
        clean_msg.text = "سلام به رهبر کشور مقابل، خوش آمدید."
        clean_msg.caption = None

        result_clean = await middleware(mock_handler, clean_msg, data_normal)
        check("پیام سالم از میدلور عبور کرد و هندلر اجرا شد", result_clean == "HANDLER_EXECUTED")
        check("هندلر دقیقاً ۱ بار فراخوانی شد", mock_handler.call_count == 1)

        # ج) پیام حاوی فحش از طرف ادمین (مثلاً دستور /addword کصکش یا تست ادمین)
        mock_handler.reset_mock()
        admin_tg_user = TgUser(id=111, is_bot=False, first_name="Admin", username="admin_boss")
        admin_msg = MagicMock(spec=Message)
        admin_msg.text = "/addword کصکش"
        admin_msg.caption = None

        data_admin = {
            "session": session,
            "event_from_user": admin_tg_user,
            "state": fsm_ctx,
            "bot": admin_msg.bot,
        }

        result_admin = await middleware(mock_handler, admin_msg, data_admin)
        check("ادمین کاملاً از فیلتر معاف است و پیامش بدون مانع عبور کرد", result_admin == "HANDLER_EXECUTED")
        check("هندلر برای ادمین اجرا شد", mock_handler.call_count == 1)

        # ۸. بررسی حفظ جدول در ریست فصل
        print("\n— آزمون ۸: بررسی حفظ جدول profanity_words در ریست فصل")
        from scripts.test_season_reset import _PRESERVED
        check("جدول profanity_words در لیست _PRESERVED ریست فصل قرار دارد", "profanity_words" in _PRESERVED)

    print("\n" + "=" * 60)
    if _failed:
        print(f"❌ آزمون‌های ناموفق ({len(_failed)} مورد):\n" + "\n".join(f"  • {f}" for f in _failed))
        sys.exit(1)
    else:
        print(f"✅ تمام {_passed} آزمون سیستم فیلتر فحش و کلمات رکیک با موفقیت ۱۰۰٪ پاس شدند.")


if __name__ == "__main__":
    asyncio.run(run_tests())
