"""هندلرهای مربوط به سیستم رول‌ها و پروژه‌های اقتصادی (آپدیت شماره ۹)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    ECON_PROJECT_YIELD_INTERVAL_HOURS,
    ECON_ROLE_LIMIT_COUNT,
    ECON_ROLE_LIMIT_HOURS,
    MAX_ROLE_PAGE_LEN,
)
from ..database.models import Country, EconomicProject, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import economic_projects as proj_repo
from ..enums import AdminGroupType, EconomicProjectStatus, ResourceType
from ..keyboards.economic_projects import (
    admin_approve_settings_kb,
    admin_group_project_kb,
    admin_quick_cash_kb,
    admin_quick_yield_kb,
    admin_rejection_reasons_kb,
    admin_resource_picker_kb,
    econ_projects_home_kb,
    project_active_view_kb,
    project_delete_confirm_kb,
    project_draft_view_kb,
    project_list_kb,
    project_pending_view_kb,
    project_submit_confirm_kb,
)
from ..loader import bot
from ..services.economic_project_service import (
    approve_and_launch_project,
    format_resources_dict,
    launch_awaiting_project,
    reject_project,
    render_project_message,
    validate_role_page,
)
from ..services.news_service import send_log, send_to_admin_group
from ..states.forms import AdminProjectReviewForm, EconProjectDraftForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="economic_projects")
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _format_cooldown(rem_seconds: int | float) -> str:
    rem_sec = max(0, int(rem_seconds))
    h = rem_sec // 3600
    m = (rem_sec % 3600) // 60
    if h > 0 and m > 0:
        return f"{fa_number(h)} ساعت و {fa_number(m)} دقیقه"
    elif h > 0:
        return f"{fa_number(h)} ساعت"
    else:
        return f"{fa_number(max(1, m))} دقیقه"


# ============================================================
#  ورودی و منوی اصلی پروژه‌ها
# ============================================================

@router.callback_query(F.data == "econ:projects")
async def cb_projects_home(
    call: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext | None = None
) -> None:
    await call.answer()
    if state:
        await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.projects"):
        return

    now = _utcnow()
    since = now - timedelta(hours=ECON_ROLE_LIMIT_HOURS)
    used = await proj_repo.count_projects_by_country_since(session, country.id, since)
    rem_quota = max(0, ECON_ROLE_LIMIT_COUNT - used)
    if rem_quota > 0:
        quota_line = f"\n📊 <b>سهمیه رول اقتصادی شما:</b> {fa_number(rem_quota)} از {fa_number(ECON_ROLE_LIMIT_COUNT)} (در {fa_number(ECON_ROLE_LIMIT_HOURS)} ساعت)\n"
    else:
        earliest = await proj_repo.get_earliest_project_since(session, country.id, since)
        rem_str = "به‌زودی"
        if earliest and earliest.created_at:
            earliest_aware = _aware(earliest.created_at)
            rem_sec = max(0, int((earliest_aware + timedelta(hours=ECON_ROLE_LIMIT_HOURS) - now).total_seconds()))
            rem_str = _format_cooldown(rem_sec)
        quota_line = f"\n⏳ <b>سهمیه ۲۴ ساعته شما پر است.</b> آزادسازی سهمیه بعدی: {rem_str}\n"

    text = (
        header("پروژه‌های اقتصادی (رول)", "🏗")
        + f"{quota_line}\n"
        "از این بخش می‌توانید رول‌ها و پروژه‌های توسعه اقتصادی کشور خود را تدوین کنید.\n"
        "پس از نگارش متن (تا ۲ صفحه)، پروژه جهت داوری و تخصیص بودجه و بازدهی ۷۲ ساعته به تیم مدیریت ارسال خواهد شد.\n\n"
        "📌 گزینه‌ی مورد نظر را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=econ_projects_home_kb())


# ============================================================
#  فهرست‌ها: پیش‌نویس‌ها، در حال بررسی، فعال
# ============================================================

@router.callback_query(F.data == "econ_proj:drafts")
async def cb_drafts_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    drafts = await proj_repo.list_drafts_by_country(session, country.id)
    if not drafts:
        await safe_edit(
            call,
            "📝 شما در حال حاضر هیچ پیش‌نویس پروژه‌ای ندارید.\nبرای ایجاد پروژه جدید از دکمه زیر استفاده کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ تعریف پروژه جدید", callback_data="econ_proj:new", style=STYLE_OK)],
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:projects", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = header("پیش‌نویس‌های من (قابل ویرایش)", "📝") + "\n\nجهت مشاهده، ویرایش یا ارسال نهایی پروژه را انتخاب کنید:"
    await safe_edit(call, text, reply_markup=project_list_kb(drafts, "econ:projects", "ep_view"))


@router.callback_query(F.data == "econ_proj:pending")
async def cb_pending_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    projects = await proj_repo.list_pending_or_awaiting_by_country(session, country.id)
    if not projects:
        await safe_edit(
            call,
            "⏳ در حال حاضر هیچ پروژه‌ای در انتظار بررسی یا در انتظار افتتاح ندارید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:projects", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = header("پروژه‌های ارسالی و در انتظار افتتاح", "⏳") + "\n\nبرای مشاهده وضعیت، پروژه را انتخاب کنید:"
    await safe_edit(call, text, reply_markup=project_list_kb(projects, "econ:projects", "ep_view"))


@router.callback_query(F.data == "econ_proj:active")
async def cb_active_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    projects = await proj_repo.list_active_by_country(session, country.id)
    if not projects:
        await safe_edit(
            call,
            "📈 در حال حاضر هیچ پروژه فعالی ندارید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:projects", style=STYLE_MAIN)],
                ]
            ),
        )
        return

    text = header("پروژه‌های فعال و در حال سوددهی", "📈") + "\n\nپروژه مورد نظر را جهت مشاهده جزئیات انتخاب کنید:"
    await safe_edit(call, text, reply_markup=project_list_kb(projects, "econ:projects", "ep_view"))


# ============================================================
#  مشاهده یک پروژه و ورق زدن صفحات
# ============================================================

@router.callback_query(F.data.startswith("ep_view:"))
async def cb_view_project(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    page_num = int(parts[2]) if len(parts) > 2 else 1

    project = await proj_repo.get_project(session, proj_id)
    if project is None:
        await safe_edit(call, "❌ پروژه یافت نشد.", reply_markup=econ_projects_home_kb())
        return

    country = await countries_repo.get_country(session, project.country_id)
    if country is None:
        await safe_edit(call, "❌ کشور یافت نشد.")
        return

    msg_text = render_project_message(country, project, page_num, db_user)

    # انتخاب کیبورد مناسب وضعیت
    if project.status == EconomicProjectStatus.DRAFT.value:
        kb = project_draft_view_kb(project, page_num)
    elif project.status in (
        EconomicProjectStatus.PENDING_REVIEW.value,
        EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value,
    ):
        kb = project_pending_view_kb(project, page_num)
    elif project.status == EconomicProjectStatus.ACTIVE.value:
        kb = project_active_view_kb(project, page_num)
    else:
        # ردشده یا لغوشده
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت به پروژه‌ها", callback_data="econ:projects", style=STYLE_MAIN)],
            ]
        )

    await safe_edit(call, msg_text, reply_markup=kb)


# ============================================================
#  فلوی ایجاد پروژه جدید (FSM)
# ============================================================

@router.callback_query(F.data == "econ_proj:new")
async def cb_new_project(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.projects"):
        return

    now = _utcnow()
    since = now - timedelta(hours=ECON_ROLE_LIMIT_HOURS)
    used = await proj_repo.count_projects_by_country_since(session, country.id, since)
    if used >= ECON_ROLE_LIMIT_COUNT:
        earliest = await proj_repo.get_earliest_project_since(session, country.id, since)
        rem_str = "به‌زودی"
        if earliest and earliest.created_at:
            rem_sec = max(0, int((_aware(earliest.created_at) + timedelta(hours=ECON_ROLE_LIMIT_HOURS) - now).total_seconds()))
            rem_str = _format_cooldown(rem_sec)
        await call.answer(
            f"⏳ سقف مجاز ثبت رول اقتصادی شما ({fa_number(ECON_ROLE_LIMIT_COUNT)} رول در {fa_number(ECON_ROLE_LIMIT_HOURS)} ساعت) پر است.\n"
            f"زمان باقیمانده تا ثبت بعدی: {rem_str}",
            show_alert=True,
        )
        return

    await state.set_state(EconProjectDraftForm.entering_title)
    await safe_edit(
        call,
        "🏗 <b>تعریف پروژه جدید</b>\n\nلطفاً <b>نام / عنوان پروژه</b> خود را ارسال کنید (حداکثر ۵۰ کاراکتر):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="econ:projects", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(EconProjectDraftForm.entering_title))
async def msg_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 50:
        await message.answer("⚠️ لطفاً نام پروژه را حداکثر تا ۵۰ کاراکتر وارد کنید:")
        return

    await state.update_data(title=title)
    await state.set_state(EconProjectDraftForm.entering_page_1)
    await message.answer(
        f"✅ عنوان پروژه: <b>{title}</b>\n\n"
        f"اکنون <b>متن صفحه اول</b> رول اقتصادی خود را ارسال کنید.\n"
        f"⚠️ <b>توجه:</b> حداکثر سقف مجاز <b>{fa_number(MAX_ROLE_PAGE_LEN)}</b> کاراکتر است.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="econ:projects", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(EconProjectDraftForm.entering_page_1))
async def msg_page_1(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    valid, err_msg = validate_role_page(text)
    if not valid:
        await message.answer(err_msg)
        return

    await state.update_data(page_1=text)
    await state.set_state(EconProjectDraftForm.entering_page_2)
    await message.answer(
        f"✅ صفحه اول با موفقیت ثبت شد ({fa_number(len(text))} کاراکتر).\n\n"
        f"در صورتی که رول شما ۲ صفحه‌ای است، اکنون <b>متن صفحه دوم</b> را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر).\n"
        f"در غیر این صورت، دکمه <b>«⏭ بدون صفحه دوم / رفتن به مرحله بعد»</b> را بزنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ بدون صفحه دوم / رفتن به مرحله بعد", callback_data="ep_skip_p2", style=STYLE_OK)],
                [InlineKeyboardButton(text="❌ انصراف", callback_data="econ:projects", style=STYLE_NO)],
            ]
        ),
    )


@router.callback_query(F.data == "ep_skip_p2", StateFilter(EconProjectDraftForm.entering_page_2))
async def cb_skip_p2(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(page_2=None)
    await state.set_state(EconProjectDraftForm.entering_budget)
    await safe_edit(
        call,
        "💰 لطفاً <b>بودجه پیشنهادی / مورد نیاز</b> برای این پروژه را به دلار وارد کنید (مثلاً: 50M یا 100000000):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="econ:projects", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(EconProjectDraftForm.entering_page_2))
async def msg_page_2(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    valid, err_msg = validate_role_page(text)
    if not valid:
        await message.answer(err_msg)
        return

    await state.update_data(page_2=text)
    await state.set_state(EconProjectDraftForm.entering_budget)
    await message.answer(
        f"✅ صفحه دوم با موفقیت ثبت شد ({fa_number(len(text))} کاراکتر).\n\n"
        f"💰 لطفاً <b>بودجه پیشنهادی / مورد نیاز</b> برای این پروژه را به دلار وارد کنید (مثلاً: 50M یا 100000000):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data="econ:projects", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(EconProjectDraftForm.entering_budget))
async def msg_budget(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    raw = (message.text or "").strip()
    amount = parse_amount(raw)
    if amount is None or amount < 0:
        await message.answer("⚠️ لطفاً مبلغ بودجه پیشنهادی را به‌درستی وارد کنید (مثال: 50M یا 100,000,000):")
        return

    data = await state.get_data()
    country = await get_player_country(session, db_user)
    if country is None:
        await message.answer(NO_COUNTRY_TEXT)
        await state.clear()
        return

    project = EconomicProject(
        country_id=country.id,
        title=data["title"],
        page_1=data["page_1"],
        page_2=data.get("page_2"),
        proposed_budget=amount,
        status=EconomicProjectStatus.DRAFT.value,
    )
    await proj_repo.create_project(session, project)
    await session.commit()
    await state.clear()

    # رندر صفحه پیش‌نویس
    msg_text = render_project_message(country, project, 1, db_user)
    await message.answer(
        f"🎉 <b>پیش‌نویس پروژه با موفقیت ذخیره شد!</b>\n\n{msg_text}",
        reply_markup=project_draft_view_kb(project, 1),
    )


# ============================================================
#  ویرایش پیش‌نویس
# ============================================================

@router.callback_query(F.data.startswith("ep_edit_"))
async def cb_start_edit_field(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    parts = call.data.split(":")
    field = parts[0].replace("ep_edit_", "")
    proj_id = int(parts[1])

    await state.set_state(EconProjectDraftForm.editing_field)
    await state.update_data(project_id=proj_id, field=field)

    prompts = {
        "title": "لطفاً عنوان جدید پروژه را وارد کنید (حداکثر ۵۰ کاراکتر):",
        "budget": "لطفاً بودجه پیشنهادی جدید را به دلار وارد کنید:",
        "p1": f"لطفاً متن جدید صفحه ۱ را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
        "p2": f"لطفاً متن جدید صفحه ۲ را ارسال کنید (حداکثر {fa_number(MAX_ROLE_PAGE_LEN)} کاراکتر):",
    }
    await safe_edit(
        call,
        prompts.get(field, "لطفاً مقدار جدید را ارسال کنید:"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ انصراف", callback_data=f"ep_view:{proj_id}:1", style=STYLE_NO)],
            ]
        ),
    )


@router.message(StateFilter(EconProjectDraftForm.editing_field))
async def msg_save_edited_field(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    proj_id = data.get("project_id")
    field = data.get("field")
    raw = (message.text or "").strip()

    project = await proj_repo.get_project(session, proj_id)
    if project is None or project.status != EconomicProjectStatus.DRAFT.value:
        await message.answer("❌ این پروژه دیگر در حالت پیش‌نویس نیست یا حذف شده است.")
        await state.clear()
        return

    if field == "title":
        if not raw or len(raw) > 50:
            await message.answer("⚠️ عنوان باید حداکثر ۵۰ کاراکتر باشد:")
            return
        project.title = raw
    elif field == "budget":
        val = parse_amount(raw)
        if val is None or val < 0:
            await message.answer("⚠️ لطفاً مبلغ معتبر وارد کنید:")
            return
        project.proposed_budget = val
    elif field == "p1":
        valid, err = validate_role_page(raw)
        if not valid:
            await message.answer(err)
            return
        project.page_1 = raw
    elif field == "p2":
        valid, err = validate_role_page(raw)
        if not valid:
            await message.answer(err)
            return
        project.page_2 = raw

    await session.commit()
    await state.clear()

    country = await countries_repo.get_country(session, project.country_id)
    msg_text = render_project_message(country, project, 1, db_user)
    await message.answer(
        f"✅ <b>تغییرات با موفقیت ذخیره شد.</b>\n\n{msg_text}",
        reply_markup=project_draft_view_kb(project, 1),
    )


# ============================================================
#  حذف پروژه / لغو پیش‌نویس
# ============================================================

@router.callback_query(F.data.startswith("ep_delete_ask:"))
async def cb_delete_ask(call: CallbackQuery) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await safe_edit(
        call,
        "⚠️ <b>آیا از حذف یا لغو این پروژه اطمینان دارید؟</b>\nاین عملیات غیرقابل بازگشت است.",
        reply_markup=project_delete_confirm_kb(proj_id),
    )


@router.callback_query(F.data.startswith("ep_delete_do:"))
async def cb_delete_do(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if project:
        # اگر پیام در گروه رول داشت، پیام گروه را آپدیت یا حذف کن
        if project.admin_message_id and project.status == EconomicProjectStatus.PENDING_REVIEW.value:
            try:
                gid = settings.role_econ_group_id
                await bot.edit_message_text(
                    chat_id=gid,
                    message_id=project.admin_message_id,
                    text=f"🗑 <b>پروژه «{project.title}» توسط بازیکن لغو/حذف گردید.</b>",
                    reply_markup=None,
                )
            except Exception:
                pass
        await proj_repo.delete_project(session, project)
        await session.commit()

    await safe_edit(call, "✅ پروژه با موفقیت حذف گردید.", reply_markup=econ_projects_home_kb())


# ============================================================
#  ارسال نهایی به تیم مدیریت (با تأیید دومرحله‌ای)
# ============================================================

@router.callback_query(F.data.startswith("ep_submit_ask:"))
async def cb_submit_ask(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await safe_edit(call, "❌ پروژه یافت نشد.")
        return

    text = (
        f"⚠️ <b>تأییدیه ارسال نهایی پروژه</b>\n\n"
        f"آیا از ارسال نهایی پروژه <b>«{project.title}»</b> به تیم مدیریت مطمئن هستید؟\n"
        f"🔒 <b>توجه مهم:</b> پس از ارسال، متن رول و مشخصات پروژه قفل شده و دیگر قابل ویرایش نخواهد بود."
    )
    await safe_edit(call, text, reply_markup=project_submit_confirm_kb(proj_id))


@router.callback_query(F.data.startswith("ep_submit_do:"))
async def cb_submit_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if not project or project.status != EconomicProjectStatus.DRAFT.value:
        await safe_edit(call, "❌ پروژه یافت نشد یا قبلاً ارسال شده است.", reply_markup=econ_projects_home_kb())
        return

    country = await countries_repo.get_country(session, project.country_id)
    if not country:
        await safe_edit(call, "❌ کشور یافت نشد.")
        return

    now = _utcnow()
    since = now - timedelta(hours=ECON_ROLE_LIMIT_HOURS)
    used = await proj_repo.count_projects_by_country_since(session, country.id, since)
    if used >= ECON_ROLE_LIMIT_COUNT:
        earliest = await proj_repo.get_earliest_project_since(session, country.id, since)
        rem_str = "به‌زودی"
        if earliest and earliest.created_at:
            rem_sec = max(0, int((_aware(earliest.created_at) + timedelta(hours=ECON_ROLE_LIMIT_HOURS) - now).total_seconds()))
            rem_str = _format_cooldown(rem_sec)
        await safe_edit(
            call,
            f"⏳ متأسفانه سقف مجاز ثبت رول اقتصادی شما ({fa_number(ECON_ROLE_LIMIT_COUNT)} رول در {fa_number(ECON_ROLE_LIMIT_HOURS)} ساعت) پر شده است.\n"
            f"زمان باقیمانده تا ثبت بعدی: {rem_str}",
            reply_markup=econ_projects_home_kb(),
        )
        return

    # ۱. تغییر وضعیت به PENDING_REVIEW
    project.status = EconomicProjectStatus.PENDING_REVIEW.value

    # ۲. رندر متن پیام و ارسال به گروه رول اقتصادی (-1004359181892)
    group_text = render_project_message(country, project, 1, db_user)
    group_kb = admin_group_project_kb(project, 1)

    sent_msg = await send_to_admin_group(
        bot,
        AdminGroupType.ROLE_ECON,
        group_text,
        reply_markup=group_kb,
    )
    if sent_msg:
        project.admin_message_id = sent_msg.message_id

    await session.commit()

    # ۳. ثبت در گروه لاگ اصلی
    await send_log(
        bot,
        f"🏗 <b>ارسال رول اقتصادی جدید جهت بررسی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"عنوان: <b>{project.title}</b>\n"
        f"بودجه پیشنهادی: {fa_money(project.proposed_budget)}\n"
        f"تعداد صفحات: {fa_number(project.total_pages)}"
    )

    await safe_edit(
        call,
        "🚀 <b>پروژه با موفقیت به تیم مدیریت ارسال شد!</b>\n\n"
        "داوری پروژه و تعیین بازدهی در گروه رول اقتصادی انجام خواهد شد و نتیجه از طریق همین ربات به اطلاع شما خواهد رسید.",
        reply_markup=econ_projects_home_kb(),
    )


# ============================================================
#  داوری ادمین در گروه رول اقتصادی (-1004359181892)
# ============================================================

@router.callback_query(F.data.startswith("ep_grp_page:"))
async def cb_grp_page(call: CallbackQuery, session: AsyncSession) -> None:
    """ورق زدن رول در گروه رول اقتصادی توسط ادمین."""
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    page_num = int(parts[2])

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        return
    country = await countries_repo.get_country(session, project.country_id)
    if not country:
        return

    text = render_project_message(country, project, page_num)
    kb = admin_group_project_kb(project, page_num)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("ep_grp_reject:"))
async def cb_grp_reject_menu(call: CallbackQuery) -> None:
    """نمایش منوی دلایل رد رول در گروه."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=admin_rejection_reasons_kb(proj_id))


