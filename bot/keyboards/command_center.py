"""
کیبوردهای ستاد فرماندهی کل (v1.10.6).

منوی نظامی از یک فهرست ساده به یک «ستاد فرماندهی» چندبخشی تبدیل شده تا
بازیکن حس کنترل واقعی ارتش را داشته باشد.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..enums import (
    OPERATION_EMOJI,
    OPERATION_FA,
    PATROL_EMOJI,
    PATROL_FA,
    TARGET_EMOJI,
    TARGET_FA,
    DrillType,
    OperationType,
    PatrolType,
    TargetType,
)
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK


def command_center_kb(is_vip: bool = False) -> InlineKeyboardMarkup:
    """منوی اصلی ستاد فرماندهی کل."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ عملیات‌ها", callback_data="cc:operations", style=STYLE_NO)
    builder.button(text="📊 وضعیت ارتش", callback_data="cc:status", style=STYLE_MAIN)
    builder.button(text="🛡 دفاع و پدافند", callback_data="cc:defense", style=STYLE_MAIN)
    builder.button(text="🎯 اطلاعات و شناسایی", callback_data="cc:intel", style=STYLE_MAIN)
    builder.button(text="🎖 فرماندهان", callback_data="cc:commanders", style=STYLE_MAIN)
    builder.button(text="📜 تاریخچه عملیات", callback_data="cc:history", style=STYLE_MAIN)
    builder.button(text="🏗 پایگاه‌های نظامی", callback_data="mil:base", style=STYLE_MAIN)
    builder.button(text="🏭 صنایع نظامی", callback_data="cc:industry", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="menu:main", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def operations_menu_kb() -> InlineKeyboardMarkup:
    """
    منوی انواع عملیات.

    (v2.1) «حمله نظامی» و «خرابکاری» از داخل ربات غیرفعال شده‌اند؛ دکمه‌ها
    نگه داشته شده‌اند تا بازیکن پیام راهنمای ارسال رول به پشتیبانی را ببیند.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔒 حمله نظامی", callback_data="op:disabled:attack")
    builder.button(text="🔒 خرابکاری", callback_data="op:disabled:sabotage")
    builder.button(text="🕵️ جاسوسی و ترور", callback_data="op:covert", style=STYLE_NO)
    builder.button(text="⚓ رهگیری محموله", callback_data="op:intercept", style=STYLE_NO)
    builder.button(text="🛩 گشت دفاعی", callback_data="op:patrol", style=STYLE_OK)
    builder.button(text="🎪 رزمایش", callback_data="op:drill", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def attack_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع حمله‌ی علنی (نیازمند اعلام جنگ)."""
    builder = InlineKeyboardBuilder()
    for op in (
        OperationType.GROUND_ASSAULT,
        OperationType.AIR_STRIKE,
        OperationType.NAVAL_STRIKE,
    ):
        builder.button(
            text=f"{OPERATION_EMOJI[op]} {OPERATION_FA[op]}",
            callback_data=f"op:new:{op.value}",
            style=STYLE_NO,
        )
    builder.button(text="🔙 بازگشت", callback_data="cc:operations", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def target_types_kb(operation: OperationType, back_data: str) -> InlineKeyboardMarkup:
    """
    انتخاب نوع هدف — فقط اهدافی که با این نوع عملیات سازگارند نمایش داده می‌شوند
    (تا بازیکن ترکیب نامعتبر انتخاب نکند و بعد رد شود).
    """
    from ..constants import TARGET_ALLOWED_OPERATIONS

    builder = InlineKeyboardBuilder()
    for target in TargetType:
        if target is TargetType.SHIPMENT:
            continue  # محموله مسیر اختصاصی خودش را دارد (رهگیری)
        allowed = TARGET_ALLOWED_OPERATIONS.get(target)
        if allowed is not None and operation not in allowed:
            continue
        builder.button(
            text=f"{TARGET_EMOJI[target]} {TARGET_FA[target]}",
            callback_data=f"op_target:{target.value}",
            style=STYLE_NO,
        )
    builder.button(text="🔙 بازگشت", callback_data=back_data, style=STYLE_MAIN)
    builder.adjust(2)
    return builder.as_markup()


def asset_picker_kb(
    assets: list[dict],
    selected: dict[str, int],
    *,
    page: int = 0,
    per_page: int = 8,
) -> InlineKeyboardMarkup:
    """
    انتخاب قلم‌به‌قلم تجهیزات از موجودی واقعی کشور.

    assets: [{"name","count","unit","category","branch"}]
    selected: {نام قلم: تعداد انتخاب‌شده}

    قلم‌های انتخاب‌شده با ✅ و تعداد نمایش داده می‌شوند.
    """
    builder = InlineKeyboardBuilder()
    start = page * per_page
    chunk = assets[start : start + per_page]

    for idx, asset in enumerate(chunk, start=start):
        name = asset["name"]
        picked = selected.get(name, 0)
        mark = f"✅ {picked}× " if picked else ""
        label = f"{mark}{name} ({asset['count']})"
        builder.button(
            text=label[:60],
            callback_data=f"op_asset:{idx}",
            style=STYLE_OK if picked else None,
        )
    builder.adjust(1)

    # ناوبری صفحه‌ها
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="◀️ قبلی", callback_data=f"op_page:{page - 1}", style=STYLE_MAIN)
        )
    if start + per_page < len(assets):
        nav.append(
            InlineKeyboardButton(text="بعدی ▶️", callback_data=f"op_page:{page + 1}", style=STYLE_MAIN)
        )
    if nav:
        builder.row(*nav)

    if selected:
        builder.row(
            InlineKeyboardButton(text="➡️ ادامه", callback_data="op_assets_done", style=STYLE_OK)
        )
        builder.row(
            InlineKeyboardButton(text="🗑 پاک‌کردن انتخاب", callback_data="op_assets_clear", style=STYLE_NO)
        )
    builder.row(
        InlineKeyboardButton(text="❌ انصراف", callback_data="cc:operations", style=STYLE_NO)
    )
    return builder.as_markup()


