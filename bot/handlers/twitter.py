"""
هندلرهای سیستم توییتر جهانی (X) در منوی دیپلماسی و کانال رسمی (v3.0).

قابلیت‌ها:
- آنبوردینگ و ثبت‌نام اولیه کشورها (انتخاب یوزرنیم یکتا و آپلود آواتار).
- نگارش و انتشار توییت در کانال رسمی با تصویر گرافیکی Dark Mode.
- دکمه شیشه‌ای لایک با شمارنده تعاملی زیر پست‌های کانال رسمی (Toggle).
- مشاهده توییت‌های اخیر کشور.
- قفل آپشن از طریق /god با گارد assert_feature.
"""

from __future__ import annotations

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

from ..constants import TWEET_CHANNEL_ID
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import twitter as twitter_repo
from ..loader import bot
from ..services.news_service import send_log, send_log_photo
from ..services.tweet_image_service import render_tweet_image
from ..states.forms import TweetForm, TwitterOnboardingForm
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)

router = Router(name="twitter")

# الگوی اعتبارسنجی نام کاربری توییتر: ۳ تا ۳۰ کاراکتر انگلیسی، اعداد و آندرلاین
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,30}$")


def _twitter_home_kb() -> InlineKeyboardMarkup:
    """کیبورد منوی اصلی توییتر."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ ارسال توییت جدید", callback_data="tweet:new", style=STYLE_OK)
    builder.button(text="📜 توییت‌های من", callback_data="tweet:mine", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به دیپلماسی", callback_data="menu:diplomacy", style=STYLE_MAIN)
    builder.adjust(1, 1, 1)
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

    profile = await twitter_repo.get_profile_by_country(session, country.id)
    if profile is None:
        # کشور هنوز حسابی ثبت نکرده است -> آغاز آنبوردینگ
        await state.set_state(TwitterOnboardingForm.entering_username)
        text = (
            "🐦 <b>راه‌اندازی حساب رسمی توییتر (X)</b>\n\n"
            f"کشور: {country.flag} <b>{country.name_fa}</b>\n\n"
            "برای انتشار مواضع رسمی کشور خود در کانال جهانی توییتر، ابتدا باید یک <b>نام کاربری (Handle)</b> "
            "و یک <b>عکس پروفایل</b> تنظیم کنید.\n\n"
            "⚠️ <i>توجه: نام کاربری و عکس پروفایل تا پایان فصل ثابت خواهند ماند.</i>\n\n"
            "لطفاً <b>نام کاربری انگلیسی</b> مد نظر خود را بدون @ ارسال کنید (مثلاً: Iran_MFA یا WhiteHouse):"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data="menu:diplomacy", style=STYLE_MAIN),
        ]])
        await safe_edit(call, text, reply_markup=kb)
        return

    # حساب از قبل وجود دارد -> نمایش صفحه خانه توییتر
    t_count = await twitter_repo.count_tweets_by_country(session, country.id)
    text = (
        "🐦 <b>شبکه اجتماعی توییتر (X) — ستاد دیپلماسی عمومی</b>\n\n"
        f"🏛 <b>کشور:</b> {country.flag} {country.name_fa}\n"
        f"👤 <b>نام کاربری رسمی:</b> <code>@{profile.username}</code> 🔹\n"
        f"📊 <b>تعداد توییت‌های فصل:</b> {fa_number(t_count)}\n\n"
        "<i>از این بخش می‌توانید پیام‌ها، بیانیه‌ها و مواضع دیپلماتیک خود را در قالب اسکرین‌شات گرافیکی رسمی در کانال توییتر جهانی منتشر کنید.</i>"
    )
    await safe_edit(call, text, reply_markup=twitter_home_kb())


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

    raw = message.text.strip().lstrip("@")
    if not USERNAME_REGEX.match(raw):
        await message.answer(
            "❌ <b>نام کاربری نامعتبر است!</b>\n\n"
            "نام کاربری باید تنها شامل حروف انگلیسی (A-Z)، اعداد (0-9) و خط زیر (_) بوده و طول آن بین ۳ تا ۳۰ کاراکتر باشد.\n"
            "لطفاً مجدداً ارسال کنید:"
        )
        return

    # بررسی عدم تکراری بودن یوزرنیم در پایگاه داده
    existing = await twitter_repo.get_profile_by_username(session, raw)
    if existing is not None:
        await message.answer(
            f"❌ نام کاربری <code>@{raw}</code> قبلاً توسط کشور دیگری ثبت شده است!\n"
            "لطفاً نام کاربری متفاوتی وارد کنید:"
        )
        return

    await state.update_data(username=raw)
    await state.set_state(TwitterOnboardingForm.uploading_avatar)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف", callback_data="menu:diplomacy", style=STYLE_MAIN),
    ]])
    await message.answer(
        f"✅ نام کاربری <code>@{raw}</code> با موفقیت تایید شد.\n\n"
        "🖼 حالا لطفاً <b>تصویر پروفایل</b> مد نظر برای این حساب را ارسال نمایید (به صورت Photo):",
        reply_markup=kb,
    )


@router.message(TwitterOnboardingForm.uploading_avatar, F.photo)
async def msg_onboarding_avatar(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """دریافت بالاترین کیفیت تصویر و ایجاد پروفایل توییتر."""
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

    photo = message.photo[-1]
    avatar_file_id = photo.file_id

    # ذخیره در دیتابیس
    profile = await twitter_repo.create_profile(
        session, country_id=country.id, username=username, avatar_file_id=avatar_file_id
    )
    await state.clear()

    await message.answer(
        "🎉 <b>حساب رسمی توییتر کشور شما با موفقیت ایجاد شد!</b>\n\n"
        f"🏛 کشور: {country.flag} <b>{country.name_fa}</b>\n"
        f"👤 نام کاربری: <code>@{profile.username}</code> 🔹 (دارای تیک آبی تایید)\n\n"
        "از هم‌اکنون می‌توانید توییت‌های رسمی خود را به کانال جهانی مخابره کنید.",
        reply_markup=_twitter_home_kb(),
    )


@router.message(TwitterOnboardingForm.uploading_avatar)
async def msg_onboarding_avatar_invalid(message: Message) -> None:
    """هشدار در صورت ارسال پیام متنی یا فایل به‌جای عکس."""
    await message.answer("⚠️ لطفاً حتماً یک **عکس معتبر (Photo)** برای تصویر پروفایل ارسال کنید:")


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
    try:
        tweet_bytes = render_tweet_image(
            country_name=country.name_fa,
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

    # ۴. ارسال به کانال رسمی توییتر با دکمه تعاملی لایک
    channel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ 0", callback_data=f"tweet:like:{tweet.id}")
    ]])
    photo_file = BufferedInputFile(tweet_bytes, filename=f"tweet_{tweet.id}.png")

    channel_msg_id: int | None = None
    try:
        sent_channel_msg = await bot.send_photo(
            chat_id=TWEET_CHANNEL_ID,
            photo=photo_file,
            reply_markup=channel_kb,
        )
        channel_msg_id = sent_channel_msg.message_id
        tweet.channel_message_id = channel_msg_id
        await session.flush()
    except Exception as exc:
        logger.error("Failed to post tweet to channel %s: %s", TWEET_CHANNEL_ID, exc)

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
