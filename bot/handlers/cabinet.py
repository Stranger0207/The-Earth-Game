"""هندلر جامع گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import CABINET_ROLES_DATA
from ..database.models import User
from ..database.repositories import (
    cabinet as cabinet_repo,
    deployments as deployments_repo,
    military_bases as bases_repo,
    military_factory as mil_fac_repo,
)
from ..enums import CabinetRole
from ..keyboards.cabinet import (
    cabinet_inquiry_menu_kb,
    cabinet_main_menu_kb,
    cabinet_memo_menu_kb,
    cabinet_roles_list_kb,
    cabinet_select_official_kb,
)
from ..services.cabinet_service import (
    can_access_domain,
    get_defcon_level,
    perform_doge_audit,
    render_domain_report,
    render_official_profile,
    set_defcon_level,
)
from ..states.cabinet import (
    CabinetExecutiveOrderForm,
    CabinetInquiryForm,
    CabinetInspectionForm,
    CabinetMemoForm,
    CabinetPressBriefingForm,
)
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK

router = Router(name="cabinet")


@router.callback_query.middleware()
async def cabinet_cb_guard(handler, event: CallbackQuery, data: dict):
    from ..config import get_settings

    if not get_settings().is_admin(event.from_user.id):
        await event.answer(
            "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید.",
            show_alert=True,
        )
        return None
    return await handler(event, data)


@router.message.middleware()
async def cabinet_msg_guard(handler, event: Message, data: dict):
    from ..config import get_settings

    if not get_settings().is_admin(event.from_user.id):
        await event.answer(
            "دسترسی به این گیم مود توسط تیم مدیریت کره زمین بسته شده. لطفا گیم مود دیگری را امتحان کنید."
        )
        return None
    return await handler(event, data)


def _back_to_desk_kb(role_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data=f"cab:menu:{role_key}", style=STYLE_MAIN)
        ]]
    )


# ============================================================
#  انتخاب، تصدی و استعفای سمت
# ============================================================


@router.callback_query(F.data.startswith("cab:claim:"))
async def cb_claim_role(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """تصدی سمت در دولت فدرال توسط کاربر."""
    role_key = call.data.split(":")[2]
    ok = await cabinet_repo.claim_member_role(session, role_key, db_user.telegram_id)
    if not ok:
        await call.answer("⚠️ این سمت پر شده یا شما هم‌اکنون سمت دیگری دارید.", show_alert=True)
        return

    await session.commit()
    await call.answer("تبریک! سمت با موفقیت به شما واگذار شد 🇺🇸", show_alert=True)
    profile_text = render_official_profile(role_key, db_user.first_name)
    await safe_edit(call, profile_text, reply_markup=cabinet_main_menu_kb(role_key))


@router.callback_query(F.data.startswith("cab:occupied:"))
async def cb_occupied_role(
    call: CallbackQuery, session: AsyncSession
) -> None:
    """اطلاع‌رسانی اشغال بودن سمت."""
    role_key = call.data.split(":")[2]
    m = await cabinet_repo.get_member_by_role(session, role_key)
    name = m.user.first_name if (m and m.user) else "یک کاربر دیگر"
    await call.answer(f"این سمت هم‌اکنون در تصدی {name} است.", show_alert=True)


@router.callback_query(F.data == "cab:resign")
async def cb_resign_prompt(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """درخواست استعفا از سمت."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if m is None:
        await call.answer("شما سمتی ندارید.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ بله، استعفا می‌دهم", callback_data=f"cab:resign:do:{m.role_key}", style=STYLE_NO),
                InlineKeyboardButton(text="❌ انصراف", callback_data=f"cab:menu:{m.role_key}", style=STYLE_MAIN),
            ]
        ]
    )
    await safe_edit(call, "⚠️ <b>آیا مطمئن هستید که می‌خواهید از سمت خود در دولت فدرال استعفا دهید؟</b>\nبا استعفا، این سمت برای سایر بازیکنان آزاد می‌شود.", reply_markup=kb)


