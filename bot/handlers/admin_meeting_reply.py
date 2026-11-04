"""هندلر ریپلای ادمین/مالک در گروه لاگ به گفتگوهای نشست (v2.12.0).

هنگامی که ادمین یا مالک در گروه لاگ اصلی روی یکی از پیام‌های رله‌شده‌ی نشست ریپلای
می‌زند، پیام او با قالب رسمی و مشخص به تمامی حاضران همان نشست ارسال می‌گردد.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import Message, ReactionTypeEmoji
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import ADMIN_REPLY_EXTENDS_MEETING_IDLE
from ..database.models import Country, GroupMeeting
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..enums import DiplomacyStatus
from ..utils.chat_access import is_internal_chat

logger = logging.getLogger(__name__)

router = Router(name="admin_meeting_reply")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.message(F.reply_to_message)
async def on_admin_meeting_log_reply(
    message: Message, session: AsyncSession, bot: Bot
) -> None:
    """
    دریافت ریپلای ادمین/مالک در گروه لاگ و ارسال آن به تمام حاضران نشست فعال.
    """
    settings = get_settings()

    # فقط در گروه لاگ اصلی یا چت‌های داخلی معتبر فعال است
    if not (
        (settings.log_group_id and message.chat.id == settings.log_group_id)
        or is_internal_chat(message.chat.id)
    ):
        return

    # فرستنده باید ادمین یا مالک باشد
    if not message.from_user or not settings.is_admin(message.from_user.id):
        return

    # پیام ریپلای‌شده باید از طرف ربات باشد
    replied = message.reply_to_message
    if not replied or not replied.from_user:
        return

    # بررسی اینکه آیا پیام ریپلای‌شده از طرف ربات است
    bot_info = await bot.get_me()
    if replied.from_user.id != bot_info.id and not replied.from_user.is_bot:
        return

    # نادیده گرفتن دستورها (شروع با /)
    text_content = message.text or message.caption or ""
    if text_content.strip().startswith("/"):
        return

    # بررسی انواع محتوای مجاز: متن یا عکس
    photo_id: str | None = None
    if message.photo:
        photo_id = message.photo[-1].file_id
        admin_body = message.caption or ""
    elif message.text:
        admin_body = message.text
    else:
        # سایر رسانه‌ها مانند استیکر، وویس، فایل و...
        try:
            await message.reply(
                "⚠️ ارسال این نوع پیام در رله نشست پشتیبانی نمی‌شود. لطفاً پیام متنی یا عکس ارسال کنید."
            )
        except Exception:
            pass
        return

    if not admin_body.strip() and not photo_id:
        return

    # یافتن نگاشت پیام لاگ به نشست در دیتابیس
    relay = await dip_repo.get_meeting_log_relay(
        session,
        log_chat_id=message.chat.id,
        log_message_id=replied.message_id,
    )

    # فال‌بک هوشمند برای پیام‌های قبل از ایجاد جدول یا نگاشت‌های گمشده
    if relay is None:
        raw_replied = (
            replied.text
            if isinstance(replied.text, str)
            else (replied.caption if isinstance(replied.caption, str) else "")
        )
        replied_text = raw_replied.strip() if isinstance(raw_replied, str) else ""

        # ۱) اگر پیام مربوط به تماس تلفنی است: 📞 [...]
        if "📞" in replied_text:
            await message.reply("⏹ این تماس تلفنی به پایان رسیده است یا امکان ارسال پیام به تماس وجود ندارد.")
            return

        # ۲) اگر پیام مربوط به صحن علنی مجمع عمومی سازمان ملل است:
        if "مجمع عمومی" in replied_text:
            await message.reply("🏛 این پیام مربوط به صحن مجمع عمومی سازمان ملل است و نشست دیپلماتیک خصوصی نیست.")
            return

        # ۳) بررسی دیدار دوجانبه: 🤝 [ایران → ترکیه]: یا 🏛 [نشست حاشیه UN] [ایران → ترکیه]: یا سفر دیپلماتیک
        bi_match = re.search(r"\[([^\s\]→]+(?:\s+[^\s\]→]+)*)\s*→\s*([^\s\]]+(?:\s+[^\s\]]+)*)\]", replied_text)
        if not bi_match:
            bi_match = re.search(
                r"(?:سفر دیپلماتیک|دیدار دوجانبه|نشست دوجانبه)[:\s]+([^\s→:]+(?:\s+[^\s→:]+)*)\s*(?:→|↔)\s*([^\s→\(\n]+(?:\s+[^\s→\(\n]+)*)",
                replied_text,
            )
        if bi_match:
            name_a = bi_match.group(1).strip()
            name_b = bi_match.group(2).strip()
            stmt_a = select(Country).where(Country.name_fa == name_a)
            stmt_b = select(Country).where(Country.name_fa == name_b)
            c_a = (await session.execute(stmt_a)).scalar_one_or_none()
            c_b = (await session.execute(stmt_b)).scalar_one_or_none()

            if c_a and c_b:
                m_found = await dip_repo.get_active_meeting_for_country(session, c_a.id)
                if (
                    m_found
                    and m_found.status == DiplomacyStatus.ACTIVE
                    and {m_found.host_country, m_found.traveler_country} == {c_a.id, c_b.id}
                ):
                    relay = await dip_repo.record_meeting_log_relay(
                        session=session,
                        log_chat_id=message.chat.id,
                        log_message_id=replied.message_id,
                        meeting_kind="bilateral",
                        meeting_id=m_found.id,
                        sender_country_id=c_a.id,
                        sender_user_id=None,
                        preview_text=replied_text[:200],
                    )
                    await session.commit()
                else:
                    await message.reply("⏹ این نشست پایان یافته است.")
                    return
            else:
                await message.reply("⏹ این نشست پایان یافته است.")
                return

        # ۴) بررسی نشست چندجانبه: 👥 [نشست برلین] فرانسه: یا 🏛 [...] یا «عنوان»
        grp_match = re.search(r"\[([^\]]+)\]\s*([^:]+):", replied_text)
        if not grp_match:
            grp_match = re.search(r"(?:نشست چندجانبه|نشست حاشیه UN)[\s#\d]*[«\"]([^»\"]+)[»\"]", replied_text)

        if not relay and grp_match and ("👥" in replied_text or "نشست" in replied_text or "🏛" in replied_text):
            title = grp_match.group(1).strip()
            stmt_g = select(GroupMeeting).where(
                GroupMeeting.title == title, GroupMeeting.status == DiplomacyStatus.ACTIVE
            )
            g_found = (await session.execute(stmt_g)).scalar_one_or_none()
            if g_found:
                relay = await dip_repo.record_meeting_log_relay(
                    session=session,
                    log_chat_id=message.chat.id,
                    log_message_id=replied.message_id,
                    meeting_kind="group",
                    meeting_id=g_found.id,
                    sender_country_id=g_found.host_country,
                    sender_user_id=None,
                    preview_text=replied_text[:200],
                )
                await session.commit()
            else:
                await message.reply("⏹ این نشست پایان یافته است.")
                return

    if relay is None:
        # پیام ریپلای‌شده ربطی به گفتگوهای نشست ندارد (سکوت جهت جلوگیری از شلوغی لاگ)
        return

    now = datetime.now(timezone.utc)
    attendee_country_ids: list[int] = []

    # بررسی وضعیت نشست دوجانبه
    if relay.meeting_kind == "bilateral":
        meeting = await dip_repo.get_meeting(session, relay.meeting_id)
        if meeting is None:
            await message.reply("⏹ این نشست پایان یافته است.")
            return

        arrived = not (_aware(meeting.travel_eta) and _aware(meeting.travel_eta) > now)
        ended = (
            meeting.status != DiplomacyStatus.ACTIVE
            or (_aware(meeting.meeting_ends_at) and _aware(meeting.meeting_ends_at) <= now)
        )

        if ended:
            await message.reply("⏹ این نشست پایان یافته است.")
            return

        if not arrived:
            await message.reply("✈️ این نشست هنوز آغاز نشده و هیئت در حال پرواز است.")
            return

        attendee_country_ids = [meeting.host_country, meeting.traveler_country]

        if ADMIN_REPLY_EXTENDS_MEETING_IDLE:
            meeting.last_msg_at = now
            await session.commit()

    # بررسی وضعیت نشست چندجانبه
    elif relay.meeting_kind == "group":
        group = await dip_repo.get_group_meeting(session, relay.meeting_id)
        if group is None:
            await message.reply("⏹ این نشست پایان یافته است.")
            return

        ended = (
            group.status != DiplomacyStatus.ACTIVE
            or (_aware(group.meeting_ends_at) and _aware(group.meeting_ends_at) <= now)
        )

        if ended:
            await message.reply("⏹ این نشست پایان یافته است.")
            return

        attendee_country_ids = await dip_repo.group_member_country_ids(session, group)

        if ADMIN_REPLY_EXTENDS_MEETING_IDLE:
            group.last_msg_at = now
            await session.commit()

    else:
        return

    # استخراج برچسب کشور فرستنده اصلی و متن خلاصه
    sender_label = "فرستنده"
    if relay.sender_country_id:
        c = await countries_repo.get_country(session, relay.sender_country_id)
        if c:
            sender_label = f"{c.flag} {c.name_fa}"

    clean_snippet = relay.preview_text
    if ": " in clean_snippet[:60]:
        clean_snippet = clean_snippet.split(": ", 1)[1]
    snippet_short = clean_snippet[:80] + ("…" if len(clean_snippet) > 80 else "")
    if not snippet_short.strip():
        snippet_short = "📷 تصویر"

    # ساخت قالب پیام
    reply_quote = f"↩️ در پاسخ به «{html.escape(sender_label)}: {html.escape(snippet_short)}»"
    admin_name = html.escape(message.from_user.full_name)
    admin_text_escaped = html.escape(admin_body)

    if admin_text_escaped:
        admin_line = f"👮‍♂️ ادمین {admin_name}: {admin_text_escaped}"
    else:
        admin_line = f"👮‍♂️ ادمین {admin_name}"

    formatted_msg = f"{reply_quote}\n{admin_line}"

    # اعتبارسنجی محدودیت طول تلگرام
    if photo_id and len(formatted_msg) > 1024:
        await message.reply(
            f"⚠️ طول پیام و کپشن شما بیش از سقف مجاز تلگرام است ({len(formatted_msg)} > ۱۰۲۴ کاراکتر)."
        )
        return
    elif not photo_id and len(formatted_msg) > 4096:
        await message.reply(
            f"⚠️ طول پیام شما بیش از سقف مجاز تلگرام است ({len(formatted_msg)} > ۴۰۹۶ کاراکتر)."
        )
        return

    # ارسال به تمام حاضران نشست
    success_count = 0
    failed_countries: list[str] = []
    total_targets = 0

    for cid in attendee_country_ids:
        country = await countries_repo.get_country(session, cid)
        if not country or not country.owner_user_id:
            continue
        total_targets += 1
        try:
            if photo_id:
                await bot.send_photo(
                    country.owner_user_id,
                    photo=photo_id,
                    caption=formatted_msg,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    country.owner_user_id,
                    formatted_msg,
                    parse_mode="HTML",
                )
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not send admin meeting relay to country %s (%s): %s",
                country.name_fa,
                country.owner_user_id,
                exc,
            )
            failed_countries.append(country.name_fa)

        await asyncio.sleep(0.05)

    # بازخورد به ادمین: واکنش ایموجی در صورت موفقیت کامل، یا ریپلای در صورت شکست جزئی
    if not failed_countries and success_count > 0:
        try:
            if hasattr(message, "react"):
                await message.react([ReactionTypeEmoji(emoji="✅")])
            else:
                await bot.set_message_reaction(
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    reaction=[ReactionTypeEmoji(emoji="✅")],
                )
        except Exception:
            pass
    elif failed_countries:
        failed_names = "، ".join(failed_countries)
        await message.reply(
            f"⚠️ پیام شما برای {success_count} از {total_targets} کشور ارسال شد.\n"
            f"ارسال به کشورهای زیر با خطا مواجه گردید: {failed_names}"
        )
