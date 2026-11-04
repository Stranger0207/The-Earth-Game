"""
اسکریپت تست جامع قابلیت‌های آپدیت ۳:
- ویرایش پروفایل توییتر (نام نمایشی، یوزرنیم، عکس پروفایل)
- اعتبارسنجی‌ها (یوزرنیم، نام نمایشی، کلمات رزروشده)
- کراپ هوشمند ۱:۱ عکس پروفایل و رندر بدون کشیدگی
- کول‌داون ۲ ساعته برای تغییر هر فیلد
- قفل آپشن twitter_profile در LOCKABLE_FEATURES
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import datetime, timezone
from PIL import Image

from bot.constants import (
    FEATURE_CAT_DIPLOMACY,
    LOCKABLE_FEATURES,
    RESERVED_TWITTER_HANDLES,
    TWITTER_AVATAR_SIZE,
    TWITTER_NAME_MAX_CHARS,
    TWITTER_NAME_MIN_CHARS,
    TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS,
)
from bot.database.base import _COLUMN_MIGRATIONS, Base, async_session_factory, engine
from bot.database.models import Country, TwitterProfile, User
from bot.enums import GovernmentType
from bot.database.repositories import cooldowns as cd_repo
from bot.database.repositories import feature_locks as locks_repo
from bot.database.repositories import twitter as twitter_repo
from bot.handlers.twitter import validate_display_name, validate_username
from bot.services.tweet_image_service import (
    _draw_circular_avatar,
    process_avatar_upload,
    render_tweet_image,
)

PASS_COUNT = 0
FAIL_COUNT = 0


def check(title: str, condition: bool, extra: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [OK] {title}")
    else:
        FAIL_COUNT += 1
        msg = f"  [FAIL] {title}"
        if extra:
            msg += f" -> {extra}"
        print(msg)


async def main() -> None:
    print("=" * 70)
    print("🐦 آغاز آزمون‌های جامع سیستم ویرایش پروفایل توییتر و کراپ ۱:۱ آواتار (Update 3)")
    print("=" * 70)

    # ----------------------------------------------------
    # ۱. بررسی ثابت‌ها و LOCKABLE_FEATURES و Migrations
    # ----------------------------------------------------
    print("\n📦 بررسی ۱: رجیستری ثابت‌ها، فیچرقفل و مایگریشن دیتابیس")
    check(
        "کلید twitter_profile در LOCKABLE_FEATURES تعریف شده است",
        "twitter_profile" in LOCKABLE_FEATURES,
    )
    title, cat = LOCKABLE_FEATURES.get("twitter_profile", ("", ""))
    check("دسته‌بندی twitter_profile برابر FEATURE_CAT_DIPLOMACY است", cat == FEATURE_CAT_DIPLOMACY)
    check("طول حداقل نام نمایشی ۳ است", TWITTER_NAME_MIN_CHARS == 3)
    check("طول حداکثر نام نمایشی ۳۵ است", TWITTER_NAME_MAX_CHARS == 35)
    check("سایز کراپ آواتار ۵۱۲ است", TWITTER_AVATAR_SIZE == 512)
    check("کول‌داون ویرایش پروفایل ۲ ساعت است", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS == 2)
    check("کلمات رزروشده شامل admin و god و official است", {"admin", "god", "official"}.issubset(RESERVED_TWITTER_HANDLES))

    has_migration = any(
        table == "twitter_profiles" and col == "display_name"
        for table, col, _ in _COLUMN_MIGRATIONS
    )
    check("ستون display_name به _COLUMN_MIGRATIONS اضافه شده است", has_migration)

    # ----------------------------------------------------
    # ۲. اعتبارسنجی نام کاربری (validate_username)
    # ----------------------------------------------------
    print("\n🏷 بررسی ۲: اعتبارسنجی دقیق نام کاربری (Handle)")
    # موارد معتبر
    valid_handles = ["Iran_MFA", "US_Gov_1", "France", "abc", "A_1234567890123"]
    for h in valid_handles:
        ok, res = validate_username(h)
        check(f"نام کاربری معتبر '{h}' پذیرفته شد", ok and res == h.lower())

    # شروع با @ باید به درستی پاکسازی شود
    ok, res = validate_username("@Tehran_Times")
    check("لیدینگ @ به درستی استریپ شد", ok and res == "tehran_times")

    # موارد نامعتبر: طول کمتر از ۳
    ok, _ = validate_username("ab")
    check("یوزرنیم ۲ کاراکتری رد شد", not ok)

    # طول بیشتر از ۱۵
    ok, _ = validate_username("A_very_long_handle_123")
    check("یوزرنیم بیش از ۱۵ کاراکتر رد شد", not ok)

    # شروع با رقم یا آندرلاین
    ok, _ = validate_username("123abc_")
    check("یوزرنیم شروع‌شده با عدد رد شد", not ok)
    ok, _ = validate_username("_myhandle")
    check("یوزرنیم شروع‌شده با آندرلاین رد شد", not ok)

    # کاراکترهای غیرمجاز (خط تیره، فاصله، فارسی، نقطه)
    ok, _ = validate_username("iran-mfa")
    check("یوزرنیم دارای هایفن (-) رد شد", not ok)
    ok, _ = validate_username("user name")
    check("یوزرنیم دارای اسپیس رد شد", not ok)
    ok, _ = validate_username("ایران")
    check("یوزرنیم فارسی رد شد", not ok)
    ok, _ = validate_username("user.name")
    check("یوزرنیم دارای نقطه رد شد", not ok)

    # یوزرنیم‌های رزروشده
    for res_name in ["admin", "ADMIN", "god", "God", "root", "unitednations", "official"]:
        ok, _ = validate_username(res_name)
        check(f"یوزرنیم رزروشده '{res_name}' بدون حساسیت به حروف بزرگ/کوچک رد شد", not ok)

    # ----------------------------------------------------
    # ۳. اعتبارسنجی نام نمایشی (validate_display_name)
    # ----------------------------------------------------
    print("\n👤 بررسی ۳: اعتبارسنجی نام نمایشی (Display Name)")
    valid_names = ["جمهوری اسلامی ایران", "United States of America", "امپراتوری ژاپن 🇯🇵", "دکتر مصدق"]
    for name in valid_names:
        ok, res = validate_display_name(name)
        check(f"نام نمایشی معتبر '{name}' تأیید شد", ok and res == name.strip())

    # طول نامعتبر
    ok, _ = validate_display_name("  AB  ")
    check("نام کمتر از ۳ کاراکتر رد شد", not ok)
    ok, _ = validate_display_name("A" * 36)
    check("نام بیشتر از ۳۵ کاراکتر رد شد", not ok)

    # کاراکترهای کنترلی
    ok, _ = validate_display_name("Iran\x00MFA")
    check("نام دارای کاراکتر کنترلی NUL رد شد", not ok)
    ok, _ = validate_display_name("Iran\x1fGov")
    check("نام دارای کاراکتر کنترلی 0x1F رد شد", not ok)
    ok, _ = validate_display_name("Iran\x85Test")
    check("نام دارای کاراکتر کنترلی یونیکد 0x85 رد شد", not ok)

    # ----------------------------------------------------
    # ۴. دیتابیس و ریپازیتوری‌ها
    # ----------------------------------------------------
    print("\n🗄 بررسی ۴: ذخیره و بازیابی در پایگاه داده و ریپازیتوری")
    if os.path.exists("./test.db"):
        try:
            os.remove("./test.db")
        except Exception:
            pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        country1 = Country(
            name_fa="آلمان",
            name_en="Germany",
            flag="🇩🇪",
            region="Europe",
            government_type=GovernmentType.FEDERAL,
        )
        country2 = Country(
            name_fa="فرانسه",
            name_en="France",
            flag="🇫🇷",
            region="Europe",
            government_type=GovernmentType.REPUBLIC,
        )
        session.add_all([country1, country2])
        await session.flush()

        # ایجاد پروفایل اول
        p1 = await twitter_repo.create_profile(
            session,
            country_id=country1.id,
            username="Germany_MFA",
            avatar_file_id="file_avatar_1",
            display_name="جمهوری فدرال آلمان",
        )
        check("پروفایل کشور ۱ ساخته شد", p1.id is not None and p1.username == "germany_mfa")
        check("display_name به درستی ذخیره شد", p1.display_name == "جمهوری فدرال آلمان")

        # جستجوی یکتا با حروف کوچک و بزرگ
        found1 = await twitter_repo.get_profile_by_username(session, "GERMANY_mfa")
        check("جستجو بر اساس یوزرنیم غیرحساس به بزرگی/کوچکی حروف کار می‌کند", found1 is not None and found1.country_id == country1.id)

        # به‌روزرسانی نام نمایشی
        updated_p = await twitter_repo.update_profile_display_name(session, country1.id, "صدراعظم آلمان")
        check("به‌روزرسانی display_name موفقیت‌آمیز بود", updated_p is not None and updated_p.display_name == "صدراعظم آلمان")

        # به‌روزرسانی یوزرنیم
        updated_u = await twitter_repo.update_profile_username(session, country1.id, "bundeskanzler")
        check("به‌روزرسانی username به حروف کوچک ذخیره شد", updated_u is not None and updated_u.username == "bundeskanzler")

        # به‌روزرسانی آواتار
        updated_a = await twitter_repo.update_profile_avatar(session, country1.id, "file_avatar_new_cropped")
        check("به‌روزرسانی avatar_file_id موفقیت‌آمیز بود", updated_a is not None and updated_a.avatar_file_id == "file_avatar_new_cropped")

        # یکتایی یوزرنیم برای کشور دوم
        p2 = await twitter_repo.create_profile(
            session,
            country_id=country2.id,
            username="Elysee_Palace",
            avatar_file_id="file_avatar_2",
            display_name="کاخ الیزه",
        )
        # بررسی تکراری بودن یوزرنیم کشور اول در صورت انتصاب به کشور دوم
        dup = await twitter_repo.get_profile_by_username(session, "bundeskanzler")
        check("تداخل یوزرنیم: یوزرنیم bundeskanzler به کشور ۱ تعلق دارد و کشور ۲ نمی‌تواند بردارد", dup is not None and dup.country_id != country2.id)

    # ----------------------------------------------------
    # ۵. بررسی کول‌داون‌های تغییر پروفایل
    # ----------------------------------------------------
    print("\n⏳ بررسی ۵: کول‌داون‌های مجزای فیلدهای پروفایل")
    async with async_session_factory() as session:
        # قبل از تاچ: زمان باقی‌مانده ۰ است
        rem_name = await cd_repo.remaining_seconds(session, country1.id, "tw_edit_name", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)
        check("کول‌داون نام قبل از تغییر ۰ است", rem_name == 0)

        # تاچ کردن کول‌داون نام
        await cd_repo.touch(session, country1.id, "tw_edit_name")
        rem_name_after = await cd_repo.remaining_seconds(session, country1.id, "tw_edit_name", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)
        check("کول‌داون نام پس از تغییر بیش از ۰ است", rem_name_after > 7100)

        # سایر فیلدها نباید مسدود شوند (کول‌داون مستقل)
        rem_user = await cd_repo.remaining_seconds(session, country1.id, "tw_edit_username", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)
        rem_avatar = await cd_repo.remaining_seconds(session, country1.id, "tw_edit_avatar", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)
        check("کول‌داون یوزرنیم مستقل از نام است و ۰ است", rem_user == 0)
        check("کول‌داون آواتار مستقل از نام است و ۰ است", rem_avatar == 0)

    # ----------------------------------------------------
    # ۶. پردازش هوشمند تصویر و کراپ ۱:۱ مربعی (Pillow)
    # ----------------------------------------------------
    print("\n✂️ بررسی ۶: کراپ مربعی ۱:۱ آواتار و رفع مشکل کشیدگی تصویر")

    # تست ۱: تصویر افقی عریض (Landscape 800x400)
    img_landscape = Image.new("RGB", (800, 400), color=(200, 50, 50))
    buf_l = io.BytesIO()
    img_landscape.save(buf_l, format="JPEG")
    bytes_l = buf_l.getvalue()

    cropped_l = process_avatar_upload(bytes_l, target_size=512)
    res_img_l = Image.open(io.BytesIO(cropped_l))
    check("تصویر افقی ۸۰۰×۴۰۰ به مربع ۵۱۲×۵۱۲ کراپ شد", res_img_l.size == (512, 512) and res_img_l.format == "PNG")

    # تست ۲: تصویر عمودی کشیده (Portrait 300x900)
    img_portrait = Image.new("RGB", (300, 900), color=(50, 150, 50))
    buf_p = io.BytesIO()
    img_portrait.save(buf_p, format="PNG")
    bytes_p = buf_p.getvalue()

    cropped_p = process_avatar_upload(bytes_p, target_size=512)
    res_img_p = Image.open(io.BytesIO(cropped_p))
    check("تصویر عمودی ۳۰۰×۹۰۰ به مربع ۵۱۲×۵۱۲ کراپ شد", res_img_p.size == (512, 512))

    # تست ۳: تصویر با کانال آلفا (RGBA با ترنسپرنسی)
    img_rgba = Image.new("RGBA", (400, 400), color=(50, 50, 200, 128))
    buf_rgba = io.BytesIO()
    img_rgba.save(buf_rgba, format="PNG")
    bytes_rgba = buf_rgba.getvalue()

    cropped_rgba = process_avatar_upload(bytes_rgba, target_size=512)
    res_img_rgba = Image.open(io.BytesIO(cropped_rgba))
    check("تصویر RGBA شفاف با پس‌زمینه مناسب به ۵۱۲×۵۱۲ تبدیل شد", res_img_rgba.size == (512, 512) and res_img_rgba.mode == "RGB")

    # تست ۴: خطای تصاویر خراب یا خالی
    try:
        process_avatar_upload(b"", target_size=512)
        check("بایت‌های خالی باید خطا دهند", False)
    except ValueError:
        check("بایت‌های خالی با ValueError به درستی رد شدند", True)

    try:
        process_avatar_upload(b"NOT_AN_IMAGE_DATA_12345", target_size=512)
        check("داده نامعتبر باید خطا دهد", False)
    except ValueError:
        check("داده نامعتبر با پیام فارسی رد شد", True)

    # تست ۵: تصویر بسیار کوچک (کمتر از ۱۶×۱۶)
    tiny_img = Image.new("RGB", (10, 10), color=(0, 0, 0))
    buf_tiny = io.BytesIO()
    tiny_img.save(buf_tiny, format="PNG")
    try:
        process_avatar_upload(buf_tiny.getvalue(), target_size=512)
        check("تصویر کوچک ۱۰×۱۰ باید خطا دهد", False)
    except ValueError:
        check("تصویر بسیار کوچک ۱۰×۱۰ رد شد", True)

    # تست ۶: بررسی _draw_circular_avatar با supersampling
    circ_im = _draw_circular_avatar(res_img_l, size=80)
    check("آواتار دایره‌ای با ابعاد ۸۰×۸۰ و مد RGBA تولید شد", circ_im.size == (80, 80) and circ_im.mode == "RGBA")
    # بررسی گوشه ترنسپرنت (گوشه بالا چپ (0, 0) باید کاملاً شفاف باشد)
    corner_pixel = circ_im.getpixel((0, 0))
    check("گوشه‌های ماسک دایره‌ای کاملاً شفاف (Alpha=0) هستند", corner_pixel[3] == 0)
    # مرکز آواتار (40, 40) باید کاملاً مات باشد
    center_pixel = circ_im.getpixel((40, 40))
    check("مرکز آواتار دایره‌ای کاملاً مات (Alpha=255) است", center_pixel[3] == 255)

    # ----------------------------------------------------
    # ۷. رندر کارت توییت با display_name جدید
    # ----------------------------------------------------
    print("\n🎨 بررسی ۷: رندر کارت گرافیکی توییت با نام نمایشی رسمی")
    card_bytes = render_tweet_image(
        country_name="فرانسه",
        president_name="کاخ الیزه — ریاست جمهوری",
        country_flag="🇫🇷",
        username="elysee_palace",
        content="صلح جهانی و احترام به حاکمیت ملی کشورها آرمان مشترک بشریت است.",
        avatar_bytes=cropped_p,
        created_at=datetime.now(timezone.utc),
    )
    check("کارت توییت با موفقیت رندر شد", len(card_bytes) > 1000)
    card_img = Image.open(io.BytesIO(card_bytes))
    check("کارت توییت دارای ابعاد استاندارد با عرض ۱۰۰۰ پیکسل است", card_img.size[0] == 1000 and card_img.size[1] >= 450)

    # ----------------------------------------------------
    # ۸. جمع‌بندی نهایی
    # ----------------------------------------------------
    print("\n" + "=" * 70)
    print(f"📊 جمع‌بندی نتایج تست: {PASS_COUNT} موفق | {FAIL_COUNT} ناموفق")
    print("=" * 70)

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
