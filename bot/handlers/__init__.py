"""ثبت همه‌ی روترهای ربات روی دیسپچر."""

from aiogram import Dispatcher

from . import (
    admin,
    advisor,
    alliance,
    bank,
    battle,
    claim,
    command_center,
    covert_ops,
    deployment,
    diplomacy,
    economy,
    god_operations,
    interception,
    godmode,
    governance,
    investment,
    joint,
    mail,
    maintenance,
    menu,
    military,
    military_base,
    nuclear,
    operations,
    patrol_drill,
    satellite,
    start,
)


def register_all_routers(dp: Dispatcher) -> None:
    """
    ترتیب ثبت مهم است: روترهای اختصاصی‌تر (start/claim/admin) زودتر،
    سپس منو و بخش‌های بازی.
    """
    dp.include_router(start.router)
    dp.include_router(claim.router)
    dp.include_router(admin.router)
    dp.include_router(maintenance.router)
    dp.include_router(godmode.router)
    dp.include_router(god_operations.router)
    dp.include_router(menu.router)
    dp.include_router(economy.router)
    dp.include_router(bank.router)
    dp.include_router(investment.router)
    dp.include_router(joint.router)
    dp.include_router(governance.router)
    dp.include_router(diplomacy.router)
    dp.include_router(mail.router)
    dp.include_router(alliance.router)
    dp.include_router(battle.router)
    dp.include_router(command_center.router)
    dp.include_router(operations.router)
    dp.include_router(covert_ops.router)
    dp.include_router(interception.router)
    dp.include_router(patrol_drill.router)
    dp.include_router(military.router)
    dp.include_router(military_base.router)
    dp.include_router(satellite.router)
    dp.include_router(nuclear.router)
    dp.include_router(deployment.router)
    dp.include_router(advisor.router)
