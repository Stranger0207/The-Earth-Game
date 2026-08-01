"""
هندلر اعلام جنگ رسمی (v1.10.6).

⚠️ تغییر مهم نسبت به v2.0: جریان ثبت حمله از این فایل حذف شد و به
`handlers/operations.py` (سیستم جدید عملیات) منتقل گردید. این فایل الان فقط
مسئول «اعلام جنگ رسمی» است که پیش‌نیاز حملات علنی محسوب می‌شود.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..keyboards.common import countries_kb
from ..services import battle_service
from ..utils.screens import safe_edit
from ..utils.ui import header
from .deps import NO_COUNTRY_TEXT, get_player_country

router = Router(name="war_declaration")


@router.callback_query(F.data == "dip:declare_war")
async def cb_declare_war_start(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """انتخاب کشور برای اعلام جنگ رسمی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    text = (
        header("اعلام جنگ رسمی", "🚨") + "\n\n"
        "برای اجرای حملات <b>علنی</b> (زمینی، هوایی، دریایی) ابتدا باید رسماً "
        "علیه کشور هدف اعلام جنگ کنید.\n\n"
        "<i>عملیات‌های مخفیانه (خرابکاری، ترور، رهگیری) به اعلام جنگ نیاز ندارند.</i>\n\n"
        "کشور موردنظر را انتخاب کنید:"
    )
    await safe_edit(
        call,
        text,
        reply_markup=countries_kb(
            others, prefix="war_decl_to", columns=2, back_data="menu:diplomacy"
        ),
    )


@router.callback_query(F.data.startswith("war_decl_to:"))
async def cb_declare_war_confirm(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """ثبت و انتشار بیانیه‌ی اعلان جنگ."""
    await call.answer()
    target_id = int(call.data.split(":")[1])

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    target = await countries_repo.get_country(session, target_id)
    if target is None:
        await safe_edit(call, "کشور هدف یافت نشد.")
        return

    try:
        await battle_service.declare_war(session, declarer=country, target=target)
    except battle_service.BattleServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}")
        return

    await safe_edit(
        call,
        f"🚨 <b>وضعیت جنگ علیه {target.flag} {target.name_fa} رسماً اعلام شد.</b>\n\n"
        "بیانیه در کانال رسمی دیپلماسی منتشر گردید.\n"
        "اکنون می‌توانید از بخش نظامی ← عملیات‌ها، حمله‌ی علنی ثبت کنید.",
    )