@router.callback_query(F.data.startswith("ep_rj_quick:"))
async def cb_grp_reject_quick(call: CallbackQuery, session: AsyncSession) -> None:
    """رد رول با یکی از دلایل سریع و آماده."""
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    reason = parts[2]

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        return

    admin_user = call.from_user
    admin_name = admin_user.full_name or f"@{admin_user.username}" if admin_user.username else str(admin_user.id)

    await reject_project(session, project, admin_user.id, reason)
    await session.commit()

    # به‌روزرسانی پیام گروه
    new_text = (call.message.text or "") + f"\n\n❌ <b>رد شد توسط {admin_name}</b>\n<b>دلیل:</b> {reason}"
    try:
        await call.message.edit_text(new_text, reply_markup=None)
    except Exception:
        pass

    # پیام به پیوی بازیکن
    country = await countries_repo.get_country(session, project.country_id)
    if country and country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"❌ <b>پروژه رول اقتصادی شما رد شد</b>\n\n"
                f"عنوان پروژه: <b>{project.title}</b>\n"
                f"دلیل تیم مدیریت: {reason}\n\n"
                f"💡 می‌توانید با بازنویسی و رفع ایراد، پروژه را مجدداً تدوین و ارسال فرمایید.",
            )
        except Exception:
            pass

    # لاگ
    await send_log(
        bot,
        f"❌ <b>رد رول اقتصادی</b>\n"
        f"کشور: {country.name_fa if country else '—'}\n"
        f"پروژه: {project.title}\n"
        f"بررسی‌کننده: {admin_name}\n"
        f"دلیل: {reason}"
    )


