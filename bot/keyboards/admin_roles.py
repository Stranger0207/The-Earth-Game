"""کیبوردهای پنل مدیریتی جامع /roles برای ادمین‌ها و مالکان (آپدیت شماره ۲)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..database.models import Country, EconomicProject, MilitaryRole, SecurityRole
from ..enums import MilitaryRoleType
from ..utils.numbers import fa_number
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def admin_roles_main_kb() -> InlineKeyboardMarkup:
    """منوی اصلی پنل مدیریت رول‌ها (/roles)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛡 آرشیو رول‌های امنیتی کشورها (تاییدشده)",
        callback_data="roles_admin:sec_archive",
        style=STYLE_MAIN,
    )
    builder.button(
        text="⏳ رول‌های امنیتی در انتظار تایید",
        callback_data="roles_admin:sec_pending",
        style=STYLE_MAIN,
    )
    builder.button(
        text="💰 رول‌های اقتصادی در انتظار تایید",
        callback_data="roles_admin:econ_pending",
        style=STYLE_MAIN,
    )
    builder.button(
        text="⚔️ رول‌های نظامی باز (در حال اجرا)",
        callback_data="roles_admin:mil_open",
        style=STYLE_MAIN,
    )
    builder.button(
        text="❌ بستن پنل",
        callback_data="roles_admin:close",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_countries_archive_kb(
    countries: list[Country]
) -> InlineKeyboardMarkup:
    """فهرست کشورهایی که رول امنیتی تاییدشده دارند."""
    builder = InlineKeyboardBuilder()
    for country in countries:
        builder.button(
            text=f"{country.flag} {country.name_fa}",
            callback_data=f"roles_admin:c_sec:{country.id}",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)
    builder.adjust(2)
    return builder.as_markup()


def admin_roles_country_security_kb(
    roles: list[SecurityRole], country_id: int
) -> InlineKeyboardMarkup:
    """فهرست پروژه‌های امنیتی تاییدشده یک کشور در پنل مدیریت."""
    builder = InlineKeyboardBuilder()
    for r in roles:
        builder.button(
            text=f"🛡 {r.title[:25]} ({fa_number(r.total_pages)} ص)",
            callback_data=f"roles_admin:sec_v:{r.id}:1:arch",
            style=STYLE_MAIN,
        )
    builder.button(
        text="🔙 بازگشت به لیست کشورها",
        callback_data="roles_admin:sec_archive",
        style=STYLE_MAIN,
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_pending_security_list_kb(
    roles: list[SecurityRole], countries_map: dict[int, Country]
) -> InlineKeyboardMarkup:
    """فهرست رول‌های امنیتی در انتظار تایید."""
    builder = InlineKeyboardBuilder()
    for r in roles:
        c = countries_map.get(r.country_id)
        c_tag = f"{c.flag} {c.name_fa}" if c else "نامشخص"
        builder.button(
            text=f"🛡 {c_tag} | {r.title[:20]}",
            callback_data=f"roles_admin:sec_v:{r.id}:1:pend",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_pending_econ_list_kb(
    projects: list[EconomicProject], countries_map: dict[int, Country]
) -> InlineKeyboardMarkup:
    """فهرست رول‌های اقتصادی در انتظار تایید."""
    builder = InlineKeyboardBuilder()
    for p in projects:
        c = countries_map.get(p.country_id)
        c_tag = f"{c.flag} {c.name_fa}" if c else "نامشخص"
        builder.button(
            text=f"🏗 {c_tag} | {p.title[:20]}",
            callback_data=f"roles_admin:econ_v:{p.id}:1",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_active_military_list_kb(
    roles: list[MilitaryRole], countries_map: dict[int, Country]
) -> InlineKeyboardMarkup:
    """فهرست رول‌های نظامی باز و در حال اجرا."""
    builder = InlineKeyboardBuilder()
    for r in roles:
        att = countries_map.get(r.attacker_country_id)
        tgt = countries_map.get(r.target_country_id)
        att_tag = f"{att.flag}" if att else ""
        tgt_tag = f"{tgt.flag}" if tgt else ""
        try:
            op_t = MilitaryRoleType(r.op_type)
            badge = "💣" if op_t == MilitaryRoleType.SABOTAGE else ("🎯" if op_t == MilitaryRoleType.ASSASSINATION else "🚀")
        except Exception:
            badge = "⚔️"

        builder.button(
            text=f"{badge} {att_tag} ⚔️ {tgt_tag} | {r.title[:18]}",
            callback_data=f"roles_admin:mil_v:{r.id}:1",
            style=STYLE_MAIN,
        )
    builder.button(text="🔙 بازگشت", callback_data="roles_admin:home", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def admin_roles_view_security_kb(
    role: SecurityRole, current_page: int, mode: str
) -> InlineKeyboardMarkup:
    """کیبورد ورق زدن و داوری رول امنیتی در پنل /roles."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    # سطر ورق زدن
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"roles_admin:sec_v:{role.id}:{current_page - 1}:{mode}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="roles_admin:noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"roles_admin:sec_v:{role.id}:{current_page + 1}:{mode}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # اگر در صف انتظار بررسی است، دکمه‌های تایید و رد قرار گیرد
    if mode == "pend":
        builder.row(
            InlineKeyboardButton(
                text="✅ تایید رول امنیتی",
                callback_data=f"roles_admin:sec_app:{role.id}",
                style=STYLE_OK,
            ),
            InlineKeyboardButton(
                text="❌ رد کردن رول",
                callback_data=f"roles_admin:sec_rej:{role.id}",
                style=STYLE_NO,
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="🔙 بازگشت به صف انتظار",
                callback_data="roles_admin:sec_pending",
                style=STYLE_MAIN,
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🔙 بازگشت به آرشیو کشور",
                callback_data=f"roles_admin:c_sec:{role.country_id}",
                style=STYLE_MAIN,
            )
        )
    return builder.as_markup()


def admin_roles_view_military_kb(
    role: MilitaryRole, current_page: int
) -> InlineKeyboardMarkup:
    """کیبورد ورق زدن و مدیریت عملیات نظامی در پنل /roles."""
    builder = InlineKeyboardBuilder()
    total = role.total_pages

    # سطر ورق زدن
    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ صفحه قبل",
                callback_data=f"roles_admin:mil_v:{role.id}:{current_page - 1}",
                style=STYLE_MAIN,
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"📄 {fa_number(current_page)}/{fa_number(total)}",
            callback_data="roles_admin:noop",
        )
    )
    if current_page < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️ صفحه بعد",
                callback_data=f"roles_admin:mil_v:{role.id}:{current_page + 1}",
                style=STYLE_MAIN,
            )
        )
    builder.row(*nav_buttons)

    # دکمه‌های عملیاتی ادمین
    builder.row(
        InlineKeyboardButton(
            text="💥 ثبت تلفات",
            callback_data=f"mil_grp_cas:{role.id}:panel",
            style=STYLE_NO,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🛡 مشاهده رول‌های امنیتی کشور هدف",
            callback_data=f"roles_admin:mil_tgt_sec:{role.id}",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🏁 پایان عملیات",
            callback_data=f"mil_grp_end:{role.id}:panel",
            style=STYLE_OK,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به لیست عملیات‌ها",
            callback_data="roles_admin:mil_open",
            style=STYLE_MAIN,
        )
    )
    return builder.as_markup()
