"""هندلرهای وضعیت عضویت ربات در گروه‌ها (v2.12.0).

مدیریت افزوده شدن/حذف ربات از گروه‌ها و سوپرگروه‌ها همراه با ارسال لاگ و خروج خودکار
از گروه‌های غیرمجاز.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated

from ..config import get_settings
from ..constants import AUTO_LEAVE_UNAUTHORIZED_GROUPS
from ..services.news_service import send_log
from ..utils.chat_access import is_internal_chat

logger = logging.getLogger(__name__)

router = Router(name="group_guard")


@router.my_chat_member()
async def on_my_chat_member_updated(event: ChatMemberUpdated, bot: Bot) -> None:
    """
    بررسی تغییر وضعیت عضویت خودِ ربات در گروه‌ها و سوپرگروه‌ها:
    - ثبت لاگ رسمی در گروه لاگ اصلی.
    - در صورت افزوده‌شدن توسط افراد غیرمجاز به گروه‌های متفرقه، ربات بلافاصله لفت می‌دهد.
    """
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    from_user = event.from_user

    # آیا ربات به تازگی وارد یا ارتقا یافته؟
    is_joining = (
        old_status not in ("member", "administrator")
        and new_status in ("member", "administrator")
    )
    # آیا ربات از گروه حذف یا اخراج شده؟
    is_leaving = (
        old_status in ("member", "administrator")
        and new_status not in ("member", "administrator")
    )

    if not (is_joining or is_leaving):
        return

    settings = get_settings()
    user_id = from_user.id if from_user else 0
    username = f"@{from_user.username}" if from_user and from_user.username else "ندارد"
    full_name = html.escape(from_user.full_name) if from_user else "نامشخص"

    if settings.is_owner(user_id):
        user_role = "👑 مالک بازی"
        is_authorized = True
    elif settings.is_admin(user_id):
        user_role = "👮‍♂️ مدیر بازی"
        is_authorized = True
    else:
        user_role = "👤 کاربر عادی (غریبه)"
        is_authorized = False

    is_internal = is_internal_chat(chat.id)

    if is_joining:
        should_leave = (not is_authorized) and (not is_internal) and AUTO_LEAVE_UNAUTHORIZED_GROUPS

        log_lines = [
            "🚨 <b>ربات به گروه غیرمجاز اضافه شد!</b>" if should_leave else "🤖 <b>افزودن ربات به گروه جدید</b>",
            "",
            f"👥 <b>نام گروه:</b> {html.escape(chat.title or 'بدون نام')}",
            f"🆔 <b>شناسه گروه:</b> <code>{chat.id}</code>",
            f"👤 <b>افزوده‌شده توسط:</b> {full_name} ({username})",
            f"🔢 <b>شناسه کاربر:</b> <code>{user_id}</code>",
            f"🎖 <b>سطح دسترسی:</b> {user_role}",
        ]
        if should_leave:
            log_lines.append("\n⚠️ <i>ربات به دلیل عدم دسترسی فرد اقدام‌کننده، به طور خودکار از گروه خارج گردید.</i>")

        # ارسال لاگ (خطا نباید مانع leave شود)
        try:
            await send_log(bot, "\n".join(log_lines))
        except Exception as exc:
            logger.warning("Could not send my_chat_member log: %s", exc)

        if should_leave:
            try:
                await bot.leave_chat(chat.id)
                logger.info("Auto-left unauthorized group %s (added by %s)", chat.id, user_id)
            except Exception as exc:
                logger.warning("Failed to leave unauthorized group %s: %s", chat.id, exc)

    elif is_leaving:
        log_text = (
            "🤖 <b>ربات از گروه خارج/حذف شد</b>\n\n"
            f"👥 <b>نام گروه:</b> {html.escape(chat.title or 'بدون نام')}\n"
            f"🆔 <b>شناسه گروه:</b> <code>{chat.id}</code>\n"
            f"👤 <b>اقدام‌کننده:</b> {full_name} ({username}) [<code>{user_id}</code>]\n"
            f"🎖 <b>سطح دسترسی:</b> {user_role}"
        )
        try:
            await send_log(bot, log_text)
        except Exception as exc:
            logger.warning("Could not send my_chat_member removal log: %s", exc)