@router.callback_query(F.data.startswith("ep_admin_approve:"))
async def cb_admin_approve_router(call: CallbackQuery, session: AsyncSession) -> None:
    """هدایت دکمه تخصیص بودجه و تایید از پنل /roles."""
    proj_id = int(call.data.split(":")[1])
    call.data = f"ep_grp_approve:{proj_id}"
    await cb_grp_approve_menu(call, session)


@router.callback_query(F.data.startswith("ep_admin_reject:"))
async def cb_admin_reject_router(call: CallbackQuery) -> None:
    """هدایت دکمه رد پروژه از پنل /roles."""
    proj_id = int(call.data.split(":")[1])
    call.data = f"ep_grp_reject:{proj_id}"
    await cb_grp_reject_menu(call)


@router.callback_query(F.data.startswith("ep_rj_custom:"))
async def cb_grp_reject_custom(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست وارد کردن دلیل رد اختصاصی."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await state.set_state(AdminProjectReviewForm.entering_reject_reason)
    await state.update_data(
        project_id=proj_id,
        admin_chat_id=call.message.chat.id,
        admin_message_id=call.message.message_id,
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data=f"ep_grp_cancel:{proj_id}", style=STYLE_NO),
    ]])
    await call.message.reply(
        "✍️ لطفاً <b>علت رد پروژه</b> را ارسال کنید تا به اطلاع بازیکن برسد:",
        reply_markup=cancel_kb,
    )


