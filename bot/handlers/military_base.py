"""هندلر بخش پایگاه‌های نظامی (v2.0)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import MILITARY_BASE_TYPES
from ..database.models import User
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import military_bases as base_repo
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.military import military_menu_kb
from ..keyboards.military_base import (
    base_details_kb,
    base_main_menu_kb,
    base_types_kb,
    bases_list_kb,
)
from ..loader import bot
from ..services import base_service
from ..services.news_service import send_log
from ..states.military_base import MilitaryBaseForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="military_base")
settings = get_settings()


@router.callback_query(F.data == "mil:base")
async def cb_base_menu(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی پایگاه‌های نظامی."""
    await call.answer()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "military.base"):
        return

    text = (
        header("پایگاه‌های نظامی", "🏗")
        + "\n\nپایگاه‌های نظامی محل استقرار نیروها و خط مقدم پشتیبانی نبردها هستند.\n"
        "کشورهای VIP می‌توانند در کشور خود یا با موافقت کشور میزبان، پایگاه نظامی بسازند."
    )
    await safe_edit(call, text, reply_markup=base_main_menu_kb())


@router.callback_query(F.data == "mbase:build")
async def cb_base_build(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع پایگاه نظامی."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if not country.is_vip:
        await safe_edit(
            call,
            "⛔️ فقط کشورهای VIP می‌توانند پایگاه نظامی احداث کنند.",
            reply_markup=base_main_menu_kb(),
        )
        return

    await state.set_state(MilitaryBaseForm.choosing_type)
    await safe_edit(
        call,
        header("احداث پایگاه نظامی", "🏗") + "\n\nنوع پایگاه مورد نظر را انتخاب کنید:",
        reply_markup=base_types_kb(),
    )


@router.callback_query(MilitaryBaseForm.choosing_type, F.data.startswith("mbase_type:"))
async def cb_base_type(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب کشور میزبان."""
    await call.answer()
    b_type = call.data.split(":")[1]
    await state.update_data(base_type=b_type)

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    countries = await countries_repo.list_countries(session)
    await state.set_state(MilitaryBaseForm.choosing_host)

    text = (
        header("انتخاب کشور میزبان", "🌍")
        + "\n\nمی‌خواهید این پایگاه را در کدام کشور احداث کنید؟\n"
        "*(اگر کشور دیگری را انتخاب کنید، برای احداث نیاز به تأیید رئیس‌جمهور آن کشور خواهد بود.)*"
    )
    await safe_edit(
        call,
        text,
        reply_markup=countries_kb(countries, prefix="mbase_host", columns=2, back_data="mbase:build"),
    )


@router.callback_query(MilitaryBaseForm.choosing_host, F.data.startswith("mbase_host:"))
async def cb_base_host(call: CallbackQuery, state: FSMContext) -> None:
    """دریافت نام پایگاه."""
    await call.answer()
    host_id = int(call.data.split(":")[1])
    await state.update_data(host_country_id=host_id)

    await state.set_state(MilitaryBaseForm.entering_name)
    await safe_edit(call, "✍️ نام پایگاه نظامی را وارد کنید (مثال: پایگاه هوایی نوژه):")


@router.message(MilitaryBaseForm.entering_name, F.text)
async def msg_base_name(message: Message, state: FSMContext) -> None:
    """دریافت محل فیزیکی پایگاه."""
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("لطفاً نام معتبرتری برای پایگاه وارد کنید.")
        return

    await state.update_data(base_name=name)
    await state.set_state(MilitaryBaseForm.entering_location)
    await message.answer("📍 محل دقیق فیزیکی/منطقه پایگاه را وارد کنید (مثال: استان همدان):")


@router.message(MilitaryBaseForm.entering_location, F.text)
async def msg_base_location(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """پیش‌نمایش و تأیید نهایی ساخت پایگاه."""
    location = message.text.strip()
    await state.update_data(base_location=location)

    data = await state.get_data()
    b_type = data["base_type"]
    host_id = data["host_country_id"]
    name = data["base_name"]

    type_name_fa, cost_usd, cap = MILITARY_BASE_TYPES[b_type]
    host = await countries_repo.get_country(session, host_id)
    owner = await get_player_country(session, db_user)

    if owner is None or host is None:
        await message.answer("خطا در دریافت اطلاعات.")
        await state.clear()
        return

    await state.set_state(MilitaryBaseForm.confirming_build)

    is_foreign = owner.id != host.id
    note = (
        "⚠️ پس از ثبت، درخواست برای رئیس‌جمهور کشور میزبان ارسال خواهد شد."
        if is_foreign
        else "✅ پایگاه پس از تأیید فوراً فعال خواهد شد."
    )

    text = (
        header("تأیید ساخت پایگاه", "🏗") + "\n\n"
        f"🏛 **نام پایگاه:** {name}\n"
        f"🏷 **نوع:** {type_name_fa}\n"
        f"🌍 **کشور میزبان:** {host.flag} {host.name_fa}\n"
        f"📍 **محل:** {location}\n"
        f"📦 **گنجایش:** {fa_number(cap)} قلم تجهیزات\n"
        f"💰 **هزینه احداث:** {fa_money(cost_usd)}\n\n"
        f"{note}\n\n"
        "آیا احداث پایگاه را تأیید می‌کنید؟"
    )

    await message.answer(text, reply_markup=confirm_cancel_kb("mbase_confirm", cancel_data="mil:base"))


@router.callback_query(MilitaryBaseForm.confirming_build, F.data == "mbase_confirm")
async def cb_base_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت پایگاه و ارسال درخواست به میزبان یا فعال‌سازی مستقیم."""
    await call.answer()
    data = await state.get_data()
    await state.clear()

    owner = await get_player_country(session, db_user)
    if owner is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    host = await countries_repo.get_country(session, data["host_country_id"])
    if host is None:
        await safe_edit(call, "کشور میزبان یافت نشد.")
        return

    try:
        base, approved = await base_service.request_create_base(
            session=session,
            owner_country=owner,
            host_country=host,
            base_type=data["base_type"],
            name=data["base_name"],
            location=data["base_location"],
        )
    except base_service.BaseServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}", reply_markup=base_main_menu_kb())
        return

    type_name_fa = MILITARY_BASE_TYPES[data["base_type"]][0]

    if approved:
        await safe_edit(
            call,
            f"✅ پایگاه نظامی **{base.name}** با موفقیت در {host.flag} {host.name_fa} احداث و فعال شد.",
            reply_markup=base_main_menu_kb(),
        )
        await send_log(
            bot,
            "🏗 **احداث پایگاه نظامی**\n"
            f"سازنده: {owner.flag} {owner.name_fa}\n"
            f"میزبان: {host.flag} {host.name_fa}\n"
            f"پایگاه: {base.name} ({type_name_fa})\n"
            f"هزینه: {fa_money(base.cost_usd)}",
        )
    else:
        await safe_edit(
            call,
            f"📨 درخواست احداث پایگاه نظامی **{base.name}** برای رئیس‌جمهور {host.flag} {host.name_fa} ارسال شد. "
            "پس از تأیید ایشان، پایگاه فعال خواهد شد.",
            reply_markup=base_main_menu_kb(),
        )

        # ارسال پیام به مالک کشور میزبان
        if host.owner_user_id:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ موافقت با احداث", callback_data=f"mbase_appr:{base.id}", style=STYLE_OK),
                    InlineKeyboardButton(text="❌ مخالفت و رد", callback_data=f"mbase_rej:{base.id}", style=STYLE_NO),
                ]]
            )
            try:
                await bot.send_message(
                    host.owner_user_id,
                    "🏗 **درخواست احداث پایگاه نظامی خارجی**\n\n"
                    f"کشور {owner.flag} {owner.name_fa} درخواست احداث یک **{type_name_fa}** "
                    f"به نام «{base.name}» در منطقه «{base.location}» خاک شما را دارد.\n\n"
                    "آیا با این درخواست موافقت می‌کنید؟",
                    reply_markup=kb,
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("mbase_appr:"))
async def cb_base_approve(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """موافقت کشور میزبان با احداث پایگاه خارجی."""
    base_id = int(call.data.split(":")[1])
    host = await get_player_country(session, db_user)
    if host is None:
        await call.answer("خطا در شناسایی کشور.", show_alert=True)
        return

    try:
        base = await base_service.approve_base_request(session, base_id, host.id)
    except base_service.BaseServiceError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("با احداث پایگاه موافقت شد ✅")
    await safe_edit(call, call.message.html_text + "\n\n✅ **با احداث این پایگاه موافقت کردید.**")

    owner = await countries_repo.get_country(session, base.owner_country_id)
    if owner and owner.owner_user_id:
        try:
            await bot.send_message(
                owner.owner_user_id,
                f"🎉 کشور {host.flag} {host.name_fa} با احداث پایگاه نظامی **{base.name}** موافقت کرد! "
                "پایگاه شما اکنون فعال است.",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("mbase_rej:"))
async def cb_base_reject(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مخالفت کشور میزبان با احداث پایگاه خارجی."""
    base_id = int(call.data.split(":")[1])
    host = await get_player_country(session, db_user)
    if host is None:
        await call.answer("خطا در شناسایی کشور.", show_alert=True)
        return

    try:
        base = await base_service.reject_base_request(session, base_id, host.id)
    except base_service.BaseServiceError as err:
        await call.answer(str(err), show_alert=True)
        return

    await call.answer("درخواست رد شد ❌")
    await safe_edit(call, call.message.html_text + "\n\n❌ **شما با احداث این پایگاه مخالفت کردید.**")

    owner = await countries_repo.get_country(session, base.owner_country_id)
    if owner and owner.owner_user_id:
        try:
            await bot.send_message(
                owner.owner_user_id,
                f"❌ کشور {host.flag} {host.name_fa} با احداث پایگاه نظامی **{base.name}** مخالفت کرد. "
                "مبلغ احداث به بودجه کشور شما بازگردانده شد.",
            )
        except Exception:
            pass


@router.callback_query(F.data == "mbase:list")
async def cb_base_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لیست پایگاه‌های نظامی تحت مدیریت کاربر."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    bases = await base_repo.list_bases_by_owner(session, country.id)
    if not bases:
        await safe_edit(call, "📋 شما در حال حاضر هیچ پایگاه نظامی فعالی ندارید.", reply_markup=base_main_menu_kb())
        return

    await safe_edit(
        call,
        header("پایگاه‌های نظامی شما", "🏛") + "\n\nبرای مشاهده جزئیات یا مدیریت، پایگاه مورد نظر را انتخاب کنید:",
        reply_markup=bases_list_kb(list(bases)),
    )


@router.callback_query(F.data.startswith("mbase_view:"))
async def cb_base_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده جزئیات یک پایگاه خاص."""
    await call.answer()
    base_id = int(call.data.split(":")[1])

    base = await base_repo.get_base(session, base_id)
    if not base:
        await safe_edit(call, "پایگاه یافت نشد.", reply_markup=base_main_menu_kb())
        return

    host = await countries_repo.get_country(session, base.host_country_id)
    host_name = f"{host.flag} {host.name_fa}" if host else "نامشخص"
    type_name_fa = MILITARY_BASE_TYPES.get(base.base_type, (base.base_type, 0, 0))[0]

    eq_lines = []
    total_eq = 0
    for eq in base.equipments:
        eq_lines.append(f"• {eq.asset_name}: {fa_number(eq.count)} عدد")
        total_eq += eq.count

    eq_str = "\n".join(eq_lines) if eq_lines else "◦ بدون تجهیزات مستقر"

    text = (
        header(base.name, "🏛") + "\n\n"
        f"🏷 **نوع:** {type_name_fa}\n"
        f"🌍 **کشور میزبان:** {host_name}\n"
        f"📍 **محل:** {base.location}\n"
        f"📦 **ظرفیت:** {fa_number(total_eq)} / {fa_number(base.capacity)}\n\n"
        f"🪖 **تجهیزات مستقر:**\n{eq_str}"
    )

    await safe_edit(call, text, reply_markup=base_details_kb(base.id))


@router.callback_query(F.data == "mbase:transfer")
async def cb_base_transfer_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """شروع آگاهانه انتقال تجهیزات: انتخاب پایگاه مقصد."""
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    bases = await base_repo.list_bases_by_owner(session, country.id)
    if not bases:
        await safe_edit(call, "⚠️ ابتدا باید حداقل یک پایگاه نظامی بسازید.", reply_markup=base_main_menu_kb())
        return

    await safe_edit(
        call,
        "📦 تجهیزات را به کدام پایگاه منتقل می‌کنید؟",
        reply_markup=bases_list_kb(list(bases)),
    )


@router.callback_query(F.data.startswith("mbase_tr_to:"))
async def cb_base_transfer_to(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """انتخاب تجهیزات برای انتقال به پایگاه مشخص."""
    await call.answer()
    base_id = int(call.data.split(":")[1])
    await state.update_data(target_base_id=base_id)

    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    assets = await mil_repo.list_assets(session, country.id)
    available = [a for a in assets if a.count > 0]

    if not available:
        await safe_edit(call, "⚠️ هیچ تجهیزاتی برای انتقال در انبار کشور ندارید.", reply_markup=base_main_menu_kb())
        return

    await state.update_data(available_assets=[{"name": a.name, "count": a.count, "branch": a.branch} for a in available])
    await state.set_state(MilitaryBaseForm.choosing_asset_to_transfer)

    builder = InlineKeyboardBuilder()
    for idx, a in enumerate(available):
        builder.button(text=f"{a.name} ({fa_number(a.count)})", callback_data=f"mbase_ass:{idx}", style=STYLE_OK)
    builder.button(text="🔙 بازگشت", callback_data="mil:base", style=STYLE_NO)
    builder.adjust(1)

    await safe_edit(call, "📦 کدام قلم تجهیزات را منتقل می‌کنید؟", reply_markup=builder.as_markup())


@router.callback_query(MilitaryBaseForm.choosing_asset_to_transfer, F.data.startswith("mbase_ass:"))
async def cb_base_asset_select(call: CallbackQuery, state: FSMContext) -> None:
    """دریافت تعداد تجهیزات برای انتقال."""
    await call.answer()
    idx = int(call.data.split(":")[1])
    data = await state.get_data()
    available = data.get("available_assets", [])

    if idx >= len(available):
        await call.answer("انتخاب نامعتبر.", show_alert=True)
        return

    asset = available[idx]
    await state.update_data(selected_asset=asset)
    await state.set_state(MilitaryBaseForm.entering_transfer_count)

    await safe_edit(
        call,
        f"🔢 چه تعداد **{asset['name']}** منتقل شود؟ (موجودی انبار کشور: {fa_number(asset['count'])})"
    )


@router.message(MilitaryBaseForm.entering_transfer_count, F.text)
async def msg_base_transfer_count(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """اعمال انتقال تجهیزات به پایگاه."""
    count = parse_amount(message.text)
    data = await state.get_data()
    asset = data.get("selected_asset")
    base_id = data.get("target_base_id")
    await state.clear()

    country = await get_player_country(session, db_user)
    if country is None or not asset or not base_id:
        await message.answer("خطا در انتقال تجهیزات.")
        return

    if count is None or count <= 0 or int(count) > asset["count"]:
        await message.answer(f"عدد نامعتبر. موجودی شما {fa_number(asset['count'])} است.")
        return

    try:
        eq = await base_service.transfer_equipment_to_base(
            session=session,
            owner_country_id=country.id,
            base_id=base_id,
            asset_name=asset["name"],
            count=int(count),
        )
    except base_service.BaseServiceError as err:
        await message.answer(f"⛔️ خطا: {err}", reply_markup=base_main_menu_kb())
        return

    base = await base_repo.get_base(session, base_id)
    base_name = base.name if base else "پایگاه"

    await message.answer(
        f"✅ تعداد **{fa_number(count)}** عدد **{asset['name']}** با موفقیت به پایگاه **{base_name}** منتقل شد.",
        reply_markup=base_main_menu_kb(),
    )


@router.callback_query(F.data.startswith("mbase_del:"))
async def cb_base_delete(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تخریب و تخلیه کامل پایگاه."""
    await call.answer()
    base_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    try:
        await base_service.destroy_or_delete_base(session, country.id, base_id)
    except base_service.BaseServiceError as err:
        await safe_edit(call, f"⛔️ خطا: {err}", reply_markup=base_main_menu_kb())
        return

    await safe_edit(
        call,
        "💥 پایگاه تخلیه و تخریب شد. تمامی تجهیزات مستقر به انبار اصلی کشور بازگردانده شدند.",
        reply_markup=base_main_menu_kb(),
    )
