"""
هندلرهای سیستم توییتر جهانی (X) در منوی دیپلماسی و کانال رسمی (v3.0).

قابلیت‌ها:
- آنبوردینگ و ثبت‌نام اولیه کشورها (انتخاب یوزرنیم یکتا و آپلود آواتار با کراپ خودکار ۱:۱).
- نگارش و انتشار توییت در کانال رسمی با تصویر گرافیکی Dark Mode.
- دکمه شیشه‌ای لایک با شمارنده تعاملی زیر پست‌های کانال رسمی (Toggle).
- مشاهده توییت‌های اخیر کشور.
- ویرایش پروفایل (تغییر نام نمایشی، یوزرنیم و عکس پروفایل مربعی با کول‌داون و ثبت لاگ ادمین).
- قفل آپشن از طریق /god با گاردهای assert_feature ("twitter", "twitter_profile").
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    RESERVED_TWITTER_HANDLES,
    TWEET_CHANNEL_ID,
    TWEET_COOLDOWN_HOURS,
    TWITTER_AVATAR_MAX_BYTES,
    TWITTER_AVATAR_SIZE,
    TWITTER_NAME_MAX_CHARS,
    TWITTER_NAME_MIN_CHARS,
    TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS,
)
from ..database.models import User
from ..database.repositories import cooldowns as cd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import twitter as twitter_repo
from ..loader import bot
from ..services.news_service import send_log, send_log_photo
from ..services.tweet_image_service import process_avatar_upload, render_tweet_image
from ..states.forms import TweetForm, TwitterEditProfileForm, TwitterOnboardingForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)

router = Router(name="twitter")

# الگوی اعتبارسنجی نام کاربری توییتر: ۳ تا ۱۵ کاراکتر، شروع با حرف انگلیسی، شامل حروف انگلیسی، اعداد و خط زیر (_)
USERNAME_SAFE_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,14}$")


def validate_username(raw: str) -> tuple[bool, str]:
    """اعتبارسنجی نام کاربری توییتر طبق قواعد بازی."""
    clean = raw.strip().lstrip("@")
    if len(clean) < 3 or len(clean) > 15:
        return False, "طول نام کاربری باید بین ۳ تا ۱۵ کاراکتر باشد."
    if not clean[0].isalpha() or not clean[0].isascii():
        return False, "نام کاربری باید با یک حرف انگلیسی (A-Z) آغاز شود."
    if not USERNAME_SAFE_REGEX.match(clean):
        return False, "نام کاربری فقط می‌تواند شامل حروف انگلیسی، اعداد و خط زیر (_) باشد."
    if clean.lower() in RESERVED_TWITTER_HANDLES:
        return False, f"نام کاربری «@{clean}» یک نام رزروشده سیستمی است و قابل استفاده نمی‌باشد."
    return True, clean.lower()


def validate_display_name(raw: str) -> tuple[bool, str]:
    """اعتبارسنجی نام نمایشی توییتر."""
    cleaned = raw.strip()
    if len(cleaned) < TWITTER_NAME_MIN_CHARS or len(cleaned) > TWITTER_NAME_MAX_CHARS:
        return (
            False,
            f"طول نام نمایشی باید بین {fa_number(TWITTER_NAME_MIN_CHARS)} تا {fa_number(TWITTER_NAME_MAX_CHARS)} کاراکتر باشد.",
        )
    for ch in cleaned:
        if ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return False, "نام نمایشی شامل کاراکترهای کنترلی یا نامعتبر است."
    return True, cleaned


def _twitter_home_kb() -> InlineKeyboardMarkup:
    """کیبورد منوی اصلی توییتر."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ ارسال توییت جدید", callback_data="tweet:new", style=STYLE_OK)
    builder.button(text="📜 توییت‌های من", callback_data="tweet:mine", style=STYLE_MAIN)
    builder.button(text="✏️ ویرایش پروفایل", callback_data="tw:edit_profile", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def _twitter_edit_profile_kb() -> InlineKeyboardMarkup:
    """کیبورد زیرمنوی ویرایش پروفایل توییتر."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📸 تغییر عکس پروفایل", callback_data="tw_edit:avatar", style=STYLE_MAIN)
    builder.button(text="✏️ تغییر نام نمایشی", callback_data="tw_edit:name", style=STYLE_MAIN)
    builder.button(text="🏷 تغییر نام کاربری", callback_data="tw_edit:username", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به توییتر", callback_data="dip:twitter", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


# ============================================================
#  ورود به بخش توییتر از منوی دیپلماسی
# ============================================================


@router.callback_query(F.data == "dip:twitter")
async def cb_twitter_main(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """منوی ورود به توییتر یا آغاز آنبوردینگ در صورت نداشتن حساب."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    # بررسی قفل آپشن
    if not await assert_feature(call, session, country, "twitter"):
        return

    await state.clear()
    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        # کشور هنوز حسابی ثبت نکرده است -> آغاز آنبوردینگ
        await state.set_state(TwitterOnboardingForm.entering_username)
        text = (
            "🐦 <b>راه‌اندازی حساب رسمی توییتر (X)</b>\n\n"
            f"کشور: {country.flag} <b>{country.name_fa}</b>\n\n"
            "برای انتشار مواضع رسمی کشور خود در کانال جهانی توییتر، ابتدا باید یک <b>نام کاربری (Handle)</b> "
            "و یک <b>عکس پروفایل</b> تنظیم کنید.\n\n"
            f"ℹ️ <i>پس از ثبت‌نام، امکان ویرایش فیلدها با کول‌داون {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعته فراهم است.</i>\n\n"
            "لطفاً <b>نام کاربری انگلیسی</b> مد نظر خود را بدون @ ارسال کنید (مثلاً: Iran_MFA یا WhiteHouse):"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN),
        ]])
        await safe_edit(call, text, reply_markup=kb)
        return

    # حساب از قبل وجود دارد -> نمایش صفحه خانه توییتر
    t_count = await twitter_repo.count_tweets_by_country(session, country.id)
    disp_name = profile.display_name or db_user.president_name or country.name_fa
    text = (
        "🐦 <b>شبکه اجتماعی توییتر (X) — ستاد دیپلماسی عمومی</b>\n\n"
        f"🏛 <b>کشور:</b> {country.flag} {country.name_fa}\n"
        f"👤 <b>نام نمایشی:</b> {html.escape(disp_name)}\n"
        f"🏷 <b>نام کاربری رسمی:</b> <code>@{profile.username}</code> 🔹\n"
        f"📊 <b>تعداد توییت‌های فصل:</b> {fa_number(t_count)}\n\n"
        "<i>از این بخش می‌توانید پیام‌ها، بیانیه‌ها و مواضع دیپلماتیک خود را در قالب اسکرین‌شات گرافیکی رسمی در کانال توییتر جهانی منتشر کنید.</i>"
    )
    await show_menu(call, text, reply_markup=_twitter_home_kb(), image_key="twitter")