@router.message(StateFilter(AdminProjectReviewForm.entering_reject_reason))
async def msg_custom_reject_reason(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت دلیل رد اختصاصی و رد پروژه."""
    reason = (message.text or "").strip()
    if not reason:
        await message.answer("⚠️ لطفاً دلیل رد را بنویسید:")
        return

    data = await state.get_data()
    proj_id = data.get("project_id")
    await state.clear()

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await message.answer("❌ پروژه یافت نشد.")
        return

    admin_user = message.from_user
    admin_name = admin_user.full_name or f"@{admin_user.username}" if admin_user.username else str(admin_user.id)

    await reject_project(session, project, admin_user.id, reason)
    await session.commit()

    admin_chat_id = data.get("admin_chat_id")
    admin_msg_id = data.get("admin_message_id")
    if admin_chat_id and admin_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=admin_chat_id,
                message_id=admin_msg_id,
                text=(message.text or "") + f"\n\n❌ <b>رد شد توسط {admin_name}</b>\n<b>دلیل:</b> {reason}",
                reply_markup=None,
            )
        except Exception:
            pass

    country = await countries_repo.get_country(session, project.country_id)
    if country and country.owner_user_id:
        try:
            await bot.send_message(
                country.owner_user_id,
                f"❌ <b>پروژه رول اقتصادی شما رد شد</b>\n\n"
                f"عنوان پروژه: <b>{project.title}</b>\n"
                f"دلیل تیم مدیریت: {reason}\n\n"
                f"💡 می‌توانید با بازنویسی و رفع ایراد، پروژه را مجدداً تدوین و ارسال فرمایید.",
            )
        except Exception:
            pass

    await send_log(
        bot,
        f"❌ <b>رد رول اقتصادی</b>\n"
        f"کشور: {country.name_fa if country else '—'}\n"
        f"پروژه: {project.title}\n"
        f"بررسی‌کننده: {admin_name}\n"
        f"دلیل: {reason}",
    )
    await message.answer("✅ پروژه با موفقیت رد شد و پیام به پیوی بازیکن ارسال گردید.")


@router.callback_query(F.data.startswith("ep_grp_cancel:"))
async def cb_grp_cancel(call: CallbackQuery, session: AsyncSession) -> None:
    """بازگشت به دکمه‌های اصلی داوری در گروه."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if project:
        await call.message.edit_reply_markup(reply_markup=admin_group_project_kb(project, 1))


# ---------- تأیید رول و تنظیمات بازدهی ----------

@router.callback_query(F.data.startswith("ep_grp_approve:"))
async def cb_grp_approve_menu(call: CallbackQuery, session: AsyncSession) -> None:
    """باز کردن منوی تعاملی تنظیم هزینه‌ها و بازدهی."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if not project:
        return

    # مقادیر اولیه
    launch_cash = project.launch_cost_cash or project.proposed_budget
    yield_cash = project.yield_cash_72h or round(project.proposed_budget * 0.15, 2)
    l_res_count = len(project.launch_resources_dict)
    y_res_count = len(project.yield_resources_dict)

    project.launch_cost_cash = launch_cash
    project.yield_cash_72h = yield_cash
    await session.commit()

    kb = admin_approve_settings_kb(proj_id, launch_cash, l_res_count, yield_cash, y_res_count)
    await call.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep_cfg_cash:"))
async def cb_cfg_cash(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if project:
        await call.message.edit_reply_markup(reply_markup=admin_quick_cash_kb(proj_id, project.proposed_budget))


@router.callback_query(F.data.startswith("ep_set_cash:"))
async def cb_set_cash(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    val = float(parts[2])

    project = await proj_repo.get_project(session, proj_id)
    if project:
        project.launch_cost_cash = val
        await session.commit()
        kb = admin_approve_settings_kb(
            proj_id,
            project.launch_cost_cash,
            len(project.launch_resources_dict),
            project.yield_cash_72h,
            len(project.yield_resources_dict),
        )
        await call.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep_cfg_ycash:"))
async def cb_cfg_ycash(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if project:
        await call.message.edit_reply_markup(reply_markup=admin_quick_yield_kb(proj_id, project.proposed_budget))


@router.callback_query(F.data.startswith("ep_set_ycash:"))
async def cb_set_ycash(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    val = float(parts[2])

    project = await proj_repo.get_project(session, proj_id)
    if project:
        project.yield_cash_72h = val
        await session.commit()
        kb = admin_approve_settings_kb(
            proj_id,
            project.launch_cost_cash,
            len(project.launch_resources_dict),
            project.yield_cash_72h,
            len(project.yield_resources_dict),
        )
        await call.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep_set_cash_custom:"))
async def cb_set_cash_custom(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست وارد کردن هزینه دلاری دلخواه افتتاح."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await state.set_state(AdminProjectReviewForm.entering_custom_cash)
    await state.update_data(
        project_id=proj_id,
        admin_chat_id=call.message.chat.id,
        admin_message_id=call.message.message_id,
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data=f"ep_grp_approve:{proj_id}", style=STYLE_NO),
    ]])
    await call.message.reply(
        "💵 لطفاً <b>هزینه دلاری افتتاح</b> مورد نظر برای این پروژه را وارد کنید (یا عدد 0 برای افتتاح رایگان):\n"
        "<i>(مثال: 50M یا 100,000,000 یا 0)</i>",
        reply_markup=cancel_kb,
    )


@router.message(StateFilter(AdminProjectReviewForm.entering_custom_cash))
async def msg_custom_cash(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت مبلغ دلخواه هزینه افتتاح."""
    raw = (message.text or "").strip()
    val = parse_amount(raw)
    if val is None or val < 0:
        await message.answer("⚠️ لطفاً مبلغ معتبری وارد کنید (مثال: 50M یا 10,000,000 یا 0):")
        return

    data = await state.get_data()
    proj_id = data.get("project_id")
    await state.clear()

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await message.answer("❌ پروژه یافت نشد.")
        return

    project.launch_cost_cash = float(val)
    await session.commit()

    kb = admin_approve_settings_kb(
        proj_id,
        project.launch_cost_cash,
        len(project.launch_resources_dict),
        project.yield_cash_72h or 0.0,
        len(project.yield_resources_dict),
    )
    admin_chat_id = data.get("admin_chat_id")
    admin_msg_id = data.get("admin_message_id")
    if admin_chat_id and admin_msg_id:
        try:
            await bot.edit_message_reply_markup(chat_id=admin_chat_id, message_id=admin_msg_id, reply_markup=kb)
        except Exception:
            pass
    await message.answer(f"✅ هزینه دلاری افتتاح پروژه روی <b>{fa_money(val)}</b> تنظیم شد.", reply_markup=kb)


@router.callback_query(F.data.startswith("ep_set_ycash_custom:"))
async def cb_set_ycash_custom(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست وارد کردن سود دلخواه ۷۲ ساعته."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await state.set_state(AdminProjectReviewForm.entering_custom_yield)
    await state.update_data(
        project_id=proj_id,
        admin_chat_id=call.message.chat.id,
        admin_message_id=call.message.message_id,
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 انصراف و بازگشت", callback_data=f"ep_grp_approve:{proj_id}", style=STYLE_NO),
    ]])
    await call.message.reply(
        "💰 لطفاً <b>مبلغ سود نقدی ۷۲ ساعته</b> مورد نظر برای این پروژه را به دلار وارد کنید:\n"
        "<i>(مثال: 20M یا 15,000,000 یا ۱۵۰۰۰۰۰۰)</i>",
        reply_markup=cancel_kb,
    )


