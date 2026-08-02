"""
هندلر رهگیری محموله و تخصیص اسکورت (v1.10.7).

دو روی یک سکه:
- **رهگیری:** کشوری که محموله از قلمروش عبور می‌کند می‌تواند آن را متوقف کند
- **اسکورت:** فروشنده می‌تواند نیروی محافظ بفرستد تا جلوی رهگیری را بگیرد

قاعده: محموله‌ی بی‌محافظ راحت رهگیری می‌شود؛ محموله‌ی اسکورت‌دار فقط با
نیروی ۳۵٪ قوی‌تر از اسکورت. نیروی ناکافی دفع می‌شود و تلفات سنگین می‌دهد.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import ESCORT_MAX_UNITS
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import trade as trade_repo
from ..keyboards.command_center import asset_picker_kb, operations_menu_kb
from ..keyboards.covert import confirm_kb, shipments_kb
from ..loader import bot
from ..services import escort_service, interception_service
from ..services import operation_service as op_service
from ..services.combat import CommittedAsset
from ..services.news_service import send_log
from ..states import EscortForm, InterceptionForm
from ..utils.numbers import fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import DIVIDER, header
from .deps import NO_COUNTRY_TEXT, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="interception")


def _summary(selected: dict[str, int]) -> str:
    """خلاصه‌ی تجهیزات انتخاب‌شده."""
    if not selected:
        return "هنوز تجهیزاتی انتخاب نشده است."
    lines = [f"  ✅ {name} — {fa_number(count)}" for name, count in selected.items()]
    lines.append(f"\n📦 مجموع: <b>{fa_number(sum(selected.values()))}</b> واحد")
    return "\n".join(lines)


def _build_committed(data: dict) -> list[CommittedAsset]:
    """تبدیل انتخاب بازیکن به مدل موتور نبرد."""
    meta = {a["name"]: a for a in (data.get("assets") or [])}
    return [
        CommittedAsset(
            name=name,
            count=int(count),
            branch=meta.get(name, {}).get("branch", ""),
            category=meta.get(name, {}).get("category", ""),
            unit=meta.get(name, {}).get("unit", "عدد"),
        )
        for name, count in (data.get("selected") or {}).items()
    ]


# ============================================================
#  ⚓ رهگیری محموله
# ============================================================
@router.callback_query(F.data == "op:intercept")
async def cb_intercept_start(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """فهرست محموله‌های قابل رهگیری."""
    await call.answer()
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    try:
        await op_service.assert_can_operate(session, country)
    except op_service.OperationError as err:
        await safe_edit(call, str(err), reply_markup=operations_menu_kb())
        return

    shipments = await interception_service.interceptable_shipments(session, country)

    if not shipments:
        await safe_edit(
            call,
            header("رهگیری محموله", "⚓") + "\n\n"
            "در حال حاضر هیچ محموله‌ای از قلمرو شما عبور نمی‌کند.\n\n"
            "<i>فقط محموله‌هایی قابل رهگیری‌اند که مسیرشان از خاک یا آب "
            "کشور شما بگذرد. محموله‌ی خودتان قابل رهگیری نیست.</i>",
            reply_markup=operations_menu_kb(),
        )
        return

    await state.set_state(InterceptionForm.choosing_shipment)

    lines = [
        header("رهگیری محموله", "⚓"),
        "",
        f"🚢 محموله‌های در حال عبور از قلمرو شما: <b>{fa_number(len(shipments))}</b>",
        DIVIDER,
        "🟢 <b>بدون اسکورت</b> — رهگیری آسان، بدون نیاز به نیرو",
        "🟠 <b>اسکورت‌دار</b> — نیاز به نیروی قوی‌تر از محافظان",
        "",
        "<i>محموله‌ی موردنظر را انتخاب کنید:</i>",
    ]
    await safe_edit(
        call, "\n".join(lines), reply_markup=shipments_kb(shipments, "cc:operations")
    )


@router.callback_query(InterceptionForm.choosing_shipment, F.data.startswith("intc_pick:"))
async def cb_intercept_pick(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """انتخاب محموله: بی‌اسکورت → تأیید مستقیم، اسکورت‌دار → انتخاب نیرو."""
    await call.answer()
    sale_id = int(call.data.split(":")[1])

    country = await get_player_country(session, db_user)
    sale = await trade_repo.get_sale(session, sale_id)
    if country is None or sale is None:
        await safe_edit(call, "محموله یافت نشد.", reply_markup=operations_menu_kb())
        return

    seller = await countries_repo.get_country(session, sale.seller_country)
    buyer = await countries_repo.get_country(session, sale.buyer_country)
    escort_power = float(getattr(sale, "escort_power", 0.0) or 0.0)
    needed = interception_service.required_power(escort_power)

    await state.update_data(
        sale_id=sale_id, escort_power=escort_power, required_power=needed, selected={}, page=0
    )

    base = (
        f"🚢 محموله: {seller.flag} {seller.name_fa} ← {buyer.flag} {buyer.name_fa}\n"
        f"📦 محتوا: {fa_number(sale.amount)} واحد\n"
        f"🛡 وضعیت: {interception_service.escort_label(escort_power)}"
    )

    # ---------- محموله‌ی بدون اسکورت: نیازی به نیرو نیست ----------
    if escort_power <= 0:
        await state.set_state(InterceptionForm.confirming)
        await safe_edit(
            call,
            header("تأیید رهگیری", "⚓") + f"\n\n{base}\n"
            f"{DIVIDER}\n"
            "✅ این محموله محافظ ندارد و با نیروهای گشت قابل توقیف است.\n\n"
            "⚠️ <i>رهگیری بحران دیپلماتیک با فروشنده و خریدار ایجاد می‌کند.</i>",
            reply_markup=confirm_kb("intc_confirm", "op:intercept"),
        )
        return

    # ---------- محموله‌ی اسکورت‌دار: انتخاب نیرو ----------
    escort_items = interception_service.parse_escort(sale)
    escort_text = "، ".join(
        f"{i.get('name')} ({fa_number(i.get('count', 0))})" for i in escort_items[:4]
    ) or "نامشخص"

    assets = await escort_service.available_escort_assets(session, country.id)
    if not assets:
        await safe_edit(
            call,
            f"{base}\n\n⚠️ شما تجهیزات مناسبی برای رهگیری ندارید "
            "(نیروی دریایی، هوایی یا پدافندی لازم است).",
            reply_markup=operations_menu_kb(),
        )
        return

    await state.update_data(assets=assets)
    await state.set_state(InterceptionForm.selecting_assets)

    await safe_edit(
        call,
        header("انتخاب نیروی رهگیر", "⚓") + f"\n\n{base}\n"
        f"🛡 محافظان: {escort_text}\n"
        f"{DIVIDER}\n"
        f"⚔️ حداقل قدرت لازم: <b>{fa_number(needed)}</b>\n\n"
        "نیرویی که برای شکستن اسکورت اعزام می‌کنید را انتخاب کنید.\n"
        "<i>نیروی ناکافی دفع می‌شود و تلفات سنگین می‌دهید.</i>",
        reply_markup=asset_picker_kb(assets, {}, page=0),
    )


@router.callback_query(InterceptionForm.selecting_assets, F.data.startswith("op_page:"))
async def cb_intercept_page(call: CallbackQuery, state: FSMContext) -> None:
    """ناوبری صفحه‌های تجهیزات."""
    await call.answer()
    page = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)
    await safe_edit(
        call,
        header("انتخاب نیروی رهگیر", "⚓") + "\n\n" + _summary(dict(data.get("selected") or {})),
        reply_markup=asset_picker_kb(
            data.get("assets") or [], dict(data.get("selected") or {}), page=page
        ),
    )


@router.callback_query(InterceptionForm.selecting_assets, F.data == "op_assets_clear")
async def cb_intercept_clear(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌کردن انتخاب."""
    await call.answer("انتخاب‌ها پاک شد")
    data = await state.get_data()
    await state.update_data(selected={})
    await safe_edit(
        call,
        header("انتخاب نیروی رهگیر", "⚓") + "\n\nهنوز تجهیزاتی انتخاب نشده است.",
        reply_markup=asset_picker_kb(data.get("assets") or [], {}, page=data.get("page", 0)),
    )