# ============================================================
#  فرم آنبوردینگ: دریافت نام کاربری و عکس پروفایل
# ============================================================


@router.message(TwitterOnboardingForm.entering_username, F.text)
async def msg_onboarding_username(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """بررسی و اعتبارسنجی نام کاربری ارسالی."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    is_valid, res = validate_username(message.text)
    if not is_valid:
        await message.answer(f"❌ <b>خطا در نام کاربری:</b>\n{res}\n\nلطفاً مجدداً ارسال کنید:")
        return

    # بررسی عدم تکراری بودن یوزرنیم در پایگاه داده
    existing = await twitter_repo.get_profile_by_username(session, res)
    if existing is not None:
        await message.answer(
            f"❌ نام کاربری <code>@{res}</code> قبلاً توسط کشور دیگری ثبت شده است!\n"
            "لطفاً نام کاربری متفاوتی وارد کنید:"
        )
        return

    await state.update_data(username=res)
    await state.set_state(TwitterOnboardingForm.uploading_avatar)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="menu:diplomacy", style=STYLE_MAIN),
    ]])
    await message.answer(
        f"✅ نام کاربری <code>@{res}</code> با موفقیت تأیید شد.\n\n"
        "🖼 حالا لطفاً <b>تصویر پروفایل</b> مد نظر برای این حساب را ارسال نمایید (عکس یا فایل تصویری):",
        reply_markup=kb,
    )


@router.message(TwitterOnboardingForm.uploading_avatar, F.photo | F.document)
async def msg_onboarding_avatar(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """دریافت تصویر، کراپ مربعی ۱:۱ و ایجاد پروفایل توییتر."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    username = data.get("username")
    if not username:
        await state.clear()
        await message.answer("خطا در روند ثبت‌نام. لطفاً مجدداً اقدام کنید.")
        return

    file_id: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        doc = message.document
        mime = doc.mime_type or ""
        if not (mime.startswith("image/") or (doc.file_name and doc.file_name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))):
            await message.answer("⚠️ فایل ارسالی باید یک تصویر معتبر (JPEG, PNG, WEBP) باشد.")
            return
        if doc.file_size and doc.file_size > TWITTER_AVATAR_MAX_BYTES:
            await message.answer("⚠️ حجم فایل تصویر نباید بیشتر از ۵ مگابایت باشد.")
            return
        file_id = doc.file_id

    if not file_id:
        await message.answer("⚠️ لطفاً یک تصویر معتبر ارسال کنید:")
        return

    avatar_file_id = file_id
    try:
        file_info = await bot.get_file(file_id)
        if file_info.file_path:
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=buf)
            raw_bytes = buf.getvalue()
            if len(raw_bytes) > TWITTER_AVATAR_MAX_BYTES:
                await message.answer("⚠️ حجم تصویر بیش از حد مجاز (۵ مگابایت) است.")
                return
            cropped_bytes = await asyncio.to_thread(process_avatar_upload, raw_bytes, TWITTER_AVATAR_SIZE)
            sent_avatar = await message.answer_photo(
                photo=BufferedInputFile(cropped_bytes, filename="avatar.png"),
                caption="✂️ تصویر پروفایل شما با کادر مربعی ۱:۱ از مرکز برش داده شد.",
            )
            if sent_avatar.photo:
                avatar_file_id = sent_avatar.photo[-1].file_id
    except ValueError as exc:
        await message.answer(f"❌ خطا در پردازش تصویر: {exc}\nلطفاً تصویر دیگری ارسال کنید:")
        return
    except Exception as exc:
        logger.warning("Could not process onboarding avatar: %s", exc)

    # ذخیره در دیتابیس
    disp_name = db_user.president_name or country.name_fa
    profile = await twitter_repo.create_profile(
        session, country_id=country.id, username=username, avatar_file_id=avatar_file_id, display_name=disp_name
    )
    await state.clear()

    await message.answer(
        "🎉 <b>حساب رسمی توییتر کشور شما با موفقیت ایجاد شد!</b>\n\n"
        f"🏛 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"👤 نام نمایشی: <b>{html.escape(disp_name)}</b>\n"
        f"🏷 نام کاربری: <code>@{profile.username}</code> 🔹 (دارای تیک آبی تأیید)\n\n"
        "از هم‌اکنون می‌توانید توییت‌های رسمی خود را به کانال جهانی مخابره کنید.",
        reply_markup=_twitter_home_kb(),
    )


