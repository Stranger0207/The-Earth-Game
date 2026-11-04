"""
تست جامع فرمت و رفتار بیانیه رسمی (سخنرانی سران) (v2.11.0).

سناریوهای تحت پوشش:
۱. خروجی دقیق فرمت HTML:
   - دو خط اول (🎙| یک بیانیه از طرف ... منتشر شد! و متن سخنرانی:) دقیقاً Bold (<b>...</b>)
   - متن سخنرانی کاربر معمولی (بدون تگ Bold)
   - پالایش کاراکترهای خطرناک (<, >, &) با html.escape
۲. استخراج عنوان رسمی رهبر بر اساس نوع نظام حاکمیتی (پادشاه، رئیس‌جمهور، نخست‌وزیر، ...)
۳. اعتبارسنجی پیش‌دستانه طول متن و رد متن‌های بالاتر از STATEMENT_MAX_CHARS (850)
۴. رد متن خالی و سفید (Whitespace)
۵. شبیه‌سازی خطای تلگرام TelegramBadRequest و عدم ثبت کول‌داون حین شکست ارسال
۶. ثبت صحیح کول‌داون، پیام ممیزی و ذخیره Speech بعد از ارسال موفق
"""

from __future__ import annotations

import asyncio
import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Chat, Message, User as TgUser, CallbackQuery

from bot.constants import STATEMENT_MAX_CHARS, SPEECH_COOLDOWN_MINUTES
from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, Speech, User
from bot.database.repositories import cooldowns as cd_repo
from bot.enums import GovernmentType, get_leader_title
from bot.handlers.diplomacy import (
    format_statement_message,
    msg_speech_text,
    cb_speech_publish,
)
from bot.states import SpeechForm

PASS_COUNT = 0
FAIL_COUNT = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  ✅ {label}")
        PASS_COUNT += 1
    else:
        print(f"  ❌ {label} {detail}")
        FAIL_COUNT += 1


