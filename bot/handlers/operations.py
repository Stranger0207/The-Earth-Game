"""
هندلر ثبت عملیات نظامی (v1.10.6).

جریان کامل حمله:
    نوع عملیات → کشور هدف → نوع هدف → انتخاب قلم‌به‌قلم تجهیزات
    → (مسئولیت، برای عملیات مخفیانه) → شرح تاکتیکی → پیش‌نمایش → تأیید

نکته‌ی کلیدی: پیش از تأیید نهایی، نتیجه‌ی محاسباتی عملیات به بازیکن
پیش‌نمایش داده می‌شود (امکان‌سنجی، هزینه، برآورد رهگیری) تا کورکورانه
نیرو اعزام نکند.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..enums import (
    COVERT_OPERATIONS,
    OPEN_WAR_OPERATIONS,
    OPERATION_EMOJI,
    OPERATION_FA,
    TARGET_FA,
    OperationType,
    TargetType,
)
from ..keyboards.command_center import (
    asset_picker_kb,
    attack_types_kb,
    claim_responsibility_kb,
    operation_confirm_kb,
    operations_menu_kb,
    owner_review_kb,
    target_types_kb,
)
from ..keyboards.common import countries_kb
from ..loader import bot
from ..services import operation_service as op_service
from ..services.combat import CommittedAsset
from ..services.news_service import send_log
from ..states import OperationForm
from ..utils.numbers import fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, header
from .deps import NO_COUNTRY_TEXT, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="operations")


def _op_title(operation: OperationType) -> str:
    return f"{OPERATION_EMOJI[operation]} {OPERATION_FA[operation]}"


async def _selected_map(state: FSMContext) -> dict[str, int]:
    """تجهیزات انتخاب‌شده تا این لحظه."""
    data = await state.get_data()
    return dict(data.get("selected") or {})


async def _render_asset_picker(
    call: CallbackQuery, state: FSMContext, *, page: int | None = None
) -> None:
    """صفحه‌ی انتخاب تجهیزات را رندر می‌کند."""
    data = await state.get_data()
    assets = data.get("assets") or []
    selected = dict(data.get("selected") or {})
    current_page = data.get("page", 0) if page is None else page
    await state.update_data(page=current_page)

    operation = OperationType(data["operation_type"])
    total_units = sum(selected.values())

    lines = [
        header("انتخاب تجهیزات عملیات", "🪖"),
        "",
        f"عملیات: {_op_title(operation)}",
    ]
    if selected:
        lines.append(f"{DIVIDER}\n<b>نیروی انتخاب‌شده:</b>")
        for name, count in selected.items():
            lines.append(f"  ✅ {name} — {fa_number(count)}")
        lines.append(f"\n📦 مجموع: <b>{fa_number(total_units)}</b> واحد")
    else:
        lines.append("\nاز فهرست زیر تجهیزات موردنظر را انتخاب کنید.")

    lines.append(
        "\n<i>روی هر قلم بزنید تا تعدادش را وارد کنید. پس از پایان، «ادامه» را بزنید.</i>"
    )

    await safe_edit(
        call,
        "\n".join(lines),
        reply_markup=asset_picker_kb(assets, selected, page=current_page),
    )


# ============================================================
#  شروع: انتخاب نوع عملیات
# ============================================================
@router.callback_query(F.data == "op:attack")
async def cb_attack_menu(call: CallbackQuery, state: FSMContext) -> None:
    """منوی انتخاب نوع حمله‌ی علنی."""
    await call.answer()
    await state.clear()
    text = (
        header("حمله نظامی", "💥") + "\n\n"
        "نوع حمله را انتخاب کنید.\n\n"
        "⚠️ <b>توجه:</b> حملات علنی نیازمند <b>اعلام جنگ رسمی</b> پیشین هستند.\n"
        "🪖 حمله‌ی زمینی فقط علیه کشورهای نزدیک ممکن است.\n"
        "🚢 حمله‌ی دریایی نیازمند آب مشترک با هدف است."
    )
    await safe_edit(call, text, reply_markup=attack_types_kb())


@router.callback_query(F.data.startswith("op:new:"))
async def cb_start_operation(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع ثبت یک عملیات: بررسی مجوزها و انتخاب کشور هدف."""
    await call.answer()
    raw = call.data.split(":", 2)[2]
    try:
        operation = OperationType(raw)
    except ValueError:
        await call.answer("نوع عملیات نامعتبر است.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    # بررسی سقف عملیات و بحران رهبری پیش از شروع فرم
    try:
        await op_service.assert_can_operate(session, country)
    except op_service.OperationError as err:
        await safe_edit(call, str(err), reply_markup=operations_menu_kb())
        return

    # عملیات ترور و رهگیری جریان اختصاصی دارند (فعلاً در دست ساخت)
    if operation in (OperationType.ASSASSINATION, OperationType.INTERCEPTION):
        await safe_edit(
            call,
            f"{_op_title(operation)}\n\n"
            "🚧 این عملیات در مرحله‌ی بعدی همین آپدیت فعال می‌شود.",
            reply_markup=operations_menu_kb(),
        )
        return

    await state.clear()
    await state.update_data(operation_type=operation.value, selected={}, page=0)
    await state.set_state(OperationForm.choosing_target_country)

    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]

    back = "op:attack" if operation in OPEN_WAR_OPERATIONS else "cc:operations"
    await safe_edit(
        call,
        f"{_op_title(operation)}\n\n🎯 <b>کشور هدف را انتخاب کنید:</b>",
        reply_markup=countries_kb(others, prefix="op_target_country", columns=2, back_data=back),
    )