@router.message(TwitterOnboardingForm.uploading_avatar)
async def msg_onboarding_avatar_invalid(message: Message) -> None:
    """هشدار در صورت ارسال پیام نامعتبر به‌جای عکس."""
    await message.answer("⚠️ لطفاً حتماً یک **عکس یا فایل تصویری معتبر** برای تصویر پروفایل ارسال کنید:")


# ============================================================
#  مدیریت و ویرایش پروفایل توییتر (عکس، نام نمایشی، یوزرنیم)
# ============================================================


@router.callback_query(F.data == "tw:edit_profile")
async def cb_twitter_edit_profile(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """نمایش زیرمنوی ویرایش پروفایل توییتر."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter_profile"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await safe_edit(call, "حساب توییتر برای کشور شما یافت نشد.", reply_markup=_twitter_home_kb())
        return

    await state.clear()
    disp_name = profile.display_name or db_user.president_name or country.name_fa
    text = (
        "✏️ <b>مدیریت و ویرایش پروفایل توییتر (X)</b>\n\n"
        f"🏛 <b>کشور:</b> {country.flag} {country.name_fa}\n"
        f"👤 <b>نام نمایشی:</b> {html.escape(disp_name)}\n"
        f"🏷 <b>نام کاربری (Handle):</b> <code>@{profile.username}</code> 🔹\n\n"
        f"ℹ️ <i>کول‌داون تغییر هر فیلد {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعت است.</i>\n\n"
        "کدام بخش را می‌خواهید ویرایش کنید؟"
    )
    await safe_edit(call, text, reply_markup=_twitter_edit_profile_kb())


# --- ۱. ویرایش نام نمایشی ---


@router.callback_query(F.data == "tw_edit:name")
async def cb_edit_name_prompt(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """ورود به مرحله تغییر نام نمایشی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter_profile"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        return

    # بررسی کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_name", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await safe_edit(
            call,
            "⏳ <b>محدودیت زمانی تغییر نام نمایشی</b>\n\n"
            f"تغییر نام نمایشی هر {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعت یک‌بار مجاز است.\n"
            f"لطفاً حدود <b>{fa_number(mins)} دقیقه</b> دیگر دوباره تلاش کنید.",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    await state.set_state(TwitterEditProfileForm.editing_name)
    current_name = profile.display_name or db_user.president_name or country.name_fa
    text = (
        "✏️ <b>تغییر نام نمایشی توییتر</b>\n\n"
        f"نام نمایشی فعلی: <b>{html.escape(current_name)}</b>\n\n"
        f"لطفاً نام نمایشی جدید کشور خود را ارسال کنید (بین {fa_number(TWITTER_NAME_MIN_CHARS)} تا {fa_number(TWITTER_NAME_MAX_CHARS)} کاراکتر):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="tw_edit:cancel", style=STYLE_MAIN),
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(TwitterEditProfileForm.editing_name, F.text)
async def msg_edit_name_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """دریافت و ذخیره نام نمایشی جدید."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await state.clear()
        return

    is_valid, res = validate_display_name(message.text)
    if not is_valid:
        await message.answer(f"❌ <b>خطا در نام نمایشی:</b>\n{res}\n\nلطفاً نام دیگری ارسال کنید:")
        return

    # بررسی مجدد کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_name", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await state.clear()
        await message.answer(
            f"⏳ محدودیت زمانی تغییر نام نمایشی فعال است ({fa_number(mins)} دقیقه مانده).",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    old_name = profile.display_name or db_user.president_name or country.name_fa
    new_name = res

    await twitter_repo.update_profile_display_name(session, country.id, new_name)
    await cd_repo.touch(session, country.id, "tw_edit_name")
    await session.flush()

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"✏️ <b>تغییر نام نمایشی توییتر</b>\n\n"
        f"🏛 کشور: {country.flag} {country.name_fa}\n"
        f"👤 شناسه: @{profile.username}\n"
        f"🔹 نام قدیم: {html.escape(old_name)}\n"
        f"🔸 نام جدید: {html.escape(new_name)}",
    )

    await state.clear()
    await message.answer(
        "✅ <b>نام نمایشی توییتر با موفقیت به‌روزرسانی شد!</b>\n\n"
        f"نام نمایشی جدید: <b>{html.escape(new_name)}</b>\n\n"
        "این نام از این پس در بالای تمام کارت‌های توییت رسمی و پنل‌ها نمایش داده خواهد شد.",
        reply_markup=_twitter_edit_profile_kb(),
    )


# --- ۲. ویرایش نام کاربری (Handle) ---


@router.callback_query(F.data == "tw_edit:username")
async def cb_edit_username_prompt(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """ورود به مرحله تغییر نام کاربری."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter_profile"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        return

    # بررسی کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_username", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await safe_edit(
            call,
            "⏳ <b>محدودیت زمانی تغییر نام کاربری</b>\n\n"
            f"تغییر نام کاربری هر {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعت یک‌بار مجاز است.\n"
            f"لطفاً حدود <b>{fa_number(mins)} دقیقه</b> دیگر دوباره تلاش کنید.",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    await state.set_state(TwitterEditProfileForm.editing_username)
    text = (
        "🏷 <b>تغییر نام کاربری (Handle) توییتر</b>\n\n"
        f"نام کاربری فعلی: <code>@{profile.username}</code>\n\n"
        "قواعد نام کاربری:\n"
        "• باید بین ۳ تا ۱۵ کاراکتر باشد.\n"
        "• باید با یک حرف انگلیسی (A-Z) شروع شود.\n"
        "• فقط شامل حروف انگلیسی، اعداد و خط زیر (_) باشد.\n"
        "• نباید تکراری یا از شناسه‌های رزروشده سیستمی باشد.\n\n"
        "لطفاً نام کاربری جدید را بدون @ ارسال کنید:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="tw_edit:cancel", style=STYLE_MAIN),
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(TwitterEditProfileForm.editing_username, F.text)
async def msg_edit_username_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """دریافت و ذخیره نام کاربری جدید."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await state.clear()
        return

    is_valid, res = validate_username(message.text)
    if not is_valid:
        await message.answer(f"❌ <b>خطا در نام کاربری:</b>\n{res}\n\nلطفاً مجدداً ارسال کنید:")
        return

    new_username = res
    if new_username == profile.username.lower():
        await message.answer("⚠️ نام کاربری جدید با نام کاربری فعلی شما یکسان است! لطفاً نام دیگری انتخاب کنید:")
        return

    # بررسی یکتایی در دیتابیس (عدم تصاحب توسط کشور دیگر)
    existing = await twitter_repo.get_profile_by_username(session, new_username)
    if existing is not None and existing.country_id != country.id:
        await message.answer(
            f"❌ نام کاربری <code>@{new_username}</code> قبلاً توسط کشور دیگری ثبت شده است!\n"
            "لطفاً نام کاربری دیگری انتخاب کنید:"
        )
        return

    # بررسی مجدد کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_username", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await state.clear()
        await message.answer(
            f"⏳ محدودیت زمانی تغییر نام کاربری فعال است ({fa_number(mins)} دقیقه مانده).",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    old_username = profile.username
    await twitter_repo.update_profile_username(session, country.id, new_username)
    await cd_repo.touch(session, country.id, "tw_edit_username")
    await session.flush()

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"🏷 <b>تغییر نام کاربری توییتر</b>\n\n"
        f"🏛 کشور: {country.flag} {country.name_fa}\n"
        f"🔹 شناسه قدیم: @{old_username}\n"
        f"🔸 شناسه جدید: @{new_username}",
    )

    await state.clear()
    await message.answer(
        "✅ <b>نام کاربری توییتر با موفقیت تغییر کرد!</b>\n\n"
        f"نام کاربری جدید شما: <code>@{new_username}</code> 🔹\n\n"
        "توییت‌های جدید شما با این شناسه منتشر خواهند شد.",
        reply_markup=_twitter_edit_profile_kb(),
    )


# --- ۳. ویرایش عکس پروفایل (کراپ ۱:۱ و پیش‌نمایش) ---


@router.callback_query(F.data == "tw_edit:avatar")
async def cb_edit_avatar_prompt(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """ورود به مرحله تغییر عکس پروفایل."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter_profile"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        return

    # بررسی کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_avatar", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await safe_edit(
            call,
            "⏳ <b>محدودیت زمانی تغییر عکس پروفایل</b>\n\n"
            f"تغییر عکس پروفایل هر {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعت یک‌بار مجاز است.\n"
            f"لطفاً حدود <b>{fa_number(mins)} دقیقه</b> دیگر دوباره تلاش کنید.",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    await state.set_state(TwitterEditProfileForm.uploading_avatar)
    text = (
        "📸 <b>تغییر تصویر پروفایل توییتر</b>\n\n"
        "لطفاً تصویر جدید مد نظر خود را به صورت عکس (Photo) یا فایل تصویری (حداکثر ۵ مگابایت) ارسال کنید.\n\n"
        "✂️ <i>ربات به صورت هوشمند وسط تصویر را با نسبت ۱:۱ (مربع ۵۱۲×۵۱۲) برش داده و پیش‌نمایش آن را به شما نشان خواهد داد.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="tw_edit:cancel", style=STYLE_MAIN),
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(TwitterEditProfileForm.uploading_avatar, F.photo | F.document)
async def msg_edit_avatar_upload(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """دریافت تصویر، پردازش و کراپ ۱:۱، و ارسال پیش‌نمایش جهت تأیید."""
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await state.clear()
        return

    file_id: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        doc = message.document
        mime = doc.mime_type or ""
        if not (mime.startswith("image/") or (doc.file_name and doc.file_name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))):
            await message.answer("⚠️ فایل ارسالی باید یک تصویر معتبر (JPEG, PNG, WEBP) باشد.")
            return
        if doc.file_size and doc.file_size > TWITTER_AVATAR_MAX_BYTES:
            await message.answer("⚠️ حجم فایل تصویر نباید بیشتر از ۵ مگابایت باشد.")
            return
        file_id = doc.file_id

    if not file_id:
        await message.answer("⚠️ لطفاً یک تصویر معتبر ارسال کنید:")
        return

    # دانلود و پردازش با Pillow در ThreadPool
    try:
        file_info = await bot.get_file(file_id)
        if not file_info.file_path:
            await message.answer("❌ امکان دانلود تصویر از تلگرام فراهم نشد. لطفاً دوباره ارسال کنید.")
            return
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        raw_bytes = buf.getvalue()
        if len(raw_bytes) > TWITTER_AVATAR_MAX_BYTES:
            await message.answer("⚠️ حجم تصویر بیش از حد مجاز (۵ مگابایت) است.")
            return

        cropped_bytes = await asyncio.to_thread(process_avatar_upload, raw_bytes, TWITTER_AVATAR_SIZE)
    except ValueError as exc:
        await message.answer(f"❌ خطا در پردازش تصویر: {exc}\nلطفاً تصویر معتبر دیگری ارسال کنید:")
        return
    except Exception as exc:
        logger.exception("Error processing avatar upload: %s", exc)
        await message.answer("❌ خطای غیرمنتظره در پردازش تصویر. لطفاً تصویر دیگری ارسال فرمایید:")
        return

    # ارسال پیش‌نمایش به کاربر
    preview_file = BufferedInputFile(cropped_bytes, filename="avatar_preview.png")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید و ذخیره آواتار", callback_data="tw_edit:avatar_confirm", style=STYLE_OK)],
        [InlineKeyboardButton(text="🔄 ارسال عکس دیگر", callback_data="tw_edit:avatar_retry", style=STYLE_MAIN)],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="tw_edit:cancel", style=STYLE_NO)],
    ])

    sent_msg = await message.answer_photo(
        photo=preview_file,
        caption=(
            "🖼 <b>پیش‌نمایش تصویر جدید پروفایل:</b>\n\n"
            "تصویر شما با موفقیت از مرکز کادر با نسبت ۱:۱ (مربع ۵۱۲×۵۱۲) برش داده شد.\n\n"
            "آیا مایلید این تصویر به عنوان عکس پروفایل توییتر رسمی شما ثبت شود؟"
        ),
        reply_markup=kb,
    )

    # شناسه فایل تصویر جدید در تلگرام را برای ذخیره نهایی در state نگه می‌داریم
    new_avatar_file_id = sent_msg.photo[-1].file_id if sent_msg.photo else file_id
    await state.update_data(pending_avatar_file_id=new_avatar_file_id)
    await state.set_state(TwitterEditProfileForm.confirming_avatar)


