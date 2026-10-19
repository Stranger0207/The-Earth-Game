"""ثبت همه‌ی روترهای ربات روی دیسپچر."""

import logging

from aiogram import Dispatcher, Router
from aiogram.types import CallbackQuery, ErrorEvent

from . import (
    admin,
    admin_roles,
    advisor,
    alliance,
    auction,
    bank,
    broadcast,
    claim,
    command_center,
    deployment,
    diplomacy,
    economic_projects,
    economy,
    god_locks,
    godmode,
    governance,
    interception,
    investment,
    joint,
    kick,
    mail,
    maintenance,
    menu,
    military,
    military_base,
    military_roles,
    nuclear,
    satellite,
    security_roles,
    start,
    straits,
    suspension,
    switch,
    team,
    twitter,
    united_nations,
)

logger = logging.getLogger(__name__)

fallback_router = Router(name="fallback")


@fallback_router.callback_query()
async def cb_unhandled_fallback(call: CallbackQuery) -> None:
    """پاسخ‌دهی به هر دکمه شیشه‌ای ناشناخته یا فاقد هندلر برای جلوگیری از لودینگ دائم."""
    logger.warning("UNHANDLED CALLBACK: data=%s user=%s", call.data, call.from_user.id)
    await call.answer("⚠️ این دکمه در حال حاضر پاسخگو نیست یا منقضی شده است.", show_alert=True)


async def global_error_handler(event: ErrorEvent) -> None:
    """هندلر خطایاب سراسری برای جلوگیری از لودینگ دائم دکمه‌ها و ثبت دقیق خطاها."""
    logger.exception("Global unhandled exception in update: %s", event.exception)
    if event.update and event.update.callback_query:
        try:
            await event.update.callback_query.answer(
                "⚠️ خطایی در اجرای این دکمه رخ داد. لطفاً مجدداً تلاش کنید.",
                show_alert=True,
            )
        except Exception:
            pass


def register_all_routers(dp: Dispatcher) -> None:
    """
    ترتیب ثبت مهم است: روترهای اختصاصی‌تر (start/claim/admin) زودتر،
    سپس منو و بخش‌های بازی.
    """
    dp.errors.register(global_error_handler)

    dp.include_router(start.router)
    dp.include_router(claim.router)
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)
    dp.include_router(admin_roles.router)
    dp.include_router(kick.router)
    dp.include_router(switch.router)
    dp.include_router(team.router)
    dp.include_router(suspension.router)
    dp.include_router(maintenance.router)
    dp.include_router(godmode.router)
    dp.include_router(god_locks.router)
    dp.include_router(menu.router)
    dp.include_router(economy.router)
    dp.include_router(economic_projects.router)
    dp.include_router(auction.router)
    dp.include_router(bank.router)
    dp.include_router(investment.router)
    dp.include_router(joint.router)
    dp.include_router(governance.router)
    dp.include_router(diplomacy.router)
    dp.include_router(united_nations.router)
    dp.include_router(mail.router)
    dp.include_router(alliance.router)
    dp.include_router(twitter.router)
    dp.include_router(command_center.router)
    dp.include_router(interception.router)
    dp.include_router(military.router)
    dp.include_router(military_roles.router)
    dp.include_router(security_roles.router)
    dp.include_router(military_base.router)
    dp.include_router(satellite.router)
    dp.include_router(nuclear.router)
    dp.include_router(straits.router)
    dp.include_router(deployment.router)
    dp.include_router(advisor.router)

    # روتر فال‌بک در انتهای صف برای گرفتن کال‌بک‌های ثبت‌نشده یا منقضی
    dp.include_router(fallback_router)


