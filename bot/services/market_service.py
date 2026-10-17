"""سرویس پویای بازار جهانی، تنظیم خودکار نرخ ذخایر و مدیریت رویدادهای اقتصادی (آپدیت شماره ۴)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    DEFAULT_BASE_PRICES,
    MARKET_MAX_PRICE_FACTOR,
    MARKET_MIN_PRICE_FACTOR,
    MARKET_REASON_TEMPLATES,
    MINE_YIELD_PER_24H,
    OIL_PLATFORM_OUTPUT_PER_24H,
    GAS_PLATFORM_OUTPUT_PER_24H,
    GOLD_MINE_YIELD_KG_PER_24H,
    STEEL_FACTORY_OUTPUT_PER_24H,
)
from ..database.models.market_price import MarketPrice
from ..database.repositories import market as market_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import MarketTrend, ResourceType

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resource_key(resource: str | ResourceType) -> str:
    if isinstance(resource, ResourceType):
        return resource.value
    return str(resource).lower()


async def init_market_prices(session: AsyncSession) -> list[MarketPrice]:
    """مقداردهی اولیه رکوردهای نرخ ذخایر در صورت خالی بودن دیتابیس."""
    now = _utcnow()
    results = []
    for rtype, base_price in DEFAULT_BASE_PRICES.items():
        res_key = rtype.value
        mp = await market_repo.get_market_price(session, res_key)
        if mp is None:
            mp = await market_repo.save_market_price(
                session=session,
                resource=res_key,
                base_price=base_price,
                current_price=base_price,
                previous_price=base_price,
                change_pct=0.0,
                trend=MarketTrend.STABLE.value,
                last_reason_code="INITIAL",
                last_reason_text="تعیین نرخ مصوب پایه اولیه",
                updated_at=now,
            )
        results.append(mp)
    return results


async def get_all_prices(session: AsyncSession) -> list[MarketPrice]:
    """دریافت تمام قیمت‌های لحظه‌ای بازار جهانی (همراه با تضمین مقداردهی اولیه)."""
    prices = await market_repo.get_all_market_prices(session)
    if len(prices) < len(DEFAULT_BASE_PRICES):
        prices = await init_market_prices(session)
    return sorted(prices, key=lambda x: x.resource)


async def get_current_price(session: AsyncSession, resource: str | ResourceType) -> float:
    """دریافت قیمت لحظه‌ای هر واحد از یک ذخیره."""
    res_key = _resource_key(resource)
    mp = await market_repo.get_market_price(session, res_key)
    if mp is None:
        await init_market_prices(session)
        mp = await market_repo.get_market_price(session, res_key)
    if mp is None:
        try:
            rtype = ResourceType(res_key)
            return DEFAULT_BASE_PRICES.get(rtype, 100.0)
        except Exception:
            return 100.0
    return mp.current_price


async def calculate_cargo_value(
    session: AsyncSession, resource: str | ResourceType, amount: float
) -> float:
    """محاسبه ارزش کل یک محموله بر اساس قیمت لحظه‌ای بازار جهانی."""
    unit_price = await get_current_price(session, resource)
    return float(amount) * float(unit_price)


async def update_price(
    session: AsyncSession,
    resource: str | ResourceType,
    delta_pct: float | None = None,
    absolute_price: float | None = None,
    reason_code: str = "ADMIN_MANUAL",
    custom_reason_text: str | None = None,
) -> MarketPrice:
    """
    به‌روزرسانی قیمت یک ذخیره با رعایت سقف و کف نوسانات (۰.۳ تا ۴.۰ برابر پایه)،
    محاسبه درصد تغییر، روند (UP/DOWN/STABLE) و ثبت دلیل.
    """
    res_key = _resource_key(resource)
    mp = await market_repo.get_market_price(session, res_key)
    if mp is None:
        await init_market_prices(session)
        mp = await market_repo.get_market_price(session, res_key)

    try:
        rtype = ResourceType(res_key)
        base_p = DEFAULT_BASE_PRICES.get(rtype, mp.base_price if mp else 100.0)
    except Exception:
        base_p = mp.base_price if mp else 100.0

    min_allowed = base_p * MARKET_MIN_PRICE_FACTOR
    max_allowed = base_p * MARKET_MAX_PRICE_FACTOR

    old_current = mp.current_price if mp else base_p

    if absolute_price is not None:
        target_price = float(absolute_price)
    elif delta_pct is not None:
        target_price = old_current * (1.0 + (float(delta_pct) / 100.0))
    else:
        target_price = old_current

    # اعمال کف و سقف قانونی بازار
    new_price = max(min_allowed, min(max_allowed, target_price))

    # محاسبه درصد تغییر نسبت به قیمت قبلی
    if old_current > 0:
        change_pct = ((new_price - old_current) / old_current) * 100.0
    else:
        change_pct = 0.0

    # تعیین روند
    if change_pct > 0.05:
        trend = MarketTrend.UP.value
    elif change_pct < -0.05:
        trend = MarketTrend.DOWN.value
    else:
        trend = MarketTrend.STABLE.value

    # تعیین متن دلیل
    if custom_reason_text and custom_reason_text.strip():
        reason_text = custom_reason_text.strip()
    else:
        reason_text = MARKET_REASON_TEMPLATES.get(
            reason_code, "نوسانات عرضه و تقاضای بازار بین‌المللی"
        )

    updated_mp = await market_repo.save_market_price(
        session=session,
        resource=res_key,
        base_price=base_p,
        current_price=round(new_price, 2),
        previous_price=round(old_current, 2),
        change_pct=round(change_pct, 2),
        trend=trend,
        last_reason_code=reason_code,
        last_reason_text=reason_text,
        updated_at=_utcnow(),
    )
    return updated_mp


# ============================================================
#  واکنش‌های خودکار به رویدادهای درون بازی (Event Hooks)
# ============================================================


def _get_daily_standard_volume(resource: str) -> float:
    """حجم استاندارد تولید ۲۴ ساعته یک واحد تأسیسات برای مقیاس‌بندی اثر معاملات."""
    res = resource.lower()
    if res == "oil":
        return float(OIL_PLATFORM_OUTPUT_PER_24H)
    if res == "gas":
        return float(GAS_PLATFORM_OUTPUT_PER_24H)
    if res == "gold":
        return float(GOLD_MINE_YIELD_KG_PER_24H)
    if res == "steel":
        return float(STEEL_FACTORY_OUTPUT_PER_24H)
    try:
        rtype = ResourceType(res)
        return float(MINE_YIELD_PER_24H.get(rtype, 50_000.0))
    except Exception:
        return 50_000.0


async def on_trade_executed(
    session: AsyncSession, resource: str, amount: float, is_gift: bool
) -> MarketPrice | None:
    """
    واکنش بازار به انجام موفق معامله در WTO:
    معاملات تجاری باعث رشد ۲٪ تا ۸٪ قیمت با دلیل HIGH_DEMAND می‌شوند.
    محموله‌های هدیه قیمت را افزایش نمی‌دهند.
    """
    if is_gift:
        return None

    std_vol = _get_daily_standard_volume(resource)
    vol_ratio = min(max(float(amount) / std_vol, 0.5), 3.0)
    # بین ۲٪ تا ۸٪ افزایش قیمت
    delta_pct = 2.0 + (vol_ratio * 2.0)

    return await update_price(
        session=session,
        resource=resource,
        delta_pct=delta_pct,
        reason_code="HIGH_DEMAND",
    )


async def on_auction_bid_placed(
    session: AsyncSession, resource: str, bid_amount: float, base_amount: float
) -> MarketPrice | None:
    """
    واکنش بازار به رقابت داغ در مزایده:
    پیشنهاد قیمت باعث رشد ۵٪ تا ۱۵٪ با دلیل AUCTION_FEVER می‌شود.
    """
    if base_amount > 0 and bid_amount > base_amount:
        diff_ratio = (bid_amount - base_amount) / base_amount
        delta_pct = min(15.0, 5.0 + (diff_ratio * 10.0))
    else:
        delta_pct = 5.0

    return await update_price(
        session=session,
        resource=resource,
        delta_pct=delta_pct,
        reason_code="AUCTION_FEVER",
    )


async def on_strait_status_changed(
    session: AsyncSession, strait_id: str, is_closed: bool
) -> list[MarketPrice]:
    """
    واکنش شوک انرژی به بستن یا بازگشایی تنگه‌ها:
    بستن تنگه -> جهش نفت و گاز (+۲۰٪ تا +۳۵٪)
    بازگشایی تنگه -> تخلیه حباب انرژی (-۱۰٪ تا -۲۰٪)
    """
    s_id = (strait_id or "").lower()
    is_major = s_id in {"hormuz", "bab_el_mandeb", "suez", "bosphorus", "gibraltar"}
    results = []

    if is_closed:
        oil_jump = 30.0 if is_major else 20.0
        gas_jump = 25.0 if is_major else 15.0
        results.append(
            await update_price(
                session=session,
                resource=ResourceType.OIL.value,
                delta_pct=oil_jump,
                reason_code="STRAIT_CLOSURE",
            )
        )
        results.append(
            await update_price(
                session=session,
                resource=ResourceType.GAS.value,
                delta_pct=gas_jump,
                reason_code="STRAIT_CLOSURE",
            )
        )
    else:
        results.append(
            await update_price(
                session=session,
                resource=ResourceType.OIL.value,
                delta_pct=-15.0,
                reason_code="STRAIT_REOPENED",
            )
        )
        results.append(
            await update_price(
                session=session,
                resource=ResourceType.GAS.value,
                delta_pct=-12.0,
                reason_code="STRAIT_REOPENED",
            )
        )

    return results


async def on_strait_incident(
    session: AsyncSession, strait_id: str, resource: str
) -> MarketPrice | None:
    """واکنش بازار به توقیف یا انهدام کشتی در تنگه یا آبراه‌ها."""
    res_key = _resource_key(resource)
    delta_pct = 20.0 if res_key in {"oil", "gas"} else 12.0
    return await update_price(
        session=session,
        resource=res_key,
        delta_pct=delta_pct,
        reason_code="STRAIT_INTERCEPTION",
    )


async def process_periodic_market_decay(session: AsyncSession) -> list[MarketPrice]:
    """
    تعدیل دوره‌ای بازار به سمت نرخ پایه هنگام عدم نوسان یا رکود معاملات:
    قیمت‌های خیلی بالا به آرامی تعدیل منفی و قیمت‌های خیلی پایین تعدیل مثبت می‌شوند.
    """
    prices = await get_all_prices(session)
    updated = []
    for mp in prices:
        # اگر بیش از ۱۵٪ بالاتر از پایه است، کمی تعدیل نزولی
        if mp.current_price > mp.base_price * 1.15:
            upd = await update_price(
                session=session,
                resource=mp.resource,
                delta_pct=-2.5,
                reason_code="LOW_DEMAND",
            )
            updated.append(upd)
        # اگر بیش از ۱۵٪ پایین‌تر از پایه است، کمی تعدیل مثبت
        elif mp.current_price < mp.base_price * 0.85:
            upd = await update_price(
                session=session,
                resource=mp.resource,
                delta_pct=2.5,
                reason_code="HIGH_DEMAND",
            )
            updated.append(upd)
    return updated


async def process_global_shortage_check(session: AsyncSession) -> list[MarketPrice]:
    """
    بررسی مجموع ذخایر جهان:
    اگر ذخایر جهانی یک منبع شدیداً کاهش یافته باشد، نرخ آن به دلیل کمبود جهانی صعود می‌کند.
    """
    from ..database.models.reserves import Reserve
    from sqlalchemy import func, select

    updated = []
    for rtype in ResourceType:
        stmt = select(func.sum(Reserve.amount)).where(Reserve.resource == rtype.value)
        res = await session.execute(stmt)
        total_res = res.scalar() or 0.0

        # آستانه‌های بحرانی کمبود جهانی
        thresholds = {
            ResourceType.OIL: 50.0,         # زیر ۵۰ میلیون بشکه
            ResourceType.GAS: 200.0,        # زیر ۲۰۰ میلیون متر مکعب
            ResourceType.URANIUM: 10_000.0, # زیر ۱۰ هزار تن
            ResourceType.GOLD: 500.0,       # زیر ۵۰۰ کیلوگرم
        }
        if rtype in thresholds and total_res < thresholds[rtype]:
            upd = await update_price(
                session=session,
                resource=rtype.value,
                delta_pct=10.0,
                reason_code="GLOBAL_SHORTAGE",
            )
            updated.append(upd)

    return updated