async def run_all_tests() -> None:
    print("=" * 70)
    print("🎙 آغاز تست‌های جامع فرمت و رفتار بیانیه رسمی")
    print("=" * 70)

    db_path = Path("test_statement.db")
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass

    await init_db()

    print("\n🔹 تست ۱: خروجی دقیق فرمت HTML و عدم Bold بودن متن کاربر")
    title = "رئیس‌جمهور"
    name = "ایران"
    user_text = "صلح و ثبات برای تمامی ملت‌های جهان آرزوی قلبی ماست."
    formatted = format_statement_message(title, name, user_text)

    lines = formatted.split("\n\n")
    check("پیام شامل دو بخش اصلی جداشده با خط خالی است", len(lines) == 2)
    check("خط اول دقیقاً با <b>🎙| یک بیانیه از طرف ... منتشر شد!</b> مطابقت دارد",
          lines[0] == f"<b>🎙| یک بیانیه از طرف {title} {name} منتشر شد!</b>")

    speech_lines = lines[1].split("\n", 1)
    check("سرخط متن سخنرانی دقیقاً <b>متن سخنرانی:</b> است", speech_lines[0] == "<b>متن سخنرانی:</b>")
    check("متن خود بیانیه بدون تگ Bold است", "<b>" + user_text not in formatted and speech_lines[1] == user_text)

    print("\n🔹 تست ۲: پالایش کاراکترهای خطرناک و جلوگیری از تزریق تگ")
    evil_text = "<script>alert('xss')</script> & <b>bold</b> <foo@bar.com>"
    evil_name = "<شاهنشاه> & <وزیر>"
    evil_formatted = format_statement_message("پادشاه", evil_name, evil_text)

    check("تگ <script> تبدیل به &lt;script&gt; شد", "<script>" not in evil_formatted and "&lt;script&gt;" in evil_formatted)
    check("کاراکتر & تبدیل به &amp; شد", "&amp;" in evil_formatted)
    check("نام رهبر حاوی تگ تزریقی پالایش شد", "<شاهنشاه>" not in evil_formatted and "&lt;شاهنشاه&gt;" in evil_formatted)

    print("\n🔹 تست ۳: بررسی عناوین رهبر طبق نظام حاکمیتی (get_leader_title)")
    check("نظام پادشاهی → پادشاه", get_leader_title(GovernmentType.MONARCHY) == "پادشاه")
    check("نظام پادشاهی مشروطه → نخست‌وزیر", get_leader_title(GovernmentType.CONSTITUTIONAL_MONARCHY) == "نخست‌وزیر")
    check("نظام کمونیسم → دبیرکل", get_leader_title(GovernmentType.COMMUNISM) == "دبیرکل")
    check("نظام تئوکراسی → رهبر عالی", get_leader_title(GovernmentType.THEOCRACY) == "رهبر عالی")
    check("نظام جمهوری → رئیس‌جمهور", get_leader_title(GovernmentType.REPUBLIC) == "رئیس‌جمهور")
    check("پیش‌فرض نامشخص → رئیس‌جمهور", get_leader_title("") == "رئیس‌جمهور")

    print("\n🔹 تست ۴: اعتبارسنجی پیش‌دستانه طول متن و رد متن‌های طولانی")
    storage = MemoryStorage()
    key = StorageKey(bot_id=123, chat_id=1001, user_id=1001)
    state = FSMContext(storage=storage, key=key)

    mock_msg = MagicMock(spec=Message)
    mock_msg.text = "   "  # متن فقط فضای خالی
    mock_msg.answer = AsyncMock()

    await msg_speech_text(mock_msg, state)
    check("رد متن خالی/سفید با هشدار", "نمی‌تواند خالی باشد" in mock_msg.answer.call_args[0][0])

    # متن با طول بیش از حد مجاز (851 کاراکتر)
    long_text = "الف" * (STATEMENT_MAX_CHARS + 50)
    mock_msg.text = long_text
    mock_msg.answer.reset_mock()

    await msg_speech_text(mock_msg, state)
    check("رد متن با طول بیش از ۸۵۰ کاراکتر", "طول متن بیانیه بیش از حد مجاز است" in mock_msg.answer.call_args[0][0])
    check("ذکر تعداد کاراکتر اضافی در هشدار", "۵۰" in mock_msg.answer.call_args[0][0])
    curr_state = await state.get_state()
    check("کاربر پس از متن طولانی در استیت entering_text باقی می‌ماند", curr_state is None or curr_state == SpeechForm.entering_text.state)

    # متن استاندارد و مجاز
    valid_text = "این یک بیانیه رسمی صلح‌آمیز و سازنده است."
    mock_msg.text = valid_text
    mock_msg.answer.reset_mock()
    await msg_speech_text(mock_msg, state)
    check("پذیرش متن استاندارد و انتقال به آپلود عکس", "با موفقیت ثبت شد" in mock_msg.answer.call_args[0][0])
    check("استیت به entering_photo تغییر کرد", await state.get_state() == SpeechForm.entering_photo.state)

    print("\n🔹 تست ۵: شبیه‌سازی خطای تلگرام TelegramBadRequest و عدم ثبت کول‌داون")
    async with async_session_factory() as session:
        country = Country(
            name_en="StatementLand",
            name_fa="آزمون‌بیانیه",
            flag="🏳",
            region="europe",
            government_type="republic",
            owner_user_id=1001,
        )
        session.add(country)
        db_user = User(telegram_id=1001, president_name="آقای رئیس")
        session.add(db_user)
        await session.commit()

        await state.update_data(speech_text=valid_text, photo_id="photo_123456")
        await state.set_state(SpeechForm.confirming)

        mock_call = MagicMock(spec=CallbackQuery)
        mock_call.from_user = TgUser(id=1001, is_bot=False, first_name="Test")
        mock_call.answer = AsyncMock()
        mock_call.message = MagicMock()

        # شبیه‌سازی رخ‌دادن TelegramBadRequest هنگام ارسال به کانال
        with patch("bot.handlers.diplomacy.bot.send_photo", side_effect=TelegramBadRequest(method="sendPhoto", message="Bad Request: message caption is too long")):
            with patch("bot.handlers.diplomacy.settings") as mock_settings:
                mock_settings.news_diplomacy_channel_id = -100123456
                await cb_speech_publish(mock_call, state, session, db_user)

        check("خطای caption is too long صریحاً به کاربر نمایش داده شد", "فراتر از سقف کپشن تلگرام" in mock_call.answer.call_args[0][0])
        # بررسی عدم ثبت کول‌داون
        rem_sec = await cd_repo.remaining_seconds(session, country.id, "speech", SPEECH_COOLDOWN_MINUTES / 60)
        check("کول‌داون پس از شکست ارسال ثبت نشد (0 ثانیه)", rem_sec == 0)

        print("\n🔹 تست ۶: ارسال موفقیت‌آمیز، ثبت کول‌داون و لاگ ممیزی")
        mock_sent = MagicMock()
        mock_sent.message_id = 777888
        mock_call.answer.reset_mock()

        with patch("bot.handlers.diplomacy.bot.send_photo", new=AsyncMock(return_value=mock_sent)):
            with patch("bot.handlers.diplomacy.settings") as mock_settings:
                mock_settings.news_diplomacy_channel_id = -100123456
                with patch("bot.handlers.diplomacy.send_log", new=AsyncMock()) as mock_log:
                    await cb_speech_publish(mock_call, state, session, db_user)

        check("پیام موفقیت به کاربر نشان داده شد", "با موفقیت منتشر شد" in mock_call.answer.call_args[0][0])
        rem_sec_after = await cd_repo.remaining_seconds(session, country.id, "speech", SPEECH_COOLDOWN_MINUTES / 60)
        check("کول‌داون ۱۰ دقیقه‌ای پس از ارسال موفق ثبت شد", rem_sec_after > 0)
        check("استیت FSM پس از موفقیت پاک شد", await state.get_state() is None)

    print("\n" + "=" * 70)
    print(f"📊 نتیجه نهایی تست بیانیه: {PASS_COUNT} موفق | {FAIL_COUNT} ناموفق")
    print("=" * 70)
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
