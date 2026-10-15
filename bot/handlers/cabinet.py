"""هندلر جامع گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

import json

from ..constants import CABINET_ROLES_DATA, OPERATION_CHAINS_CONFIG
from ..database.models import User
from ..database.repositories import (
    cabinet as cabinet_repo,
    deployments as deployments_repo,
    military_bases as bases_repo,
    military_factory as mil_fac_repo,
)
from ..enums import (
    CabinetBudgetStatus,
    CabinetCrisisStatus,
    CabinetOperationStatus,
    CabinetRole,
)
from ..keyboards.cabinet import (
    cabinet_agenda_view_kb,
    cabinet_budget_request_view_kb,
    cabinet_budget_requests_list_kb,
    cabinet_chain_type_selection_kb,
    cabinet_crises_list_kb,
    cabinet_crisis_view_kb,
    cabinet_inquiry_menu_kb,
    cabinet_leak_menu_kb,
    cabinet_leaks_list_kb,
    cabinet_main_menu_kb,
    cabinet_memo_menu_kb,
    cabinet_operation_view_kb,
    cabinet_operations_list_kb,
    cabinet_operations_menu_kb,
    cabinet_roles_list_kb,
    cabinet_select_official_kb,
)
from ..services.cabinet_service import (
    approve_or_reject_budget_request,
    can_access_domain,
    claim_agenda_reward,
    conduct_press_briefing,
    execute_completed_operation,
    get_defcon_level,
    get_usa_country,
    issue_executive_order,
    leak_confidential_info,
    lobby_senate,
    perform_doge_audit,
    render_domain_report,
    render_official_profile,
    request_department_budget,
    resolve_crisis_step,
    scan_leak_hunter,
    set_defcon_level,
)
from ..states.cabinet import (
    CabinetBudgetRequestForm,
    CabinetExecutiveOrderForm,
    CabinetInquiryForm,
    CabinetInspectionForm,
    CabinetLeakForm,
    CabinetMemoForm,
    CabinetPressBriefingForm,
)
from ..utils.numbers import fa_money, fa_number
from ..utils.screens import safe_edit
from ..utils.ui import header, STYLE_MAIN, STYLE_NO, STYLE_OK
from .deps import assert_feature, get_player_country

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
    m = await cabinet_repo.get_member_by_role(session, role_key)
    profile_text = render_official_profile(role_key, db_user.first_name, m)
    await safe_edit(call, profile_text, reply_markup=cabinet_main_menu_kb(role_key, m))


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

    profile_text = render_official_profile(m.role_key, db_user.first_name, m)
    await safe_edit(call, profile_text, reply_markup=cabinet_main_menu_kb(m.role_key, m))


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
async def cb_exec_order(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.exec_order"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.PRESIDENT.value:
        await call.answer("تنها رئیس‌جمهور حق صدور فرمان اجرایی دارد.", show_alert=True)
        return
    if m.political_capital < 25:
        await call.answer(
            f"سرمایه سیاسی شما کافی نیست! (موجود: {m.political_capital} | نیاز: ۲۵)",
            show_alert=True,
        )
        return
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
    title = data.get("order_title", "فرمان اجرایی")
    content = message.text.strip()
    await state.clear()

    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    role_key = m.role_key if m else "president"
    ok, msg = await issue_executive_order(session, role_key, title, content)
    await session.commit()
    await message.answer(f"👑 <b>فرمان اجرایی رئیس‌جمهور ابلاغ شد:</b>\n\n📌 <b>{title}</b>\n{content}\n\n{msg}")


# ۲. سخنگوی کاخ سفید: کنفرانس مطبوعاتی
@router.callback_query(F.data == "cab:action:press_briefing")
async def cb_press_briefing(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.PRESS_SECRETARY.value:
        await call.answer("تنها سخنگوی کاخ سفید صلاحیت کنفرانس مطبوعاتی دارد.", show_alert=True)
        return
    await state.set_state(CabinetPressBriefingForm.entering_text)
    await call.message.answer("🎤 <b>کنفرانس مطبوعاتی کاخ سفید:</b>\nمتن بیانیه و مواضع دولت را جهت اعلام به رسانه‌ها ارسال کنید:")


@router.message(CabinetPressBriefingForm.entering_text, F.text)
async def msg_press_briefing_text(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User
) -> None:
    text = message.text.strip()
    await state.clear()
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    role_key = m.role_key if m else "press_secretary"
    ok, res_msg = await conduct_press_briefing(session, role_key, text)
    await session.commit()
    await message.answer(f"🎤 <b>بیانیه مطبوعاتی کاخ سفید منتشر شد:</b>\n\n{text}\n\n{res_msg}")


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


# ============================================================
#  ابزارهای عملیاتی ویژه ۱۵ مقام دولت
# ============================================================


@router.callback_query(F.data == "cab:action:senate_lobby")
async def cb_senate_lobby(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """لابی‌گری در صحن سنا توسط معاون رئیس‌جمهور."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.VICE_PRESIDENT.value:
        await call.answer("این ابزار اختصاصی معاون رئیس‌جمهور است.", show_alert=True)
        return
    ok, msg = await lobby_senate(session, m.role_key, "لایحه افزایش اختیارات و اعتبارات فدرال")
    await session.commit()
    await safe_edit(call, f"🏛 <b>لابی‌گری در صحن سنا (Senate Floor)</b>\n\n{msg}", reply_markup=_back_to_desk_kb(m.role_key))


