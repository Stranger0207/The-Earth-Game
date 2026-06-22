"""هندلر مدیریت: تأیید/رد کشورگیری و ابزارهای مالک."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.models import User
from ..database.repositories import claims as claims_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import users as users_repo
from ..enums import ClaimStatus
from ..keyboards.menu import main_menu_kb
from ..loader import bot

router = Router(name="admin")
settings = get_settings()


def _is_owner(user_id: int) -> bool:
    return settings.is_owner(user_id)


@router.callback_query(F.data.startswith("claim_approve:"))
async def cb_approve(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تأیید درخواست کشورگیری توسط مالک."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند تأیید کند.", show_alert=True)
        return

    claim_id = int(call.data.split(":")[1])
    claim = await claims_repo.get_claim(session, claim_id)
    if claim is None or claim.status != ClaimStatus.PENDING:
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    country = await countries_repo.get_country(session, claim.country_id)
    if country is None or country.is_claimed:
        await call.answer("کشور دیگر در دسترس نیست.", show_alert=True)
        await claims_repo.set_status(session, claim_id, ClaimStatus.REJECTED, call.from_user.id)
        return

    # واگذاری مالکیت و به‌روزرسانی کاربر
    await countries_repo.assign_owner(session, claim.country_id, claim.user_id)
    if claim.president_name:
        await users_repo.set_president_name(session, claim.user_id, claim.president_name)
    await claims_repo.set_status(session, claim_id, ClaimStatus.APPROVED, call.from_user.id)

    await call.answer("تأیید شد ✅")
    await call.message.edit_text(
        call.message.html_text + "\n\n✅ <b>تأیید شد</b>"
    )

    # اطلاع به بازیکن
    try:
        await bot.send_message(
            claim.user_id,
            f"🎉 تبریک! درخواست شما تأیید شد.\n"
            f"شما اکنون رهبر {country.flag} <b>{country.name_fa}</b> هستید.\n\n"
            "پنل مدیریت کشور:",
            reply_markup=main_menu_kb(),
        )
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("claim_reject:"))
async def cb_reject(call: CallbackQuery, session: AsyncSession) -> None:
    """رد درخواست کشورگیری توسط مالک."""
    if not _is_owner(call.from_user.id):
        await call.answer("فقط مالک بازی می‌تواند رد کند.", show_alert=True)
        return

    claim_id = int(call.data.split(":")[1])
    claim = await claims_repo.get_claim(session, claim_id)
    if claim is None or claim.status != ClaimStatus.PENDING:
        await call.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    await claims_repo.set_status(session, claim_id, ClaimStatus.REJECTED, call.from_user.id)
    await call.answer("رد شد ❌")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>رد شد</b>")

    try:
        await bot.send_message(
            claim.user_id,
            "متأسفانه درخواست کشورگیری شما رد شد. می‌توانید کشور دیگری را امتحان کنید. /claim",
        )
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("pending"))
async def cmd_pending(
    message: Message, session: AsyncSession
) -> None:
    """فهرست درخواست‌های در انتظار (فقط برای مالک/مدیر)."""
    if not settings.is_admin(message.from_user.id):
        return
    pending = await claims_repo.list_pending(session)
    if not pending:
        await message.answer("هیچ درخواست در انتظاری وجود ندارد.")
        return
    lines = ["📋 <b>درخواست‌های در انتظار تأیید:</b>", ""]
    for c in pending:
        country = await countries_repo.get_country(session, c.country_id)
        cname = country.name_fa if country else "?"
        lines.append(
            f"• #{c.id} — کاربر <code>{c.user_id}</code> برای {cname}"
        )
    await message.answer("\n".join(lines))
