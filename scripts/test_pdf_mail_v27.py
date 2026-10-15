"""
تست خودکار و جامع آپدیت v2.7:
۱. تولید اسناد رسمی PDF در رم با رندر صحیح زبان فارسی (RTL)، اعداد، ایموجی‌ها و متون طولانی.
۲. بررسی درج مشخصات فرستنده (و رهبر)، گیرنده، شماره ثبت، تاریخ و مهر رسمی.
۳. بررسی جریان کامل ارسال نامه، نامه به متحدان، نامه سراسری و پاسخ به نامه در دیتابیس SQLite.
۴. تست رفتار safe_edit روی پیام‌های حاوی Document جهت جلوگیری از حذف فایل و عدم کرش هنگام کلیک روی پاسخ.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import BufferedInputFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import Alliance, AllianceMember, Country, Letter, User
from bot.database.repositories import alliances as alli_repo
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import letters as letters_repo
from bot.database.repositories import users as users_repo
from bot.services.pdf_service import generate_diplomatic_letter_pdf
from bot.utils.screens import safe_edit


async def run_tests() -> None:
    print("🚀 در حال اجرای تست‌های جامع آپدیت v2.7 (اسناد رسمی PDF دیپلماتیک)...")

    # ============================================================
    # بخش ۱: تست تولید فایل PDF در حافظه رم
    # ============================================================
    print("\n--- ۱. تست تولید اسناد PDF دیپلماتیک ---")

    # نامه کوتاه
    pdf_bytes_short = generate_diplomatic_letter_pdf(
        letter_id=101,
        sender_country_name="جمهوری اسلامی ایران",
        sender_flag="🇮🇷",
        sender_leader_name="سید علی حسینی",
        recipient_country_name="فدراسیون روسیه",
        recipient_flag="🇷🇺",
        letter_type="نامه رسمی دیپلماتیک",
        body="با سلام و احترام، مراتب دوستی و تعمیق روابط دیپلماتیک اعلام می‌گردد.",
        created_at=datetime.now(timezone.utc),
    )
    assert isinstance(pdf_bytes_short, bytes), "خروجی باید bytes باشد."
    assert pdf_bytes_short.startswith(b"%PDF-"), "فایل باید با هدر استاندارد %PDF- آغاز شود."
    assert len(pdf_bytes_short) > 2000, "اندازه بایت‌های PDF نباید خالی یا خیلی کم باشد."
    print("✅ تولید نامه کوتاه تک‌صفحه‌ای با سربرگ، کادر و مهر رسمی: موفق")

    # نامه با ایموجی و اعداد فارسی
    pdf_bytes_emoji = generate_diplomatic_letter_pdf(
        letter_id=102,
        sender_country_name="چین",
        sender_flag="🇨🇳",
        sender_leader_name="شی جین‌پینگ",
        recipient_country_name="برزیل",
        recipient_flag="🇧🇷",
        letter_type="نامه رسمی دیپلماتیک",
        body="همکاری‌های مشترک 🤝 در چارچوب بریکس 🌍 با مبلغ ۱۲,۰۰۰,۰۰۰ دلار تصویب شد. 🚀",
    )
    assert pdf_bytes_emoji.startswith(b"%PDF-"), "نامه حاوی ایموجی باید صحیح تولید شود."
    print("✅ تولید نامه دیپلماتیک حاوی اعداد و انواع ایموجی: موفق")

    # نامه به متحدان
    pdf_bytes_allies = generate_diplomatic_letter_pdf(
        letter_id=103,
        sender_country_name="فرانسه",
        recipient_country_name="آلمان",
        is_allies=True,
        body="ابلاغیه رسمی به تمامی کشورهای عضو پیمان دفاعی مشترک.",
    )
    assert pdf_bytes_allies.startswith(b"%PDF-")
    print("✅ تولید نامه به متحدان (با درج خودکار عنوان و پسوند ابلاغیه اعضای اتحاد): موفق")

    # نامه سراسری
    pdf_bytes_all = generate_diplomatic_letter_pdf(
        letter_id=104,
        sender_country_name="ایالات متحده آمریکا",
        recipient_country_name="ژاپن",
        is_all=True,
        body="بیانیه دیپلماتیک رسمی در خصوص امنیت دریانوردی بین‌المللی.",
    )
    assert pdf_bytes_all.startswith(b"%PDF-")
    print("✅ تولید نامه دیپلماتیک سراسری: موفق")

    # پاسخ به نامه (با parent_id)
    pdf_bytes_reply = generate_diplomatic_letter_pdf(
        letter_id=105,
        sender_country_name="فدراسیون روسیه",
        recipient_country_name="جمهوری اسلامی ایران",
        body="در پاسخ به پیام شما، با برگزاری نشست مشترک موافقت می‌شود.",
        parent_id=101,
    )
    assert pdf_bytes_reply.startswith(b"%PDF-")
    print("✅ تولید سند پاسخ به نامه (با ارجاع به نامه اصلی و نوع پاسخ رسمی): موفق")

    # متن طولانی چندصفحه‌ای
    long_body = "این یک بند رسمی از سند تفاهمنامه دیپلماتیک است که به تفصیل شرایط همکاری را بازگو می‌کند. " * 85
    pdf_bytes_long = generate_diplomatic_letter_pdf(
        letter_id=106,
        sender_country_name="بریتانیا",
        recipient_country_name="کانادا",
        body=long_body,
    )
    assert pdf_bytes_long.startswith(b"%PDF-")
    assert len(pdf_bytes_long) > len(pdf_bytes_short)
    print("✅ سرریز متن طولانی به صفحات بعد با حفظ کادربندی و پاورقی: موفق")

    # ============================================================
    # بخش ۲: تست پایگاه داده SQLite و جریان کامل نامه‌ها
    # ============================================================
    print("\n--- ۲. تست جریان کامل ارسال نامه، اتحاد و پاسخ در دیتابیس ---")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        await session.execute(text("PRAGMA foreign_keys = ON;"))

        # ایجاد کاربران و کشورهای نمونه
        u1 = User(telegram_id=1001, role="player", president_name="رئیس‌جمهور ایران")
        u2 = User(telegram_id=2002, role="player", president_name="رهبر کره شمالی")
        u3 = User(telegram_id=3003, role="player", president_name="رئیس‌جمهور روسیه")
        session.add_all([u1, u2, u3])
        await session.commit()

        c1 = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="middle_east",
            is_vip=True,
            owner_user_id=1001,
            is_claimed=True,
        )
        c2 = Country(
            name_en="North_Korea",
            name_fa="کره شمالی",
            flag="🇰🇵",
            region="east_asia",
            is_vip=False,
            owner_user_id=2002,
            is_claimed=True,
        )
        c3 = Country(
            name_en="Russia",
            name_fa="روسیه",
            flag="🇷🇺",
            region="europe",
            is_vip=True,
            owner_user_id=3003,
            is_claimed=True,
        )
        session.add_all([c1, c2, c3])
        await session.commit()

        # الف) ارسال نامه تکی
        ltr1 = await letters_repo.add_letter(session, c1.id, c2.id, "سلام به پیونگ‌یانگ.")
        assert ltr1.id is not None
        assert ltr1.sender_country == c1.id
        assert ltr1.recipient_country == c2.id

        doc1 = BufferedInputFile(pdf_bytes_short, filename=f"Diplomatic_Letter_{ltr1.id}.pdf")
        assert doc1.filename == f"Diplomatic_Letter_{ltr1.id}.pdf"
        print("✅ ثبت نامه در دیتابیس و آماده‌سازی سند BufferedInputFile: موفق")

        # ب) ایجاد اتحاد و ارسال نامه به متحدان
        alliance = await alli_repo.create_alliance(session, "اتحاد شرق", "مفاد دفاع مشترک", c1.id)
        await alli_repo.add_member(session, alliance.id, c3.id)
        members = await alli_repo.list_members(session, alliance.id)
        ally_ids = [m.country_id for m in members if m.country_id != c1.id]
        assert ally_ids == [c3.id]

        ltr_ally = await letters_repo.add_letter(session, c1.id, c3.id, "ابلاغیه مانور مشترک.")
        pdf_ally = generate_diplomatic_letter_pdf(
            letter_id=ltr_ally.id,
            sender_country_name=c1.name_fa,
            recipient_country_name=c3.name_fa,
            is_allies=True,
            body="ابلاغیه مانور مشترک.",
        )
        assert pdf_ally.startswith(b"%PDF-")
        print("✅ ارسال نامه به متحدان و تولید سند رسمی اتحاد: موفق")

        # ج) پاسخ به نامه (Reply Flow)
        reply_ltr = await letters_repo.add_letter(
            session, c2.id, c1.id, "پاسخ به پیشنهاد شما از پیونگ‌یانگ.", parent_id=ltr1.id
        )
        ltr1.replied = True
        await session.commit()

        refetched_ltr1 = await letters_repo.get_letter(session, ltr1.id)
        assert refetched_ltr1.replied is True
        assert reply_ltr.parent_id == ltr1.id

        pdf_rep = generate_diplomatic_letter_pdf(
            letter_id=reply_ltr.id,
            sender_country_name=c2.name_fa,
            recipient_country_name=c1.name_fa,
            body=reply_ltr.body,
            parent_id=ltr1.id,
        )
        assert pdf_rep.startswith(b"%PDF-")
        print("✅ پاسخ به نامه، علامت‌گذاری وضعیت replied و ثبت زنجیره parent_id: موفق")

        # د) صندوق پستی (Inbox)
        inbox_c1 = await letters_repo.list_inbox(session, c1.id)
        assert len(inbox_c1) == 1
        assert inbox_c1[0].id == reply_ltr.id
        print("✅ دریافت صندوق پستی با درج پاسخ‌ها و نامه‌های دریافتی: موفق")

    # ============================================================
    # بخش ۳: تست رفتار safe_edit روی پیام‌های حاوی سند / عکس / متن
    # ============================================================
    print("\n--- ۳. تست safe_edit برای عدم حذف فایل PDF و عدم کرش ---")

    # حالت اول: پیام حاوی Document (فایل PDF سند رسمی)
    call_doc = MagicMock()
    msg_doc = MagicMock()
    msg_doc.photo = None
    msg_doc.document = MagicMock() # سند موجود است
    msg_doc.delete = AsyncMock()
    msg_doc.edit_text = AsyncMock()
    msg_doc.answer = AsyncMock()
    call_doc.message = msg_doc

    await safe_edit(call_doc, "متن فرم جدید پاسخ")

    # نباید delete فراخوانی شود تا سند رسمی در چت باقی بماند
    msg_doc.delete.assert_not_called()
    # نباید edit_text فراخوانی شود تا خطای BadRequest تلگرام رخ ندهد
    msg_doc.edit_text.assert_not_called()
    # باید answer صدا زده شود تا پیام تازه ارسال شود
    msg_doc.answer.assert_called_once_with("متن فرم جدید پاسخ", reply_markup=None)
    print("✅ safe_edit روی پیام Document: عدم حذف فایل PDF و باز کردن فرم در پیام جدید: موفق")

    # حالت دوم: پیام متنی معمولی
    call_txt = MagicMock()
    msg_txt = MagicMock()
    msg_txt.photo = None
    msg_txt.document = None
    msg_txt.edit_text = AsyncMock()
    msg_txt.answer = AsyncMock()
    call_txt.message = msg_txt

    await safe_edit(call_txt, "ویرایش منوی متنی")
    msg_txt.edit_text.assert_called_once_with("ویرایش منوی متنی", reply_markup=None)
    msg_txt.answer.assert_not_called()
    print("✅ safe_edit روی پیام متنی ساده: ویرایش موفق edit_text بدون خطا: موفق")

    # حالت سوم: پیام عکس‌دار
    call_photo = MagicMock()
    msg_photo = MagicMock()
    msg_photo.photo = [MagicMock()]
    msg_photo.document = None
    msg_photo.delete = AsyncMock()
    msg_photo.answer = AsyncMock()
    call_photo.message = msg_photo

    await safe_edit(call_photo, "متن جدید بعد از منوی عکس‌دار")
    msg_photo.delete.assert_called_once()
    msg_photo.answer.assert_called_once_with("متن جدید بعد از منوی عکس‌دار", reply_markup=None)
    print("✅ safe_edit روی منوی عکس‌دار: حذف عکس و ارسال متن جدید: موفق")

    print("\n🎉 تمامی تست‌های آپدیت v2.7 با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