# ============================================================
#  انتخاب کشور هدف → نوع هدف
# ============================================================
@router.callback_query(
    OperationForm.choosing_target_country, F.data.startswith("op_target_country:")
)
async def cb_target_country(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت کشور هدف و نمایش وضعیت جغرافیایی + انتخاب نوع هدف."""
    await call.answer()
    target_id = int(call.data.split(":")[1])
    data = await state.get_data()
    operation = OperationType(data["operation_type"])

    country = await get_player_country(session, db_user)
    target = await countries_repo.get_country(session, target_id)
    if country is None or target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=operations_menu_kb())
        return

    # اعلام جنگ را همین‌جا بررسی کن تا بازیکن تا آخر فرم نرود و بعد رد شود
    try:
        await op_service.assert_war_declared(session, country, target, operation)
    except op_service.OperationError as err:
        await safe_edit(call, str(err), reply_markup=operations_menu_kb())
        return

    await state.update_data(target_country_id=target_id)
    await state.set_state(OperationForm.choosing_target_type)

    from ..services import geo_service as geo

    position = geo.describe_position(country.name_en, target.name_en)
    text = (
        f"{_op_title(operation)}\n\n"
        f"🎯 هدف: {target.flag} <b>{target.name_fa}</b>\n"
        f"🗺 موقعیت: {position}\n"
        f"{DIVIDER}\n"
        "<b>نوع هدف را مشخص کنید:</b>\n"
        "<i>(فقط اهداف سازگار با این نوع عملیات نمایش داده می‌شوند)</i>"
    )
    await safe_edit(call, text, reply_markup=target_types_kb(operation, "cc:operations"))


# ============================================================
#  انتخاب نوع هدف → انتخاب تجهیزات
# ============================================================
@router.callback_query(OperationForm.choosing_target_type, F.data.startswith("op_target:"))
async def cb_target_type(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت نوع هدف و نمایش فهرست تجهیزات قابل‌استفاده."""
    await call.answer()
    try:
        target_type = TargetType(call.data.split(":")[1])
    except ValueError:
        await call.answer("نوع هدف نامعتبر است.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    data = await state.get_data()
    operation = OperationType(data["operation_type"])

    assets = await op_service.available_assets(session, country.id, operation)
    if not assets:
        await safe_edit(
            call,
            f"⚠️ کشور شما تجهیزات مناسبی برای <b>{OPERATION_FA[operation]}</b> ندارد.\n\n"
            "<i>هر نوع عملیات فقط با شاخه‌ی تجهیزات متناسب خودش قابل اجراست.</i>",
            reply_markup=operations_menu_kb(),
        )
        return

    await state.update_data(target_type=target_type.value, assets=assets, selected={}, page=0)
    await state.set_state(OperationForm.selecting_assets)
    await _render_asset_picker(call, state, page=0)


# ============================================================
#  انتخاب قلم‌به‌قلم تجهیزات
# ============================================================
@router.callback_query(OperationForm.selecting_assets, F.data.startswith("op_page:"))
async def cb_asset_page(call: CallbackQuery, state: FSMContext) -> None:
    """ناوبری صفحه‌های فهرست تجهیزات."""
    await call.answer()
    page = int(call.data.split(":")[1])
    await _render_asset_picker(call, state, page=page)


@router.callback_query(OperationForm.selecting_assets, F.data == "op_assets_clear")
async def cb_assets_clear(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌کردن همه‌ی انتخاب‌ها."""
    await call.answer("انتخاب‌ها پاک شد")
    await state.update_data(selected={})
    await _render_asset_picker(call, state)


@router.callback_query(OperationForm.selecting_assets, F.data.startswith("op_asset:"))
async def cb_pick_asset(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب یک قلم تجهیزات و درخواست تعداد."""
    await call.answer()
    index = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets") or []
    if index >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = assets[index]
    await state.update_data(pending_index=index)
    await state.set_state(OperationForm.entering_asset_count)

    selected = dict(data.get("selected") or {})
    current = selected.get(asset["name"], 0)
    hint = f"\n\n<i>انتخاب فعلی: {fa_number(current)}</i>" if current else ""

    await safe_edit(
        call,
        f"🪖 <b>{asset['name']}</b>\n"
        f"📦 موجودی: {fa_number(asset['count'])} {asset['unit']}\n"
        f"{DIVIDER}\n"
        "چه تعداد از این قلم را اعزام می‌کنید؟\n"
        "<i>عدد را بفرستید. برای حذف این قلم، صفر بفرستید.</i>"
        + hint,
    )


@router.message(OperationForm.entering_asset_count, F.text)
async def msg_asset_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد یک قلم و بازگشت به فهرست تجهیزات."""
    data = await state.get_data()
    assets = data.get("assets") or []
    index = data.get("pending_index")

    if index is None or index >= len(assets):
        await state.set_state(OperationForm.selecting_assets)
        await message.answer("خطا در انتخاب قلم. دوباره تلاش کنید.")
        return

    asset = assets[index]
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("⚠️ عدد معتبر وارد کنید.")
        return

    count = int(amount)
    if count > asset["count"]:
        await message.answer(
            f"⚠️ موجودی کافی نیست. حداکثر {fa_number(asset['count'])} {asset['unit']} دارید."
        )
        return

    selected = dict(data.get("selected") or {})
    if count == 0:
        selected.pop(asset["name"], None)
    else:
        selected[asset["name"]] = count

    await state.update_data(selected=selected, pending_index=None)
    await state.set_state(OperationForm.selecting_assets)

    # نمایش دوباره‌ی فهرست (پیام تازه، چون از سمت Message آمده‌ایم)
    operation = OperationType(data["operation_type"])
    total = sum(selected.values())
    lines = [header("انتخاب تجهیزات عملیات", "🪖"), "", f"عملیات: {_op_title(operation)}"]
    if selected:
        lines.append(f"{DIVIDER}\n<b>نیروی انتخاب‌شده:</b>")
        for name, cnt in selected.items():
            lines.append(f"  ✅ {name} — {fa_number(cnt)}")
        lines.append(f"\n📦 مجموع: <b>{fa_number(total)}</b> واحد")
    else:
        lines.append("\nهنوز قلمی انتخاب نشده است.")

    await message.answer(
        "\n".join(lines),
        reply_markup=asset_picker_kb(assets, selected, page=data.get("page", 0)),
    )


# ============================================================
#  پایان انتخاب تجهیزات → مسئولیت / شرح تاکتیکی
# ============================================================
@router.callback_query(OperationForm.selecting_assets, F.data == "op_assets_done")
async def cb_assets_done(call: CallbackQuery, state: FSMContext) -> None:
    """پایان انتخاب تجهیزات؛ برای عملیات مخفیانه سؤال مسئولیت، وگرنه شرح تاکتیکی."""
    await call.answer()
    selected = await _selected_map(state)
    if not selected:
        await call.answer("ابتدا حداقل یک قلم تجهیزات انتخاب کنید.", show_alert=True)
        return

    data = await state.get_data()
    operation = OperationType(data["operation_type"])

    if operation in COVERT_OPERATIONS:
        await state.set_state(OperationForm.choosing_claim)
        await safe_edit(
            call,
            header("مسئولیت عملیات", "🕵️") + "\n\n"
            "آیا کشور شما رسماً مسئولیت این عملیات را می‌پذیرد؟\n\n"
            "✋ <b>پذیرش مسئولیت:</b> اثر بازدارندگی و اعتبار نظامی، ولی تنش دیپلماتیک آشکار.\n"
            "🤫 <b>عملیات ناشناس:</b> بدون هزینه‌ی دیپلماتیک — مگر آنکه افشا شود.",
            reply_markup=claim_responsibility_kb(),
        )
        return

    await state.update_data(claim_responsibility=True)
    await state.set_state(OperationForm.entering_tactical_note)
    await safe_edit(
        call,
        header("شرح تاکتیکی", "📝") + "\n\n"
        "نقشه‌ی عملیات را کوتاه توضیح دهید (اختیاری ولی توصیه‌شده).\n\n"
        "<i>مثال: «حمله‌ی شبانه از مسیر دریا با پشتیبانی پهپادی روی پایگاه ساحلی»</i>\n\n"
        "برای رد کردن این مرحله، یک خط تیره (-) بفرستید.",
    )


@router.callback_query(OperationForm.choosing_claim, F.data.startswith("op_claim:"))
async def cb_claim(call: CallbackQuery, state: FSMContext) -> None:
    """ثبت تصمیم پذیرش مسئولیت و درخواست شرح تاکتیکی."""
    await call.answer()
    claim = call.data.split(":")[1] == "yes"
    await state.update_data(claim_responsibility=claim)
    await state.set_state(OperationForm.entering_tactical_note)

    label = "پذیرش رسمی مسئولیت" if claim else "عملیات ناشناس"
    await safe_edit(
        call,
        header("شرح تاکتیکی", "📝") + f"\n\n🕵️ حالت: <b>{label}</b>\n\n"
        "شرح عملیات را بنویسید.\n"
        "<i>مثال: «نفوذ عوامل به تأسیسات و کارگذاری خرابکاری در سیستم برق»</i>\n\n"
        "برای رد کردن این مرحله، یک خط تیره (-) بفرستید.",
    )


# ============================================================
#  شرح تاکتیکی → پیش‌نمایش نتیجه
# ============================================================
@router.message(OperationForm.entering_tactical_note, F.text)
async def msg_tactical_note(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت شرح تاکتیکی و نمایش پیش‌نمایش محاسباتی عملیات."""
    note = message.text.strip()
    if note == "-":
        note = ""
    await state.update_data(tactical_note=note)

    data = await state.get_data()
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return

    target = await countries_repo.get_country(session, data["target_country_id"])
    if target is None:
        await state.clear()
        await message.answer("کشور هدف یافت نشد.")
        return

    operation = OperationType(data["operation_type"])
    target_type = TargetType(data["target_type"])
    committed = _build_committed(data)

    result = await op_service.preview_operation(
        session, country, target, operation, target_type, committed
    )

    if not result.feasible:
        await state.clear()
        await message.answer(
            f"⛔️ <b>این عملیات قابل اجرا نیست</b>\n\n{result.reject_reason}",
            reply_markup=operations_menu_kb(),
        )
        return

    await state.set_state(OperationForm.confirming)
    total_units = sum(a.count for a in committed)

    lines = [
        header("پیش‌نمایش عملیات", "📋"),
        "",
        f"{_op_title(operation)} علیه {target.flag} <b>{target.name_fa}</b>",
        f"🎯 هدف: {TARGET_FA[target_type]}",
        f"📦 نیروی اعزامی: {fa_number(total_units)} واحد",
        DIVIDER,
        "<b>برآورد ستاد اطلاعات:</b>",
        f"🛡 رهگیری تخمینی پدافند دشمن: <b>{fa_number(result.intercept_pct, 1)}٪</b>",
        f"💥 خسارت تخمینی به هدف: <b>{fa_number(result.infra_damage_pct, 1)}٪</b>",
        f"🏆 نتیجه‌ی محتمل: {result.outcome}",
    ]
    if result.civilian_casualties:
        lines.append(
            f"⚠️ برآورد تلفات غیرنظامی: <b>{fa_number(result.civilian_casualties)}</b> نفر"
        )
    lines += [
        DIVIDER,
        "<b>هزینه‌ها:</b>",
        f"⛽️ سوخت: {fa_number(result.fuel_cost, 2)} میلیون بشکه",
        f"💰 بودجه: {fa_number(result.budget_cost / 1e9, 2)} میلیارد دلار",
    ]
    if result.attacker_losses:
        lost = sum(i["count"] for i in result.attacker_losses)
        lines.append(f"💀 برآورد تلفات نیروی خودی: {fa_number(lost)} واحد")

    lines.append(
        "\n<i>این عملیات پس از تأیید مدیریت بازی اجرا و در فازهای خبری منتشر می‌شود.</i>"
    )

    await message.answer("\n".join(lines), reply_markup=operation_confirm_kb())


def _build_committed(data: dict) -> list[CommittedAsset]:
    """تجهیزات انتخاب‌شده را به مدل موتور نبرد تبدیل می‌کند."""
    assets = {a["name"]: a for a in (data.get("assets") or [])}
    committed: list[CommittedAsset] = []
    for name, count in (data.get("selected") or {}).items():
        meta = assets.get(name, {})
        committed.append(
            CommittedAsset(
                name=name,
                count=int(count),
                branch=meta.get("branch", ""),
                category=meta.get("category", ""),
                unit=meta.get("unit", "عدد"),
            )
        )
    return committed


# ============================================================
#  تأیید نهایی → ثبت و ارسال به مالک
# ============================================================
@router.callback_query(OperationForm.confirming, F.data == "op_confirm")
async def cb_confirm_operation(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """ثبت نهایی عملیات و ارسال برای تأیید مالک بازی."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    target = await countries_repo.get_country(session, data["target_country_id"])
    if target is None:
        await safe_edit(call, "کشور هدف یافت نشد.", reply_markup=operations_menu_kb())
        return

    operation = OperationType(data["operation_type"])
    target_type = TargetType(data["target_type"])
    committed = _build_committed(data)

    try:
        row = await op_service.create_operation(
            session,
            country,
            target,
            operation,
            target_type,
            committed,
            tactical_note=data.get("tactical_note", ""),
            claim_responsibility=bool(data.get("claim_responsibility", True)),
            target_label=TARGET_FA[target_type],
        )
    except op_service.OperationError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=operations_menu_kb())
        return

    await safe_edit(
        call,
        "✅ <b>عملیات ثبت شد</b>\n\n"
        f"{_op_title(operation)} علیه {target.flag} {target.name_fa}\n\n"
        "درخواست برای تأیید نهایی به فرماندهی کل (مدیریت بازی) ارسال شد.\n"
        "پس از تأیید، عملیات اجرا و اخبار آن منتشر می‌شود.",
        reply_markup=operations_menu_kb(),
    )

    # ارسال به گروه لاگ برای تأیید مالک
    claim_text = "بله" if row.claim_responsibility else "خیر (ناشناس)"
    assets_text = "\n".join(
        f"  • {a.name} — {fa_number(a.count)} {a.unit}" for a in committed
    )
    await send_log(
        bot,
        "⚔️ <b>درخواست عملیات نظامی — نیازمند تأیید</b>\n\n"
        f"🔴 مهاجم: {country.flag} {country.name_fa}\n"
        f"🔵 مدافع: {target.flag} {target.name_fa}\n"
        f"🏷 نوع: {OPERATION_FA[operation]}\n"
        f"🎯 هدف: {TARGET_FA[target_type]}\n"
        f"🕵️ پذیرش مسئولیت: {claim_text}\n"
        f"📊 شدت محاسبه‌شده: {fa_number(row.intensity)}/۱۰\n"
        f"🛡 رهگیری تخمینی: {fa_number(row.intercept_pct, 1)}٪\n"
        f"💥 خسارت تخمینی: {fa_number(row.infra_damage_pct, 1)}٪\n"
        + (f"⚠️ تلفات غیرنظامی: {fa_number(row.civilian_casualties)}\n" if row.civilian_casualties else "")
        + f"⛽️ سوخت: {fa_number(row.fuel_cost, 2)} م.بشکه\n"
        f"{DIVIDER}\n"
        f"<b>نیروی اعزامی:</b>\n{assets_text}\n"
        + (f"\n📝 <b>شرح تاکتیکی:</b>\n{row.tactical_note}" if row.tactical_note else ""),
        reply_markup=owner_review_kb(row.id),
    )


# ============================================================
#  تأیید / رد توسط مالک بازی
# ============================================================
@router.callback_query(F.data.startswith("op_approve:"))
async def cb_owner_approve(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید عملیات توسط مالک (کلیک از گروه لاگ)."""
    operation_id = int(call.data.split(":")[1])
    try:
        row = await op_service.approve_operation(session, operation_id)
    except op_service.OperationError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("عملیات تأیید و آغاز شد ✅")
    try:
        await call.message.edit_text(
            call.message.html_text
            + f"\n\n✅ <b>تأیید شد</b> — عملیات آغاز شد "
            f"({fa_number(row.total_phases)} فاز خبری)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not annotate approval message: %s", exc)

    # اطلاع به مهاجم
    attacker = await countries_repo.get_country(session, row.attacker_country_id)
    if attacker and attacker.owner_user_id:
        try:
            await bot.send_message(
                attacker.owner_user_id,
                "✅ <b>عملیات شما تأیید شد و در حال اجراست.</b>\n"
                f"اخبار عملیات در {fa_number(row.total_phases)} مرحله منتشر می‌شود.",
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("op_reject:"))
async def cb_owner_reject(call: CallbackQuery, session: AsyncSession) -> None:
    """رد عملیات توسط مالک."""
    operation_id = int(call.data.split(":")[1])
    try:
        row = await op_service.reject_operation(session, operation_id)
    except op_service.OperationError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("عملیات رد شد ❌")
    try:
        await call.message.edit_text(call.message.html_text + "\n\n❌ <b>ردشده توسط مدیریت</b>")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not annotate rejection message: %s", exc)

    attacker = await countries_repo.get_country(session, row.attacker_country_id)
    if attacker and attacker.owner_user_id:
        try:
            await bot.send_message(
                attacker.owner_user_id,
                "❌ <b>درخواست عملیات شما رد شد.</b>\n"
                "برای اطلاعات بیشتر با مدیریت بازی در تماس باشید.",
            )
        except Exception:  # noqa: BLE001
            pass
