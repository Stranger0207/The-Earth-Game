"""کیبوردهای بخش اقتصاد."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import FACILITY_FA, RESOURCE_EMOJI, RESOURCE_FA, FacilityType, ResourceType
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK

# منابعی که معدن برایشان معنا دارد (پلی‌بوک: فرم احداث معدن).
# (v1.11.1) یک‌جا تعریف شد تا فرم احداث و فهرست معادن از هم جدا نیفتند.
MINEABLE_RESOURCES: list[ResourceType] = [
    ResourceType.COAL,
    ResourceType.ALUMINUM,
    ResourceType.IRON,
    ResourceType.GOLD,
]


def economy_menu_kb(is_usa: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی اقتصاد. برای آمریکا دکمه‌ی تعرفه‌ی بین‌المللی هم اضافه می‌شود (v1.5)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 گزارش اقتصادی", callback_data="econ:report", style=STYLE_MAIN)
    builder.button(text="📦 ذخایر", callback_data="econ:reserves", style=STYLE_MAIN)
    builder.button(text="🏗 احداث تأسیسات", callback_data="econ:build", style=STYLE_OK)
    builder.button(text="💱 فروش ذخیره", callback_data="econ:sell", style=STYLE_OK)
    builder.button(text="🏦 بانک", callback_data="econ:bank", style=STYLE_MAIN)
    builder.button(text="📈 سرمایه‌گذاری", callback_data="econ:invest", style=STYLE_MAIN)
    builder.button(text="🏷 مزایده", callback_data="econ:auction", style=STYLE_MAIN)
    if is_usa:
        builder.button(text="🇺🇸 تعرفه بین‌المللی", callback_data="econ:tariffs", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    if is_usa:
        builder.adjust(2, 2, 2, 1, 1, 1)
    else:
        builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def invest_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی سرمایه‌گذاری (v1.9)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 سرمایه‌گذاری داخلی", callback_data="inv:internal", style=STYLE_OK)
    builder.button(text="🌍 سرمایه‌گذاری خارجی", callback_data="inv:foreign", style=STYLE_MAIN)
    builder.button(text="📋 سرمایه‌گذاری‌های من", callback_data="inv:mine", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def invest_foreign_kb() -> InlineKeyboardMarkup:
    """منوی سرمایه‌گذاری خارجی (v1.9)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 سرمایه‌گذاری‌های من", callback_data="inv:mine", style=STYLE_MAIN)
    builder.button(text="📥 سرمایه‌گذاری روی کشور من", callback_data="inv:on_me", style=STYLE_MAIN)
    builder.button(text="💸 سرمایه‌گذاری روی کشور خارجی", callback_data="inv:new_foreign", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="econ:invest", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def invest_category_kb(back_data: str = "econ:invest") -> InlineKeyboardMarkup:
    """انتخاب دسته‌ی سرمایه‌گذاری به‌همراه درصد سود (v1.9)."""
    from ..constants import INVESTMENT_CATEGORIES

    builder = InlineKeyboardBuilder()
    for key, (fa, pct) in INVESTMENT_CATEGORIES.items():
        # درصد به‌صورت عدد انگلیسی در callback، نمایش فارسی در متن دکمه
        pct_txt = str(int(pct)) if float(pct).is_integer() else str(pct)
        builder.button(text=f"{fa} ({pct_txt}٪)", callback_data=f"inv_cat:{key}", style=STYLE_MAIN)
    builder.adjust(2)
    from aiogram.types import InlineKeyboardButton
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN))
    return builder.as_markup()