@router.message(TwitterEditProfileForm.uploading_avatar)
async def msg_edit_avatar_invalid(message: Message) -> None:
    """هشدار در صورت ارسال پیام نامعتبر."""
    await message.answer("⚠️ لطفاً حتماً یک **عکس یا فایل تصویری معتبر** ارسال فرمایید:")


@router.callback_query(TwitterEditProfileForm.confirming_avatar, F.data == "tw_edit:avatar_confirm")
async def cb_edit_avatar_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """تأیید نهایی و ذخیره آواتار جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter_profile"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await state.clear()
        return

    # بررسی مجدد کول‌داون
    secs = await cd_repo.remaining_seconds(
        session, country.id, "tw_edit_avatar", TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS
    )
    mins = int((secs + 59) // 60)
    if mins > 0:
        await state.clear()
        await safe_edit(
            call,
            f"⏳ محدودیت زمانی تغییر عکس پروفایل فعال است ({fa_number(mins)} دقیقه مانده).",
            reply_markup=_twitter_edit_profile_kb(),
        )
        return

    data = await state.get_data()
    pending_file_id = data.get("pending_avatar_file_id")
    if not pending_file_id:
        await state.clear()
        await safe_edit(call, "اطلاعات تصویر یافت نشد. لطفاً مجدداً تلاش فرمایید.", reply_markup=_twitter_edit_profile_kb())
        return

    await twitter_repo.update_profile_avatar(session, country.id, pending_file_id)
    await cd_repo.touch(session, country.id, "tw_edit_avatar")
    await session.flush()

    # لاگ به گروه مدیران
    await send_log(
        bot,
        f"🖼 <b>تغییر عکس پروفایل توییتر</b>\n\n"
        f"🏛 کشور: {country.flag} {country.name_fa}\n"
        f"👤 شناسه: @{profile.username}\n"
        "عکس پروفایل با موفقیت تغییر کرد و برش ۱:۱ اعمال شد.",
    )

    await state.clear()
    await safe_edit(
        call,
        "✅ <b>عکس پروفایل توییتر با موفقیت به‌روزرسانی شد!</b>\n\n"
        "تصویر جدید شما در توییت‌های بعدی و کارت‌های گرافیکی به صورت دایره‌ای بدون کشیدگی درج خواهد شد.",
        reply_markup=_twitter_edit_profile_kb(),
    )


@router.callback_query(TwitterEditProfileForm.confirming_avatar, F.data == "tw_edit:avatar_retry")
async def cb_edit_avatar_retry(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست ارسال مجدد عکس دیگر."""
    await call.answer()
    await state.set_state(TwitterEditProfileForm.uploading_avatar)
    text = "🔄 لطفاً تصویر جدید دیگری را ارسال فرمایید (به صورت عکس یا فایل تصویری):"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="tw_edit:cancel", style=STYLE_MAIN),
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.callback_query(F.data == "tw_edit:cancel")
async def cb_edit_cancel(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """انصراف از ویرایش و بازگشت به زیرمنوی مدیریت پروفایل."""
    await call.answer("انصراف داده شد.")
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await safe_edit(call, "حساب توییتر یافت نشد.", reply_markup=_twitter_home_kb())
        return

    disp_name = profile.display_name or db_user.president_name or country.name_fa
    text = (
        "✏️ <b>مدیریت و ویرایش پروفایل توییتر (X)</b>\n\n"
        f"🏛 <b>کشور:</b> {country.flag} {country.name_fa}\n"
        f"👤 <b>نام نمایشی:</b> {html.escape(disp_name)}\n"
        f"🏷 <b>نام کاربری (Handle):</b> <code>@{profile.username}</code> 🔹\n\n"
        f"ℹ️ <i>کول‌داون تغییر هر فیلد {fa_number(TWITTER_PROFILE_CHANGE_COOLDOWN_HOURS)} ساعت است.</i>\n\n"
        "کدام بخش را می‌خواهید ویرایش کنید؟"
    )
    await safe_edit(call, text, reply_markup=_twitter_edit_profile_kb())


# ============================================================
#  فرم نگارش و انتشار توییت جدید
# ============================================================


@router.callback_query(F.data == "tweet:new")
async def cb_tweet_new(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """ورود به فرم نوشتن توییت جدید."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not await assert_feature(call, session, country, "twitter"):
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await call.answer("ابتدا باید حساب توییتر خود را بسازید.", show_alert=True)
        return

    # بررسی محدودیت زمانی (هر ۱ ساعت ۱ توییت)
    secs = await cd_repo.remaining_seconds(session, country.id, "tweet", TWEET_COOLDOWN_HOURS)
    mins = int((secs + 59) // 60)
    if mins > 0:
        await safe_edit(
            call,
            "⏳ <b>محدودیت زمانی ارسال توییت</b>\n\n"
            "ارسال توییت رسمی هر ۱ ساعت یک‌بار امکان‌پذیر است.\n"
            f"لطفاً حدود <b>{fa_number(mins)} دقیقه</b> دیگر دوباره تلاش کنید.",
            reply_markup=_twitter_home_kb(),
        )
        return

    await state.set_state(TweetForm.entering_content)
    text = (
        "✍️ <b>نگارش توییت رسمی جدید</b>\n\n"
        "متن توییت خود را بنویسید (حداکثر ۲۸۰ کاراکتر):\n\n"
        "<i>این پیام در قالب گرافیکی تاریک (Dark Mode) همراه با تیک آبی و نشان رسمی کشور شما در کانال توییتر جهانی منتشر خواهد شد.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت به توییتر", callback_data="dip:twitter", style=STYLE_MAIN),
    ]])
    await safe_edit(call, text, reply_markup=kb)


@router.message(TweetForm.entering_content, F.text)
async def msg_tweet_content(message: Message, state: FSMContext) -> None:
    """بررسی طول متن و نمایش پیش‌نمایش قبل از ارسال."""
    content = message.text.strip()
    if len(content) < 3:
        await message.answer("❌ متن توییت بیش از حد کوتاه است. لطفاً حداقل ۳ کاراکتر بنویسید:")
        return

    if len(content) > 280:
        await message.answer(
            f"❌ طول متن ({fa_number(len(content))} کاراکتر) بیش از حد مجاز ۲۸۰ کاراکتر است!\n"
            "لطفاً متن خلاصه‌تری وارد کنید:"
        )
        return

    await state.update_data(content=content)
    await state.set_state(TweetForm.confirming)

    preview_text = (
        "📝 <b>پیش‌نمایش توییت شما:</b>\n\n"
        f"<blockquote>{content}</blockquote>\n\n"
        f"📏 تعداد کاراکتر: {fa_number(len(content))} / ۲۸۰\n\n"
        "آیا از انتشار این توییت در کانال رسمی توییتر جهانی اطمینان دارید؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 انتشار رسمی در توییتر", callback_data="tweet:confirm", style=STYLE_OK)],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="tweet:cancel", style=STYLE_NO)],
    ])
    await message.answer(preview_text, reply_markup=kb)


@router.callback_query(TweetForm.confirming, F.data == "tweet:confirm")
async def cb_tweet_confirm(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """رندر گرافیکی و ارسال نهایی توییت به کانال رسمی توییتر."""
    country = await get_player_country(session, db_user)
    if country is None:
        await call.answer("کشوری برای شما ثبت نشده است.", show_alert=True)
        return

    data = await state.get_data()
    content = data.get("content")
    if not content:
        await state.clear()
        await call.answer("خطا در بازیابی اطلاعات توییت.", show_alert=True)
        return

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        await state.clear()
        await call.answer("پروفایل توییتر یافت نشد.", show_alert=True)
        return

    # بررسی مجدد کول‌داون قبل از انتشار رسمی
    secs = await cd_repo.remaining_seconds(session, country.id, "tweet", TWEET_COOLDOWN_HOURS)
    mins = int((secs + 59) // 60)
    if mins > 0:
        await state.clear()
        await safe_edit(
            call,
            "⏳ <b>محدودیت زمانی ارسال توییت</b>\n\n"
            "ارسال توییت رسمی هر ۱ ساعت یک‌بار امکان‌پذیر است.\n"
            f"لطفاً حدود <b>{fa_number(mins)} دقیقه</b> دیگر دوباره تلاش کنید.",
            reply_markup=_twitter_home_kb(),
        )
        return

    await call.answer("در حال طراحی و مخابره تصویر توییت... ⏳")
    await safe_edit(call, "⏳ در حال رندر و ارسال توییت به کانال جهانی توییتر...")

    # ۱. دانلود بایت‌های آواتار کاربر از تلگرام
    avatar_bytes: bytes | None = None
    try:
        file_info = await bot.get_file(profile.avatar_file_id)
        if file_info.file_path:
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=buf)
            avatar_bytes = buf.getvalue()
    except Exception as exc:
        logger.warning("Could not download avatar for country %s: %s", country.id, exc)

    # ۲. ثبت توییت در دیتابیس
    tweet = await twitter_repo.add_tweet(session, country_id=country.id, content=content)

    # ۳. تولید تصویر گرافیکی توییت با Pillow در رم
    now = datetime.now(timezone.utc)
    pres_name = profile.display_name or db_user.president_name or country.name_fa
    try:
        tweet_bytes = render_tweet_image(
            country_name=country.name_fa,
            president_name=pres_name,
            country_flag=country.flag,
            username=profile.username,
            content=content,
            avatar_bytes=avatar_bytes,
            created_at=now,
        )
    except Exception as exc:
        logger.exception("Failed to render tweet image: %s", exc)
        await safe_edit(
            call,
            "❌ خطا در پردازش تصویر توییت. لطفاً مجدداً تلاش فرمایید.",
            reply_markup=_twitter_home_kb(),
        )
        return

    # ۴. ارسال به کانال رسمی توییتر با دکمه تعاملی لایک و کپشن رسمی
    channel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ 0", callback_data=f"tweet:like:{tweet.id}")
    ]])
    photo_file = BufferedInputFile(tweet_bytes, filename=f"tweet_{tweet.id}.png")
    tweet_caption = (
        "🌍 توییت حساب رسمی\n"
        f"📤 فرستنده: {pres_name} ({country.name_fa})\n\n"
        "🖼 متن کامل توییت در تصویر سند رسمی بالا درج شده است."
    )

    channel_msg_id: int | None = None
    try:
        sent_channel_msg = await bot.send_photo(
            chat_id=TWEET_CHANNEL_ID,
            photo=photo_file,
            caption=tweet_caption,
            reply_markup=channel_kb,
        )
        channel_msg_id = sent_channel_msg.message_id
        tweet.channel_message_id = channel_msg_id
        await session.flush()
    except Exception as exc:
        logger.error("Failed to post tweet to channel %s: %s", TWEET_CHANNEL_ID, exc)

    # ثبت زمان ارسال برای اعمال محدودیت زمانی ۱ ساعته
    await cd_repo.touch(session, country.id, "tweet")
    await session.flush()

    # ۵. ارسال نسخه به گروه لاگ مدیران
    log_photo = BufferedInputFile(tweet_bytes, filename=f"tweet_{tweet.id}.png")
    await send_log_photo(
        bot,
        photo=log_photo,
        caption=(
            f"🐦 <b>توییت جدید در کانال توییتر منتشر شد</b>\n\n"
            f"🏛 کشور: {country.flag} {country.name_fa}\n"
            f"👤 شناسه: @{profile.username}\n"
            f"🔢 شماره توییت: #{tweet.id}"
        ),
    )

    await state.clear()
    success_text = (
        "✅ <b>توییت شما با موفقیت در کانال رسمی منتشر شد!</b>\n\n"
        f"🏛 کشور: {country.flag} {country.name_fa}\n"
        f"👤 نام کاربری: @{profile.username}\n"
        f"🆔 شناسه پیام: #{tweet.id}\n\n"
        "بازیکنان می‌توانند با کلیک روی دکمه قلب در کانال به این توییت واکنش نشان دهند."
    )
    await safe_edit(call, success_text, reply_markup=_twitter_home_kb())


@router.callback_query(TweetForm.confirming, F.data == "tweet:cancel")
async def cb_tweet_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """انصراف از ارسال توییت و بازگشت."""
    await call.answer("انصراف داده شد.")
    await state.clear()
    await safe_edit(call, "ارسال توییت لغو شد.", reply_markup=_twitter_home_kb())


# ============================================================
#  سیستم لایک تعاملی در کانال رسمی (-1004317808331)
# ============================================================


@router.callback_query(F.data.startswith("tweet:like:"))
async def cb_tweet_like(call: CallbackQuery, session: AsyncSession) -> None:
    """مدیریت لایک و پس گرفتن لایک روی پیام‌های کانال توییتر."""
    try:
        tweet_id = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer("درخواست نامعتبر است.")
        return

    user_id = call.from_user.id
    is_liked, new_count = await twitter_repo.toggle_like(session, tweet_id, user_id)

    # نمایش اعلان به کاربر
    if is_liked:
        await call.answer("توییت لایک شد ❤️")
    else:
        await call.answer("لایک پس گرفته شد 💔")

    # آپدیت عدد روی دکمه شیشه‌ای پیام داخل کانال
    new_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"❤️ {fa_number(new_count)}", callback_data=f"tweet:like:{tweet_id}")
    ]])
    try:
        await call.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:  # noqa: BLE001
        pass


# ============================================================
#  توییت‌های من
# ============================================================


@router.callback_query(F.data == "tweet:mine")
async def cb_tweet_mine(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    """نمایش فهرست آخرین توییت‌های منتشرشده توسط کشور."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    tweets = await twitter_repo.list_tweets_by_country(session, country.id, limit=5)
    if not tweets:
        await safe_edit(
            call,
            "📜 تاکنون هیچ توییتی توسط کشور شما منتشر نشده است.",
            reply_markup=_twitter_home_kb(),
        )
        return

    lines = [
        f"📜 <b>آخرین توییت‌های منتشرشده توسط {country.flag} {country.name_fa}:</b>",
        "",
    ]
    for idx, tw in enumerate(tweets, start=1):
        clean_content = tw.content if len(tw.content) <= 80 else tw.content[:77] + "..."
        time_display = tw.created_at.strftime("%Y/%m/%d %H:%M") if tw.created_at else ""
        lines.append(
            f"<b>{fa_number(idx)}.</b> «{clean_content}»\n"
            f"   ❤️ لایک‌ها: {fa_number(tw.likes_count)}   |   🕒 {time_display}"
        )
        lines.append("")

    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ ارسال توییت جدید", callback_data="tweet:new", style=STYLE_OK)
    builder.button(text="🔙 بازگشت به توییتر", callback_data="dip:twitter", style=STYLE_MAIN)
    builder.adjust(1, 1)

    await safe_edit(call, "\n".join(lines), reply_markup=builder.as_markup())
