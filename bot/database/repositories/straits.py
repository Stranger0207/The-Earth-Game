"""
ریپازیتوری مدیریت تنگه‌ها، عوارض، مسدودسازی و اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

import logging
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...enums import StraitBlockScope
from ...services.geo_service import STRAITS_DEFINITIONS, list_all_strait_defs
from ..models.strait import BlockedCargo, StraitBlockRule, StraitConfig

logger = logging.getLogger(__name__)


async def ensure_default_straits(session: AsyncSession) -> None:
    """
    اطمینان از وجود رکوردهای اولیه ۱۴ تنگه استراتژیک در دیتابیس.
    اگر رکوردی هنوز ساخته نشده باشد، رکورد پیش‌فرض آن با عوارض ۰ و وضعیت باز ساخته می‌شود.
    """
    existing = await session.execute(select(StraitConfig.strait_id))
    existing_ids = set(existing.scalars().all())

    for s_def in list_all_strait_defs():
        sid = s_def["id"]
        if sid not in existing_ids:
            cfg = StraitConfig(
                strait_id=sid,
                name_fa=s_def["name_fa"],
                name_en=s_def["name_en"],
                controller_country_name=s_def["controller"],
                is_blocked=False,
                block_scope=StraitBlockScope.NONE.value,
                default_toll=0.0,
            )
            session.add(cfg)
    await session.flush()


async def get_strait_config(session: AsyncSession, strait_id: str) -> StraitConfig | None:
    """دریافت تنظیمات یک تنگه بر اساس شناسه."""
    await ensure_default_straits(session)
    return await session.get(StraitConfig, strait_id)


async def list_all_strait_configs(session: AsyncSession) -> list[StraitConfig]:
    """فهرست تمام تنگه‌های بازی."""
    await ensure_default_straits(session)
    res = await session.execute(select(StraitConfig).order_by(StraitConfig.name_fa))
    return list(res.scalars().all())


async def list_straits_by_controller(
    session: AsyncSession, country_name_en: str
) -> list[StraitConfig]:
    """فهرست تنگه‌های تحت کنترل یک کشور خاص."""
    await ensure_default_straits(session)
    res = await session.execute(
        select(StraitConfig)
        .where(StraitConfig.controller_country_name == country_name_en)
        .order_by(StraitConfig.name_fa)
    )
    return list(res.scalars().all())


async def update_strait_config(
    session: AsyncSession,
    strait_id: str,
    *,
    is_blocked: bool | None = None,
    block_scope: str | None = None,
    default_toll: float | None = None,
) -> StraitConfig | None:
    """به‌روزرسانی تنظیمات و عوارض یک تنگه."""
    cfg = await get_strait_config(session, strait_id)
    if not cfg:
        return None
    if is_blocked is not None:
        cfg.is_blocked = is_blocked
    if block_scope is not None:
        cfg.block_scope = block_scope
    if default_toll is not None:
        cfg.default_toll = max(0.0, default_toll)
    await session.flush()
    return cfg


async def list_block_rules(session: AsyncSession, strait_id: str) -> list[StraitBlockRule]:
    """فهرست قوانین اختصاصی مسدودسازی/عوارض یک تنگه."""
    res = await session.execute(
        select(StraitBlockRule)
        .where(StraitBlockRule.strait_id == strait_id)
        .order_by(StraitBlockRule.target_country_id)
    )
    return list(res.scalars().all())


async def get_block_rule(
    session: AsyncSession, strait_id: str, target_country_id: int
) -> StraitBlockRule | None:
    """قانون اختصاصی مسدودسازی/عوارض برای یک کشور خاص روی یک تنگه."""
    res = await session.execute(
        select(StraitBlockRule).where(
            StraitBlockRule.strait_id == strait_id,
            StraitBlockRule.target_country_id == target_country_id,
        )
    )
    return res.scalar_one_or_none()


async def set_block_rule(
    session: AsyncSession,
    strait_id: str,
    target_country_id: int,
    *,
    is_blocked: bool,
    custom_toll: float | None = None,
) -> StraitBlockRule:
    """تنظیم یا به‌روزرسانی مسدودسازی اختصاصی یا عوارض ویژه برای یک کشور."""
    rule = await get_block_rule(session, strait_id, target_country_id)
    if rule is None:
        rule = StraitBlockRule(
            strait_id=strait_id,
            target_country_id=target_country_id,
            is_blocked=is_blocked,
            custom_toll=custom_toll,
        )
        session.add(rule)
    else:
        rule.is_blocked = is_blocked
        if custom_toll is not None:
            rule.custom_toll = custom_toll
    await session.flush()
    return rule


async def remove_block_rule(
    session: AsyncSession, strait_id: str, target_country_id: int
) -> None:
    """حذف قانون اختصاصی یک کشور برای یک تنگه."""
    await session.execute(
        delete(StraitBlockRule).where(
            StraitBlockRule.strait_id == strait_id,
            StraitBlockRule.target_country_id == target_country_id,
        )
    )
    await session.flush()


async def is_strait_blocked_for_country(
    session: AsyncSession, strait_id: str, country_id: int
) -> bool:
    """
    بررسی اینکه آیا تنگه به روی این کشور مسدود است یا خیر.
    """
    cfg = await get_strait_config(session, strait_id)
    if not cfg:
        return False

    # اگر تنگه کلاً باز باشد
    if not cfg.is_blocked or cfg.block_scope == StraitBlockScope.NONE.value:
        return False

    # مسدود سراسری برای همه
    if cfg.block_scope == StraitBlockScope.ALL.value:
        return True

    # مسدود برای کشورهای خاص
    if cfg.block_scope == StraitBlockScope.CUSTOM.value:
        rule = await get_block_rule(session, strait_id, country_id)
        if rule and rule.is_blocked:
            return True

    return False


async def get_effective_strait_toll(
    session: AsyncSession, strait_id: str, payer_country_id: int
) -> float:
    """
    محاسبه مبلغ عوارض عبور از یک تنگه برای کشور پرداخت‌کننده.
    اگر عوارض اختصاصی تعریف شده باشد، از آن استفاده می‌شود؛ در غیر این صورت default_toll.
    """
    cfg = await get_strait_config(session, strait_id)
    if not cfg:
        return 0.0

    rule = await get_block_rule(session, strait_id, payer_country_id)
    if rule is not None and rule.custom_toll is not None:
        return float(rule.custom_toll)

    return float(cfg.default_toll)


async def calculate_route_tolls(
    session: AsyncSession, strait_ids: list[str], payer_country_id: int
) -> dict[str, float]:
    """
    محاسبه عوارض تک‌تک تنگه‌های مسیر برای کشور پرداخت‌کننده.
    خروجی: دیکشنری {strait_id: toll_amount}
    """
    tolls: dict[str, float] = {}
    for sid in strait_ids:
        toll = await get_effective_strait_toll(session, sid, payer_country_id)
        tolls[sid] = toll
    return tolls


async def get_first_blocked_strait(
    session: AsyncSession, strait_ids: list[str], seller_id: int, buyer_id: int
) -> str | None:
    """
    بررسی اینکه آیا تنگه‌ای در مسیر به روی فروشنده یا خریدار مسدود است یا خیر.
    اولین تنگه مسدود مسیر برگردانده می‌شود. در صورت باز بودن همه، None.
    """
    for sid in strait_ids:
        blocked_for_seller = await is_strait_blocked_for_country(session, sid, seller_id)
        blocked_for_buyer = await is_strait_blocked_for_country(session, sid, buyer_id)
        if blocked_for_seller or blocked_for_buyer:
            return sid
    return None


# --- مدیریت اموال بلوکه‌شده ---

async def add_blocked_cargo(
    session: AsyncSession,
    *,
    holding_country_id: int,
    source_country_id: int,
    dest_country_id: int,
    resource: str,
    amount: float,
    strait_id: str,
    original_sale_id: int | None = None,
) -> BlockedCargo:
    """افزودن محموله مصادره‌شده به اموال بلوکه‌شده کشور."""
    cargo = BlockedCargo(
        holding_country_id=holding_country_id,
        source_country_id=source_country_id,
        dest_country_id=dest_country_id,
        resource=resource,
        amount=amount,
        strait_id=strait_id,
        original_sale_id=original_sale_id,
    )
    session.add(cargo)
    await session.flush()
    return cargo


async def list_blocked_cargos_by_holding(
    session: AsyncSession, holding_country_id: int
) -> list[BlockedCargo]:
    """فهرست تمام محموله‌های بلوکه‌شده در اختیار یک کشور."""
    res = await session.execute(
        select(BlockedCargo)
        .where(BlockedCargo.holding_country_id == holding_country_id)
        .order_by(BlockedCargo.captured_at.desc())
    )
    return list(res.scalars().all())


async def get_blocked_cargo(session: AsyncSession, cargo_id: int) -> BlockedCargo | None:
    """دریافت رکورد یک محموله بلوکه‌شده بر اساس شناسه."""
    return await session.get(BlockedCargo, cargo_id)


async def delete_blocked_cargo(session: AsyncSession, cargo_id: int) -> None:
    """حذف رکورد یک محموله بلوکه‌شده (پس از تخریب یا ترخیص)."""
    await session.execute(delete(BlockedCargo).where(BlockedCargo.id == cargo_id))
    await session.flush()