@router.message(StateFilter(AdminProjectReviewForm.entering_custom_yield))
async def msg_custom_yield(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """دریافت مبلغ دلخواه سود ۷۲ ساعته."""
    raw = (message.text or "").strip()
    val = parse_amount(raw)
    if val is None or val < 0:
        await message.answer("⚠️ لطفاً مبلغ معتبری وارد کنید (مثال: 20M یا 15,000,000):")
        return

    data = await state.get_data()
    proj_id = data.get("project_id")
    await state.clear()

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await message.answer("❌ پروژه یافت نشد.")
        return

    project.yield_cash_72h = float(val)
    await session.commit()

    kb = admin_approve_settings_kb(
        proj_id,
        project.launch_cost_cash or 0.0,
        len(project.launch_resources_dict),
        project.yield_cash_72h,
        len(project.yield_resources_dict),
    )
    admin_chat_id = data.get("admin_chat_id")
    admin_msg_id = data.get("admin_message_id")
    if admin_chat_id and admin_msg_id:
        try:
            await bot.edit_message_reply_markup(chat_id=admin_chat_id, message_id=admin_msg_id, reply_markup=kb)
        except Exception:
            pass
    await message.answer(f"✅ سود ۷۲ ساعته پروژه روی <b>{fa_money(val)}</b> تنظیم شد.", reply_markup=kb)


@router.callback_query(F.data.startswith("ep_cfg_res:"))
async def cb_cfg_res(call: CallbackQuery) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=admin_resource_picker_kb(proj_id, "cost"))