@router.callback_query(F.data.startswith("cab:resign:do:"))
async def cb_resign_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تأیید نهایی استعفا."""
    role_key = call.data.split(":")[3]
    await cabinet_repo.vacate_member_role(session, role_key)
    await session.commit()
    await call.answer("استعفای شما ثبت شد ✅")

    members = await cabinet_repo.list_members(session)
    await safe_edit(
        call,
        "🏛 <b>دولت فدرال ایالات متحده آمریکا</b>\n\nشما با موفقیت استعفا دادید. برای ادامه می‌توانید سمت دیگری انتخاب کنید:",
        reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
    )


# ============================================================
#  میز کار و مشاهده اعضای کابینه
# ============================================================


@router.callback_query(F.data == "cab:menu")
@router.callback_query(F.data.startswith("cab:menu:"))
async def cb_cabinet_menu(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """نمایش پنل اصلی میز کار مقام دولتی."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if m is None:
        members = await cabinet_repo.list_members(session)
        await safe_edit(
            call,
            "🏛 شما سمتی در دولت ندارید. لطفاً یک سمت انتخاب کنید:",
            reply_markup=cabinet_roles_list_kb(members, db_user.telegram_id),
        )
        return

    profile_text = render_official_profile(m.role_key, db_user.first_name)
    await safe_edit(call, profile_text, reply_markup=cabinet_main_menu_kb(m.role_key))