@router.callback_query(F.data == "cab:action:leak_hunter")
async def cb_leak_hunter(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اسکن ضدجاسوسی کابینه (Leak Hunter) توسط وزیر امنیت داخلی."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.HOMELAND_SECURITY.value:
        await call.answer("این ابزار اختصاصی وزیر امنیت داخلی است.", show_alert=True)
        return
    ok, report = await scan_leak_hunter(session)
    await session.commit()
    await safe_edit(call, f"🔍 <b>سامانه اسکن ضدجاسوسی فدرال (Leak Hunter)</b>\n\n{report}", reply_markup=_back_to_desk_kb(m.role_key))


@router.callback_query(F.data == "cab:action:cia_decrypt")
async def cb_cia_decrypt(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """رمزگشایی اطلاعات خام سیا."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.CIA_DIRECTOR.value:
        await call.answer("این ابزار اختصاصی مدیر سیا است.", show_alert=True)
        return
    report = (
        "📡 <b>بولتن محرمانه رمزگشایی سیا (CIA Decrypted Cable):</b>\n\n"
        "• ردگیری ارتباطات ماهواره‌ای ارتش روسیه در پایگاه‌های دریای سیاه\n"
        "• فعالیت‌های غیرمتعارف هسته‌ای در تاسیسات زیرزمینی آسیا\n"
        "• حرکت ناوگروه تهاجمی چین در آب‌های پیرامونی تنگه تایوان\n\n"
        "<i>گزارش تحلیلی به میز مشاور امنیت ملی و رئیس‌جمهور ارسال گردید.</i>"
    )
    await safe_edit(call, report, reply_markup=_back_to_desk_kb(m.role_key))


@router.callback_query(F.data == "cab:action:situation_room")
async def cb_situation_room(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """داشبورد اتاق وضعیت کاخ سفید (Situation Room)."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    active_crises, _ = await cabinet_repo.list_crises(session, status="ACTIVE")
    defcon = get_defcon_level()
    text = (
        "🖥 <b>اتاق وضعیت کاخ سفید (White House Situation Room)</b>\n\n"
        f"🚨 <b>سطح هشدار آمادگی ارتش:</b> DEFCON {defcon}\n"
        f"💥 <b>بحران‌های فعال ملی:</b> {len(active_crises)} بحران اضطراری\n"
        "🛰 <b>شبکه ماهواره‌های تجسسی:</b> آنلاین و پایش ۲۴ ساعته\n"
        "⚓️ <b>ناوگان مستقر در آب‌های بین‌المللی:</b> ۶ ناوگروه هواپیمابر در وضعیت رزمی\n\n"
        "<i>تمامی ارتباطات نظامی و امنیتی از طریق این مرکز کنترل می‌گردد.</i>"
    )
    await safe_edit(call, text, reply_markup=_back_to_desk_kb(m.role_key if m else "president"))


@router.callback_query(F.data == "cab:action:eval_ministers")
async def cb_eval_ministers(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """توبیخ یا تشویق وزرا توسط رئیس‌جمهور."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.PRESIDENT.value:
        await call.answer("فقط رئیس‌جمهور صلاحیت ارزیابی وزرا را دارد.", show_alert=True)
        return
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, "🎖 <b>کدام مقام را جهت توبیخ یا تشویق انتخاب می‌کنید؟</b>", reply_markup=cabinet_select_official_kb(members, prefix="cab:eval_pick"))


@router.callback_query(F.data.startswith("cab:eval_pick:"))
async def cb_eval_pick(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    target_role = call.data.split(":")[2]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎖 تشویق (+۱۰ سرمایه، +۵۰۰$ بودجه)", callback_data=f"cab:eval_do:{target_role}:praise", style=STYLE_OK),
                InlineKeyboardButton(text="⚡️ توبیخ (-۱۰ سرمایه، -۵۰۰$ بودجه)", callback_data=f"cab:eval_do:{target_role}:reprimand", style=STYLE_NO),
            ],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="cab:menu", style=STYLE_MAIN)],
        ]
    )
    await safe_edit(call, f"🎖 <b>ارزیابی عملکرد مقام: {target_role}</b>\nنوع اقدام را انتخاب کنید:", reply_markup=kb)


@router.callback_query(F.data.startswith("cab:eval_do:"))
async def cb_eval_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    parts = call.data.split(":")
    target_role = parts[2]
    act_type = parts[3]

    if act_type == "praise":
        await cabinet_repo.modify_capital(session, target_role, 10)
        await cabinet_repo.modify_budget(session, target_role, 500.0)
        msg = f"مقام {target_role} با تقدیر رئیس‌جمهور تشویق شد (+۱۰ سرمایه سیاسی، +۵۰۰$ بودجه) 🎖"
    else:
        await cabinet_repo.modify_capital(session, target_role, -10)
        await cabinet_repo.modify_budget(session, target_role, -500.0)
        msg = f"مقام {target_role} با دستور رئیس‌جمهور توبیخ شد (-۱۰ سرمایه سیاسی، -۵۰۰$ بودجه) ⚡️"

    await session.commit()
    await call.answer(msg, show_alert=True)
    await cb_cabinet_menu(call, session, db_user)


# ============================================================
#  سیستم بوروکراسی زنجیره‌ای (CabinetOperation)
# ============================================================


@router.callback_query(F.data == "cab:ops:menu")
async def cb_ops_menu(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی اصلی کارتابل پرونده‌های زنجیره‌ای."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    text = (
        "🔗 <b>کارتابل پرونده‌ها و بوروکراسی زنجیره‌ای ایالات متحده</b>\n\n"
        "در ساختار قدرت فدرال، هیچ اقدام کلانی تک‌نفره صورت نمی‌پذیرد.\n"
        "تمام فرامین نظامی، دیپلماتیک، اقتصادی، امنیتی و لوایح کنگره باید "
        "مراحل تایید ارگان‌های مربوطه را طی کنند.\n\n"
        "• هر امضا: <b>+۵ سرمایه سیاسی</b>\n"
        "• تکمیل کل زنجیره: <b>+۱۰ سرمایه سیاسی</b> به آغازگر\n"
        "• ممیزی DOGE و تعلیق قضایی DOJ امکان متوقف‌سازی پرونده‌ها را دارند."
    )
    await safe_edit(call, text, reply_markup=cabinet_operations_menu_kb())


@router.callback_query(F.data == "cab:ops:new")
async def cb_ops_new(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب نوع پرونده زنجیره‌ای جدید جهت گشایش."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return
    text = (
        "➕ <b>آغاز پرونده جدید در بوروکراسی فدرال</b>\n\n"
        "یکی از ۵ زنجیره عملیاتی زیر را انتخاب کنید:\n"
        "توجه: هزینه آغاز زنجیره از بودجه وزارتخانه شما (Allocated Budget) کسر می‌گردد."
    )
    await safe_edit(call, text, reply_markup=cabinet_chain_type_selection_kb())


@router.callback_query(F.data.startswith("cab:chain:start:"))
async def cb_chain_start(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ثبت و گشایش یک زنجیره عملیاتی جدید."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    chain_type = call.data.split(":")[3]
    cfg = OPERATION_CHAINS_CONFIG.get(chain_type)
    if not cfg:
        await call.answer("نوع پرونده نامعتبر است.", show_alert=True)
        return

    cost = cfg.get("budget_cost", 0.0)
    if m.allocated_budget < cost:
        await call.answer(
            f"⚠️ بودجه وزارتخانه شما کافی نیست! (موجود: {fa_money(m.allocated_budget)} | نیاز: {fa_money(cost)})\nابتدا درخواست بودجه ثبت کنید.",
            show_alert=True,
        )
        return

    m.allocated_budget -= cost
    op = await cabinet_repo.create_operation(
        session,
        op_type=chain_type,
        title=cfg["title"],
        initiator_role=m.role_key,
        steps=cfg["steps"],
        budget_cost=cost,
    )
    await session.commit()
    await call.answer("پرونده با موفقیت گشوده شد ✅", show_alert=True)
    await _show_operation_detail(call, session, op.id, m.role_key)


async def _show_operation_detail(call: CallbackQuery, session: AsyncSession, op_id: int, user_role: str) -> None:
    """هلپر مشترک نمایش جزئیات و پیشرفت یک پرونده زنجیره‌ای."""
    op = await cabinet_repo.get_operation(session, op_id)
    if not op:
        await call.answer("پرونده یافت نشد.", show_alert=True)
        return

    steps = json.loads(op.steps_json)
    history = json.loads(op.signed_by_json or "[]")

    can_sign = False
    if op.status == "PENDING" and 1 <= op.current_step <= len(steps):
        target_step = steps[op.current_step - 1]
        req_role = target_step.get("role")
        if req_role == "any" or req_role == user_role:
            can_sign = True

    status_fa = {
        "PENDING": "⏳ در جریان امضا",
        "DOGE_FROZEN": "✂️ فریز شده توسط DOGE",
        "DOJ_SUSPENDED": "⚖️ تعلیق قضایی توسط دادستان کل",
        "VETOED": "🚫 وتو شده توسط رئیس‌جمهور",
        "COMPLETED": "✅ تکمیل و اجرا شده",
        "EXPIRED": "⌛️ منقضی شده",
    }.get(op.status, op.status)

    lines = [
        f"🔗 <b>پرونده: {op.title}</b>",
        f"📌 <b>وضعیت:</b> {status_fa}",
        f"👤 <b>ارگان آغازگر:</b> {op.initiator_role}",
        f"💰 <b>هزینه بودجه:</b> {fa_money(op.budget_cost)}",
        f"🔢 <b>گام فعلی:</b> {op.current_step} از {len(steps)}",
        "────────────────────",
        "📋 <b>مراحل تایید و امضا:</b>",
    ]

    for s in steps:
        s_num = s.get("step", 1)
        s_role = s.get("role", "any")
        s_title = s.get("title", "")
        if s_num < op.current_step or (op.status == "COMPLETED" and s_num <= op.current_step):
            mark = "✅"
        elif s_num == op.current_step and op.status == "PENDING":
            mark = "⏳"
        elif op.status in ("DOGE_FROZEN", "DOJ_SUSPENDED", "VETOED"):
            mark = "🔒"
        else:
            mark = "⚪️"
        lines.append(f"{mark} گام {s_num} ({s_role}): {s_title}")

    lines.append("────────────────────")
    if history:
        lines.append("✍️ <b>امضاکنندگان:</b>")
        for h in history:
            lines.append(f"• گام {h.get('step')}: {h.get('role')} (ثبت در سیستم)")

    await safe_edit(call, "\n".join(lines), reply_markup=cabinet_operation_view_kb(op, user_role, can_sign))


@router.callback_query(F.data.startswith("cab:ops:active:"))
@router.callback_query(F.data.startswith("cab:ops:my:"))
@router.callback_query(F.data.startswith("cab:ops:history:"))
async def cb_ops_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده فهرست پرونده‌ها با فیلتر و صفحه‌بندی ۱۰تایی."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    parts = call.data.split(":")
    filter_type = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 1

    if filter_type == "my":
        operations, total_pages = await cabinet_repo.list_pending_for_role(session, m.role_key, page=page, limit=10)
        title_hdr = "کارتابل امضای من (در انتظار نوبت شما)"
    elif filter_type == "history":
        operations, total_pages = await cabinet_repo.list_operations(session, status="HISTORY", page=page, limit=10)
        title_hdr = "آرشیو پرونده‌های تکمیل یا بایگانی‌شده"
    else:
        operations, total_pages = await cabinet_repo.list_operations(session, status="ACTIVE", page=page, limit=10)
        title_hdr = "پرونده‌های فعال و در جریان کابینه"

    if not operations:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به کارتابل", callback_data="cab:ops:menu", style=STYLE_MAIN)]]
        )
        await safe_edit(call, f"📋 <b>{title_hdr}</b>\n\nهیچ پرونده‌ای در این بخش یافت نشد.", reply_markup=kb)
        return

    text = f"📋 <b>{title_hdr}</b> (صفحه {page} از {max(1, total_pages)}):\nبرای مشاهده جزئیات روی پرونده کلیک کنید:"
    await safe_edit(call, text, reply_markup=cabinet_operations_list_kb(operations, page, total_pages, filter_type))


@router.callback_query(F.data.startswith("cab:op:view:"))
async def cb_op_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده جزئیات یک پرونده."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    user_role = m.role_key if m else ""
    op_id = int(call.data.split(":")[3])
    await _show_operation_detail(call, session, op_id, user_role)


@router.callback_query(F.data.startswith("cab:op:sign:"))
async def cb_op_sign(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """امضا و پیشبرد گام پرونده توسط مقام مسئول."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.operation"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    op_id = int(call.data.split(":")[3])
    op, is_completed = await cabinet_repo.sign_operation_step(session, op_id, m.role_key, db_user.telegram_id)
    if not op:
        await call.answer("⚠️ امکان امضا وجود ندارد (نوبت شما نیست یا پرونده قفل است).", show_alert=True)
        return

    await cabinet_repo.modify_capital(session, m.role_key, 5)

    if is_completed:
        ok, res_msg = await execute_completed_operation(session, op.id)
        await session.commit()
        await call.answer("🎉 پرونده با موفقیت تکمیل و اجرا شد! (+۱۰ سرمایه سیاسی به آغازگر)", show_alert=True)
    else:
        await session.commit()
        await call.answer("✅ گام امضا شد و به مرحله بعد فرستاده شد (+۵ سرمایه سیاسی).", show_alert=True)

    await _show_operation_detail(call, session, op.id, m.role_key)


@router.callback_query(F.data.startswith("cab:op:freeze:"))
async def cb_op_freeze(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فریز پرونده به دلیل عدم صرفه اقتصادی توسط DOGE."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.TECH_EFFICIENCY.value:
        await call.answer("فقط وزیر کارآمدی (DOGE) اختیار فریز پرونده را دارد.", show_alert=True)
        return

    op_id = int(call.data.split(":")[3])
    op = await cabinet_repo.freeze_operation_doge(session, op_id, m.role_key)
    if not op:
        await call.answer("امکان فریز این پرونده وجود ندارد.", show_alert=True)
        return

    await session.commit()
    await call.answer("✂️ پرونده به دلیل عدم صرفه اقتصادی توسط DOGE فریز گردید.", show_alert=True)
    await _show_operation_detail(call, session, op.id, m.role_key)


@router.callback_query(F.data.startswith("cab:op:suspend:"))
async def cb_op_suspend(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تعلیق قضایی پرونده به دلیل مغایرت قانونی توسط دادستان کل."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.ATTORNEY_GENERAL.value:
        await call.answer("فقط دادستان کل اختیار تعلیق قضایی پرونده را دارد.", show_alert=True)
        return

    op_id = int(call.data.split(":")[3])
    op = await cabinet_repo.suspend_operation_doj(session, op_id, m.role_key)
    if not op:
        await call.answer("امکان تعلیق این پرونده وجود ندارد.", show_alert=True)
        return

    await session.commit()
    await call.answer("⚖️ پرونده به دلیل مغایرت قانونی توسط دادستان کل تعلیق گردید.", show_alert=True)
    await _show_operation_detail(call, session, op.id, m.role_key)


@router.callback_query(F.data.startswith("cab:op:unfreeze:"))
async def cb_op_unfreeze(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """شکستن قفل پرونده توسط رئیس‌جمهور یا حکمیت معاون رئیس‌جمهور."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key not in (CabinetRole.PRESIDENT.value, CabinetRole.VICE_PRESIDENT.value):
        await call.answer("تنها رئیس‌جمهور یا معاون رئیس‌جمهور امکان شکستن قفل را دارند.", show_alert=True)
        return

    if m.political_capital < 10:
        await call.answer("سرمایه سیاسی شما برای حکمیت و شکستن قفل کافی نیست (نیاز به ۱۰ سرمایه سیاسی).", show_alert=True)
        return

    op_id = int(call.data.split(":")[3])
    op = await cabinet_repo.unfreeze_operation(session, op_id, m.role_key)
    if not op:
        await call.answer("امکان شکستن قفل وجود ندارد.", show_alert=True)
        return

    await cabinet_repo.modify_capital(session, m.role_key, -10)
    await session.commit()
    await call.answer("🔓 قفل پرونده با حکمیت فدرال شکسته شد (-۱۰ سرمایه سیاسی).", show_alert=True)
    await _show_operation_detail(call, session, op.id, m.role_key)


@router.callback_query(F.data.startswith("cab:op:veto:"))
async def cb_op_veto(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """وتوی رسمی پرونده توسط رئیس‌جمهور."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.PRESIDENT.value:
        await call.answer("تنها شخص رئیس‌جمهور حق وتوی پرونده‌های فدرال را دارد.", show_alert=True)
        return

    op_id = int(call.data.split(":")[3])
    op = await cabinet_repo.veto_operation(session, op_id, m.role_key)
    if not op:
        await call.answer("امکان وتو وجود ندارد.", show_alert=True)
        return

    await session.commit()
    await call.answer("🚫 پرونده با وتوی رسمی رئیس‌جمهور بایگانی شد.", show_alert=True)
    await _show_operation_detail(call, session, op.id, m.role_key)


@router.callback_query(F.data == "cab:ops:veto_menu")
@router.callback_query(F.data == "cab:ops:arbitrate_menu")
@router.callback_query(F.data == "cab:ops:doge_freeze_menu")
@router.callback_query(F.data == "cab:ops:doj_suspend_menu")
async def cb_ops_shortcuts(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """میانبرهای دسترسی سریع مقامات به پرونده‌های قابل اقدام."""
    operations, total_pages = await cabinet_repo.list_operations(session, status="ACTIVE", page=1, limit=10)
    if not operations:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)]]
        )
        await safe_edit(call, "📋 هیچ پرونده فعالی جهت بررسی یافت نشد.", reply_markup=kb)
        return
    await safe_edit(
        call,
        "📋 <b>فهرست پرونده‌های در جریان جهت اقدام و بازبینی:</b>",
        reply_markup=cabinet_operations_list_kb(operations, 1, total_pages, "active"),
    )


# ============================================================
#  موتور بحران‌های فدرال (CabinetCrisis)
# ============================================================


@router.callback_query(F.data.startswith("cab:crises:list:"))
async def cb_crises_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست بحران‌های فعال و سابق کابینه با صفحه‌بندی ۱۰تایی."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.crisis"):
        return
    page = int(call.data.split(":")[3]) if len(call.data.split(":")) > 3 else 1
    crises, total_pages = await cabinet_repo.list_crises(session, page=page, limit=10)

    if not crises:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)]]
        )
        await safe_edit(call, "🚨 <b>مدیریت بحران‌های فدرال</b>\n\nدر حال حاضر هیچ بحران فعالی در کشور وجود ندارد. وضعیت عادی است ✅", reply_markup=kb)
        return

    text = f"🚨 <b>سامانه ملی مدیریت بحران‌های فدرال</b> (صفحه {page} از {max(1, total_pages)}):\nبرای بررسی و مشارکت در مهار روی بحران کلیک کنید:"
    await safe_edit(call, text, reply_markup=cabinet_crises_list_kb(crises, page, total_pages))


