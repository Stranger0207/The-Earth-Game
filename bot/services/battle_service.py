"""
سرویس اعلام جنگ رسمی (v1.10.6).

⚠️ تغییر مهم: منطق نبرد و ثبت حمله از این سرویس حذف شد و به
`operation_service` و موتور `services/combat` منتقل گردید.
این فایل الان فقط مسئول «اعلام جنگ رسمی» است.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Country
from ..database.repositories import battles as war_repo
from ..loader import bot
from ..services.news_service import send_log


class BattleServiceError(Exception):
    """خطای قابل‌نمایش به بازیکن."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def declare_war(session: AsyncSession, declarer: Country, target: Country) -> None:
    """
    اعلام جنگ رسمی از سوی یک کشور علیه کشور دیگر.

    اعلام جنگ پیش‌نیاز حملات علنی (زمینی، هوایی، دریایی) است.
    عملیات مخفیانه (خرابکاری، ترور، رهگیری) به اعلام جنگ نیاز ندارند.
    """
    if declarer.id == target.id:
        raise BattleServiceError("نمی‌توانید علیه خودتان جنگ اعلام کنید.")

    # بررسی اینکه قبلاً اعلام نشده باشد
    existing = await war_repo.has_active_war_declaration(session, declarer.id, target.id)
    if existing:
        raise BattleServiceError(
            f"کشور شما قبلاً علیه {target.flag} {target.name_fa} اعلام جنگ کرده است."
        )

    # ثبت رکورد جنگ (از مخزن استفاده می‌کنیم تا نام ستون‌ها یک‌جا مدیریت شود)
    await war_repo.declare_war(session, declarer.id, target.id)

    # انتشار بیانیه در کانال دیپلماسی و گروه لاگ
    from ..enums import NewsCategory
    from ..services.news_service import publish_news

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🚨 <b>اعلام رسمی وضعیت جنگ</b>\n\n"
        f"دولت {declarer.flag} <b>{declarer.name_fa}</b> رسماً علیه "
        f"{target.flag} <b>{target.name_fa}</b> اعلام جنگ کرد.\n"
        "فرماندهی نیروهای مسلح وضعیت آماده‌باش کامل اعلام نموده است.",
    )
    await send_log(
        bot,
        f"🚨 <b>اعلام جنگ رسمی</b>\n\n"
        f"🔴 مهاجم: {declarer.flag} {declarer.name_fa}\n"
        f"🔵 هدف: {target.flag} {target.name_fa}\n\n"
        "حملات علنی این کشور اکنون مجاز است.",
    )
