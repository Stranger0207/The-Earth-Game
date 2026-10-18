"""
کیبوردهای شیشه‌ای مدیریت تنگه‌ها، مسدودسازی، عوارض، اخطار عبور و اموال بلوکه‌شده (آپدیت ۳ و ۱۱).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import Country
from ..database.models.strait import BlockedCargo, StraitBlockRule, StraitConfig
from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA, ResourceType, StraitBlockScope
from ..services.geo_service import get_strait_def
from ..utils.numbers import fa_money, fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK

BLOCKED_PAGE_SIZE = 6
CUSTOM_COUNTRY_PAGE_SIZE = 8


def straits_menu_kb(controlled_straits: list[StraitConfig]) -> InlineKeyboardMarkup:
    """منوی اصلی مدیریت تنگه‌های تحت کنترل کشور."""
    builder = InlineKeyboardBuilder()

    for s in controlled_straits:
        if s.is_blocked:
            if s.block_scope == StraitBlockScope.ALL.value:
                status_icon = "🔴 مسدود کامل"
            else:
                status_icon = "🟡 مسدود گزینشی"
        else:
            status_icon = f"🟢 باز ({fa_money(s.default_toll)})"

        btn_text = f"🌊 {s.name_fa} — {status_icon}"
        builder.button(
            text=btn_text, callback_data=f"strait_detail:{s.strait_id}", style=STYLE_MAIN
        )

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text="🔒 اموال بلوکه‌شده", callback_data="strait:blocked_cargos", style=STYLE_MAIN
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main", style=STYLE_MAIN)
    )
    return builder.as_markup()


def strait_detail_kb(strait: StraitConfig) -> InlineKeyboardMarkup:
    """منوی جزئیات و تنظیمات یک تنگه خاص."""
    builder = InlineKeyboardBuilder()

    # وضعیت مسدودسازی
    if strait.is_blocked and strait.block_scope == StraitBlockScope.ALL.value:
        builder.button(
            text="🟢 باز کردن تنگه (آزادسازی عبور)",
            callback_data=f"strait_unblock:{strait.strait_id}",
            style=STYLE_OK,
        )
    else:
        builder.button(
            text="🌍 بستن به روی همه کشورها",
            callback_data=f"strait_block_all:{strait.strait_id}",
            style=STYLE_NO,
        )

    builder.button(
        text="🎯 قوانین اختصاصی و مسدودسازی کشورها",
        callback_data=f"strait_custom:{strait.strait_id}:0",
        style=STYLE_MAIN,
    )
    builder.button(
        text=f"💵 تغییر عوارض عمومی ({fa_money(strait.default_toll)})",
        callback_data=f"strait_toll:{strait.strait_id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔙 بازگشت به مدیریت تنگه‌ها",
        callback_data="menu:straits",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def strait_custom_countries_kb(
    strait_id: str,
    countries: list[Country],
    rules_map: dict[int, StraitBlockRule],
    page: int = 0,
) -> InlineKeyboardMarkup:
    """فهرست صفحه‌بندی‌شده کشورها برای تنظیم مسدودسازی یا عوارض اختصاصی."""
    builder = InlineKeyboardBuilder()

    start = page * CUSTOM_COUNTRY_PAGE_SIZE
    end = start + CUSTOM_COUNTRY_PAGE_SIZE
    page_countries = countries[start:end]

    for c in page_countries:
        rule = rules_map.get(c.id)
        if rule and rule.is_blocked:
            tag = "🔴 مسدود"
        elif rule and rule.custom_toll is not None:
            tag = f"💵 {fa_money(rule.custom_toll)}"
        else:
            tag = "⚪️ پیش‌فرض"

        builder.button(
            text=f"{c.flag} {c.name_fa} [{tag}]",
            callback_data=f"strait_crule:{strait_id}:{c.id}",
            style=STYLE_MAIN,
        )

    builder.adjust(1)

    # ناوبری صفحات
    nav_buttons: list[InlineKeyboardButton] = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"strait_custom:{strait_id}:{page - 1}",
                style=STYLE_MAIN,
            )
        )
    if end < len(countries):
        nav_buttons.append(
            InlineKeyboardButton(
                text="صفحه بعد ➡️",
                callback_data=f"strait_custom:{strait_id}:{page + 1}",
                style=STYLE_MAIN,
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به تنگه",
            callback_data=f"strait_detail:{strait_id}",
            style=STYLE_MAIN,
        )
    )
    return builder.as_markup()


def strait_country_rule_kb(
    strait_id: str,
    target_country: Country,
    rule: StraitBlockRule | None,
) -> InlineKeyboardMarkup:
    """تنظیمات مسدودسازی و عوارض برای یک کشور خاص."""
    builder = InlineKeyboardBuilder()

    is_blocked = rule.is_blocked if rule else False
    custom_toll = rule.custom_toll if rule else None

    if is_blocked:
        builder.button(
            text=f"🟢 رفع مسدودیت {target_country.name_fa}",
            callback_data=f"strait_toggle_block:{strait_id}:{target_country.id}:0",
            style=STYLE_OK,
        )
    else:
        builder.button(
            text=f"🔴 مسدود کردن عبور {target_country.name_fa}",
            callback_data=f"strait_toggle_block:{strait_id}:{target_country.id}:1",
            style=STYLE_NO,
        )

    toll_label = f"💵 تنظیم عوارض اختصاصی ({fa_money(custom_toll) if custom_toll is not None else 'ندارد'})"
    builder.button(
        text=toll_label,
        callback_data=f"strait_set_ctoll:{strait_id}:{target_country.id}",
        style=STYLE_MAIN,
    )

    if rule:
        builder.button(
            text="♻️ ریست به تنظیمات پیش‌فرض تنگه",
            callback_data=f"strait_reset_rule:{strait_id}:{target_country.id}",
            style=STYLE_MAIN,
        )

    builder.button(
        text="🔙 بازگشت به لیست کشورها",
        callback_data=f"strait_custom:{strait_id}:0",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def strait_standoff_ctrl_kb(
    sale_id: int, strait_id: str, warning_count: int = 0, is_running: bool = False
) -> InlineKeyboardMarkup:
    """کیبورد رویارویی و ایست‌بازرسی تنگه برای کشور کنترل‌کننده."""
    rows: list[list[InlineKeyboardButton]] = []

    # دکمه صدور اخطار (۱ تا ۳)
    if warning_count < 3:
        next_w = warning_count + 1
        w_label = "اخطار اول" if next_w == 1 else ("اخطار دوم (جدی)" if next_w == 2 else "اخطار سوم (اولتیماتوم)")
        rows.append([
            InlineKeyboardButton(
                text=f"⚠️ صدور {w_label} ({fa_number(next_w)} از ۳)",
                callback_data=f"strait_act:warn:{sale_id}:{strait_id}",
                style=STYLE_NO,
            )
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                text="🔴 اولتیماتوم نهایی صادر شده (۳ اخطار کامل)",
                callback_data=f"strait_act:warn_max:{sale_id}:{strait_id}",
                style=STYLE_NO,
            )
        ])

    # ردیف عملیات نظامی و قاطع (صرفاً پس از صدور هر ۳ اخطار مجاز است)
    mil_row: list[InlineKeyboardButton] = []
    if warning_count >= 3:
        mil_row.append(
            InlineKeyboardButton(
                text="💥 شلیک به کشتی",
                callback_data=f"strait_act:fire:{sale_id}:{strait_id}",
                style=STYLE_NO,
            )
        )
        mil_row.append(
            InlineKeyboardButton(
                text="⚓ مصادره بار",
                callback_data=f"strait_act:confiscate_menu:{sale_id}:{strait_id}",
                style=STYLE_MAIN,
            )
        )
    else:
        mil_row.append(
            InlineKeyboardButton(
                text=f"🔒 شلیک ({fa_number(warning_count)}/۳ اخطار)",
                callback_data=f"strait_act:fire_locked:{sale_id}:{strait_id}",
                style=STYLE_MAIN,
            )
        )
        mil_row.append(
            InlineKeyboardButton(
                text=f"🔒 مصادره ({fa_number(warning_count)}/۳ اخطار)",
                callback_data=f"strait_act:conf_locked:{sale_id}:{strait_id}",
                style=STYLE_MAIN,
            )
        )
    rows.append(mil_row)

    # ردیف صدور اجازه عبور
    rows.append([
        InlineKeyboardButton(
            text="✅ صدور اجازه عبور",
            callback_data=f"strait_act:allow:{sale_id}:{strait_id}",
            style=STYLE_OK,
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def strait_standoff_owner_kb(
    sale_id: int, strait_id: str, current_action: str = "STANDOFF"
) -> InlineKeyboardMarkup:
    """کیبورد تصمیم‌گیری مالک محموله در مواجهه با تنگه مسدود."""
    if current_action == "HOLD":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚓ لنگر انداخته‌اید (در انتظار دستور)",
                        callback_data=f"strait_owner:info_hold:{sale_id}:{strait_id}",
                        style=STYLE_MAIN,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 عقب‌نشینی و بازگشت محموله به کشور",
                        callback_data=f"strait_owner:retreat:{sale_id}:{strait_id}",
                        style=STYLE_OK,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚢 شکستن محاصره و ادامه مسیر",
                        callback_data=f"strait_owner:run:{sale_id}:{strait_id}",
                        style=STYLE_NO,
                    )
                ],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚓ ۱- توقف و لنگراندازی در دهانه تنگه",
                    callback_data=f"strait_owner:hold:{sale_id}:{strait_id}",
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 ۲- عقب‌نشینی و بازگشت محموله به کشور",
                    callback_data=f"strait_owner:retreat:{sale_id}:{strait_id}",
                    style=STYLE_OK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚢 ۳- ادامه مسیر با ریسک خود (تلاش برای عبور)",
                    callback_data=f"strait_owner:run:{sale_id}:{strait_id}",
                    style=STYLE_NO,
                )
            ],
        ]
    )


def strait_intercept_alert_kb(sale_id: int, strait_id: str) -> InlineKeyboardMarkup:
    """کیبورد پیش‌فرض اخطار توقیف به پیوی کشور کنترل‌کننده تنگه."""
    return strait_standoff_ctrl_kb(sale_id, strait_id, warning_count=0)


def strait_intercept_attack_kb(sale_id: int, strait_id: str) -> InlineKeyboardMarkup:
    """گزینه‌های عملیاتی حمله به شناور در تنگه."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💥 ۱- حمله و تخریب کشتی",
                    callback_data=f"strait_act:destroy:{sale_id}:{strait_id}",
                    style=STYLE_NO,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚓ ۲- مصادره کردن کشتی",
                    callback_data=f"strait_act:confiscate_menu:{sale_id}:{strait_id}",
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=f"strait_act:back_alert:{sale_id}:{strait_id}",
                    style=STYLE_MAIN,
                )
            ],
        ]
    )


