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


def cabinet_main_menu_kb(role_key: str, member: CabinetMember | None = None) -> InlineKeyboardMarkup:
    """کیبورد اختصاصی میز کار هر مقام دولتی (v2.6)."""
    builder = InlineKeyboardBuilder()

    # دکمه‌های تخصصی عملیاتی هر یک از ۱۵ مقام
    if role_key == CabinetRole.PRESIDENT.value:
        builder.button(text="📜 صدور فرمان اجرایی (Executive Order)", callback_data="cab:action:exec_order", style=STYLE_OK)
        builder.button(text="⚖️ وتو و حل بن‌بست پرونده‌ها", callback_data="cab:ops:veto_menu", style=STYLE_MAIN)
        builder.button(text="🎖 توبیخ یا تشویق وزرا", callback_data="cab:action:eval_ministers", style=STYLE_MAIN)
        builder.button(text="🎤 سخنرانی رسمی کاخ سفید", callback_data="cab:action:address", style=STYLE_MAIN)
        builder.adjust(1, 2, 1)

    elif role_key == CabinetRole.VICE_PRESIDENT.value:
        builder.button(text="🏛 لابی‌گری در سنا (Senate Floor)", callback_data="cab:action:senate_lobby", style=STYLE_OK)
        builder.button(text="🔨 حکمیت اختلافات پرونده‌ها", callback_data="cab:ops:arbitrate_menu", style=STYLE_MAIN)
        builder.button(text="🦅 فراخوان جلسه اضطراری", callback_data="cab:action:vp_summon", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.SECRETARY_STATE.value:
        builder.button(text="🌐 آغاز زنجیره تحریم/معاهده", callback_data="cab:chain:start:diplomatic_economic", style=STYLE_OK)
        builder.button(text="🌍 دیپلماسی و سفارتخانه‌ها", callback_data="cab:domain:diplomacy", style=STYLE_MAIN)
        builder.button(text="✉️ یادداشت رسمی دیپلماتیک", callback_data="cab:action:diplo_cable", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.SECRETARY_DEFENSE.value:
        builder.button(text="🚨 سطح هشدار DEFCON", callback_data="cab:action:defcon", style=STYLE_OK)
        builder.button(text="🎖 تخصیص بودجه و فروش سلاح", callback_data="cab:action:pentagon_alloc", style=STYLE_MAIN)
        builder.button(text="🛡 وضعیت ارتش و پنتاگون", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.CENTCOM_COMMANDER.value:
        builder.button(text="🎯 آغاز زنجیره استقرار نظامی", callback_data="cab:chain:start:military_deployment", style=STYLE_OK)
        builder.button(text="⚓ رهگیری و کنترل کاروان‌ها", callback_data="cab:action:intercept", style=STYLE_MAIN)
        builder.button(text="🛡 گزارش آمادگی رزم", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.CIA_DIRECTOR.value:
        builder.button(text="📡 رمزگشایی اطلاعات خام سیا", callback_data="cab:action:cia_decrypt", style=STYLE_OK)
        builder.button(text="🕶 آغاز زنجیره عملیات امنیتی", callback_data="cab:chain:start:intel_security", style=STYLE_MAIN)
        builder.button(text="🕵️ بولتن روزانه سیا", callback_data="cab:domain:intel", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.HOMELAND_SECURITY.value:
        builder.button(text="🔍 اسکن ضدجاسوسی (Leak Hunter)", callback_data="cab:action:leak_hunter", style=STYLE_OK)
        builder.button(text="🛡 امنیت مرزها و گواهی امنیتی", callback_data="cab:action:borders", style=STYLE_MAIN)
        builder.button(text="🚔 سامانه امنیت فدرال", callback_data="cab:domain:intel", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.PRESS_SECRETARY.value:
        builder.button(text="🎙 کنفرانس مطبوعاتی کاخ سفید", callback_data="cab:action:press_briefing", style=STYLE_OK)
        builder.button(text="👥 رصد رضایت افکار عمومی", callback_data="cab:domain:press", style=STYLE_MAIN)
        builder.adjust(1, 1)

    elif role_key == CabinetRole.TREASURY_SECRETARY.value:
        builder.button(text="🏦 کارتابل تخصیص بودجه وزارتخانه‌ها", callback_data="cab:budget:inbox:1", style=STYLE_OK)
        builder.button(text="📊 تنظیم تعرفه‌ها و اوراق قرضه", callback_data="cab:action:tariff_bonds", style=STYLE_MAIN)
        builder.button(text="💰 دخل‌وخرج و خزانه فدرال", callback_data="cab:domain:economy", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.TECH_EFFICIENCY.value:
        builder.button(text="✂️ تابلوی ممیزی و فریز DOGE", callback_data="cab:ops:doge_freeze_menu", style=STYLE_OK)
        builder.button(text="🛡 سپر دفاع سایبری و اتوماسیون", callback_data="cab:action:cyber_shield", style=STYLE_MAIN)
        builder.button(text="⚡️ گزارش ممیزی DOGE", callback_data="cab:action:doge_audit", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.ATTORNEY_GENERAL.value:
        builder.button(text="⚖️ تعلیق قضایی عملیات‌ها", callback_data="cab:ops:doj_suspend_menu", style=STYLE_OK)
        builder.button(text="📂 بازرسی ویژه دادستان کل", callback_data="cab:action:inspect_organ", style=STYLE_MAIN)
        builder.button(text="🏛 گزارش سلامت اداری", callback_data="cab:domain:justice", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.AEROSPACE_DEFENSE.value:
        builder.button(text="🏭 آغاز زنجیره صنایع دفاعی/هوافضا", callback_data="cab:chain:start:aerospace_rd", style=STYLE_OK)
        builder.button(text="📡 پرتاب ماهواره جاسوسی", callback_data="cab:action:launch_sat", style=STYLE_MAIN)
        builder.button(text="🚀 فناوری‌های فضایی", callback_data="cab:domain:tech", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.HEALTH_CRISIS.value:
        builder.button(text="🚑 ستاد مدیریت بحران FEMA", callback_data="cab:action:crisis_protocol", style=STYLE_OK)
        builder.button(text="🏥 شاخص سلامت و بهداشت ملی", callback_data="cab:domain:health", style=STYLE_MAIN)
        builder.adjust(1, 1)

    elif role_key == CabinetRole.JOINT_CHIEFS.value:
        builder.button(text="🗺 آغاز زنجیره استقرار و لجستیک", callback_data="cab:chain:start:military_deployment", style=STYLE_OK)
        builder.button(text="📡 تحلیل تصاویر ماهواره تجسسی", callback_data="cab:action:sat_recon", style=STYLE_MAIN)
        builder.button(text="⚔️ گزارش تجمیعی ارتش", callback_data="cab:domain:military", style=STYLE_MAIN)
        builder.adjust(1, 2)

    elif role_key == CabinetRole.NATIONAL_SECURITY.value:
        builder.button(text="🖥 اتاق وضعیت (Situation Room)", callback_data="cab:action:situation_room", style=STYLE_OK)
        builder.button(text="👁 بولتن امنیتی روزانه NSC", callback_data="cab:action:nsc_brief", style=STYLE_MAIN)
        builder.button(text="☢️ وضعیت بازدارندگی هسته‌ای", callback_data="cab:action:nuclear_status", style=STYLE_MAIN)
        builder.adjust(1, 2)

    # بخش پرونده‌های بوروکراتیک و موتور بحران‌ها (مشترک برای همه)
    builder.row(
        InlineKeyboardButton(text="🔗 پرونده‌های زنجیره‌ای", callback_data="cab:ops:menu", style=STYLE_OK),
        InlineKeyboardButton(text="🚨 مدیریت بحران‌ها", callback_data="cab:crises:list:1", style=STYLE_NO),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 ماموریت محرمانه", callback_data="cab:agenda:view", style=STYLE_MAIN),
        InlineKeyboardButton(text="📰 درز اطلاعات به رسانه", callback_data="cab:leak:menu", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="🏦 درخواست بودجه وزارتخانه", callback_data="cab:budget:req", style=STYLE_MAIN),
        InlineKeyboardButton(text="📑 استعلام اطلاعات رسمی", callback_data="cab:inquiry:menu", style=STYLE_MAIN),
    )

    # بخش مکاتبات و ابزارهای ارتباطی
    builder.row(
        InlineKeyboardButton(text="✉️ نامه‌نگاری", callback_data="cab:memo:menu", style=STYLE_MAIN),
        InlineKeyboardButton(text="🤝 دیدار حضوری", callback_data="cab:meet:start", style=STYLE_MAIN),
        InlineKeyboardButton(text="📞 تماس تلفنی", callback_data="cab:call:start", style=STYLE_MAIN),
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


# ============================================================
#  کیبوردهای سیستم بوروکراسی زنجیره‌ای (CabinetOperation)
# ============================================================


def cabinet_operations_menu_kb() -> InlineKeyboardMarkup:
    """منوی اصلی کارتابل پرونده‌های زنجیره‌ای."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ آغاز پرونده جدید", callback_data="cab:ops:new", style=STYLE_OK),
        InlineKeyboardButton(text="✍️ کارتابل امضای من", callback_data="cab:ops:my:1", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="📋 پرونده‌های در جریان", callback_data="cab:ops:active:1", style=STYLE_MAIN),
        InlineKeyboardButton(text="📜 آرشیو و سوابق", callback_data="cab:ops:history:1", style=STYLE_MAIN),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_chain_type_selection_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع پرونده زنجیره‌ای از میان ۵ زنجیره مصوب."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⚔️ عملیات و استقرار نظامی (ستاد مشترک / سنتکام)",
            callback_data="cab:chain:start:military_deployment",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🌐 معاهدات، تحریم و تعرفه اقتصادی (خارجه / خزانه‌داری)",
            callback_data="cab:chain:start:diplomatic_economic",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🚀 صنایع دفاعی، هوافضا و ماهواره (هوافضا / DOGE)",
            callback_data="cab:chain:start:aerospace_rd",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🕶 عملیات اطلاعاتی و امنیت مشترک (سیا / دادگستری)",
            callback_data="cab:chain:start:intel_security",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🏛 لوایح کنگره و بودجه اضطراری (سنا / دادگستری)",
            callback_data="cab:chain:start:congressional_bill",
            style=STYLE_MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به کارتابل پرونده‌ها", callback_data="cab:ops:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_operations_list_kb(
    operations: list[CabinetOperation],
    page: int,
    total_pages: int,
    filter_type: str = "active",
) -> InlineKeyboardMarkup:
    """فهرست پرونده‌های زنجیره‌ای با صفحه‌بندی ۱۰تایی."""
    builder = InlineKeyboardBuilder()

    status_icons = {
        "PENDING": "⏳",
        "DOGE_FROZEN": "✂️",
        "DOJ_SUSPENDED": "⚖️",
        "VETOED": "🚫",
        "COMPLETED": "✅",
        "EXPIRED": "⌛️",
    }

    for op in operations:
        icon = status_icons.get(op.status, "📄")
        btn_text = f"{icon} {op.title[:32]} (گام {op.current_step})"
        builder.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"cab:op:view:{op.id}", style=STYLE_MAIN)
        )

    # ناوبری صفحه‌بندی
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cab:ops:{filter_type}:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"صفحه {page} از {max(1, total_pages)}", callback_data="noop")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cab:ops:{filter_type}:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🔙 منوی پرونده‌ها", callback_data="cab:ops:menu", style=STYLE_MAIN),
        InlineKeyboardButton(text="🏛 میز کار", callback_data="cab:menu", style=STYLE_MAIN),
    )
    return builder.as_markup()


def cabinet_operation_view_kb(
    op: CabinetOperation,
    user_role: str,
    can_sign: bool = False,
) -> InlineKeyboardMarkup:
    """دکمه‌های اختصاصی بررسی، امضا، فریز، تعلیق و وتوی یک پرونده."""
    builder = InlineKeyboardBuilder()

    # ۱. امضای مرحله در صورت صلاحیت
    if can_sign and op.status == "PENDING":
        builder.row(
            InlineKeyboardButton(text="✍️ امضا و پیشبرد پرونده (+5 سرمایه سیاسی)", callback_data=f"cab:op:sign:{op.id}", style=STYLE_OK)
        )

    # ۲. دکمه فریز وزیر DOGE
    if user_role == CabinetRole.TECH_EFFICIENCY.value and op.status == "PENDING":
        builder.row(
            InlineKeyboardButton(text="✂️ فریز DOGE (جلوگیری از هدررفت بودجه)", callback_data=f"cab:op:freeze:{op.id}", style=STYLE_NO)
        )

    # ۳. دکمه تعلیق دادستان کل
    if user_role == CabinetRole.ATTORNEY_GENERAL.value and op.status == "PENDING":
        builder.row(
            InlineKeyboardButton(text="⚖️ تعلیق قضایی دادستانی (مغایرت قانونی)", callback_data=f"cab:op:suspend:{op.id}", style=STYLE_NO)
        )

    # ۴. دکمه باز کردن قفل توسط رئیس‌جمهور یا معاون رئیس‌جمهور
    if user_role in (CabinetRole.PRESIDENT.value, CabinetRole.VICE_PRESIDENT.value) and op.status in ("DOGE_FROZEN", "DOJ_SUSPENDED"):
        builder.row(
            InlineKeyboardButton(text="🔓 شکستن قفل پرونده (حکمیت فدرال)", callback_data=f"cab:op:unfreeze:{op.id}", style=STYLE_OK)
        )

    # ۵. دکمه وتوی رسمی توسط رئیس‌جمهور
    if user_role == CabinetRole.PRESIDENT.value and op.status == "PENDING":
        builder.row(
            InlineKeyboardButton(text="🚫 وتوی رسمی رئیس‌جمهور", callback_data=f"cab:op:veto:{op.id}", style=STYLE_NO)
        )

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به فهرست", callback_data="cab:ops:active:1", style=STYLE_MAIN)
    )
    return builder.as_markup()


# ============================================================
#  کیبوردهای موتور بحران (CabinetCrisis)
# ============================================================


def cabinet_crises_list_kb(
    crises: list[CabinetCrisis],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """فهرست بحران‌های فعال و سابق کابینه با صفحه‌بندی ۱۰تایی."""
    builder = InlineKeyboardBuilder()

    status_icons = {
        "ACTIVE": "🚨",
        "RESOLVED": "✅",
        "FAILED": "💥",
    }

    for c in crises:
        icon = status_icons.get(c.status, "🚨")
        stars = "⭐️" * min(5, max(1, c.severity))
        btn_text = f"{icon} {c.title[:28]} [{stars}]"
        builder.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"cab:crisis:view:{c.id}", style=STYLE_MAIN)
        )

    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cab:crises:list:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"صفحه {page} از {max(1, total_pages)}", callback_data="noop")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cab:crises:list:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_crisis_view_kb(
    crisis: CabinetCrisis,
    user_role: str,
) -> InlineKeyboardMarkup:
    """نمایش گزینه‌های حل بحران برای مسئولین مربوطه."""
    builder = InlineKeyboardBuilder()

    if crisis.status == "ACTIVE":
        is_involved = user_role in (crisis.primary_role, crisis.secondary_role)
        is_already_approved = (
            (user_role == crisis.primary_role and crisis.primary_approved)
            or (user_role == crisis.secondary_role and crisis.secondary_approved)
        )

        if is_involved and not is_already_approved and crisis.options_json:
            for idx, opt in enumerate(crisis.options_json):
                label = opt.get("title", f"راهکار {idx + 1}")
                builder.row(
                    InlineKeyboardButton(
                        text=f"⚡️ انتخاب راهکار {idx + 1}: {label[:28]}",
                        callback_data=f"cab:crisis:solve:{crisis.id}:{idx}",
                        style=STYLE_OK,
                    )
                )

    builder.row(
        InlineKeyboardButton(text="🔙 فهرست بحران‌ها", callback_data="cab:crises:list:1", style=STYLE_MAIN),
        InlineKeyboardButton(text="🏛 میز کار", callback_data="cab:menu", style=STYLE_MAIN),
    )
    return builder.as_markup()


# ============================================================
#  کیبوردهای کارتابل بودجه وزارتخانه‌ها (CabinetBudgetRequest)
# ============================================================


def cabinet_budget_requests_list_kb(
    requests: list[CabinetBudgetRequest],
    page: int,
    total_pages: int,
    is_treasury: bool,
) -> InlineKeyboardMarkup:
    """فهرست درخواست‌های بودجه وزارتخانه‌ها با صفحه‌بندی ۱۰تایی."""
    builder = InlineKeyboardBuilder()

    status_icons = {
        "PENDING": "⏳",
        "APPROVED": "✅",
        "REJECTED": "❌",
        "ADJUSTED": "✂️",
    }

    for req in requests:
        icon = status_icons.get(req.status, "⏳")
        dept_name = CABINET_ROLES_DATA.get(CabinetRole(req.department_role), {}).get("title_fa", req.department_role) if req.department_role in [r.value for r in CabinetRole] else req.department_role
        btn_text = f"{icon} {dept_name}: {req.requested_amount:,.0f}$"
        builder.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"cab:budget:view:{req.id}", style=STYLE_MAIN)
        )

    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cab:budget:inbox:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"صفحه {page} از {max(1, total_pages)}", callback_data="noop")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cab:budget:inbox:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    if not is_treasury:
        builder.row(
            InlineKeyboardButton(text="➕ درخواست بودجه جدید", callback_data="cab:budget:req", style=STYLE_OK)
        )

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_budget_request_view_kb(
    req: CabinetBudgetRequest,
    is_treasury: bool,
) -> InlineKeyboardMarkup:
    """دکمه‌های بررسی درخواست بودجه توسط وزیر خزانه‌داری."""
    builder = InlineKeyboardBuilder()

    if is_treasury and req.status == "PENDING":
        builder.row(
            InlineKeyboardButton(text="✅ موافقت کامل و تخصیص", callback_data=f"cab:budget:act:{req.id}:approve", style=STYLE_OK),
            InlineKeyboardButton(text="✂️ تعدیل به ۵۰٪", callback_data=f"cab:budget:act:{req.id}:half", style=STYLE_MAIN),
        )
        builder.row(
            InlineKeyboardButton(text="❌ رد درخواست بودجه", callback_data=f"cab:budget:act:{req.id}:reject", style=STYLE_NO)
        )

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به کارتابل بودجه", callback_data="cab:budget:inbox:1", style=STYLE_MAIN)
    )
    return builder.as_markup()


# ============================================================
#  کیبوردهای ماموریت محرمانه (CabinetAgenda) و افشاگری (CabinetLeak)
# ============================================================


def cabinet_agenda_view_kb(agenda: CabinetAgenda | None) -> InlineKeyboardMarkup:
    """کیبورد ماموریت محرمانه ۲۴ ساعته مقام دولتی."""
    builder = InlineKeyboardBuilder()

    if agenda is None:
        builder.row(
            InlineKeyboardButton(text="🎯 دریافت ماموریت محرمانه روز", callback_data="cab:agenda:claim_new", style=STYLE_OK)
        )
    elif agenda.is_completed and not agenda.reward_claimed:
        builder.row(
            InlineKeyboardButton(text="🎁 دریافت پاداش (+15 سرمایه سیاسی)", callback_data="cab:agenda:claim_reward", style=STYLE_OK)
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🔄 به‌روزرسانی وضعیت ماموریت", callback_data="cab:agenda:view", style=STYLE_MAIN)
        )

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_leak_menu_kb() -> InlineKeyboardMarkup:
    """منوی افشاگری و درز اطلاعات به رسانه‌ها."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📰 درز دادن اطلاعات ناشناس (افشاگری)", callback_data="cab:leak:new", style=STYLE_NO)
    )
    builder.row(
        InlineKeyboardButton(text="📋 فهرست درزهای اخیر به رسانه‌ها", callback_data="cab:leak:list:1", style=STYLE_MAIN)
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
    )
    return builder.as_markup()


def cabinet_leaks_list_kb(leaks: list[CabinetLeak], page: int, total_pages: int) -> InlineKeyboardMarkup:
    """فهرست درزهای اطلاعاتی با صفحه‌بندی ۱۰تایی."""
    builder = InlineKeyboardBuilder()

    for lk in leaks:
        builder.row(
            InlineKeyboardButton(text=f"📰 {lk.headline[:35]}", callback_data=f"cab:leak:view:{lk.id}", style=STYLE_MAIN)
        )

    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cab:leak:list:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(text=f"صفحه {page} از {max(1, total_pages)}", callback_data="noop")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cab:leak:list:{page + 1}")
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🔙 منوی افشاگری", callback_data="cab:leak:menu", style=STYLE_MAIN),
        InlineKeyboardButton(text="🏛 میز کار", callback_data="cab:menu", style=STYLE_MAIN),
    )
    return builder.as_markup()
