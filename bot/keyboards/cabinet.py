"""کیبوردهای اینلاین برای گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..constants import CABINET_ROLES_DATA
from ..database.models.cabinet import CabinetMember
from ..enums import CabinetRole
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def gamemode_selection_kb(current_mode: str = "global") -> InlineKeyboardMarkup:
    """کیبورد انتخاب و تغییر حالت بازی."""
    builder = InlineKeyboardBuilder()

    glob_mark = "🟢 " if current_mode == "global" else "⚪️ "
    cab_mark = "🟢 " if current_mode == "cabinet" else "⚪️ "

    builder.row(
        InlineKeyboardButton(
            text=f"{glob_mark}🌍 ۱. کشوری جهانی (کلاسیک)",
            callback_data="gamemode:set:global",
            style=STYLE_OK if current_mode == "global" else STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{cab_mark}🏛 ۲. کشوری مقاماتی (دولت آمریکا)",
            callback_data="gamemode:set:cabinet",
            style=STYLE_OK if current_mode == "cabinet" else STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="menu:main", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_roles_list_kb(
    members: list[CabinetMember], current_user_id: int
) -> InlineKeyboardMarkup:
    """کیبورد فهرست ۱۵ مقام کابینه جهت انتخاب و تصدی سمت."""
    builder = InlineKeyboardBuilder()

    member_map = {m.role_key: m for m in members}

    for role_enum in CabinetRole:
        m = member_map.get(role_enum.value)
        data = CABINET_ROLES_DATA.get(role_enum, {})
        icon = data.get("icon", "🏛")
        title = data.get("title_fa", role_enum.value)
        name = data.get("official_name", "")

        if m is not None and m.user_id is not None:
            if m.user_id == current_user_id:
                status_txt = "⭐️ (سمت شما)"
                btn_style = STYLE_OK
                cb = f"cab:menu:{role_enum.value}"
            else:
                status_txt = "🔴 اشغال"
                btn_style = STYLE_NO
                cb = f"cab:occupied:{role_enum.value}"
        else:
            status_txt = "🟢 خالی"
            btn_style = STYLE_MAIN
            cb = f"cab:claim:{role_enum.value}"

        btn_text = f"{icon} {title} ({name}) — {status_txt}"
        builder.button(text=btn_text, callback_data=cb, style=btn_style)

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔄 تغییر گیم‌مود (/gamemode)", callback_data="gamemode:menu", style=STYLE_MAIN),
        InlineKeyboardButton(text="🔙 منوی اصلی", callback_data="menu:main", style=STYLE_MAIN),
    )
    return builder.as_markup()


def cabinet_main_menu_kb(role_key: str) -> InlineKeyboardMarkup:
    """کیبورد اختصاصی میز کار هر مقام دولتی."""
    builder = InlineKeyboardBuilder()

    # دکمه‌های تخصصی بر اساس هر مقام
    if role_key == CabinetRole.PRESIDENT.value:
        builder.button(text="👑 صدور فرمان اجرایی", callback_data="cab:action:exec_order", style=STYLE_OK)
        builder.button(text="🎤 سخنرانی رسمی کاخ سفید", callback_data="cab:action:address", style=STYLE_MAIN)
        builder.button(text="💰 گزارش جامع خزانه‌داری", callback_data="cab:domain:economy", style=STYLE_MAIN)
        builder.button(text="🛡 وضعیت ارتش و پنتاگون", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.button(text="🕵️ بولتن اطلاعاتی سیا", callback_data="cab:domain:intel", style=STYLE_MAIN)
        builder.button(text="🌍 دیپلماسی و تحریم‌ها", callback_data="cab:domain:diplomacy", style=STYLE_MAIN)
        builder.adjust(2, 2, 2)

    elif role_key == CabinetRole.VICE_PRESIDENT.value:
        builder.button(text="🦅 فراخوان جلسه اضطراری", callback_data="cab:action:vp_summon", style=STYLE_OK)
        builder.button(text="💰 نظارت بر خزانه‌داری", callback_data="cab:domain:economy", style=STYLE_MAIN)
        builder.button(text="🛡 نظارت بر پنتاگون", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.button(text="⚖️ نظارت بر دادگستری", callback_data="cab:domain:justice", style=STYLE_MAIN)
        builder.adjust(2, 2)

    elif role_key == CabinetRole.SECRETARY_STATE.value:
        builder.button(text="🌍 دیپلماسی و معاهدات", callback_data="cab:domain:diplomacy", style=STYLE_MAIN)
        builder.button(text="🚫 تحریم‌های بین‌المللی", callback_data="cab:action:sanctions", style=STYLE_MAIN)
        builder.button(text="✉️ یادداشت دیپلماتیک", callback_data="cab:action:diplo_cable", style=STYLE_OK)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.SECRETARY_DEFENSE.value:
        builder.button(text="🛡 وضعیت ارتش و پنتاگون", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.button(text="🚨 سطح هشدار DEFCON", callback_data="cab:action:defcon", style=STYLE_OK)
        builder.button(text="🏗 پایگاه‌های نظامی جهان", callback_data="cab:action:bases", style=STYLE_MAIN)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.CENTCOM_COMMANDER.value:
        builder.button(text="⚔️ استقرار نیروها در جهان", callback_data="cab:action:deploy", style=STYLE_OK)
        builder.button(text="⚓ رهگیری و کنترل کاروان‌ها", callback_data="cab:action:intercept", style=STYLE_MAIN)
        builder.button(text="🛡 گزارش آمادگی رزم", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.CIA_DIRECTOR.value:
        builder.button(text="🕵️ بولتن روزانه سیا", callback_data="cab:domain:intel", style=STYLE_MAIN)
        builder.button(text="🔍 ماموریت اطلاعاتی محرمانه", callback_data="cab:action:intel_op", style=STYLE_OK)
        builder.adjust(2)

    elif role_key == CabinetRole.HOMELAND_SECURITY.value:
        builder.button(text="🚔 سامانه ضدجاسوسی فدرال", callback_data="cab:domain:intel", style=STYLE_MAIN)
        builder.button(text="🛡 امنیت مرزها و زیرساخت‌ها", callback_data="cab:action:borders", style=STYLE_OK)
        builder.adjust(2)

    elif role_key == CabinetRole.PRESS_SECRETARY.value:
        builder.button(text="🎤 کنفرانس مطبوعاتی کاخ سفید", callback_data="cab:action:press_briefing", style=STYLE_OK)
        builder.button(text="👥 رصد رضایت افکار عمومی", callback_data="cab:domain:press", style=STYLE_MAIN)
        builder.adjust(1, 1)

    elif role_key == CabinetRole.TREASURY_SECRETARY.value:
        builder.button(text="💰 دخل‌وخرج و بودجه فدرال", callback_data="cab:domain:economy", style=STYLE_MAIN)
        builder.button(text="📈 سرمایه‌گذاری‌های خزانه‌داری", callback_data="cab:action:invest", style=STYLE_OK)
        builder.button(text="💵 تنظیم مالیات فدرال", callback_data="cab:action:tax", style=STYLE_MAIN)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.TECH_EFFICIENCY.value:
        builder.button(text="⚡️ ممیزی کارآمدی سازمان‌ها (DOGE)", callback_data="cab:action:doge_audit", style=STYLE_OK)
        builder.button(text="🛡 وضعیت پدافند سایبری", callback_data="cab:action:cyber_shield", style=STYLE_MAIN)
        builder.button(text="🤖 اتوماسیون با هوش مصنوعی", callback_data="cab:domain:tech", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.ATTORNEY_GENERAL.value:
        builder.button(text="⚖️ صدور حکم بازرسی ویژه ارگان‌ها", callback_data="cab:action:inspect_organ", style=STYLE_OK)
        builder.button(text="📋 پرونده‌های بازرسی فعال", callback_data="cab:action:inspect_list", style=STYLE_MAIN)
        builder.button(text="🏛 گزارش سلامت اداری", callback_data="cab:domain:justice", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.AEROSPACE_DEFENSE.value:
        builder.button(text="📡 پرتاب ماهواره جاسوسی فضایی", callback_data="cab:action:launch_sat", style=STYLE_OK)
        builder.button(text="🏭 صنایع و کارخانه‌های نظامی", callback_data="cab:action:mil_factories", style=STYLE_MAIN)
        builder.button(text="🚀 فناوری‌های فضایی", callback_data="cab:domain:tech", style=STYLE_MAIN)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.HEALTH_CRISIS.value:
        builder.button(text="☣️ پروتکل مدیریت بحران ملی", callback_data="cab:action:crisis_protocol", style=STYLE_OK)
        builder.button(text="🏥 شاخص سلامت و بهداشت", callback_data="cab:domain:health", style=STYLE_MAIN)
        builder.adjust(1, 1)

    elif role_key == CabinetRole.JOINT_CHIEFS.value:
        builder.button(text="🗺 نقشه‌برداری ژئوپلیتیک و کریدورها", callback_data="cab:action:geo_map", style=STYLE_OK)
        builder.button(text="📡 هماهنگی رصد ماهواره‌ای", callback_data="cab:action:sat_recon", style=STYLE_MAIN)
        builder.button(text="⚔️ گزارش تجمیعی شاخه‌های ارتش", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(2, 1)

    elif role_key == CabinetRole.NATIONAL_SECURITY.value:
        builder.button(text="👁 جلسه شورای امنیت ملی (NSC)", callback_data="cab:action:nsc_brief", style=STYLE_OK)
        builder.button(text="☢️ وضعیت بازدارندگی هسته‌ای", callback_data="cab:action:nuclear_status", style=STYLE_MAIN)
        builder.button(text="🛡 ارزیابی ترکیبی تهدیدات", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(2, 1)

    # بخش دسترسی‌های عمومی و مشترک میان تمام مقامات
    builder.row(
        InlineKeyboardButton(text="✉️ نامه‌نگاری", callback_data="cab:memo:menu", style=STYLE_MAIN),
        InlineKeyboardButton(text="🤝 دیدار حضوری", callback_data="cab:meet:start", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="📞 تماس تلفنی", callback_data="cab:call:start", style=STYLE_MAIN),
        InlineKeyboardButton(text="📑 استعلام اطلاعات", callback_data="cab:inquiry:menu", style=STYLE_MAIN),
    )

    # ردیف ابزارهای پایین صفحه
    builder.row(
        InlineKeyboardButton(text="👥 اعضای دولت", callback_data="cab:roster", style=STYLE_MAIN),
        InlineKeyboardButton(text="🔄 تغییر گیم‌مود", callback_data="gamemode:menu", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="🚪 استعفا از سمت", callback_data="cab:resign", style=STYLE_NO)
    )

    return builder.as_markup()


def cabinet_memo_menu_kb() -> InlineKeyboardMarkup:
    """کیبورد منوی مکاتبات و نامه‌نگاری کابینه."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✉️ نگارش نامه جدید", callback_data="cab:memo:new", style=STYLE_OK),
        InlineKeyboardButton(text="📥 صندوق یادداشت‌ها", callback_data="cab:memo:inbox", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_inquiry_menu_kb() -> InlineKeyboardMarkup:
    """کیبورد منوی استعلام اطلاعات میان ارگان‌ها."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📑 ثبت استعلام جدید", callback_data="cab:inquiry:new", style=STYLE_OK),
        InlineKeyboardButton(text="📬 کارتابل استعلام‌ها", callback_data="cab:inquiry:list", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_select_official_kb(
    members: list[CabinetMember], prefix: str, allow_all: bool = False
) -> InlineKeyboardMarkup:
    """کیبورد انتخاب یک مقام دولتی برای ارسال نامه، استعلام، دیدار یا بازرسی."""
    builder = InlineKeyboardBuilder()

    if allow_all:
        builder.button(text="🌍 تمام اعضای کابینه (سراسری)", callback_data=f"{prefix}:all", style=STYLE_OK)

    for m in members:
        role_enum = CabinetRole(m.role_key) if m.role_key in [r.value for r in CabinetRole] else None
        if not role_enum or role_enum not in CABINET_ROLES_DATA:
            continue
        data = CABINET_ROLES_DATA[role_enum]
        icon = data.get("icon", "🏛")
        title = data.get("title_fa", m.role_key)
        name = data.get("official_name", "")
        builder.button(
            text=f"{icon} {title} ({name})",
            callback_data=f"{prefix}:{m.role_key}",
            style=STYLE_MAIN,
        )

    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()