def claim_responsibility_kb() -> InlineKeyboardMarkup:
    """عملیات مخفیانه: پذیرش مسئولیت یا ماندن در سایه."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✋ پذیرش رسمی مسئولیت", callback_data="op_claim:yes", style=STYLE_NO
    )
    builder.button(
        text="🤫 عملیات ناشناس (بدون مسئولیت)", callback_data="op_claim:no", style=STYLE_OK
    )
    builder.button(text="🔙 بازگشت", callback_data="cc:operations", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def patrol_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع گشت دفاعی."""
    builder = InlineKeyboardBuilder()
    for ptype in PatrolType:
        builder.button(
            text=f"{PATROL_EMOJI[ptype]} {PATROL_FA[ptype]}",
            callback_data=f"patrol_type:{ptype.value}",
            style=STYLE_OK,
        )
    builder.button(text="📋 گشت‌های فعال", callback_data="patrol:list", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="cc:operations", style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def drill_types_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع رزمایش."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎪 رزمایش تکی", callback_data=f"drill_type:{DrillType.SOLO.value}", style=STYLE_OK)
    builder.button(text="🤝 رزمایش مشترک", callback_data=f"drill_type:{DrillType.JOINT.value}", style=STYLE_OK)
    builder.button(text="📋 رزمایش‌های جاری", callback_data="drill:list", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت", callback_data="cc:operations", style=STYLE_MAIN)
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def defense_menu_kb() -> InlineKeyboardMarkup:
    """منوی دفاع و پدافند."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛡 آرایش پدافندی", callback_data="cc:def_layout", style=STYLE_MAIN)
    builder.button(text="🛩 گشت‌های فعال", callback_data="patrol:list", style=STYLE_MAIN)
    builder.button(text="⚠️ گزارش تهدید", callback_data="cc:threats", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def intel_menu_kb() -> InlineKeyboardMarkup:
    """منوی اطلاعات و شناسایی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📡 ماهواره فضایی", callback_data="mil:sat", style=STYLE_MAIN)
    builder.button(text="⚠️ گزارش تهدید", callback_data="cc:threats", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 1)
    return builder.as_markup()


def industry_menu_kb() -> InlineKeyboardMarkup:
    """منوی صنایع نظامی (اتصال به سیستم‌های موجود)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏭 کارخانه نظامی", callback_data="mil:factory", style=STYLE_MAIN)
    builder.button(text="💰 فروش تجهیزات", callback_data="mil:sell", style=STYLE_OK)
    builder.button(text="🪖 استقرار نیرو", callback_data="mil:deploy", style=STYLE_MAIN)
    builder.button(text="☢️ تأسیسات هسته‌ای", callback_data="mil:nuclear", style=STYLE_NO)
    builder.button(text="🔙 بازگشت", callback_data="menu:military", style=STYLE_MAIN)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def operation_confirm_kb() -> InlineKeyboardMarkup:
    """تأیید نهایی ثبت عملیات."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ثبت و ارسال به فرماندهی", callback_data="op_confirm", style=STYLE_OK)
    builder.button(text="❌ انصراف", callback_data="cc:operations", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def owner_review_kb(operation_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های تأیید/رد عملیات برای مالک بازی (در گروه لاگ)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ تأیید و شروع عملیات", callback_data=f"op_approve:{operation_id}", style=STYLE_OK
    )
    builder.button(text="❌ رد عملیات", callback_data=f"op_reject:{operation_id}", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()