def bank_menu_kb() -> InlineKeyboardMarkup:
    """منوی بانک (v1.9)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 موجودی", callback_data="bank:balance", style=STYLE_MAIN)
    builder.button(text="📉 بدهی", callback_data="bank:debt", style=STYLE_MAIN)
    builder.button(text="🔁 انتقال وجه", callback_data="bank:transfer", style=STYLE_OK)
    builder.button(text="🏛 وام", callback_data="bank:loan", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def facility_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع تأسیسات برای احداث."""
    builder = InlineKeyboardBuilder()
    for ftype in FacilityType:
        builder.button(
            text=FACILITY_FA[ftype], callback_data=f"build_type:{ftype.value}", style=STYLE_OK
        )
    builder.button(text="🤝 تأسیسات مشترک", callback_data="joint:start", style=STYLE_OK)
    builder.button(text="🏭 تأسیسات من", callback_data="econ:facilities", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()


def my_facilities_menu_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    """
    منوی «تأسیسات من» (v1.11.1): برای هر نوع تأسیسات یک دکمه با تعداد.

    counts: {مقدار FacilityType: تعداد}
    معدن به صفحه‌ی انتخاب نوع منبع می‌رود؛ بقیه مستقیم به فهرست خودشان.
    """
    builder = InlineKeyboardBuilder()
    for ftype in FacilityType:
        n = counts.get(ftype.value, 0)
        builder.button(
            text=f"{FACILITY_FA[ftype]} ({fa_number(n)})",
            callback_data=f"facl:{ftype.value}:0",
            style=STYLE_MAIN if n else None,
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:build", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def mine_resource_pages_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    """
    (v1.11.1) انتخاب نوع معدن برای دیدن فهرست جداگانه‌ی هر منبع.

    counts: {مقدار ResourceType: تعداد معدن}
    """
    builder = InlineKeyboardBuilder()
    for r in MINEABLE_RESOURCES:
        n = counts.get(r.value, 0)
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]} ({fa_number(n)})",
            callback_data=f"facl:mine:{r.value}:0",
            style=STYLE_MAIN if n else None,
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:facilities", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def facility_list_nav_kb(
    page: int,
    total: int,
    *,
    prefix: str,
    back_data: str,
    items: list | None = None,
    start_idx: int = 1,
) -> InlineKeyboardMarkup:
    """
    ناوبری صفحه‌های فهرست تأسیسات (v1.11.1) + دکمه‌های تخریب (v2.3).

    prefix: پیشوند کال‌بک بدون شماره‌ی صفحه (مثلاً "facl:mine:iron").
    """
    builder = InlineKeyboardBuilder()

    if items:
        for idx, f in enumerate(items, start=start_idx):
            builder.button(
                text=f"🗑 تخریب #{fa_number(idx)}",
                callback_data=f"fac_del:{f.id}",
                style=STYLE_NO,
            )
        builder.adjust(2)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ صفحه قبلی", callback_data=f"{prefix}:{page - 1}", style=STYLE_MAIN
            )
        )
    if page < total - 1:
        nav.append(
            InlineKeyboardButton(
                text="صفحه بعدی ▶️", callback_data=f"{prefix}:{page + 1}", style=STYLE_MAIN
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN)
    )
    return builder.as_markup()


def joint_facility_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع تأسیسات مشترک (همان انواع عادی)."""
    builder = InlineKeyboardBuilder()
    for ftype in FacilityType:
        builder.button(
            text=FACILITY_FA[ftype], callback_data=f"joint_type:{ftype.value}", style=STYLE_OK
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:build", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def joint_mine_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای معدن مشترک."""
    builder = InlineKeyboardBuilder()
    for r in MINEABLE_RESOURCES:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"joint_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="joint:start", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def mine_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای معدن (فقط منابع معدنی قابل‌استخراج)."""
    builder = InlineKeyboardBuilder()
    for r in MINEABLE_RESOURCES:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"mine_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:build", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def sell_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع برای فروش."""
    builder = InlineKeyboardBuilder()
    for r in ResourceType:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"sell_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def loan_panel_kb(has_active_loan: bool = False) -> InlineKeyboardMarkup:
    """کیبورد بخش وام بانکی (v2.2)."""
    builder = InlineKeyboardBuilder()
    if has_active_loan:
        builder.button(text="💳 بازپرداخت وام", callback_data="bank:loan_repay", style=STYLE_OK)
    else:
        builder.button(text="💸 درخواست اخذ وام", callback_data="bank:loan_take", style=STYLE_OK)
    builder.button(text="🔙 بازگشت به بانک", callback_data="econ:bank", style=STYLE_MAIN)
    builder.adjust(1, 1)
    return builder.as_markup()


def auction_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی سیستم مزایده (v2.2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏷 مزایده‌های فعال", callback_data="auc:active:0", style=STYLE_MAIN)
    builder.button(text="➕ ثبت مزایده جدید", callback_data="auc:create", style=STYLE_OK)
    builder.button(text="📋 مزایده‌های من", callback_data="auc:mine:0", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:economy", style=STYLE_MAIN)
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def auction_resources_kb() -> InlineKeyboardMarkup:
    """انتخاب منبع طبیعی برای مزایده (v2.2)."""
    builder = InlineKeyboardBuilder()
    for r in ResourceType:
        builder.button(
            text=f"{RESOURCE_EMOJI[r]} {RESOURCE_FA[r]}",
            callback_data=f"auc_res:{r.value}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="econ:auction", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def auction_durations_kb() -> InlineKeyboardMarkup:
    """انتخاب مدت زمان مزایده به ساعت (v2.2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ ۶ ساعت", callback_data="auc_dur:6", style=STYLE_MAIN)
    builder.button(text="⏱ ۱۲ ساعت", callback_data="auc_dur:12", style=STYLE_MAIN)
    builder.button(text="⏱ ۲۴ ساعت (۱ روز)", callback_data="auc_dur:24", style=STYLE_MAIN)
    builder.button(text="⏱ ۴۸ ساعت (۲ روز)", callback_data="auc_dur:48", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="econ:auction", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()