@router.callback_query(F.data.startswith("cab:crisis:view:"))
async def cb_crisis_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده جزئیات بحران و راهکارهای مهار آن."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.crisis"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    user_role = m.role_key if m else ""
    crisis_id = int(call.data.split(":")[3])
    crisis = await cabinet_repo.get_crisis(session, crisis_id)
    if not crisis:
        await call.answer("بحران یافت نشد.", show_alert=True)
        return

    status_fa = {
        "ACTIVE": "🚨 فعال و اضطراری",
        "RESOLVED": "✅ مهار شده با موفقیت",
        "FAILED": "💥 شکست در مهار (منقضی شده)",
    }.get(crisis.status, crisis.status)

    stars = "⭐️" * min(5, max(1, crisis.severity))
    pr_status = "✅ تایید شده" if crisis.primary_approved else "⏳ در انتظار اقدام"
    sec_status = "✅ تایید شده" if crisis.secondary_approved else "⏳ در انتظار اقدام"

    lines = [
        f"🚨 <b>بحران ملی: {crisis.title}</b>",
        f"⚠️ <b>شدت بحران:</b> {stars} (سطح {crisis.severity})",
        f"📌 <b>وضعیت:</b> {status_fa}",
        f"📂 <b>دسته‌بندی:</b> {crisis.category}",
        f"👮‍♂️ <b>مسئول اول:</b> {crisis.primary_role} [{pr_status}]",
        f"🤝 <b>مسئول دوم:</b> {crisis.secondary_role} [{sec_status}]",
        "────────────────────",
        f"📖 <b>شرح وضعیت اضطراری:</b>\n{crisis.description}",
        "────────────────────",
    ]

    if crisis.options_json and crisis.status == "ACTIVE":
        lines.append("🛠 <b>راهکارهای پیشنهادی مهار بحران:</b>")
        for idx, opt in enumerate(crisis.options_json):
            c_type = opt.get("cost_type", "capital")
            c_val = opt.get("cost_val", 0)
            cost_str = f"{fa_number(c_val)} سرمایه سیاسی" if c_type == "capital" else fa_money(c_val)
            lines.append(f"• <b>راهکار {idx + 1} ({opt.get('title')}):</b> هزینه: {cost_str}\n  {opt.get('desc')}")
        lines.append("────────────────────\n<i>برای حل بحران، هر دو مقام مسئول باید راهکار مورد نظر را تایید کنند.</i>")

    await safe_edit(call, "\n".join(lines), reply_markup=cabinet_crisis_view_kb(crisis, user_role))


