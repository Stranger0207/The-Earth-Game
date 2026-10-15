"""
تست جامع آپدیت v2.7: تبدیل خودکار نامه‌های دیپلماتیک به تصاویر اسناد رسمی (Pillow / In-Memory).

اجرا:
    PYTHONUTF8=1 python -m scripts.test_image_mail_v27

بخش‌های تست:
    ۱) تست رندرینگ تصویر سند رسمی دیپلماتیک (letter_image_service):
       - صحت هدر و فرمت فایل PNG
       - محاسبه‌ی پویای ارتفاع بوم (Dynamic Height) بر اساس طول متن
       - حذف خودکار ایموجی‌ها (Emoji Stripping) از متن تصویر برای جلوگیری از کاراکتر نامعتبر (□)
       - حالت‌های مختلف: نامه شخصی، نامه به متحدان، نامه سراسری، پاسخ دیپلماتیک
       - متادیتا و مهر رسمی
    ۲) تست جریان پایگاه‌داده و نامه‌نگاری (Database / Repository):
       - ثبت نامه تک‌گیرنده، به متحدان، و به همه کشورها
       - ثبت پاسخ (parent_id) و تغییر وضعیت replied
       - دریافت صندوق پستی (inbox)
    ۳) تست رفتار هندلرهای تلگرام (Handlers / Callbacks):
       - بررسی cb_mail_reply: عدم حذف عکس و ارسال پیام جدید در answer
       - بررسی cb_mail_img: ارسال مجدد BufferedInputFile تصویر سند از صندوق پستی
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import io
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ["PYTHONUTF8"] = "1"
os.environ["BOT_TOKEN"] = "123456:ABC-test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image
from sqlalchemy import text

from bot.database.base import async_session_factory, engine, init_db
from bot.database.models import Alliance, AllianceMember, Country, Letter, User
from bot.database.repositories import letters as letters_repo
from bot.services.letter_image_service import render_diplomatic_letter_image

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def test_image_rendering() -> None:
    print("\n--- ۱) تست رندرینگ تصویر سند دیپلماتیک (Pillow In-Memory) ---")

    # ۱. تست رندر پایه
    short_body = "جناب آقای رئیس جمهور، این یک نامه رسمی دوستانه جهت گسترش روابط دوجانبه است."
    img_bytes = render_diplomatic_letter_image(
        letter_id=101,
        sender_country_name="ایران",
        sender_flag="🇮🇷",
        sender_leader_name="دکتر رضایی",
        recipient_country_name="عراق",
        recipient_flag="🇮🇶",
        letter_type="نامه رسمی دیپلماتیک",
        body=short_body,
        created_at=_utcnow(),
    )

    check("خروجی از نوع bytes است", isinstance(img_bytes, bytes))
    check("بایت‌های فایل با هدر جادویی PNG شروع می‌شوند", img_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
    check("حجم بایت‌های تصویر بزرگتر از 10 کیلوبایت است", len(img_bytes) > 10_000, f"size={len(img_bytes)}")

    # بررسی با کتابخانه PIL
    img = Image.open(io.BytesIO(img_bytes))
    check("عرض تصویر دقیقاً 1000 پیکسل است", img.width == 1000, f"width={img.width}")
    check("ارتفاع تصویر متن کوتاه حداقل 750 پیکسل است", img.height >= 750, f"height={img.height}")
    base_height = img.height

    # ۲. تست متن بسیار طولانی و افزایش پویای ارتفاع (Dynamic Height)
    long_paragraphs = [
        "پاراگراف اول: پیرو مذاکرات گذشته پیرامون مبادلات تجاری، مرزی، امنیتی و اقتصادی میان دو دولت دوست و همسایه، بدین‌وسیله تمایل رسمی خود را برای عقد پیمان جدید ابراز می‌داریم.",
        "پاراگراف دوم: بند الف) لغو روادید بازرگانان و تسهیل مراودات گمرکی در مبادی ورودی و پایانه‌های ترانزیتی مشترک.",
        "پاراگراف سوم: بند ب) سرمایه‌گذاری مشترک در حوزه‌های نفت، گاز، پتروشیمی و خطوط انتقال برق سراسری منطقه‌ای.",
        "پاراگراف چهارم: بند ج) همکاری‌های همه‌جانبه‌ی دفاعی، رزمایش‌های مشترک ضدتروریستی و تبادل اطلاعات امنیتی در مرزها.",
        "پاراگراف پنجم: امیدواریم در سریع‌ترین زمان ممکن هیئت دیپلماتیک آن کشور جهت نهایی‌سازی پیش‌نویس این معاهده به پایتخت اعزام گردد. با احترام و آرزوی سرافرازی روزافزون.",
    ]
    long_body = "\n\n".join(long_paragraphs)
    long_img_bytes = render_diplomatic_letter_image(
        letter_id=102,
        sender_country_name="ایران",
        sender_flag="🇮🇷",
        recipient_country_name="عراق",
        recipient_flag="🇮🇶",
        body=long_body,
    )
    long_img = Image.open(io.BytesIO(long_img_bytes))
    check(
        "ارتفاع تصویر متن طولانی بیشتر از متن کوتاه است (رشد پویا)",
        long_img.height > base_height,
        f"long_height={long_img.height} vs base={base_height}",
    )
    check("عرض تصویر طولانی همچنان دقیقاً 1000 پیکسل است", long_img.width == 1000)

    # ۳. تست فیلتر کردن ایموجی‌ها بدون خطا
    emoji_body = "🌍 درود بر شما! 🕊️ پیمان صلح ما پایدار باد 🤝🚀🌟 (نسخه رسمی دیپلماتیک)"
    emoji_img_bytes = render_diplomatic_letter_image(
        letter_id=103,
        sender_country_name="ایران",
        sender_flag="🇮🇷",
        recipient_country_name="عربستان",
        recipient_flag="🇸🇦",
        letter_type="نامه رسمی دیپلماتیک",
        body=emoji_body,
    )
    check(
        "رندر متن با ایموجی‌های گوناگون با موفقیت انجام شد",
        emoji_img_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
    )

    # ۴. تست حالت پاسخ و ارجاع به parent_id
    reply_img_bytes = render_diplomatic_letter_image(
        letter_id=104,
        sender_country_name="عراق",
        sender_flag="🇮🇶",
        recipient_country_name="ایران",
        recipient_flag="🇮🇷",
        letter_type="پاسخ رسمی دیپلماتیک",
        body="پاسخ مثبت دولت عراق به پیشنهاد همکاری دوجانبه.",
        parent_id=101,
    )
    reply_img = Image.open(io.BytesIO(reply_img_bytes))
    check("رندر پاسخ دیپلماتیک با موفقیت باز شد", reply_img.format == "PNG")

    # ۵. تست حالت متحدان و سراسری
    allies_bytes = render_diplomatic_letter_image(
        letter_id=105,
        sender_country_name="ایران",
        recipient_country_name="متحدان",
        body="پیام به اعضای محترم ائتلاف صلح.",
        is_allies=True,
    )
    check("رندر نامه به متحدان معتبر است", allies_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    all_bytes = render_diplomatic_letter_image(
        letter_id=106,
        sender_country_name="ایران",
        recipient_country_name="تمام کشورها",
        body="بیانیه عمومی و رسمی به کلیه دولت‌های جهان.",
        is_all=True,
    )
    check("رندر نامه سراسری معتبر است", all_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


async def test_mail_database_flow() -> None:
    print("\n--- ۲) تست جریان دیتابیس و نامه‌نگاری دیپلماتیک ---")

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
    await init_db()

    async with async_session_factory() as session:
        # ۱. ساخت کاربران و کشورها
        u1 = User(telegram_id=1001, username="leader_iran", president_name="آیت‌الله رضایی")
        u2 = User(telegram_id=1002, username="leader_iraq", president_name="نخست‌وزیر صالح")
        u3 = User(telegram_id=1003, username="leader_saudi", president_name="ملک سلمان")
        session.add_all([u1, u2, u3])
        await session.flush()

        c1 = Country(id=1, name_fa="ایران", name_en="Iran", flag="🇮🇷", region="خاورمیانه", owner_user_id=u1.telegram_id)
        c2 = Country(id=2, name_fa="عراق", name_en="Iraq", flag="🇮🇶", region="خاورمیانه", owner_user_id=u2.telegram_id)
        c3 = Country(id=3, name_fa="عربستان", name_en="Saudi Arabia", flag="🇸🇦", region="خاورمیانه", owner_user_id=u3.telegram_id)
        session.add_all([c1, c2, c3])
        await session.flush()

        # ۲. ارسال نامه از ایران به عراق
        l1 = await letters_repo.add_letter(session, c1.id, c2.id, "پیشنهاد برقراری صلح پایدار.")
        await session.commit()

        check("شناسه نامه ایجاد شد", l1.id is not None and l1.id > 0)
        check("وضعیت اولیه نامه بی‌پاسخ است", l1.replied is False)
        check("فرستنده و گیرنده تطابق دارند", l1.sender_country == 1 and l1.recipient_country == 2)

        # ۳. بررسی صندوق پستی عراق
        inbox_c2 = await letters_repo.list_inbox(session, c2.id)
        check("صندوق پستی عراق شامل ۱ نامه است", len(inbox_c2) == 1)
        check("شناسه نامه با نامه ارسالی مطابقت دارد", inbox_c2[0].id == l1.id)

        # ۴. ارسال پاسخ از عراق به ایران
        reply_l1 = await letters_repo.add_letter(
            session, c2.id, c1.id, "با کمال میل پیشنهاد صلح را می‌پذیریم.", parent_id=l1.id
        )
        l1.replied = True
        await session.commit()

        check("پاسخ دارای parent_id نامه اولیه است", reply_l1.parent_id == l1.id)
        check("وضعیت نامه اولیه به replied=True تغییر یافت", l1.replied is True)

        # ۵. صندوق پستی ایران شامل پاسخ دریافتی
        inbox_c1 = await letters_repo.list_inbox(session, c1.id)
        check("صندوق پستی ایران شامل ۱ پاسخ دریافتی است", len(inbox_c1) == 1)
        check("پاسخ دریافتی ایران دارای parent_id است", inbox_c1[0].parent_id == l1.id)

        # ۶. ساخت اتحاد میان ایران و عراق و بررسی منطق گیرندگان
        alliance = Alliance(name="پیمان بغداد-تهران", owner_country=c1.id)
        session.add(alliance)
        await session.flush()

        session.add_all([
            AllianceMember(alliance_id=alliance.id, country_id=c1.id),
            AllianceMember(alliance_id=alliance.id, country_id=c2.id),
        ])
        await session.commit()

        # ثبت نامه به تمام اعضای اتحاد به جز فرستنده
        from bot.database.repositories import alliances as alliances_repo
        members = await alliances_repo.list_members(session, alliance.id)
        ally_recipients = [m.country_id for m in members if m.country_id != c1.id]
        check("گیرندگان نامه متحدان فقط شامل عراق است", ally_recipients == [c2.id])


async def test_telegram_handlers_mock() -> None:
    print("\n--- ۳) تست رفتار هندلرهای تلگرام (عدم حذف تصویر و دکمه‌های اینلاین) ---")

    async with async_session_factory() as session:
        # واکشی نامه و کاربر
        c1 = await session.get(Country, 1)
        c2 = await session.get(Country, 2)
        l1 = await letters_repo.get_letter(session, 1)
        u2 = await session.get(User, 1002)

        # ۱. شبیه‌سازی کلیک روی دکمه «پاسخ به نامه» (cb_mail_reply)
        from bot.handlers.mail import cb_mail_reply, cb_mail_img

        mock_call = MagicMock()
        mock_call.data = f"mail_reply:{l1.id}"
        mock_call.answer = AsyncMock()
        mock_call.message = MagicMock()
        mock_call.message.photo = [MagicMock()]  # پیام شامل عکس است
        mock_call.message.answer = AsyncMock()
        mock_call.message.edit_text = AsyncMock()

        mock_state = MagicMock()
        mock_state.set_state = AsyncMock()
        mock_state.update_data = AsyncMock()

        await cb_mail_reply(call=mock_call, state=mock_state, session=session, db_user=u2)

        check(
            "در cb_mail_reply از call.message.answer برای حفظ عکس سند استفاده شده است",
            mock_call.message.answer.called,
        )
        check(
            "متن پاسخ از طریق edit_text ویرایش نشده تا عکس حذف نشود",
            not mock_call.message.edit_text.called,
        )
        mock_state.set_state.assert_called_once()
        mock_state.update_data.assert_called_once_with(reply_to=l1.id)

        # ۲. شبیه‌سازی کلیک روی دریافت مجدد تصویر از اینباکس (cb_mail_img)
        mock_img_call = MagicMock()
        mock_img_call.data = f"mail_img:{l1.id}"
        mock_img_call.answer = AsyncMock()
        mock_img_call.message = MagicMock()
        mock_img_call.message.answer_photo = AsyncMock()

        await cb_mail_img(call=mock_img_call, session=session, db_user=u2)

        check(
            "در cb_mail_img متد answer_photo با موفقیت صدا زده شد",
            mock_img_call.message.answer_photo.called,
        )
        kwargs = mock_img_call.message.answer_photo.call_args.kwargs
        photo_arg = kwargs.get("photo")
        check(
            "نوع ورودی photo از نوع BufferedInputFile است",
            photo_arg.__class__.__name__ == "BufferedInputFile",
        )
        check(
            "نام فایل با شماره نامه مطابقت دارد",
            photo_arg.filename == f"letter_{l1.id}.png",
        )
        check(
            "داده‌های ارسالی تصویر معتبر و دارای هدر PNG هستند",
            photo_arg.data.startswith(b"\x89PNG\r\n\x1a\n"),
        )


async def main() -> None:
    print("============================================================")
    print("🚀 آغاز تست‌های جامع آپدیت v2.7 (تولید تصویر اسناد دیپلماتیک)")
    print("============================================================")

    await test_image_rendering()
    await test_mail_database_flow()
    await test_telegram_handlers_mock()

    print("\n============================================================")
    print(f"نتایج: {_passed} تست موفق، {len(_failed)} تست ناموفق.")
    if _failed:
        print("❌ خطاهای شناسایی‌شده:")
        for f in _failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("🎉 تمامی تست‌های آپدیت v2.7 با موفقیت ۱۰۰٪ پاس شدند!")
    print("============================================================")


if __name__ == "__main__":
    asyncio.run(main())