@router.callback_query(F.data == "cab:roster")
async def cb_cabinet_roster(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده لیست و وضعیت تمام ۱۵ مقام دولت آمریکا."""
    members = await cabinet_repo.list_members(session)
    lines = ["👥 <b>کابینه دولت فدرال ایالات متحده آمریکا</b>\n"]
    for m in members:
        role_enum = CabinetRole(m.role_key) if m.role_key in [r.value for r in CabinetRole] else None
        data = CABINET_ROLES_DATA.get(role_enum, {})
        icon = data.get("icon", "🏛")
        title = data.get("title_fa", m.role_key)
        name = data.get("official_name", "")
        if m.user:
            holder = f"👤 {m.user.first_name}"
        else:
            holder = "🟢 <i>خالی</i>"
        lines.append(f"{icon} <b>{title}</b> ({name}): {holder}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)
        ]]
    )
    await safe_edit(call, "\n".join(lines), reply_markup=kb)


# ============================================================
#  حوزه‌های اطلاعاتی و استعلام
# ============================================================


@router.callback_query(F.data.startswith("cab:domain:"))
async def cb_view_domain(
    call: CallbackQuery, session: AsyncSession, db_user: User
) -> None:
    """مشاهده گزارش اطلاعاتی حوزه با اعمال گارد دسترسی."""
    domain = call.data.split(":")[2]
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    role_key = m.role_key if m else "guest"

    # بررسی دسترسی مستقیم
    if not can_access_domain(role_key, domain):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📑 ثبت استعلام رسمی", callback_data="cab:inquiry:new", style=STYLE_OK)],
                [InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)],
            ]
        )
        await safe_edit(
            call,
            "⛔️ <b>دسترسی مستقیم مسدود است (طبقه‌بندی محرمانه)</b>\n\n"
            "شما طبق اختیارات سازمانی خود نمی‌توانید مستقیماً به داده‌های این بخش دسترسی پیدا کنید.\n"
            "جهت دریافت این اطلاعات، باید از طریق دکمه زیر به ارگان مسئول <b>استعلام رسمی</b> ارسال کنید.",
            reply_markup=kb,
        )
        return

    report = await render_domain_report(session, domain, role_key)
    await safe_edit(call, report, reply_markup=_back_to_desk_kb(role_key))


# ============================================================
#  مکاتبات درون‌سازمانی (Memos)
# ============================================================


@router.callback_query(F.data == "cab:memo:menu")
async def cb_memo_menu(call: CallbackQuery) -> None:
    await safe_edit(call, "✉️ <b>بخش مکاتبات و نامه‌نگاری کابینه</b>\n\nارسال و دریافت یادداشت‌های درون‌سازمانی:", reply_markup=cabinet_memo_menu_kb())


@router.callback_query(F.data == "cab:memo:new")
async def cb_memo_new(call: CallbackQuery, session: AsyncSession) -> None:
    members = await cabinet_repo.list_members(session)
    await safe_edit(
        call,
        "✉️ <b>گیرنده یادداشت را انتخاب کنید:</b>",
        reply_markup=cabinet_select_official_kb(members, prefix="cab:memo_to", allow_all=True),
    )


@router.callback_query(F.data.startswith("cab:memo_to:"))
async def cb_memo_pick_target(
    call: CallbackQuery, state: FSMContext
) -> None:
    target_role = call.data.split(":")[2]
    await state.update_data(memo_target=target_role)
    await state.set_state(CabinetMemoForm.entering_subject)
    await call.message.answer("📝 لطفاً <b>موضوع یادداشت</b> را ارسال کنید:")


@router.message(CabinetMemoForm.entering_subject, F.text)
async def msg_memo_subject(message: Message, state: FSMContext) -> None:
    await state.update_data(memo_subject=message.text.strip())
    await state.set_state(CabinetMemoForm.entering_body)
    await message.answer("✍️ حالا <b>متن کامل یادداشت یا نامه</b> را ارسال کنید:")


@router.message(CabinetMemoForm.entering_body, F.text)
async def msg_memo_body(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    data = await state.get_data()
    target_role = data.get("memo_target", "all")
    subject = data.get("memo_subject", "بدون عنوان")
    body = message.text.strip()
    await state.clear()

    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    sender_role = m.role_key if m else "official"

    memo = await cabinet_repo.create_memo(
        session,
        sender_role=sender_role,
        recipient_role=target_role,
        sender_user_id=db_user.telegram_id,
        subject=subject,
        body=body,
    )
    await session.commit()
    await message.answer(f"✅ یادداشت «{subject}» با موفقیت در سیستم فدرال ثبت و ارسال شد.")


@router.callback_query(F.data == "cab:memo:inbox")
async def cb_memo_inbox(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    role_key = m.role_key if m else "all"
    memos = await cabinet_repo.list_memos_for_role(session, role_key)
    if not memos:
        await safe_edit(call, "📥 صندوق یادداشت‌های شما خالی است.", reply_markup=cabinet_memo_menu_kb())
        return

    lines = ["📥 <b>صندوق یادداشت‌های دریافتی و ارسالی:</b>\n"]
    for memo in memos[:10]:
        lines.append(f"• <b>{memo.subject}</b> (از: {memo.sender_role} به: {memo.recipient_role})\n  {memo.body[:80]}...")

    await safe_edit(call, "\n".join(lines), reply_markup=cabinet_memo_menu_kb())


# ============================================================
#  استعلام اطلاعات (Inquiries)
# ============================================================


@router.callback_query(F.data == "cab:inquiry:menu")
async def cb_inquiry_menu(call: CallbackQuery) -> None:
    await safe_edit(call, "📑 <b>سامانه استعلام اطلاعات رسمی میان وزارتخانه‌ها</b>\n\nثبت پرسش و دریافت داده‌های محرمانه:", reply_markup=cabinet_inquiry_menu_kb())


@router.callback_query(F.data == "cab:inquiry:new")
async def cb_inquiry_new(call: CallbackQuery, session: AsyncSession) -> None:
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, "📑 <b>ارگان مقصد استعلام را انتخاب کنید:</b>", reply_markup=cabinet_select_official_kb(members, prefix="cab:inq_to"))


@router.callback_query(F.data.startswith("cab:inq_to:"))
async def cb_inquiry_pick_target(call: CallbackQuery, state: FSMContext) -> None:
    target_role = call.data.split(":")[2]
    await state.update_data(inq_target=target_role)
    await state.set_state(CabinetInquiryForm.entering_topic)
    await call.message.answer("📑 لطفاً <b>موضوع استعلام</b> را وارد کنید (مثلاً: بودجه دفاعی، آمار ذخایر نفتی):")


@router.message(CabinetInquiryForm.entering_topic, F.text)
async def msg_inquiry_topic(message: Message, state: FSMContext) -> None:
    await state.update_data(inq_topic=message.text.strip())
    await state.set_state(CabinetInquiryForm.entering_question)
    await message.answer("❓ شرح دقیق سوال یا اطلاعات مورد نیاز خود را بنویسید:")


@router.message(CabinetInquiryForm.entering_question, F.text)
async def msg_inquiry_question(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    data = await state.get_data()
    target_role = data.get("inq_target")
    topic = data.get("inq_topic", "استعلام رسمی")
    question = message.text.strip()
    await state.clear()

    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    from_role = m.role_key if m else "unknown"

    await cabinet_repo.create_inquiry(
        session,
        from_role=from_role,
        to_role=target_role,
        sender_user_id=db_user.telegram_id,
        topic=topic,
        question=question,
    )
    await session.commit()
    await message.answer(f"✅ استعلام رسمی «{topic}» به ارگان مربوطه ارسال شد.")


@router.callback_query(F.data == "cab:inquiry:list")
async def cb_inquiry_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    role_key = m.role_key if m else "unknown"
    inquiries = await cabinet_repo.list_inquiries_for_role(session, role_key)
    if not inquiries:
        await safe_edit(call, "📬 هیچ استعلامی ثبت نشده است.", reply_markup=cabinet_inquiry_menu_kb())
        return

    lines = ["📬 <b>فهرست استعلام‌های رسمی:</b>\n"]
    for inq in inquiries[:8]:
        st = "✅ پاسخ‌داده‌شده" if inq.status == "answered" else "⏳ در انتظار پاسخ"
        ans = f"\n  پاسخ: {inq.response}" if inq.response else ""
        lines.append(f"• <b>{inq.topic}</b> ({inq.from_role} ⬅️ {inq.to_role}) [{st}]\n  سوال: {inq.question}{ans}")

    await safe_edit(call, "\n\n".join(lines), reply_markup=cabinet_inquiry_menu_kb())


# ============================================================
#  دیدار حضوری و تماس امن
# ============================================================


@router.callback_query(F.data == "cab:meet:start")
@router.callback_query(F.data == "cab:call:start")
async def cb_meet_start(call: CallbackQuery, session: AsyncSession) -> None:
    mtype = "دیدار حضوری" if "meet" in call.data else "تماس امن تلفنی"
    prefix = "cab:meet_with" if "meet" in call.data else "cab:call_with"
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, f"🤝 <b>برای {mtype}، مقام مورد نظر را انتخاب کنید:</b>", reply_markup=cabinet_select_official_kb(members, prefix=prefix))


@router.callback_query(F.data.startswith("cab:meet_with:"))
@router.callback_query(F.data.startswith("cab:call_with:"))
async def cb_meet_send(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    target_role = call.data.split(":")[2]
    is_call = "call" in call.data
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    host_role = m.role_key if m else "official"

    target_m = await cabinet_repo.get_member_by_role(session, target_role)
    if target_m is None or target_m.user_id is None:
        await call.answer("این سمت فعلاً بدون متصدی است.", show_alert=True)
        return

    act = "تماس تلفنی" if is_call else "دیدار حضوری"
    await cabinet_repo.create_meeting(
        session,
        host_role=host_role,
        guest_role=target_role,
        host_user_id=db_user.telegram_id,
        guest_user_id=target_m.user_id,
        meeting_type="call" if is_call else "meeting",
    )
    await session.commit()
    await safe_edit(call, f"✅ درخواست {act} به {target_role} ارسال شد.", reply_markup=_back_to_desk_kb(host_role))


# ============================================================
#  دستورات و فرامین اختصاصی مقامات
# ============================================================


# ۱. رئیس‌جمهور: صدور فرمان اجرایی
@router.callback_query(F.data == "cab:action:exec_order")
async def cb_exec_order(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CabinetExecutiveOrderForm.entering_title)
    await call.message.answer("👑 <b>صدور فرمان اجرایی رئیس‌جمهور (Executive Order):</b>\nعنوان فرمان را ارسال کنید:")


@router.message(CabinetExecutiveOrderForm.entering_title, F.text)
async def msg_exec_order_title(message: Message, state: FSMContext) -> None:
    await state.update_data(order_title=message.text.strip())
    await state.set_state(CabinetExecutiveOrderForm.entering_content)
    await message.answer("📜 متن دستور و ابلاغیه رسمی را وارد کنید:")


@router.message(CabinetExecutiveOrderForm.entering_content, F.text)
async def msg_exec_order_content(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    data = await state.get_data()
    title = data.get("order_title")
    content = message.text.strip()
    await state.clear()

    await cabinet_repo.log_action(session, "president", db_user.telegram_id, "executive_order", f"{title}: {content}")
    await session.commit()
    await message.answer(f"👑 <b>فرمان اجرایی رئیس‌جمهور ابلاغ شد:</b>\n\n📌 <b>{title}</b>\n{content}\n\n<i>این فرمان به تمام ارگان‌های فدرال مخابره شد.</i>")


# ۲. سخنگوی کاخ سفید: کنفرانس مطبوعاتی
@router.callback_query(F.data == "cab:action:press_briefing")
async def cb_press_briefing(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CabinetPressBriefingForm.entering_text)
    await call.message.answer("🎤 <b>کنفرانس مطبوعاتی کاخ سفید:</b>\nمتن بیانیه و مواضع دولت را جهت اعلام به رسانه‌ها ارسال کنید:")


@router.message(CabinetPressBriefingForm.entering_text, F.text)
async def msg_press_briefing_text(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    text = message.text.strip()
    await state.clear()
    await cabinet_repo.log_action(session, "press_secretary", db_user.telegram_id, "press_briefing", text)
    await session.commit()
    await message.answer(f"🎤 <b>بیانیه مطبوعاتی کاخ سفید منتشر شد:</b>\n\n{text}")


# ۳. وزیر دفاع: تنظیم وضعیت DEFCON
@router.callback_query(F.data == "cab:action:defcon")
async def cb_defcon_menu(call: CallbackQuery) -> None:
    cur = get_defcon_level()
    builder = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔴 DEFCON 1 (جنگ اتمی / اضطرار کامل)", callback_data="cab:set_defcon:1", style=STYLE_NO)],
            [InlineKeyboardButton(text="🟠 DEFCON 2 (آمادگی فوق‌العاده نظامی)", callback_data="cab:set_defcon:2", style=STYLE_MAIN)],
            [InlineKeyboardButton(text="🟡 DEFCON 3 (آماده‌باش رزمی ارتش)", callback_data="cab:set_defcon:3", style=STYLE_MAIN)],
            [InlineKeyboardButton(text="🟢 DEFCON 4 (پایش و مراقبت اطلاعاتی)", callback_data="cab:set_defcon:4", style=STYLE_OK)],
            [InlineKeyboardButton(text="⚪️ DEFCON 5 (وضعیت عادی صلح)", callback_data="cab:set_defcon:5", style=STYLE_MAIN)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="cab:menu", style=STYLE_MAIN)],
        ]
    )
    await safe_edit(call, f"🚨 <b>سطح فعلی هشدار آمادگی دفاعی (DEFCON): {cur}</b>\nسطح مورد نظر را انتخاب کنید:", reply_markup=builder)


@router.callback_query(F.data.startswith("cab:set_defcon:"))
async def cb_set_defcon(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lvl = int(call.data.split(":")[2])
    set_defcon_level(lvl)
    await cabinet_repo.log_action(session, "secretary_defense", db_user.telegram_id, "set_defcon", f"تغییر دِف‌کان به DEFCON {lvl}")
    await session.commit()
    await call.answer(f"سطح DEFCON به {lvl} تغییر یافت 🚨", show_alert=True)
    await safe_edit(call, f"🚨 <b>سطح آمادگی ارتش ایالات متحده به DEFCON {lvl} تغییر یافت.</b>", reply_markup=_back_to_desk_kb("secretary_defense"))


# ۴. DOGE: ممیزی کارآمدی سازمان‌ها
@router.callback_query(F.data == "cab:action:doge_audit")
async def cb_doge_audit_select(call: CallbackQuery, session: AsyncSession) -> None:
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, "⚡️ <b>کدام سازمان را برای ممیزی کارآمدی DOGE انتخاب می‌کنید؟</b>", reply_markup=cabinet_select_official_kb(members, prefix="cab:doge_do"))


@router.callback_query(F.data.startswith("cab:doge_do:"))
async def cb_doge_do_audit(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    target = call.data.split(":")[2]
    result = perform_doge_audit(target)
    await cabinet_repo.log_action(session, "tech_efficiency", db_user.telegram_id, "doge_audit", f"ممیزی {target}: صرفه‌جویی {result['savings']}")
    await session.commit()

    text = (
        f"⚡️ <b>گزارش ممیزی کارآمدی DOGE — ارگان: {result['target_title']}</b>\n\n"
        f"💰 <b>صرفه‌جویی بودجه شناسایی‌شده:</b> {fa_money(result['savings'])}\n"
        f"📈 <b>افزایش بهره‌وری محاسبه‌شده:</b> +{fa_number(result['efficiency_gain'])}٪\n"
        f"💡 <b>پیشنهاد فوری ایلان ماسک / ویوک راماسوامی:</b>\n«{result['recommendation']}»"
    )
    await safe_edit(call, text, reply_markup=_back_to_desk_kb("tech_efficiency"))


# ۵. دادستان کل: بازرسی ویژه ارگان‌ها
@router.callback_query(F.data == "cab:action:inspect_organ")
async def cb_inspect_organ_select(call: CallbackQuery, session: AsyncSession) -> None:
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, "⚖️ <b>ارگان هدف را جهت صدور حکم بازرسی ویژه انتخاب کنید:</b>", reply_markup=cabinet_select_official_kb(members, prefix="cab:inspect_pick"))


@router.callback_query(F.data.startswith("cab:inspect_pick:"))
async def cb_inspect_pick(call: CallbackQuery, state: FSMContext) -> None:
    target = call.data.split(":")[2]
    await state.update_data(inspect_target=target)
    await state.set_state(CabinetInspectionForm.entering_reason)
    await call.message.answer(f"⚖️ علت و زمینه بازرسی از ارگان <b>{target}</b> را وارد کنید:")


@router.message(CabinetInspectionForm.entering_reason, F.text)
async def msg_inspect_reason(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    data = await state.get_data()
    target = data.get("inspect_target", "organ")
    reason = message.text.strip()
    await state.clear()

    await cabinet_repo.create_inspection(
        session,
        target_role=target,
        target_user_id=None,
        initiated_by_user_id=db_user.telegram_id,
        reason=reason,
        findings="بازرسی انجام شد: اسناد مالی و فرامین بررسی شدند. تخلف حادی یافت نشد.",
    )
    await session.commit()
    await message.answer(f"⚖️ <b>حکم بازرسی ویژه صادر و ثبت شد:</b>\nهدف: {target}\nعلت: {reason}\n\n<i>گزارش در کارتابل دادستان کل ثبت گردید.</i>")


# سایر اکشن‌های خلاصه و پرکاربرد
@router.callback_query(F.data.startswith("cab:action:"))
async def cb_generic_action(call: CallbackQuery, session: AsyncSession) -> None:
    act = call.data.split(":")[2]
    await call.answer()

    if act == "bases":
        bases = await bases_repo.list_by_country(session, 1)  # USA
        cnt = len(bases)
        await safe_edit(call, f"🏗 <b>پایگاه‌های نظامی ایالات متحده آمریکا</b>\nتعداد پایگاه‌های فعال جهانی: {fa_number(cnt)} پایگاه راهبردی در اروپا، خاورمیانه و شرق آسیا.", reply_markup=_back_to_desk_kb("secretary_defense"))
    elif act == "deploy":
        deps = await deployments_repo.list_by_country(session, 1)
        await safe_edit(call, f"⚔️ <b>استقرار نیروهای ارتش آمریکا در جهان</b>\nتعداد یگان‌های مستقر در مناطق برون‌مرزی: {fa_number(len(deps))} ناوگروه و تیپ واکنش سریع.", reply_markup=_back_to_desk_kb("centcom_commander"))
    elif act == "geo_map":
        await safe_edit(call, "🗺 <b>نقشه‌برداری ژئوپلیتیک ستاد مشترک</b>\nرصد کریدورها: تنگه هرمز، باب المندب، کانال پاناما و تنگه تایوان تحت پوشش کامل تجسسی ارتش آمریکا قرار دارند.", reply_markup=_back_to_desk_kb("joint_chiefs"))
    elif act == "nuclear_status":
        await safe_edit(call, "☢️ <b>وضعیت زرادخانه هسته‌ای آمریکا</b>\nسه‌گانه اتمی (هوایی، زیردریایی، موشکی) در آماده‌باش ۱۰۰٪ بازدارنده قرار دارد.", reply_markup=_back_to_desk_kb("national_security"))
    elif act == "crisis_protocol":
        await safe_edit(call, "☣️ <b>پروتکل مدیریت بحران ملی (HHS / RFK Jr.)</b>\nوضعیت ذخایر حیاتی در بالاترین سطح آمادگی قرار دارد.", reply_markup=_back_to_desk_kb("health_crisis"))
    elif act == "launch_sat":
        await safe_edit(call, "📡 <b>سازمان هوافضا (NASA / Defense Aerospace)</b>\nسامانه پرتاب ماهواره‌های تجسسی مدار پایین و ژئواستیشنری آماده ماموریت است.", reply_markup=_back_to_desk_kb("aerospace_defense"))
    elif act == "mil_factories":
        await safe_edit(call, "🏭 <b>صنایع و کارخانه‌های دفاعی آمریکا</b>\n۱۲ خط تولید تسلیحات استراتژیک پنتاگون با حداکثر ظرفیت فعال هستند.", reply_markup=_back_to_desk_kb("aerospace_defense"))
    else:
        await safe_edit(call, f"✅ دستور «{act}» با موفقیت در سیستم فدرال به ثبت رسید.", reply_markup=_back_to_desk_kb("president"))