@router.callback_query(F.data.startswith("ep_cfg_yres:"))
async def cb_cfg_yres(call: CallbackQuery) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=admin_resource_picker_kb(proj_id, "yield"))


@router.callback_query(F.data.startswith("ep_clear_res:"))
async def cb_clear_res(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer()
    parts = call.data.split(":")
    proj_id = int(parts[1])
    mode = parts[2]

    project = await proj_repo.get_project(session, proj_id)
    if project:
        if mode == "cost":
            project.launch_resources_dict = {}
        else:
            project.yield_resources_dict = {}
        await session.commit()

        kb = admin_approve_settings_kb(
            proj_id,
            project.launch_cost_cash,
            len(project.launch_resources_dict),
            project.yield_cash_72h,
            len(project.yield_resources_dict),
        )
        await call.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep_pick_res:"))
async def cb_pick_res(call: CallbackQuery, session: AsyncSession) -> None:
    """افزودن مقدار پیش‌فرض یک منبع به لیست هزینه‌ها یا سود."""
    await call.answer("منبع افزوده شد ✅")
    parts = call.data.split(":")
    proj_id = int(parts[1])
    mode = parts[2]
    rtype_str = parts[3]

    project = await proj_repo.get_project(session, proj_id)
    if not project:
        return

    # مقادیر نمونه پیش‌فرض جهت سرعت کار ادمین
    defaults = {
        "steel": 50_000.0,
        "aluminum": 30_000.0,
        "iron": 40_000.0,
        "oil": 0.5,
        "gas": 5.0,
        "coal": 20_000.0,
        "gold": 200.0,
        "uranium": 5.0,
    }
    amt = defaults.get(rtype_str, 10_000.0)

    if mode == "cost":
        cur = project.launch_resources_dict
        cur[rtype_str] = cur.get(rtype_str, 0.0) + amt
        project.launch_resources_dict = cur
    else:
        cur = project.yield_resources_dict
        cur[rtype_str] = cur.get(rtype_str, 0.0) + amt
        project.yield_resources_dict = cur

    await session.commit()
    kb = admin_approve_settings_kb(
        proj_id,
        project.launch_cost_cash,
        len(project.launch_resources_dict),
        project.yield_cash_72h,
        len(project.yield_resources_dict),
    )
    await call.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(F.data.startswith("ep_adm_confirm:"))
async def cb_adm_confirm(call: CallbackQuery, session: AsyncSession) -> None:
    """تأیید نهایی، کسر هزینه و اعمال بازدهی به کشور."""
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if not project:
        return

    country = await countries_repo.get_country(session, project.country_id)
    if not country:
        return

    admin_user = call.from_user
    admin_name = admin_user.full_name or f"@{admin_user.username}" if admin_user.username else str(admin_user.id)

    res = await approve_and_launch_project(
        session,
        project,
        country,
        admin_user.id,
        project.launch_cost_cash,
        project.launch_resources_dict,
        project.yield_cash_72h,
        project.yield_resources_dict,
    )
    await session.commit()

    launch_cash_str = fa_money(project.launch_cost_cash)
    launch_res_str = format_resources_dict(project.launch_resources_dict)
    yield_cash_str = fa_money(project.yield_cash_72h)
    yield_res_str = format_resources_dict(project.yield_resources_dict)

    if res["launched"]:
        # افتتاح فوری
        status_line = (
            f"\n\n✅ <b>تأیید و افتتاح شد توسط {admin_name}</b>\n"
            f"💵 هزینه دلاری افتتاح: {launch_cash_str}\n"
            f"📦 ذخایر مصرف‌شده: {launch_res_str}\n"
            f"📈 سود هر ۷۲ ساعت: {yield_cash_str} | {yield_res_str}\n"
            f"🟢 <b>وضعیت: فعال و در حال سوددهی</b>"
        )
        try:
            await call.message.edit_text((call.message.text or "") + status_line, reply_markup=None)
        except Exception:
            pass

        # پیام به پیوی بازیکن
        if country.owner_user_id:
            try:
                await bot.send_message(
                    country.owner_user_id,
                    f"🎉 <b>پروژه اقتصادی شما با موفقیت تأیید و افتتاح شد!</b>\n\n"
                    f"🏗 عنوان پروژه: <b>«{project.title}»</b>\n"
                    f"💵 هزینه افتتاح کسرشده از بودجه: {launch_cash_str}\n"
                    f"📦 ذخایر کسرشده: {launch_res_str}\n\n"
                    f"📈 <b>بازدهی پروژه در هر ۷۲ ساعت:</b>\n"
                    f"- واریز نقدی: <b>{yield_cash_str}</b>\n"
                    f"- بازدهی ذخایر: <b>{yield_res_str}</b>\n\n"
                    f"⏳ اولین واریز سود: ۷۲ ساعت دیگر",
                )
            except Exception:
                pass

        await send_log(
            bot,
            f"🟢 <b>افتتاح پروژه اقتصادی</b>\n"
            f"کشور: {country.flag} {country.name_fa}\n"
            f"پروژه: {project.title}\n"
            f"هزینه افتتاح: {launch_cash_str}\n"
            f"سود ۷۲ ساعته: {yield_cash_str}\n"
            f"تأییدکننده: {admin_name}"
        )
    else:
        # در انتظار تأمین بودجه توسط بازیکن
        status_line = (
            f"\n\n🟡 <b>تأیید شد توسط {admin_name} (در انتظار تأمین منابع توسط کشور)</b>\n"
            f"💵 هزینه افتتاح: {launch_cash_str}\n"
            f"📦 ذخایر افتتاح: {launch_res_str}\n"
            f"📈 سود ۷۲ساعته: {yield_cash_str} | {yield_res_str}"
        )
        try:
            await call.message.edit_text((call.message.text or "") + status_line, reply_markup=None)
        except Exception:
            pass

        if country.owner_user_id:
            try:
                await bot.send_message(
                    country.owner_user_id,
                    f"🟡 <b>پروژه اقتصادی شما تأیید شد اما بودجه یا ذخایر کشور برای افتتاح کافی نبود!</b>\n\n"
                    f"🏗 پروژه: <b>«{project.title}»</b>\n"
                    f"هزینه افتتاح مورد نیاز:\n"
                    f"- نقدینگی: {launch_cash_str} (کسری: {fa_money(res['missing_cash'])})\n"
                    f"- ذخایر مورد نیاز: {launch_res_str}\n\n"
                    f"💡 نگران نباشید، پروژه نسوخته است! هر زمان که بودجه و منابع را تأمین کردید، "
                    f"به بخش «پروژه‌ها» مراجعه کرده و دکمه <b>🟢 افتتاح پروژه</b> را بزنید.",
                )
            except Exception:
                pass


# ============================================================
#  افتتاح دستی پروژه در انتظار توسط بازیکن
# ============================================================

@router.callback_query(F.data.startswith("ep_launch_do:"))
async def cb_launch_do(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    proj_id = int(call.data.split(":")[1])
    project = await proj_repo.get_project(session, proj_id)
    if not project:
        await safe_edit(call, "❌ پروژه یافت نشد.")
        return

    country = await countries_repo.get_country(session, project.country_id)
    if not country:
        await safe_edit(call, "❌ کشور یافت نشد.")
        return

    res = await launch_awaiting_project(session, project, country)
    if not res["success"]:
        await call.answer(f"⚠️ {res['error']}", show_alert=True)
        return

    await session.commit()
    await call.answer("🎉 پروژه با موفقیت افتتاح شد و سوددهی آغاز گردید!", show_alert=True)

    await send_log(
        bot,
        f"🟢 <b>افتتاح دستی پروژه اقتصادی</b>\n"
        f"کشور: {country.flag} {country.name_fa}\n"
        f"پروژه: {project.title}\n"
        f"هزینه پرداخت شد و پروژه به چرخه ۷۲ ساعته وارد شد."
    )

    # بازگشت به نمای پروژه فعال
    msg_text = render_project_message(country, project, 1, db_user)
    await safe_edit(call, msg_text, reply_markup=project_active_view_kb(project, 1))