@router.callback_query(F.data.startswith("cab:crisis:solve:"))
async def cb_crisis_solve(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ثبت انتخاب و امضای راهکار بحران توسط یکی از دو مسئول."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.crisis"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    parts = call.data.split(":")
    crisis_id = int(parts[3])
    opt_idx = int(parts[4])

    ok, msg = await resolve_crisis_step(session, crisis_id, m.role_key, opt_idx)
    await session.commit()
    await call.answer(msg, show_alert=True)

    crisis = await cabinet_repo.get_crisis(session, crisis_id)
    if crisis:
        await cb_crisis_view(call, session, db_user)


# ============================================================
#  کارتابل بودجه وزارتخانه‌ها (CabinetBudgetRequest)
# ============================================================


@router.callback_query(F.data.startswith("cab:budget:inbox:"))
async def cb_budget_inbox(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده کارتابل بودجه و درخواست‌ها."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.budget_req"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    is_treasury = (m.role_key == CabinetRole.TREASURY_SECRETARY.value)
    page = int(call.data.split(":")[3]) if len(call.data.split(":")) > 3 else 1
    requests, total_pages = await cabinet_repo.list_budget_requests(
        session,
        role_key=None if is_treasury else m.role_key,
        page=page,
        limit=10,
    )

    hdr = "کارتابل تخصیص بودجه فدرال (خزانه‌داری)" if is_treasury else "درخواست‌های بودجه وزارتخانه شما"
    if not requests:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ درخواست بودجه جدید", callback_data="cab:budget:req", style=STYLE_OK)] if not is_treasury else [],
                [InlineKeyboardButton(text="🔙 بازگشت به میز کار", callback_data="cab:menu", style=STYLE_MAIN)],
            ]
        )
        await safe_edit(call, f"🏦 <b>{hdr}</b>\n\nهیچ درخواستی در کارتابل موجود نیست.", reply_markup=kb)
        return

    text = f"🏦 <b>{hdr}</b> (صفحه {page} از {max(1, total_pages)}):\nبرای بررسی روی درخواست کلیک کنید:"
    await safe_edit(call, text, reply_markup=cabinet_budget_requests_list_kb(requests, page, total_pages, is_treasury))


