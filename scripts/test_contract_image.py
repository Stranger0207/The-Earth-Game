"""
تست جامع تبدیل قراردادهای دیپلماتیک به تصاویر گرافیکی رسمی با امضای واقعی (v2.9).
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import datetime, timezone

# اطمینان از خروجی یونیکد در ویندوز
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# افزودن ریشه پروژه به مسیر پایتون
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.database.base import Base
from bot.database.models import Contract, Country, User
from bot.enums import DiplomacyStatus, UserRole
from bot.services.letter_image_service import (
    _draw_ink_signature,
    _draw_wax_seal,
    render_contract_image,
)


def test_treaty_image_rendering_short():
    """تست تولید تصویر معاهده رسمی با متن کوتاه و بررسی ابعاد."""
    print("🔹 تست ۱: تولید تصویر معاهده با متن استاندارد...")
    img_bytes = render_contract_image(
        contract_id=101,
        title="پیمان همکاری‌های امنیتی و اقتصادی مشترک",
        country_a_name="ایران",
        country_a_flag="🇮🇷",
        country_a_leader="دکتر مسعود پزشکیان",
        country_b_name="روسیه",
        country_b_flag="🇷🇺",
        country_b_leader="ولادیمیر پوتین",
        body=(
            "ماده ۱: طرفین متعهد می‌گردند در کلیه بحران‌های منطقه‌ای هماهنگی اطلاعاتی داشته باشند.\n"
            "ماده ۲: تبادلات تجاری و بانکی با ارزهای ملی دو کشور تسهیل و تقویت خواهد شد.\n"
            "ماده ۳: این معاهده از تاریخ امضا برای طرفین لازم‌الاجرا و غیرقابل نقض می‌باشد."
        ),
        created_at=datetime.now(timezone.utc),
    )

    assert isinstance(img_bytes, bytes), "خروجی باید بایت باشد"
    assert img_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "خروجی باید فرمت معتبر PNG باشد"

    im = Image.open(io.BytesIO(img_bytes))
    width, height = im.size
    print(f"   ابعاد سند: {width}x{height} پیکسل")
    assert width == 1000, f"عرض تصویر باید ۱۰۰۰ پیکسل باشد، اما {width} است"
    assert height >= 860, f"حداقل ارتفاع معاهده باید ۸۶۰ پیکسل باشد، اما {height} است"
    print("   ✅ تصویر معاهده با موفقیت تولید و ابعاد تایید شد.")


def test_treaty_image_rendering_long_dynamic_height():
    """تست تولید تصویر معاهده با متن بسیار طولانی جهت بررسی گسترش پویای ارتفاع."""
    print("🔹 تست ۲: بررسی گسترش پویای ارتفاع بوم معاهده (Dynamic Canvas Expansion)...")
    long_body = "\n".join([
        f"بند {i}: این یک بند تفصیلی و مهم در زمینه پروتکل‌های گمرکی، ترانزیت کالا و استانداردهای متقابل امنیتی میان طرفین معاهده می‌باشد که تعهدات حقوقی سنگینی برای هر دو دولت به همراه دارد."
        for i in range(1, 26)
    ])

    img_bytes = render_contract_image(
        contract_id=102,
        title="معاهده جامع صلح، دریانوردی و کریدورهای ترانزیتی شمال-جنوب",
        country_a_name="ایران",
        country_a_flag="🇮🇷",
        country_a_leader="دکتر مسعود پزشکیان",
        country_b_name="چین",
        country_b_flag="🇨🇳",
        country_b_leader="شی جین پینگ",
        body=long_body,
        created_at=datetime.now(timezone.utc),
    )

    im = Image.open(io.BytesIO(img_bytes))
    width, height = im.size
    print(f"   ابعاد سند طولانی: {width}x{height} پیکسل")
    assert width == 1000
    assert height > 1100, f"ارتفاع باید متناسب با ۲۵ بند طولانی به بیش از ۱۱۰۰ پیکسل افزایش یابد، اما {height} است"
    print("   ✅ گسترش پویای ارتفاع بوم در متون طولانی تایید شد.")


def test_ink_signature_determinism():
    """تست قطعی (Deterministic) بودن امضاهای جوهری شبیه‌سازی‌شده."""
    print("🔹 تست ۳: بررسی یکتایی و قطعیت امضاهای جوهری...")
    from PIL import ImageDraw

    im1 = Image.new("RGB", (300, 150), "#FFFFFF")
    draw1 = ImageDraw.Draw(im1)
    _draw_ink_signature(draw1, 150, 75, seed_text="Iran_Leader_1")

    im2 = Image.new("RGB", (300, 150), "#FFFFFF")
    draw2 = ImageDraw.Draw(im2)
    _draw_ink_signature(draw2, 150, 75, seed_text="Iran_Leader_1")

    im3 = Image.new("RGB", (300, 150), "#FFFFFF")
    draw3 = ImageDraw.Draw(im3)
    _draw_ink_signature(draw3, 150, 75, seed_text="Russia_Leader_2")

    buf1 = io.BytesIO()
    im1.save(buf1, format="PNG")
    buf2 = io.BytesIO()
    im2.save(buf2, format="PNG")
    buf3 = io.BytesIO()
    im3.save(buf3, format="PNG")

    assert buf1.getvalue() == buf2.getvalue(), "امضای تولید شده با Seed یکسان باید ۱۰۰٪ تطابق بایتی داشته باشد"
    assert buf1.getvalue() != buf3.getvalue(), "امضای کشورهای مختلف با Seed متفاوت نباید یکسان باشد"
    print("   ✅ قطعیت و تنوع امضاهای جوهری تایید شد.")


async def test_database_and_signing_flow():
    """تست جریان امضای قرارداد و استخراج اطلاعات در دیتابیس آزمایشی SQLite."""
    print("🔹 تست ۴: تست کامل چرخه انعقاد معاهده در پایگاه داده...")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # ساخت کاربران طرفین
        user_a = User(
            telegram_id=11111,
            username="leader_iran",
            first_name="مسعود",
            president_name="دکتر مسعود پزشکیان",
            role=UserRole.PLAYER,
        )
        user_b = User(
            telegram_id=22222,
            username="leader_russia",
            first_name="ولادیمیر",
            president_name="ولادیمیر پوتین",
            role=UserRole.PLAYER,
        )
        session.add_all([user_a, user_b])
        await session.flush()

        # ساخت کشورهای طرفین
        country_a = Country(
            name_en="Iran",
            name_fa="ایران",
            flag="🇮🇷",
            region="خاورمیانه",
            owner_user_id=user_a.telegram_id,
            is_claimed=True,
        )
        country_b = Country(
            name_en="Russia",
            name_fa="روسیه",
            flag="🇷🇺",
            region="اوراسیا",
            owner_user_id=user_b.telegram_id,
            is_claimed=True,
        )
        session.add_all([country_a, country_b])
        await session.flush()

        # ثبت قرارداد در حالت PENDING
        contract = Contract(
            country_a=country_a.id,
            country_b=country_b.id,
            title="پیمان راهبردی تهران - مسکو",
            body="مفاد رسمی همکاری‌های صلح‌آمیز و گسترش خطوط کشتیرانی دریای خزر.",
            signed_a=True,
            signed_b=False,
            status=DiplomacyStatus.PENDING,
        )
        session.add(contract)
        await session.commit()

        # شبیه‌سازی امضای طرف دوم و فعال‌سازی
        contract.signed_b = True
        contract.status = DiplomacyStatus.ACTIVE
        await session.commit()

        # رندر سند رسمی با اطلاعات دیتابیس
        treaty_bytes = render_contract_image(
            contract_id=contract.id,
            title=contract.title,
            country_a_name=country_a.name_fa,
            country_a_flag=country_a.flag,
            country_a_leader=user_a.president_name,
            country_b_name=country_b.name_fa,
            country_b_flag=country_b.flag,
            country_b_leader=user_b.president_name,
            body=contract.body,
            created_at=contract.created_at,
        )

        assert isinstance(treaty_bytes, bytes)
        assert len(treaty_bytes) > 20000, "سند گرافیکی باید حجم تصویری واقعی داشته باشد"
        print(f"   حجم سند رسمی تولیدشده: {len(treaty_bytes):,} بایت")
        print("   ✅ چرخه معاهده در دیتابیس و اتصال اطلاعات رهبران با موفقیت تایید شد.")

    await engine.dispose()


def main():
    print("=" * 65)
    print("🚀 آغاز تست‌های خودکار Update #1 (تصویرسازی اسناد معاهدات دیپلماتیک)")
    print("=" * 65)

    test_treaty_image_rendering_short()
    test_treaty_image_rendering_long_dynamic_height()
    test_ink_signature_determinism()
    asyncio.run(test_database_and_signing_flow())

    print("=" * 65)
    print("🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند! سیستم معاهدات آماده است.")
    print("=" * 65)


if __name__ == "__main__":
    main()