def strait_confiscate_choice_kb(sale_id: int, strait_id: str) -> InlineKeyboardMarkup:
    """انتخاب سرنوشت بار پس از مصادره کشتی."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ افزودن فوری به ذخایر خودم",
                    callback_data=f"strait_act:conf_reserves:{sale_id}:{strait_id}",
                    style=STYLE_OK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔒 انتقال به اموال بلوکه‌شده",
                    callback_data=f"strait_act:conf_blocked:{sale_id}:{strait_id}",
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=f"strait_act:attack_menu:{sale_id}:{strait_id}",
                    style=STYLE_MAIN,
                )
            ],
        ]
    )


def blocked_cargos_kb(
    cargos: list[BlockedCargo],
    countries_map: dict[int, Country],
    page: int = 0,
) -> InlineKeyboardMarkup:
    """فهرست محموله‌های بلوکه‌شده با صفحه‌بندی."""
    builder = InlineKeyboardBuilder()

    start = page * BLOCKED_PAGE_SIZE
    end = start + BLOCKED_PAGE_SIZE
    page_cargos = cargos[start:end]

    for item in page_cargos:
        src = countries_map.get(item.source_country_id)
        src_name = f"{src.flag} {src.name_fa}" if src else "?"

        try:
            rname = RESOURCE_FA[ResourceType(item.resource)]
            unit = RESOURCE_UNIT_FA[ResourceType(item.resource)]
        except (ValueError, KeyError):
            rname = item.resource
            unit = ""

        builder.button(
            text=f"📦 #{item.id} — {fa_number(item.amount)} {unit} {rname} (از {src_name})",
            callback_data=f"blk_view:{item.id}",
            style=STYLE_MAIN,
        )

    builder.adjust(1)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"strait:blocked_pg:{page - 1}",
                style=STYLE_MAIN,
            )
        )
    if end < len(cargos):
        nav.append(
            InlineKeyboardButton(
                text="صفحه بعد ➡️",
                callback_data=f"strait:blocked_pg:{page + 1}",
                style=STYLE_MAIN,
            )
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به مدیریت تنگه‌ها", callback_data="menu:straits", style=STYLE_MAIN
        )
    )
    return builder.as_markup()


def blocked_cargo_actions_kb(cargo_id: int) -> InlineKeyboardMarkup:
    """عملیات سه‌گانه برای یک محموله بلوکه‌شده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 تخریب اموال",
                    callback_data=f"blk_act:destroy:{cargo_id}",
                    style=STYLE_NO,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 افزودن به ذخایر کشور خودم",
                    callback_data=f"blk_act:claim:{cargo_id}",
                    style=STYLE_OK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚢 بازگرداندن به کشور ارسال‌کننده",
                    callback_data=f"blk_act:return:{cargo_id}",
                    style=STYLE_MAIN,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت به لیست اموال",
                    callback_data="strait:blocked_cargos",
                    style=STYLE_MAIN,
                )
            ],
        ]
    )


def blocked_cargo_confirm_kb(action: str, cargo_id: int) -> InlineKeyboardMarkup:
    """تأیید دومرحله‌ای برای اقدامات روی اموال بلوکه‌شده."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ بله، کاملاً مطمئنم و تأیید می‌کنم",
                    callback_data=f"blk_cfm:{action}:{cargo_id}",
                    style=STYLE_OK,
                ),
                InlineKeyboardButton(
                    text="❌ منصرف شدم",
                    callback_data=f"blk_view:{cargo_id}",
                    style=STYLE_NO,
                ),
            ]
        ]
    )