@router.callback_query(F.data.startswith("cab:budget:view:"))
async def cb_budget_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده جزئیات یک درخواست بودجه."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.budget_req"):
        return
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی ندارید.", show_alert=True)
        return

    req_id = int(call.data.split(":")[3])
    req = await cabinet_repo.get_budget_request(session, req_id)
    if not req:
        await call.answer("درخواست بودجه یافت نشد.", show_alert=True)
        return

    is_treasury = (m.role_key == CabinetRole.TREASURY_SECRETARY.value)
    status_fa = {
        "PENDING": "⏳ در انتظار بررسی خزانه‌داری",
        "APPROVED": "✅ موافقت کامل و تخصیص یافته",
        "REJECTED": "❌ رد شده توسط وزیر خزانه‌داری",
        "ADJUSTED": "✂️ تعدیل و نصف شده",
    }.get(req.status, req.status)

    lines = [
        f"🏦 <b>درخواست بودجه وزارتخانه: {req.department_role}</b>",
        f"📌 <b>وضعیت:</b> {status_fa}",
        f"💵 <b>مبلغ درخواستی:</b> {fa_money(req.requested_amount)}",
        f"💰 <b>مبلغ نهایی تخصیص‌یافته:</b> {fa_money(req.approved_amount)}",
        "────────────────────",
        f"📝 <b>دلیل و توجیه درخواست:</b>\n{req.reason}",
        "────────────────────",
    ]
    await safe_edit(call, "\n".join(lines), reply_markup=cabinet_budget_request_view_kb(req, is_treasury))