@router.callback_query(InterceptionForm.selecting_assets, F.data.startswith("op_asset:"))
async def cb_intercept_asset(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب یک قلم و درخواست تعداد."""
    await call.answer()
    index = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets") or []
    if index >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = assets[index]
    await state.update_data(pending_index=index)
    await state.set_state(InterceptionForm.entering_asset_count)
    await safe_edit(
        call,
        f"⚓ <b>{asset['name']}</b>\n"
        f"📦 موجودی: {fa_number(asset['count'])} {asset['unit']}\n\n"
        "چه تعداد اعزام می‌کنید؟\n"
        "<i>برای حذف، صفر بفرستید.</i>",
    )


@router.message(InterceptionForm.entering_asset_count, F.text)
async def msg_intercept_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد و نمایش قدرت فعلی در برابر اسکورت."""
    data = await state.get_data()
    assets = data.get("assets") or []
    index = data.get("pending_index")

    if index is None or index >= len(assets):
        await state.set_state(InterceptionForm.selecting_assets)
        await message.answer("خطا در انتخاب. دوباره تلاش کنید.")
        return

    asset = assets[index]
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("⚠️ عدد معتبر وارد کنید.")
        return

    count = int(amount)
    if count > asset["count"]:
        await message.answer(f"⚠️ حداکثر {fa_number(asset['count'])} {asset['unit']} دارید.")
        return

    selected = dict(data.get("selected") or {})
    if count == 0:
        selected.pop(asset["name"], None)
    else:
        selected[asset["name"]] = count

    await state.update_data(selected=selected, pending_index=None)
    await state.set_state(InterceptionForm.selecting_assets)

    # نمایش قدرت فعلی در برابر آستانه — بازخورد زنده به بازیکن
    fresh = await state.get_data()
    power = escort_service.compute_escort_power(
        [
            {**assets_meta, "count": cnt}
            for name, cnt in selected.items()
            if (assets_meta := next((a for a in assets if a["name"] == name), None))
        ]
    )
    needed = float(fresh.get("required_power", 0.0))
    verdict = "✅ کافی" if power >= needed else "⚠️ ناکافی"

    await message.answer(
        header("انتخاب نیروی رهگیر", "⚓") + "\n\n"
        + _summary(selected)
        + f"\n\n⚔️ قدرت شما: <b>{fa_number(power)}</b>\n"
        f"🛡 حداقل لازم: {fa_number(needed)} — {verdict}",
        reply_markup=asset_picker_kb(assets, selected, page=fresh.get("page", 0)),
    )


@router.callback_query(InterceptionForm.selecting_assets, F.data == "op_assets_done")
async def cb_intercept_done(call: CallbackQuery, state: FSMContext) -> None:
    """تأیید نهایی رهگیری اسکورت‌دار."""
    await call.answer()
    data = await state.get_data()
    selected = dict(data.get("selected") or {})
    if not selected:
        await call.answer("ابتدا نیرو انتخاب کنید.", show_alert=True)
        return

    committed = _build_committed(data)
    from ..services.combat import strike_power

    power = strike_power(committed).total
    needed = float(data.get("required_power", 0.0))
    escort_power = float(data.get("escort_power", 0.0))

    warning = ""
    if power < needed:
        warning = (
            "\n\n⚠️ <b>هشدار:</b> نیروی شما از آستانه کمتر است. "
            "احتمال دفع شدن و تلفات سنگین بالاست."
        )

    await state.set_state(InterceptionForm.confirming)
    await safe_edit(
        call,
        header("تأیید رهگیری", "⚓") + "\n\n"
        f"⚔️ قدرت نیروی شما: <b>{fa_number(power)}</b>\n"
        f"🛡 قدرت اسکورت: {fa_number(escort_power)}\n"
        f"📊 حداقل لازم: {fa_number(needed)}\n"
        f"{DIVIDER}\n"
        + _summary(selected)
        + warning
        + "\n\n<i>رهگیری بحران دیپلماتیک ایجاد می‌کند.</i>",
        reply_markup=confirm_kb("intc_confirm", "op:intercept"),
    )


@router.callback_query(InterceptionForm.confirming, F.data == "intc_confirm")
async def cb_intercept_confirm(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """اجرای رهگیری و انتشار نتیجه."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    country = await get_player_country(session, db_user)
    sale = await trade_repo.get_sale(session, data.get("sale_id", 0))
    if country is None or sale is None:
        await safe_edit(call, "محموله یافت نشد.", reply_markup=operations_menu_kb())
        return

    committed = _build_committed(data)

    try:
        result = await interception_service.resolve_interception(
            session, country, sale, committed=committed
        )
    except interception_service.InterceptionError as err:
        await safe_edit(call, f"⛔️ {err}", reply_markup=operations_menu_kb())
        return

    await session.commit()

    # ---------- گزارش به رهگیرنده ----------
    def _losses(items: list[dict]) -> str:
        if not items:
            return "بدون تلفات"
        return "، ".join(
            f"{fa_number(i['count'])} {i.get('unit', '')} {i['name']}" for i in items[:4]
        )

    if result["repulsed"]:
        text = (
            header("عملیات دفع شد", "🛡") + "\n\n"
            f"{result['effect_note']}\n"
            f"{DIVIDER}\n"
            f"💀 تلفات شما: {_losses(result['interceptor_losses'])}"
        )
    elif result["success"]:
        text = (
            header("رهگیری موفق", "✅") + "\n\n"
            f"{result['effect_note']}\n"
            f"{DIVIDER}\n"
            f"💀 تلفات شما: {_losses(result['interceptor_losses'])}\n"
            f"🛡 تلفات اسکورت: {_losses(result['escort_losses'])}\n\n"
            "⚠️ <i>این اقدام روابط شما با هر دو کشور را تیره کرد.</i>"
        )
    else:
        text = (
            header("رهگیری ناموفق", "❌") + "\n\n"
            f"{result['effect_note']}"
        )

    await safe_edit(call, text, reply_markup=operations_menu_kb())

    # ---------- لاگ و اطلاع به طرفین ----------
    outcome = "دفع‌شده" if result["repulsed"] else ("موفق" if result["success"] else "ناموفق")
    await send_log(
        bot,
        f"⚓ <b>رهگیری محموله — {outcome}</b>\n"
        f"رهگیر: {country.flag} {country.name_fa}\n"
        f"محموله: {result['seller']} ← {result['buyer']}\n"
        f"محتوا: {fa_number(result['amount'])} {result['unit']} {result['resource_fa']}\n"
        f"قدرت حمله: {fa_number(result['attack_power'])} | "
        f"اسکورت: {fa_number(result['escort_power'])}\n"
        + (f"مصادره: {'بله' if result['seized'] else 'خیر (نابود شد)'}\n" if result["success"] else ""),
    )

    if result["success"] or result["repulsed"]:
        seller = await countries_repo.get_country(session, sale.seller_country)
        buyer = await countries_repo.get_country(session, sale.buyer_country)
        fate = "مصادره" if result["seized"] else "نابود"

        for side in (seller, buyer):
            if side is None or not side.owner_user_id:
                continue
            if result["repulsed"]:
                msg = (
                    "🛡 <b>اسکورت شما حمله را دفع کرد</b>\n\n"
                    f"کشور {country.flag} {country.name_fa} تلاش کرد محموله‌ی "
                    f"{result['seller']} ← {result['buyer']} را رهگیری کند.\n"
                    "محافظان محموله حمله را ناکام گذاشتند."
                )
            else:
                msg = (
                    "🚨 <b>محموله‌ی شما رهگیری شد</b>\n\n"
                    f"رهگیر: {country.flag} {country.name_fa}\n"
                    f"محموله: {fa_number(result['amount'])} {result['unit']} "
                    f"{result['resource_fa']}\n"
                    f"سرنوشت: {fate} شد"
                )
            try:
                await bot.send_message(side.owner_user_id, msg)
            except Exception:  # noqa: BLE001
                pass


# ============================================================
#  🛡 تخصیص اسکورت به محموله
# ============================================================
@router.callback_query(F.data.startswith("escort:skip:"))
async def cb_escort_skip(call: CallbackQuery) -> None:
    """ارسال محموله بدون اسکورت."""
    await call.answer("محموله بدون اسکورت ارسال شد")
    try:
        await call.message.edit_text(
            call.message.html_text
            + "\n\n🚫 <b>بدون اسکورت</b> — این محموله در برابر رهگیری آسیب‌پذیر است."
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("escort skip annotate failed: %s", exc)


@router.callback_query(F.data.startswith("escort:add:"))
async def cb_escort_add(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """شروع انتخاب نیروی اسکورت."""
    await call.answer()
    parts = call.data.split(":")
    kind, sale_id = parts[2], int(parts[3])

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    assets = await escort_service.available_escort_assets(session, country.id)
    if not assets:
        await call.answer(
            "⚠️ تجهیزات مناسبی برای اسکورت ندارید (نیروی دریایی/هوایی/پدافندی).",
            show_alert=True,
        )
        return

    await state.clear()
    await state.update_data(escort_kind=kind, escort_sale_id=sale_id, assets=assets, selected={}, page=0)
    await state.set_state(EscortForm.selecting_assets)

    await safe_edit(
        call,
        header("انتخاب نیروی اسکورت", "🛡") + "\n\n"
        f"حداکثر {fa_number(ESCORT_MAX_UNITS)} واحد می‌توانید اختصاص دهید.\n"
        "هرچه اسکورت قوی‌تر، رهگیری محموله سخت‌تر.\n\n"
        "<i>اسکورت سوخت مصرف می‌کند و در صورت نبرد تلفات می‌دهد.</i>",
        reply_markup=asset_picker_kb(assets, {}, page=0),
    )


@router.callback_query(EscortForm.selecting_assets, F.data.startswith("op_page:"))
async def cb_escort_page(call: CallbackQuery, state: FSMContext) -> None:
    """ناوبری صفحه‌های اسکورت."""
    await call.answer()
    page = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)
    await safe_edit(
        call,
        header("انتخاب نیروی اسکورت", "🛡") + "\n\n" + _summary(dict(data.get("selected") or {})),
        reply_markup=asset_picker_kb(
            data.get("assets") or [], dict(data.get("selected") or {}), page=page
        ),
    )


@router.callback_query(EscortForm.selecting_assets, F.data == "op_assets_clear")
async def cb_escort_clear(call: CallbackQuery, state: FSMContext) -> None:
    """پاک‌کردن انتخاب اسکورت."""
    await call.answer("انتخاب‌ها پاک شد")
    data = await state.get_data()
    await state.update_data(selected={})
    await safe_edit(
        call,
        header("انتخاب نیروی اسکورت", "🛡") + "\n\nهنوز تجهیزاتی انتخاب نشده است.",
        reply_markup=asset_picker_kb(data.get("assets") or [], {}, page=data.get("page", 0)),
    )


@router.callback_query(EscortForm.selecting_assets, F.data.startswith("op_asset:"))
async def cb_escort_asset(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب یک قلم اسکورت."""
    await call.answer()
    index = int(call.data.split(":")[1])
    data = await state.get_data()
    assets = data.get("assets") or []
    if index >= len(assets):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = assets[index]
    await state.update_data(pending_index=index)
    await state.set_state(EscortForm.entering_asset_count)
    await safe_edit(
        call,
        f"🛡 <b>{asset['name']}</b>\n"
        f"📦 موجودی: {fa_number(asset['count'])} {asset['unit']}\n\n"
        "چه تعداد به اسکورت اختصاص می‌دهید؟\n"
        "<i>برای حذف، صفر بفرستید.</i>",
    )


@router.message(EscortForm.entering_asset_count, F.text)
async def msg_escort_count(message: Message, state: FSMContext) -> None:
    """ثبت تعداد اسکورت و نمایش قدرت حاصل."""
    data = await state.get_data()
    assets = data.get("assets") or []
    index = data.get("pending_index")

    if index is None or index >= len(assets):
        await state.set_state(EscortForm.selecting_assets)
        await message.answer("خطا در انتخاب. دوباره تلاش کنید.")
        return

    asset = assets[index]
    amount = parse_amount(message.text)
    if amount is None or amount < 0:
        await message.answer("⚠️ عدد معتبر وارد کنید.")
        return

    count = int(amount)
    if count > asset["count"]:
        await message.answer(f"⚠️ حداکثر {fa_number(asset['count'])} {asset['unit']} دارید.")
        return

    selected = dict(data.get("selected") or {})
    if count == 0:
        selected.pop(asset["name"], None)
    else:
        selected[asset["name"]] = count

    total = sum(selected.values())
    if total > ESCORT_MAX_UNITS:
        await message.answer(
            f"⚠️ مجموع اسکورت از سقف {fa_number(ESCORT_MAX_UNITS)} واحد بیشتر شد "
            f"({fa_number(total)}). تعداد کمتری انتخاب کنید."
        )
        return

    await state.update_data(selected=selected, pending_index=None)
    await state.set_state(EscortForm.selecting_assets)

    payload = [
        {**meta, "count": cnt}
        for name, cnt in selected.items()
        if (meta := next((a for a in assets if a["name"] == name), None))
    ]
    power = escort_service.compute_escort_power(payload)
    fuel = escort_service.escort_fuel_cost(payload)

    await message.answer(
        header("انتخاب نیروی اسکورت", "🛡") + "\n\n"
        + _summary(selected)
        + f"\n\n🛡 قدرت اسکورت: <b>{fa_number(power)}</b>\n"
        f"⛽️ سوخت لازم: {fa_number(fuel, 2)} میلیون بشکه",
        reply_markup=asset_picker_kb(assets, selected, page=data.get("page", 0)),
    )


@router.callback_query(EscortForm.selecting_assets, F.data == "op_assets_done")
async def cb_escort_done(
    call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    """چسباندن اسکورت به محموله."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    selected = dict(data.get("selected") or {})
    if not selected:
        await call.answer("ابتدا نیرو انتخاب کنید.", show_alert=True)
        return

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    kind = data.get("escort_kind", "res")
    sale_id = data.get("escort_sale_id", 0)

    if kind == "mil":
        from ..database.repositories import military_sale as milsale_repo

        sale = await milsale_repo.get_sale(session, sale_id)
    else:
        sale = await trade_repo.get_sale(session, sale_id)

    if sale is None:
        await safe_edit(call, "محموله یافت نشد.")
        return

    assets = data.get("assets") or []
    payload = [
        {**meta, "count": cnt}
        for name, cnt in selected.items()
        if (meta := next((a for a in assets if a["name"] == name), None))
    ]

    try:
        power = await escort_service.attach_escort(session, country, sale, payload)
    except escort_service.EscortError as err:
        await safe_edit(call, f"⛔️ {err}")
        return

    await session.commit()

    await safe_edit(
        call,
        header("اسکورت تخصیص یافت", "🛡") + "\n\n"
        f"✅ محموله با اسکورت ارسال شد.\n"
        f"🛡 قدرت اسکورت: <b>{fa_number(power)}</b>\n"
        f"⚔️ حداقل قدرت لازم برای رهگیری آن: "
        f"<b>{fa_number(interception_service.required_power(power))}</b>\n\n"
        "<i>محموله‌ی شما اکنون در برابر رهگیری محافظت می‌شود.</i>",
    )

    await send_log(
        bot,
        f"🛡 <b>تخصیص اسکورت به محموله</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"قدرت اسکورت: {fa_number(power)}\n"
        f"نیرو: {escort_service.describe_escort(sale)}",
    )