@router.callback_query(F.data.startswith("cab:budget:act:"))
async def cb_budget_act(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اقدام وزیر خزانه‌داری روی درخواست بودجه (تایید، نصف، رد)."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m or m.role_key != CabinetRole.TREASURY_SECRETARY.value:
        await call.answer("تنها وزیر خزانه‌داری صلاحیت تخصیص بودجه دارد.", show_alert=True)
        return

    parts = call.data.split(":")
    req_id = int(parts[3])
    action = parts[4]

    ok, msg = await approve_or_reject_budget_request(session, req_id, action)
    await session.commit()
    await call.answer(msg, show_alert=True)

    await cb_budget_view(call, session, db_user)


@router.callback_query(F.data == "cab:budget:req")
async def cb_budget_req(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """آغاز فرم درخواست بودجه وزارتخانه."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return
    if m.role_key == CabinetRole.TREASURY_SECRETARY.value:
        await call.answer("شما وزیر خزانه‌داری هستید و خودتان بودجه‌ها را تخصیص می‌دهید!", show_alert=True)
        return

    await state.set_state(CabinetBudgetRequestForm.entering_amount)
    await call.message.answer("💵 <b>درخواست بودجه از خزانه فدرال:</b>\nلطفاً مبلغ مورد نیاز خود را به دلار ارسال کنید (مثلاً: 5000):")


@router.message(CabinetBudgetRequestForm.entering_amount, F.text)
async def msg_budget_amount(message: Message, state: FSMContext) -> None:
    """دریافت مبلغ بودجه درخواستی."""
    raw = message.text.replace(",", "").replace("$", "").strip()
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ لطفاً یک عدد معتبر و مثبت به دلار وارد کنید:")
        return

    await state.update_data(budget_amount=amount)
    await state.set_state(CabinetBudgetRequestForm.entering_reason)
    await message.answer(f"📝 مبلغ درخواستی: <b>{fa_money(amount)}</b>\nحالا دلیل و زمینه مصرف این بودجه را به تفصیل بنویسید:")


@router.message(CabinetBudgetRequestForm.entering_reason, F.text)
async def msg_budget_reason(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت نهایی درخواست بودجه."""
    data = await state.get_data()
    amount = data.get("budget_amount", 1000.0)
    reason = message.text.strip()
    await state.clear()

    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await message.answer("خطا: سمت شما در کابینه یافت نشد.")
        return

    ok, msg = await request_department_budget(session, m.role_key, amount, reason)
    await session.commit()
    await message.answer(f"✅ {msg}")


# ============================================================
#  اهداف و ماموریت‌های محرمانه (CabinetAgenda)
# ============================================================


@router.callback_query(F.data == "cab:agenda:view")
async def cb_agenda_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده ماموریت محرمانه ۲۴ ساعته مقام دولتی."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    agenda = await cabinet_repo.get_active_agenda(session, m.role_key)
    if not agenda:
        text = (
            "🎯 <b>ماموریت محرمانه ۲۴ ساعته (Secret Agenda)</b>\n\n"
            "شما هم‌اکنون هیچ هدف محرمانه‌ای ندارید.\n"
            "هر مقام در هر شبانه‌روز می‌تواند یک ماموریت ویژه دریافت کند.\n"
            "پاداش تکمیل موفق: <b>+۱۵ سرمایه سیاسی</b>\n\n"
            "روی دکمه زیر بزنید تا ماموریت امروز شما صادر شود:"
        )
    else:
        st_icon = "🎁 آماده دریافت پاداش!" if (agenda.is_completed and not agenda.reward_claimed) else ("✅ تکمیل شده" if agenda.is_completed else "⏳ در حال انجام")
        text = (
            f"🎯 <b>ماموریت محرمانه: {agenda.title}</b>\n\n"
            f"📌 <b>وضعیت:</b> {st_icon}\n"
            f"📊 <b>پیشرفت هدف:</b> {agenda.current_progress} از {agenda.target_value}\n"
            f"🎁 <b>پاداش:</b> +۱۵ سرمایه سیاسی\n"
            "────────────────────\n"
            f"📜 <b>شرح ماموریت محرمانه:</b>\n{agenda.description}\n"
            "────────────────────"
        )
    await safe_edit(call, text, reply_markup=cabinet_agenda_view_kb(agenda))


@router.callback_query(F.data == "cab:agenda:claim_new")
async def cb_agenda_claim_new(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تولید و تخصیص ماموریت محرمانه جدید ۲۴ ساعته."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    agenda = await cabinet_repo.get_active_agenda(session, m.role_key)
    if agenda:
        await call.answer("شما هم‌اکنون یک ماموریت محرمانه فعال دارید.", show_alert=True)
        return

    import random
    templates = [
        ("امضای ۲ پرونده در زنجیره بوروکراتیک", "امروز حداقل ۲ مرحله از پرونده‌های زنجیره‌ای ارسالی به کارتابل خود را امضا کنید.", "sign_op", 2),
        ("افزایش بودجه وزارتخانه به میزان ۲۰٪", "یک درخواست بودجه موفق به خزانه‌داری ارسال کنید تا بودجه وزارتخانه شما شارژ شود.", "increase_budget", 1),
        ("مشارکت در حل یک بحران اضطراری فدرال", "در تصمیم‌گیری و تایید راهکار یکی از بحران‌های فعال کابینه همکاری کنید.", "resolve_crisis", 1),
        ("ممیزی یا بازرسی یک ارگان فدرال", "از ابزارهای نظارتی مقام خود جهت بازرسی یا ممیزی سایر بخش‌ها بهره ببرید.", "inspect_audit", 1),
    ]
    title, desc, t_type, t_val = random.choice(templates)
    await cabinet_repo.create_agenda(session, m.role_key, title, desc, t_type, t_val)
    await session.commit()
    await call.answer("ماموریت محرمانه صادر شد 🎯", show_alert=True)
    await cb_agenda_view(call, session, db_user)


@router.callback_query(F.data == "cab:agenda:claim_reward")
async def cb_agenda_claim_reward(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """دریافت پاداش سرمایه سیاسی ماموریت محرمانه تکمیل‌شده."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return

    agenda = await cabinet_repo.get_active_agenda(session, m.role_key)
    if not agenda:
        await call.answer("ماموریتی یافت نشد.", show_alert=True)
        return

    ok, msg = await claim_agenda_reward(session, agenda.id)
    await session.commit()
    await call.answer(msg, show_alert=True)
    await cb_agenda_view(call, session, db_user)


# ============================================================
#  درز اطلاعات به رسانه‌ها (CabinetLeak)
# ============================================================


@router.callback_query(F.data == "cab:leak:menu")
async def cb_leak_menu(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی افشاگری و درز اطلاعات به رسانه‌ها."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.leak"):
        return
    text = (
        "📰 <b>درز اطلاعات محرمانه به رسانه‌ها (افشاگری ناشناس)</b>\n\n"
        "شما می‌توانید علیه عملکرد ضعیف، هدررفت بودجه یا اقدامات جنجالی "
        "یک وزارتخانه دیگر، اسناد و بیانیه محرمانه به رسانه‌ها درز دهید.\n\n"
        "⚠️ <b>پیامدهای بازی:</b>\n"
        "• کاهش <b>۱۰ سرمایه سیاسی</b> از مقام قربانی\n"
        "• افزایش <b>+۳۰ واحد مظنونیت امنیتی (Leak Suspicion)</b> برای شما!\n"
        "• در صورتی که وزیر امنیت داخلی و دادستان کل شما را کشف کنند، مجازات سنگینی در انتظار شماست."
    )
    await safe_edit(call, text, reply_markup=cabinet_leak_menu_kb())


@router.callback_query(F.data.startswith("cab:leak:list:"))
async def cb_leak_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست درزهای اطلاعاتی با صفحه‌بندی ۱۰تایی."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.leak"):
        return
    page = int(call.data.split(":")[3]) if len(call.data.split(":")) > 3 else 1
    leaks, total_pages = await cabinet_repo.list_leaks(session, page=page, limit=10)

    if not leaks:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به منوی افشاگری", callback_data="cab:leak:menu", style=STYLE_MAIN)]]
        )
        await safe_edit(call, "📋 هیچ درز اطلاعاتی در رسانه‌ها ثبت نشده است.", reply_markup=kb)
        return

    text = f"📋 <b>گزارش درزهای اطلاعاتی به رسانه‌ها</b> (صفحه {page} از {max(1, total_pages)}):\nبرای مشاهده گزارش کامل کلیک کنید:"
    await safe_edit(call, text, reply_markup=cabinet_leaks_list_kb(leaks, page, total_pages))


@router.callback_query(F.data.startswith("cab:leak:view:"))
async def cb_leak_view(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مشاهده جزئیات یک افشاگری رسانه‌ای."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "cab.leak"):
        return
    leak_id = int(call.data.split(":")[3])
    lk = await cabinet_repo.get_leak(session, leak_id)
    if not lk:
        await call.answer("افشاگری یافت نشد.", show_alert=True)
        return

    lines = [
        f"📰 <b>تیتر افشاگری: {lk.headline}</b>",
        f"🎯 <b>وزارتخانه هدف:</b> {lk.target_role}",
        f"👤 <b>منبع خبر:</b> منبع موثق و ناشناس در کاخ سفید",
        "────────────────────",
        f"📝 <b>متن منتشرشده در رسانه‌ها:</b>\n{lk.content}",
        "────────────────────",
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به فهرست", callback_data="cab:leak:list:1", style=STYLE_MAIN)]]
    )
    await safe_edit(call, "\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "cab:leak:new")
async def cb_leak_new(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """انتخاب مقام هدف جهت افشاگری رسانه‌ای."""
    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await call.answer("شما سمتی در کابینه ندارید.", show_alert=True)
        return
    members = await cabinet_repo.list_members(session)
    await safe_edit(call, "🎯 <b>کدام وزارتخانه را هدف افشاگری رسانه‌ای قرار می‌دهید؟</b>", reply_markup=cabinet_select_official_kb(members, prefix="cab:leak_to"))


@router.callback_query(F.data.startswith("cab:leak_to:"))
async def cb_leak_pick_target(call: CallbackQuery, state: FSMContext) -> None:
    """دریافت تیتر افشاگری رسانه‌ای."""
    target_role = call.data.split(":")[2]
    await state.update_data(leak_target=target_role)
    await state.set_state(CabinetLeakForm.entering_headline)
    await call.message.answer(f"📰 هدف: <b>{target_role}</b>\nلطفاً <b>تیتر جنجالی افشاگری</b> را ارسال کنید:")


@router.message(CabinetLeakForm.entering_headline, F.text)
async def msg_leak_headline(message: Message, state: FSMContext) -> None:
    """دریافت متن افشاگری رسانه‌ای."""
    await state.update_data(leak_headline=message.text.strip())
    await state.set_state(CabinetLeakForm.entering_content)
    await message.answer("📝 حالا <b>متن کامل اسناد یا افشاگری</b> را برای درج در رسانه‌ها ارسال کنید:")


@router.message(CabinetLeakForm.entering_content, F.text)
async def msg_leak_content(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت نهایی افشاگری رسانه‌ای."""
    data = await state.get_data()
    target = data.get("leak_target", "government")
    headline = data.get("leak_headline", "افشاگری کاخ سفید")
    content = message.text.strip()
    await state.clear()

    m = await cabinet_repo.get_member_by_user(session, db_user.telegram_id)
    if not m:
        await message.answer("خطا: سمت شما یافت نشد.")
        return

    ok, msg = await leak_confidential_info(session, m.role_key, target, headline, content)
    await session.commit()
    await message.answer(f"📰 {msg}\n\n<i>شاخص مظنونیت امنیتی شما ۳۰ واحد افزایش یافت.</i>")
