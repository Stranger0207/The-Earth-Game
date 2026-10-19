"""
هندلر جامع سازمان ملل متحد (UN)، آژانس انرژی اتمی (IAEA)، اجلاس مجمع عمومی در نیویورک و دیوان دادگستری (ICJ).
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import (
    DIPLOMATIC_FLIGHT_KM_RATE,
    DIPLOMATIC_FLIGHT_MAX_MINUTES,
    DIPLOMATIC_FLIGHT_MIN_MINUTES,
    UN_ASSEMBLY_SPEECH_DURATION_MINUTES,
)
from ..database.models import Country, PhoneCall, User
from ..database.models.nuclear import NuclearInspection, NuclearProgram
from ..database.models.united_nations import (
    CourtParty,
    InternationalCourtCase,
    UNAssemblyParticipant,
    UNAssemblySession,
    UNResolution,
    UNSpeechQueue,
)
from ..database.repositories import countries as countries_repo
from ..database.repositories import diplomacy as dip_repo
from ..database.repositories import nuclear as nuc_repo
from ..database.repositories import united_nations as un_repo
from ..database.repositories import users as users_repo
from ..enums import DiplomacyStatus, NewsCategory
from ..keyboards.common import countries_kb
from ..keyboards.united_nations import (
    assembly_hall_kb,
    assembly_invite_kb,
    assembly_ny_lobby_kb,
    court_issues_kb,
    court_main_kb,
    iaea_inspection_action_kb,
    resolution_vote_kb,
    un_assembly_admin_kb,
    un_court_admin_kb,
    un_court_verdict_choices_kb,
    un_iaea_case_view_kb,
    un_iaea_menu_kb,
    un_iaea_summon_call_kb,
    un_main_menu_kb,
)
from ..loader import bot
from ..services import geo_service as geo
from ..services.news_service import publish_news, send_log
from ..services.un_speech_service import analyze_and_publish_speech
from ..states.united_nations import (
    CourtForm,
    HumanitarianForm,
    IAEAForm,
    ResolutionForm,
    UNAssemblyForm,
)
from ..utils.numbers import fa_number
from ..utils.screens import safe_edit, show_menu
from ..utils.ui import DIVIDER, STYLE_MAIN, STYLE_NO, STYLE_OK, header
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

logger = logging.getLogger(__name__)
router = Router(name="united_nations")
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _get_pres_name(session: AsyncSession, country: Country | None) -> str:
    """دریافت نام رهبر/رئیس‌جمهور کشور."""
    if country is None:
        return "—"
    if country.owner_user_id:
        u = await users_repo.get_user(session, country.owner_user_id)
        if u and u.president_name:
            return u.president_name
    return country.name_fa


# ============================================================
#  🇺🇳 پنل اصلی فرماندهی دبیرکل سازمان ملل
# ============================================================


@router.callback_query(F.data == "un:main")
async def cb_un_main(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """بازگشت به پنل فرماندهی دبیرکل سازمان ملل."""
    country = await get_player_country(session, db_user)
    if country is None or country.name_en != "UN":
        await call.answer("دسترسی غیرمجاز؛ فقط دبیرکل سازمان ملل به این پنل دسترسی دارد.", show_alert=True)
        return

    text = (
        header("مقر فرماندهی دبیرکل سازمان ملل متحد", "🇺🇳") + "\n\n"
        "🏛 <b>SECRETARIAT OF THE UNITED NATIONS</b>\n"
        f"دبیرکل محترم، تالار فرماندهی و ارکان سازمان ملل متحد در خدمت شماست.\n"
        f"بودجه صندوق بشردوستانه: <b>{fa_number(country.budget / 1e6)} میلیون دلار</b>\n\n"
        "بخش مورد نظر را انتخاب نمایید:"
    )
    await safe_edit(call, text, reply_markup=un_main_menu_kb())


# ============================================================
#  ☢️ آژانس بین‌المللی انرژی اتمی (IAEA)
# ============================================================


@router.callback_query(F.data == "un:iaea")
async def cb_un_iaea(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """منوی آژانس بین‌المللی انرژی اتمی."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "un.iaea"):
        return

    text = (
        header("آژانس بین‌المللی انرژی اتمی (IAEA)", "☢️") + "\n\n"
        "پایش پادمان، بازرسی از تأسیسات هسته‌ای، بررسی سطوح غنی‌سازی و احضار سفرا.\n"
        "از این بخش می‌توانید تیم بازرسان را به کشورهای مظنون اعزام کنید یا گزارش‌های اطلاعاتی را بررسی نمایید."
    )
    await safe_edit(call, text, reply_markup=un_iaea_menu_kb())


@router.callback_query(F.data == "un:iaea_send")
async def cb_un_iaea_send(call: CallbackQuery, session: AsyncSession) -> None:
    """انتخاب کشور جهت اعزام تیم بازرسان آژانس."""
    countries = await countries_repo.list_countries(session)
    valid_targets = [c for c in countries if c.name_en != "UN" and c.is_claimed]
    if not valid_targets:
        await call.answer("کشور تحت مالکیتی برای بازرسی یافت نشد.", show_alert=True)
        return

    await safe_edit(
        call,
        "🔍 کشوری را که می‌خواهید تیم بازرسان پادمان آژانس به آن اعزام شوند انتخاب کنید:",
        reply_markup=countries_kb(valid_targets, prefix="iaea_target", columns=2),
    )


@router.callback_query(F.data.startswith("iaea_target:"))
async def cb_iaea_pick_country(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """اعزام بازرسان به کشور هدف و ارسال درخواست پذیرش/ممانعت."""
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    un_country = await countries_repo.get_country_by_name(session, "UN")

    if not target or not un_country:
        await call.answer("کشور هدف یافت نشد.", show_alert=True)
        return

    # ثبت بازرسی در جدول nuclear_inspections
    inspection = NuclearInspection(
        requester_id=un_country.id,
        target_id=target.id,
        status="pending",
        report="در انتظار پاسخ و ورود تیم بازرسان پادمان آژانس...",
    )
    session.add(inspection)
    await session.flush()

    # ارسال اعلان رسمی به رهبر کشور هدف
    if target.owner_user_id:
        target_text = (
            "🚨 <b>ابلاغیه رسمی آژانس بین‌المللی انرژی اتمی (IAEA):</b>\n\n"
            "تیم بازرسان پادمان سازمان ملل متحد به دستور دبیرکل به مرزهای کشور شما اعزام شده‌اند "
            "و خواستار ورود فوری به کلیه تأسیسات هسته‌ای و پایش سانتریفیوژها می‌باشند.\n\n"
            "⚠️ <i>ممانعت از ورود بازرسان نقض تعهدات بین‌المللی بوده و شاخص افشا و مظنونیت هسته‌ای شما را افزایش خواهد داد.</i>"
        )
        try:
            await bot.send_message(
                target.owner_user_id,
                target_text,
                reply_markup=iaea_inspection_action_kb(inspection.id),
            )
        except Exception:
            pass

    await call.answer("تیم بازرسان اعزام شد.", show_alert=True)
    await safe_edit(
        call,
        f"🔍 تیم بازرسان آژانس به مقصد کشور {target.flag} <b>{target.name_fa}</b> اعزام شد.\n"
        "پیام پذیرش یا ممانعت برای رهبر آن کشور ارسال گردید. به محض پاسخ، پرونده در آژانس فعال خواهد شد.",
        reply_markup=un_iaea_menu_kb(),
    )


@router.callback_query(F.data.startswith("iaea_ok:"))
async def cb_iaea_accept(call: CallbackQuery, session: AsyncSession) -> None:
    """پذیرش بازرسان توسط کشور هدف."""
    inspection_id = int(call.data.split(":")[1])
    insp = await session.get(NuclearInspection, inspection_id)
    if not insp or insp.status != "pending":
        await call.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
        return

    insp.status = "accepted"
    insp.answered_at = _utcnow()
    insp.report = "بازرسان در تأسیسات مستقر شدند و پرونده اطلاعاتی ثبت شد."
    await session.flush()

    target = await countries_repo.get_country(session, insp.target_id)
    un_country = await countries_repo.get_country_by_name(session, "UN")

    await safe_edit(
        call,
        "✅ <b>ورود بازرسان آژانس تایید شد:</b>\n"
        "اطلاعات زنجیره سوخت و سطح فعالیت‌های هسته‌ای در اختیار تیم بازرسان بین‌المللی قرار گرفت.",
    )

    # اطلاع به دبیرکل سازمان ملل
    if un_country and un_country.owner_user_id:
        target_name = target.name_fa if target else "?"
        try:
            await bot.send_message(
                un_country.owner_user_id,
                f"📋 <b>گزارش آژانس:</b> کشور {target_name} ورود بازرسان را تایید کرد.\n"
                "پرونده اطلاعاتی تأسیسات و غنی‌سازی این کشور آماده بررسی است.",
                reply_markup=un_iaea_case_view_kb(insp.target_id),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("iaea_no:"))
async def cb_iaea_reject(call: CallbackQuery, session: AsyncSession) -> None:
    """ممانعت از ورود بازرسان توسط کشور هدف."""
    inspection_id = int(call.data.split(":")[1])
    insp = await session.get(NuclearInspection, inspection_id)
    if not insp or insp.status != "pending":
        await call.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
        return

    insp.status = "rejected"
    insp.answered_at = _utcnow()
    insp.report = "ممانعت شدید از ورود بازرسان به تأسیسات و اخراج تیم پادمان."

    target = await countries_repo.get_country(session, insp.target_id)
    # افزایش شاخص افشا و مظنونیت
    prog = await nuc_repo.get_program(session, insp.target_id)
    if prog:
        prog.exposure = min(100.0, prog.exposure + 25.0)
    await session.flush()

    await safe_edit(
        call,
        "❌ <b>ممانعت از ورود بازرسان:</b>\n"
        "شما اجازه ورود به بازرسان آژانس را ندادید. شاخص سوءظن بین‌المللی و افشای برنامه هسته‌ای کشور شما افزایش یافت.",
    )

    un_country = await countries_repo.get_country_by_name(session, "UN")
    if un_country and un_country.owner_user_id:
        tname = target.name_fa if target else "?"
        try:
            await bot.send_message(
                un_country.owner_user_id,
                f"⚠️ <b>هشدار امنیتی آژانس:</b> کشور {tname} از ورود بازرسان ممانعت به عمل آورد!\n"
                "شاخص مظنونیت این کشور بالا رفت. می‌توانید فوراً سفیر این کشور را احضار نمایید.",
                reply_markup=un_iaea_case_view_kb(insp.target_id),
            )
        except Exception:
            pass

    # انتشار خبر در کانال دیپلماسی
    tname_fa = target.name_fa if target else "یک کشور"
    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🚨 <b>بیانیه فوری آژانس بین‌المللی انرژی اتمی:</b>\n"
        f"دولت {tname_fa} رسماً از ورود تیم بازرسان پادمان به تأسیسات خود ممانعت کرده و بازرسان سازمان ملل را اخراج نمود. "
        "شورای حکام آژانس نسبت به پیامدهای این اقدام هشدار داد.",
    )


@router.callback_query(F.data == "un:iaea_cases")
async def cb_iaea_cases(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده لیست پرونده‌های بازرسی."""
    res = await session.execute(
        select(NuclearInspection).order_by(NuclearInspection.id.desc()).limit(10)
    )
    inspections = res.scalars().all()
    if not inspections:
        await call.answer("هیچ پرونده بازرسی اخیری ثبت نشده است.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for ins in inspections:
        t = await countries_repo.get_country(session, ins.target_id)
        tflag = t.flag if t else "🏴"
        tname = t.name_fa if t else f"کشور #{ins.target_id}"
        st_icon = "🟢" if ins.status == "accepted" else ("🔴" if ins.status == "rejected" else "⏳")
        builder.button(
            text=f"{st_icon} {tflag} {tname} ({ins.status})",
            callback_data=f"iaea_view_case:{ins.target_id}",
        )
    builder.button(text="🔙 بازگشت به آژانس", callback_data="un:iaea")
    builder.adjust(1)
    await safe_edit(call, "📋 <b>پرونده‌های اخیر بازرسی آژانس انرژی اتمی:</b>", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("iaea_view_case:"))
async def cb_iaea_view_case(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده جزئیات پرونده هسته‌ای کشور."""
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    if not target:
        await call.answer("کشور یافت نشد.", show_alert=True)
        return

    prog = await nuc_repo.get_program(session, target_id)
    facilities = await nuc_repo.list_facilities(session, target_id)
    warheads = await nuc_repo.count_ready_warheads(session, target_id)

    if prog is None:
        prog_info = "این کشور فاقد برنامه رسمی توسعه هسته‌ای است."
    else:
        cover_txt = "✅ فعال (پوشش صلح‌آمیز)" if prog.civilian_cover else "❌ غیرفعال (علنی/تسلیحاتی)"
        prog_info = (
            f"🔹 بالاترین فاز هسته‌ای: <b>فاز {prog.phase}</b>\n"
            f"🔹 ذخایر کیک زرد: <b>{prog.yellowcake_tons:.1f} تن</b> | گاز UF6: <b>{prog.uf6_tons:.1f} تن</b>\n"
            f"🔹 اورانیوم غنی‌شده: ۳.۵٪ ({prog.leu_35_kg:.1f} kg) | ۲۰٪ ({prog.leu_20_kg:.1f} kg) | ۶۰٪ ({prog.heu_60_kg:.1f} kg) | ۹۰٪ ({prog.heu_90_kg:.1f} kg)\n"
            f"🔹 تعداد سانتریفیوژها: <b>{fa_number(prog.centrifuges)} دستگاه</b> (غنی‌سازی فعال: {prog.enrich_centrifuges})\n"
            f"🔹 وضعیت پوشش صلح‌آمیز: {cover_txt}\n"
            f"🔹 شاخص افشا و سوءظن آژانس: <b>{prog.exposure:.1f} از ۱۰۰</b>\n"
            f"🔹 کلاهک‌های مونتاژشده: <b>{warheads} عدد</b>\n"
            f"🔹 تعداد کل تأسیسات سطحی/زیرزمینی: <b>{len(facilities)} مرکز</b>"
        )

    text = (
        header(f"پرونده اطلاعاتی پادمان: {target.flag} {target.name_fa}", "☢️") + "\n\n"
        f"{prog_info}\n\n"
        "در صورت وجود ناهنجاری یا غنی‌سازی مشکوک، می‌توانید سفیر این کشور را برای جلسه احضار نمایید."
    )
    await safe_edit(call, text, reply_markup=un_iaea_case_view_kb(target_id))


# ============================================================
#  📞 احضار سفیر کشور به سازمان ملل (تماس تلفنی اختصاصی)
# ============================================================


@router.callback_query(F.data.startswith("iaea_summon:"))
async def cb_iaea_summon(call: CallbackQuery, session: AsyncSession) -> None:
    """احضار تلفنی سفیر کشور توسط دبیرکل."""
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    un_country = await countries_repo.get_country_by_name(session, "UN")

    if not target or not un_country:
        await call.answer("اطلاعات نامعتبر است.", show_alert=True)
        return

    # ایجاد تماس تلفنی اختصاصی
    phone_call = PhoneCall(
        caller_country=un_country.id,
        callee_country=target.id,
        status=DiplomacyStatus.ACTIVE,
        created_at=_utcnow(),
        ends_at=_utcnow() + timedelta(minutes=10),
    )
    session.add(phone_call)
    await session.flush()

    # پیام به سفیر کشور
    if target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"📞 <b>احضار فوری سفیر {target.flag} {target.name_fa}:</b>\n\n"
                "جناب دبیرکل سازمان ملل متحد هم‌اکنون شما را برای ادای توضیحات پیرامون فعالیت‌های هسته‌ای "
                "به خط مستقیم احضار نموده‌اند. هر پیامی بفرستید مستقیماً به دبیرکل منتقل می‌شود.",
            )
        except Exception:
            pass

    text = (
        header(f"جلسه احضار سفیر {target.flag} {target.name_fa}", "📞") + "\n\n"
        "خط مستقیم دوجانبه برقرار است. پیام‌های متنی شما به سفیر این کشور منتقل خواهد شد.\n"
        "پس از شنیدن دفاعیات و ادله، تصمیم نهایی خود را اعلام نمایید:"
    )
    await safe_edit(call, text, reply_markup=un_iaea_summon_call_kb(target_id))


@router.callback_query(F.data.startswith("iaea_call_acquit:"))
async def cb_iaea_call_acquit(call: CallbackQuery, session: AsyncSession) -> None:
    """تبرئه در بحث و مختومه کردن پرونده."""
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    prog = await nuc_repo.get_program(session, target_id)

    if prog:
        prog.exposure = max(0.0, prog.exposure - 20.0)
    # بستن تماس
    call_active = await dip_repo.get_active_call_for_country(session, target_id)
    if call_active:
        call_active.status = DiplomacyStatus.COMPLETED
    await session.flush()

    tname = target.name_fa if target else "?"
    if target and target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                "🟢 <b>پایان جلسه احضار:</b>\nدبیرکل سازمان ملل توضیحات شما را موجه تشخیص داد و پرونده بازرسی آژانس مختومه اعلام شد.",
            )
        except Exception:
            pass

    await safe_edit(
        call,
        f"🟢 <b>پرونده مختومه شد:</b>\nفعالیت‌های کشور {tname} صلح‌آمیز تایید گردید و شاخص سوءظن کاهش یافت.",
        reply_markup=un_main_menu_kb(),
    )

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"🕊 <b>مختومه شدن پرونده پادمان کشور {tname}:</b>\n"
        f"در پی مذاکرات مستقیم دبیرکل سازمان ملل با سفیر {tname}، فعالیت‌های این کشور صلح‌آمیز ارزیابی شده و سوءظن‌های آژانس رفع گردید.",
    )


@router.callback_query(F.data.startswith("iaea_call_court:"))
async def cb_iaea_call_court(call: CallbackQuery, session: AsyncSession) -> None:
    """ارجاع به دادگاه بین‌الملل و پایان صحبت."""
    target_id = int(call.data.split(":")[1])
    target = await countries_repo.get_country(session, target_id)
    un_country = await countries_repo.get_country_by_name(session, "UN")

    # بستن تماس
    call_active = await dip_repo.get_active_call_for_country(session, target_id)
    if call_active:
        call_active.status = DiplomacyStatus.COMPLETED

    # ثبت پرونده در دادگاه لاهه
    case_num = f"ICJ-IAEA-{random.randint(1000, 9999)}"
    court_case = InternationalCourtCase(
        case_number=case_num,
        claimant_country_id=un_country.id if un_country else 1,
        defendant_country_id=target_id,
        issue_type="nuclear_violation",
        claim_title="نقض فاحش پادمان هسته‌ای و غنی‌سازی مشکوک",
        claim_description="ارجاع مستقیم توسط دبیرکل سازمان ملل در پی عدم اقناع آژانس و انحراف احتمالی برنامه هسته‌ای.",
        demanded_compensation=50_000_000.0,
        status="pending",
    )
    session.add(court_case)
    await session.flush()

    tname = target.name_fa if target else "?"
    if target and target.owner_user_id:
        try:
            await bot.send_message(
                target.owner_user_id,
                f"⚖️ <b>احضاریه دادگاه بین‌المللی لاهه (ICJ):</b>\n"
                f"دبیرکل سازمان ملل پرونده هسته‌ای کشور شما را به دیوان بین‌الملل ارجاع داد (شماره پرونده: {case_num}).",
            )
        except Exception:
            pass

    await safe_edit(
        call,
        f"⚖️ تماس قطع شد و کیفرخواست رسمی علیه کشور {tname} در دیوان بین‌المللی دادگستری صادر گردید.",
        reply_markup=un_main_menu_kb(),
    )

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        f"⚖️ <b>فوری / ارجاع پرونده هسته‌ای کشور {tname} به دادگاه لاهه:</b>\n"
        f"دبیرکل سازمان ملل متحد پس از احضار سفیر {tname}، پرونده فعالیت‌های هسته‌ای این کشور را به دیوان بین‌المللی دادگستری ارجاع داد.",
    )


# ============================================================
#  🏛 مدیریت مجمع عمومی سازمان ملل (اجلاس سالانه نیویورک)
# ============================================================


@router.callback_query(F.data == "un:assembly")
async def cb_un_assembly(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """مدیریت مجمع عمومی در پنل دبیرکل."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "un.assembly"):
        return

    active_session = await un_repo.get_active_session(session)
    if active_session is None:
        text = (
            header("اجلاس سالانه مجمع عمومی سازمان ملل", "🏛") + "\n\n"
            "هم‌اکنون هیچ اجلاس فعالی در نیویورک در جریان نیست.\n"
            "با آغاز رسمی اجلاس، دعوت‌نامه سفر ریاست‌جمهوری برای کلیه رهبران جهان ارسال خواهد شد."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🚀 آغاز رسمی و ارسال دعوت‌نامه به سران جهان", callback_data="un_asmb_create", style=STYLE_OK)
        builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
        builder.adjust(1)
        await safe_edit(call, text, reply_markup=builder.as_markup())
        return

    # جلسه فعال است
    participants = await un_repo.list_participants(session, active_session.id)
    in_hall = [p for p in participants if p.status == "inside_hall"]
    in_ny = [p for p in participants if p.status == "in_new_york"]
    in_flight = [p for p in participants if p.status == "in_flight"]
    queue = await un_repo.get_speech_queue(session, active_session.id)

    curr_speaker_txt = "—"
    if active_session.current_speaker_country_id:
        spk = await countries_repo.get_country(session, active_session.current_speaker_country_id)
        if spk:
            curr_speaker_txt = f"{spk.flag} {spk.name_fa}"

    text = (
        header(active_session.title, "🏛") + "\n\n"
        f"وضعیت اجلاس: <b>{active_session.status.upper()}</b>\n"
        f"🔹 پروازهای در راه: <b>{len(in_flight)} کشور</b>\n"
        f"🔹 در شهر نیویورک (لابی): <b>{len(in_ny)} کشور</b>\n"
        f"🔹 داخل صحن علنی تالار: <b>{len(in_hall)} کشور</b>\n"
        f"🎙 سخنران پشت تریبون: <b>{curr_speaker_txt}</b>\n"
        f"📋 صف انتظار سخنرانی: <b>{len(queue)} کشور</b>\n"
    )
    await safe_edit(
        call,
        text,
        reply_markup=un_assembly_admin_kb(active_session.id, is_active=(active_session.status == "active")),
    )


@router.callback_query(F.data == "un_asmb_create")
async def cb_un_asmb_create(call: CallbackQuery, session: AsyncSession) -> None:
    """ایجاد اجلاس سالانه و ارسال دعوت به کشورها."""
    new_s = UNAssemblySession(
        session_number=random.randint(80, 85),
        status="pending",
        title="اجلاس سالانه مجمع عمومی سازمان ملل متحد — نیویورک",
        started_at=_utcnow(),
    )
    new_s = await un_repo.create_session(session, new_s)

    # ارسال دعوت‌نامه به تمام کشورهای دارای مالک (غیر از UN)
    all_countries = await countries_repo.list_countries(session)
    sent_count = 0
    for c in all_countries:
        if c.name_en != "UN" and c.is_claimed and c.owner_user_id:
            try:
                invite_text = (
                    "🏛 <b>دعوت‌نامه رسمی دبیرکل سازمان ملل متحد:</b>\n\n"
                    f"جناب رهبر محترم کشور {c.flag} <b>{c.name_fa}</b>،\n"
                    "از شما دعوت به عمل می‌آید تا در اجلاس سالانه مجمع عمومی سازمان ملل متحد در مقر نیویورک حضور به هم رسانید.\n"
                    "با پذیرش دعوت، هواپیمای ریاست‌جمهوری شما عازم نیویورک خواهد شد."
                )
                await bot.send_message(c.owner_user_id, invite_text, reply_markup=assembly_invite_kb(new_s.id))
                sent_count += 1
            except Exception:
                pass

    await call.answer("اجلاس ایجاد و دعوت‌نامه‌ها ارسال شد.", show_alert=True)
    await safe_edit(
        call,
        f"🚀 <b>اجلاس ایجاد شد!</b>\nدعوت‌نامه رسمی برای {sent_count} کشور جهان ارسال گردید.\n"
        "پس از ورود رهبران به نیویورک، می‌توانید صحن علنی را رسماً فعال کنید.",
        reply_markup=un_assembly_admin_kb(new_s.id, is_active=False),
    )


@router.callback_query(F.data.startswith("asmb_fly:"))
async def cb_asmb_fly(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پذیرش دعوت مجمع عمومی و آغاز پرواز ریاست‌جمهوری به نیویورک."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        await call.answer(NO_COUNTRY_TEXT, show_alert=True)
        return

    # محاسبه مدت زمان پرواز بر اساس مسافت پایتخت تا نیویورک
    flight_dur = geo.compute_flight_duration(country.name_en, "UN")
    now = _utcnow()
    eta = now + timedelta(minutes=flight_dur)

    part = UNAssemblyParticipant(
        session_id=session_id,
        country_id=country.id,
        status="in_flight",
        travel_eta=eta,
    )
    await un_repo.add_participant(session, part)

    await safe_edit(
        call,
        f"✈️ <b>پرواز رسمی به مقصد نیویورک آغاز شد:</b>\n\n"
        f"هواپیمای ریاست‌جمهوری {country.flag} {country.name_fa} عازم مقر سازمان ملل در منهتن نیویورک گردید.\n"
        f"⏳ مدت زمان سفر متناسب با مسافت: <b>{fa_number(flight_dur)} دقیقه</b>\n"
        "به محض فرود در نیویورک، اعلان رسمی دریافت خواهید کرد.",
    )


@router.callback_query(F.data.startswith("asmb_decline:"))
async def cb_asmb_decline(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """رد مودبانه دعوت مجمع عمومی."""
    await call.answer("دعوت رد شد.")
    await safe_edit(call, "❌ شما از شرکت در اجلاس امسال مجمع عمومی انصراف دادید.")


@router.callback_query(F.data.startswith("un_asmb_activate:"))
async def cb_un_asmb_activate(call: CallbackQuery, session: AsyncSession) -> None:
    """آغاز رسمی صحن علنی تالار توسط دبیرکل."""
    session_id = int(call.data.split(":")[1])
    asmb = await un_repo.get_session(session, session_id)
    if asmb:
        asmb.status = "active"
        asmb.activated_at = _utcnow()
        await session.flush()

    await call.answer("صحن علنی مجمع عمومی رسماً آغاز شد!", show_alert=True)
    await safe_edit(
        call,
        "🏛 <b>صحن علنی مجمع عمومی هم‌اکنون فعال است.</b>\nکشورهای حاضر در نیویورک می‌توانند وارد تالار شوند.",
        reply_markup=un_assembly_admin_kb(session_id, is_active=True),
    )

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        "🇺🇳 <b>آغاز صحن علنی مجمع عمومی سازمان ملل متحد در نیویورک:</b>\n"
        "با حضور گسترده هیئت‌های دیپلماتیک و سران کشورها، چکش افتتاح اجلاس مجمع عمومی به صدا درآمد.",
    )


# ============================================================
#  🗽 لابی و محیط شهر نیویورک (بیرون تالار مجمع)
# ============================================================


@router.callback_query(F.data.startswith("asmb_enter_hall:"))
async def cb_asmb_enter_hall(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ورود به تالار مجمع عمومی (قفل شدن پنل کشوری)."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    part = await un_repo.get_participant(session, session_id, country.id)
    if not part:
        await call.answer("شما در این اجلاس حضور ندارید.", show_alert=True)
        return

    part.status = "inside_hall"
    part.joined_hall_at = _utcnow()
    await session.flush()

    pres_name = await _get_pres_name(session, country)

    # اعلان ورود به تمام افرادی که از قبل داخل تالار هستند و دبیرکل
    in_hall_parts = await un_repo.list_participants_by_status(session, session_id, "inside_hall")
    for p in in_hall_parts:
        if p.country_id != country.id:
            c = await countries_repo.get_country(session, p.country_id)
            if c and c.owner_user_id:
                try:
                    await bot.send_message(
                        c.owner_user_id,
                        f"🔔 <b>رئیس‌جمهور محترم کشور {country.flag} {country.name_fa} ({pres_name}) وارد تالار مجمع عمومی شد.</b>",
                    )
                except Exception:
                    pass

    # اطلاع به دبیرکل
    un_c = await countries_repo.get_country_by_name(session, "UN")
    if un_c and un_c.owner_user_id:
        try:
            await bot.send_message(
                un_c.owner_user_id,
                f"🔔 <b>ورود به صحن:</b> رهبر کشور {country.flag} {country.name_fa} وارد تالار مجمع شد.",
            )
        except Exception:
            pass

    text = (
        header("تالار مجمع عمومی سازمان ملل متحد", "🏛") + "\n\n"
        f"شما هم‌اکنون بر روی صندلی نمایندگی کشور {country.flag} <b>{country.name_fa}</b> در صحن علنی مستقر شدید.\n"
        "⚠️ <b>توجه:</b> تا زمانی که داخل تالار حضور دارید، جهت حفظ نظم دیپلماتیک دسترسی به پنل کشور قفل است.\n"
        "می‌توانید برای سخنرانی اعلام حضور نمایید یا هر زمان تمایل داشتید از تالار خارج شوید."
    )
    await safe_edit(call, text, reply_markup=assembly_hall_kb(session_id, is_speaker=False))


@router.callback_query(F.data.startswith("asmb_exit_hall:"))
async def cb_asmb_exit_hall(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """خروج از تالار مجمع به لابی شهر نیویورک (باز شدن پنل کشوری)."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    part = await un_repo.get_participant(session, session_id, country.id)
    if part:
        part.status = "in_new_york"
        await session.flush()

    # اعلام خروج به حاضران تالار
    in_hall_parts = await un_repo.list_participants_by_status(session, session_id, "inside_hall")
    for p in in_hall_parts:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"🔕 <b>رئیس‌جمهور کشور {country.flag} {country.name_fa} از تالار مجمع خارج شد.</b>",
                )
            except Exception:
                pass

    await safe_edit(
        call,
        "🗽 شما از تالار مجمع عمومی خارج شدید و هم‌اکنون در شهر نیویورک حضور دارید.\n"
        "پنل کشوری شما کاملاً باز است و پیام‌های داخل صحن برای شما ارسال نمی‌شود.",
        reply_markup=assembly_ny_lobby_kb(session_id),
    )


@router.callback_query(F.data.startswith("asmb_return_home:"))
async def cb_asmb_return_home(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """بازگشت درجا به کشور و خروج از نیویورک."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    part = await un_repo.get_participant(session, session_id, country.id)
    if part:
        part.status = "left"
        await session.flush()

    await safe_edit(
        call,
        f"🏡 <b>بازگشت به وطن:</b>\nشما به سلامت به پایتخت کشور {country.flag} {country.name_fa} بازگشتید "
        "و اداره امور کشوری را به شکل عادی از سر گرفتید.",
    )


@router.callback_query(F.data.startswith("asmb_sideline_meet:"))
async def cb_asmb_sideline_meet(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """دیدار دوجانبه در حاشیه اجلاس نیویورک با کشورهای حاضر در نیویورک."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    parts = await un_repo.list_participants(session, session_id)
    ny_country_ids = [p.country_id for p in parts if p.status in ("in_new_york", "inside_hall") and p.country_id != country.id]
    if not ny_country_ids:
        await call.answer("کشور دیگری در حال حاضر در نیویورک در دسترس نیست.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for cid in ny_country_ids:
        c = await countries_repo.get_country(session, cid)
        if c:
            builder.button(text=f"🤝 {c.flag} {c.name_fa}", callback_data=f"call_to:{c.id}")
    builder.button(text="🔙 بازگشت به لابی", callback_data=f"asmb_exit_hall:{session_id}")
    builder.adjust(2)

    await safe_edit(
        call,
        "🤝 <b>دیدار در حاشیه اجلاس نیویورک:</b>\n"
        "کشورهای زیر هم‌اکنون در نیویورک حضور دارند و می‌توانید بدون اتلاف وقت و پرواز با آن‌ها تماس بگیرید یا دیدار کنید:",
        reply_markup=builder.as_markup(),
    )


# ============================================================
#  🎙 نوبت سخنرانی و صحن علنی
# ============================================================


@router.callback_query(F.data.startswith("asmb_req_speech:"))
async def cb_asmb_req_speech(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """درخواست نوبت سخنرانی (اعلام حضور)."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    q = UNSpeechQueue(
        session_id=session_id,
        country_id=country.id,
        status="waiting",
        requested_at=_utcnow(),
    )
    await un_repo.add_speech_request(session, q)

    # اطلاع به دبیرکل
    un_c = await countries_repo.get_country_by_name(session, "UN")
    if un_c and un_c.owner_user_id:
        try:
            await bot.send_message(
                un_c.owner_user_id,
                f"✋ <b>نوبت سخنرانی:</b> رهبر کشور {country.flag} {country.name_fa} در صحن علنی اعلام حضور کرد و در صف سخنرانی قرار گرفت.",
            )
        except Exception:
            pass

    await call.answer("شما در صف سخنرانی مجمع عمومی قرار گرفتید.", show_alert=True)


@router.callback_query(F.data.startswith("un_asmb_next:"))
async def cb_un_asmb_next(call: CallbackQuery, session: AsyncSession) -> None:
    """اعطای تریبون به نفر بعدی صف سخنرانی توسط دبیرکل."""
    session_id = int(call.data.split(":")[1])
    asmb = await un_repo.get_session(session, session_id)
    if not asmb:
        return

    # بستن سخنران فعلی در صورت وجود
    curr = await un_repo.get_active_speech(session, session_id)
    if curr:
        await un_repo.set_speaker_done(session, curr.id)
        # آنالیز سخنرانی قبلی
        old_spk = await countries_repo.get_country(session, curr.country_id)
        if old_spk:
            pname = await _get_pres_name(session, old_spk)
            await analyze_and_publish_speech(bot, old_spk.name_fa, pname, curr.speech_transcript, old_spk.is_vip)

    nxt = await un_repo.get_next_speaker(session, session_id)
    if not nxt:
        asmb.current_speaker_country_id = None
        asmb.speech_ends_at = None
        await session.flush()
        await call.answer("هیچ کشوری در صف نوبت سخنرانی نیست.", show_alert=True)
        return

    now = _utcnow()
    nxt.status = "speaking"
    nxt.started_at = now
    nxt.ends_at = now + timedelta(minutes=UN_ASSEMBLY_SPEECH_DURATION_MINUTES)
    asmb.current_speaker_country_id = nxt.country_id
    asmb.speech_ends_at = nxt.ends_at
    await session.flush()

    spk_country = await countries_repo.get_country(session, nxt.country_id)
    pname = await _get_pres_name(session, spk_country)

    # اطلاع به همه حاضران تالار
    in_hall_parts = await un_repo.list_participants_by_status(session, session_id, "inside_hall")
    broadcast_txt = (
        f"🎙 <b>تریبون مجمع عمومی سازمان ملل متحد:</b>\n\n"
        f"هم‌اکنون نوبت سخنرانی جناب آقای <b>{pname}</b> رهبر محترم کشور {spk_country.flag} <b>{spk_country.name_fa}</b> آغاز شد.\n"
        f"⏳ مدت زمان سخنرانی: <b>۵ دقیقه</b> (ارسال متن و عکس مجاز است)."
    )
    for p in in_hall_parts:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id:
            try:
                is_spk = (c.id == spk_country.id)
                await bot.send_message(
                    c.owner_user_id,
                    broadcast_txt,
                    reply_markup=assembly_hall_kb(session_id, is_speaker=is_spk),
                )
            except Exception:
                pass

    await call.answer("تریبون به سخنران بعدی داده شد.")


@router.callback_query(F.data.startswith("asmb_end_speech:"))
async def cb_asmb_end_speech(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """پایان داوطلبانه سخنرانی توسط خود سخنران."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    curr = await un_repo.get_active_speech(session, session_id)
    if curr and curr.country_id == country.id:
        await un_repo.set_speaker_done(session, curr.id)
        asmb = await un_repo.get_session(session, session_id)
        if asmb:
            asmb.current_speaker_country_id = None
            asmb.speech_ends_at = None

        pname = await _get_pres_name(session, country)
        await analyze_and_publish_speech(bot, country.name_fa, pname, curr.speech_transcript, country.is_vip)

    await call.answer("سخنرانی شما پایان یافت و نطق شما توسط هوش مصنوعی آنالیز شد.", show_alert=True)
    await safe_edit(call, "⏹ سخنرانی شما خاتمه یافت.", reply_markup=assembly_hall_kb(session_id, is_speaker=False))


@router.callback_query(F.data.startswith("asmb_applaud:"))
async def cb_asmb_applaud(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """تشویق سخنران توسط حاضران."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    in_hall_parts = await un_repo.list_participants_by_status(session, session_id, "inside_hall")
    for p in in_hall_parts:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id and c.id != country.id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"👏 هیئت دیپلماتیک کشور {country.flag} {country.name_fa} سخنران را تشویق کرد.",
                )
            except Exception:
                pass
    await call.answer("تشویق ارسال شد.")


@router.callback_query(F.data.startswith("asmb_walkout:"))
async def cb_asmb_walkout(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ترک اعتراضی تالار (Walkout)."""
    session_id = int(call.data.split(":")[1])
    country = await get_player_country(session, db_user)
    if not country:
        return

    part = await un_repo.get_participant(session, session_id, country.id)
    if part:
        part.status = "in_new_york"
        part.walkout = True
        await session.flush()

    # اعلام ترک اعتراضی به همه حاضران
    in_hall_parts = await un_repo.list_participants_by_status(session, session_id, "inside_hall")
    for p in in_hall_parts:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(
                    c.owner_user_id,
                    f"🚶‍♂️ <b>اعتراض دیپلماتیک شدید:</b> هیئت کشور {country.flag} {country.name_fa} در اعتراض به سخنرانی جاری، صحن علنی مجمع عمومی را ترک کرد!",
                )
            except Exception:
                pass

    await safe_edit(
        call,
        "🚶‍♂️ شما در اعتراض به مواضع سخنران، صحن تالار را ترک نمودید و به لابی نیویورک بازگشتید.",
        reply_markup=assembly_ny_lobby_kb(session_id),
    )


@router.callback_query(F.data.startswith("un_asmb_close:"))
async def cb_un_asmb_close(call: CallbackQuery, session: AsyncSession) -> None:
    """پایان دادن رسمی به اجلاس سالانه مجمع عمومی توسط دبیرکل."""
    session_id = int(call.data.split(":")[1])
    await un_repo.close_session(session, session_id)

    # اطلاع به همه مشارکت‌کنندگان
    parts = await un_repo.list_participants(session, session_id)
    close_text = (
        "🏁 <b>پایان رسمی اجلاس سالانه مجمع عمومی سازمان ملل متحد (نیویورک):</b>\n\n"
        "دبیرکل محترم پایان رسمی مذاکرات صحن علنی امسال را اعلام نمودند.\n"
        "شما می‌توانید در صورت تمایل جهت مذاکرات دوجانبه در نیویورک بمانید، یا با دکمه «🔙 بازگشت به کشور» فوراً به پایتخت خود بازگردید."
    )
    for p in parts:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, close_text, reply_markup=assembly_ny_lobby_kb(session_id))
            except Exception:
                pass

    await call.answer("اجلاس با موفقیت پایان یافت.", show_alert=True)
    await safe_edit(call, "🏁 اجلاس سالانه مجمع عمومی با موفقیت بسته شد.", reply_markup=un_main_menu_kb())

    await publish_news(
        bot,
        NewsCategory.DIPLOMACY,
        "🇺🇳 <b>پایان اجلاس سالانه مجمع عمومی سازمان ملل متحد:</b>\n"
        "با صدور بیانیه نهایی دبیرکل، هشتاد و یکمین اجلاس مجمع عمومی سازمان ملل متحد در نیویورک رسماً به کار خود پایان داد.",
    )


# ============================================================
#  ⚖️ دیوان بین‌المللی دادگستری (دادگاه لاهه - ICJ)
# ============================================================


@router.callback_query(F.data == "court:main")
async def cb_court_main(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ورود به دادگاه بین‌الملل از منوی دیپلماسی کشورها."""
    country = await get_player_country(session, db_user)
    if not await assert_feature(call, session, country, "un.court"):
        return

    text = (
        header("دیوان بین‌المللی دادگستری (دادگاه لاهه - ICJ)", "⚖️") + "\n\n"
        "رکن اصلی قضایی سازمان ملل متحد جهت حل‌وفصل دعاوی حقوقی، اختلافات مرزی/تنگه‌ای، "
        "جبران خسارات نظامی و رسیدگی به نقض معاهدات بین‌المللی."
    )
    await safe_edit(call, text, reply_markup=court_main_kb())


@router.callback_query(F.data == "court:new_claim")
async def cb_court_new_claim(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """شروع ثبت دادخواست رسمی."""
    country = await get_player_country(session, db_user)
    if not country:
        return

    countries = await countries_repo.list_countries(session)
    valid_targets = [c for c in countries if c.id != country.id and c.name_en != "UN"]

    await state.set_state(CourtForm.choosing_defendant)
    await safe_edit(
        call,
        "⚖️ <b>انتخاب طرف خوانده (متهم):</b>\nشکایت رسمی خود را علیه کدام کشور ثبت می‌کنید؟",
        reply_markup=countries_kb(valid_targets, prefix="court_def", columns=2),
    )


@router.callback_query(CourtForm.choosing_defendant, F.data.startswith("court_def:"))
async def cb_court_def_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """انتخاب خوانده و سپس انتخاب موضوع شکایت."""
    def_id = int(call.data.split(":")[1])
    await state.update_data(defendant_id=def_id)
    await state.set_state(CourtForm.choosing_issue)
    await safe_edit(call, "📜 موضوع دادخواست خود را انتخاب کنید:", reply_markup=court_issues_kb())


@router.callback_query(CourtForm.choosing_issue, F.data.startswith("court_issue:"))
async def cb_court_issue_pick(call: CallbackQuery, state: FSMContext) -> None:
    """انتخاب موضوع و درخواست عنوان شکایت."""
    issue = call.data.split(":")[1]
    await state.update_data(issue_type=issue)
    await state.set_state(CourtForm.entering_claim_title)
    await safe_edit(call, "✍️ لطفاً <b>عنوان مختصر دادخواست</b> را بنویسید (مثلاً: ادعای خسارت بابت توقیف شناور در هرمز):")


@router.message(CourtForm.entering_claim_title)
async def msg_court_claim_title(message: Message, state: FSMContext) -> None:
    """دریافت عنوان دادخواست."""
    title = (message.text or "").strip()
    await state.update_data(claim_title=title)
    await state.set_state(CourtForm.entering_claim_description)
    await message.answer("📝 لطفاً <b>شرح شکایت و ادله حقوقی</b> خود را به صورت مفصل تایپ نمایید:")


@router.message(CourtForm.entering_claim_description)
async def msg_court_claim_desc(message: Message, state: FSMContext) -> None:
    """دریافت شرح و ادله و درخواست مبلغ غرامت."""
    desc = (message.text or "").strip()
    await state.update_data(claim_description=desc)
    await state.set_state(CourtForm.entering_demanded_compensation)
    await message.answer("💸 مبلغ غرامت درخواستی خود را به <b>میلیون دلار</b> وارد نمایید (مثلاً عدد 50 برای ۵۰ میلیون دلار، یا 0):")


@router.message(CourtForm.entering_demanded_compensation)
async def msg_court_claim_comp(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """ثبت قطعی دادخواست در دیوان لاهه."""
    country = await get_player_country(session, db_user)
    if not country:
        return

    try:
        val = float(message.text.strip())
        demanded = val * 1_000_000.0
    except ValueError:
        demanded = 0.0

    data = await state.get_data()
    await state.clear()

    case_num = f"ICJ-{_utcnow().year}-{random.randint(100, 999)}"
    court_case = InternationalCourtCase(
        case_number=case_num,
        claimant_country_id=country.id,
        defendant_country_id=data["defendant_id"],
        issue_type=data["issue_type"],
        claim_title=data["claim_title"],
        claim_description=data["claim_description"],
        demanded_compensation=demanded,
        status="pending",
    )
    session.add(court_case)
    await session.flush()

    defendant = await countries_repo.get_country(session, data["defendant_id"])
    un_country = await countries_repo.get_country_by_name(session, "UN")

    # اطلاع به دبیرکل سازمان ملل (رئیس دیوان)
    if un_country and un_country.owner_user_id:
        try:
            await bot.send_message(
                un_country.owner_user_id,
                f"⚖️ <b>دادخواست جدید در دیوان لاهه:</b>\n\n"
                f"شاکی: {country.flag} {country.name_fa}\n"
                f"متهم: {defendant.flag if defendant else ''} {defendant.name_fa if defendant else ''}\n"
                f"عنوان: {data['claim_title']}\n"
                f"شماره پرونده: <b>{case_num}</b>",
            )
        except Exception:
            pass

    await message.answer(
        f"⚖️ <b>دادخواست شما با موفقیت در دیوان بین‌المللی دادگستری ثبت گردید:</b>\n\n"
        f"شماره پرونده: <code>{case_num}</code>\n"
        f"پرونده به دبیرکل سازمان ملل جهت تعیین وقت دادرسی و تشکیل جلسه ابلاغ شد."
    )


@router.callback_query(F.data == "un:court")
async def cb_un_court_admin(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """کارتابل قضایی دیوان لاهه در پنل دبیرکل سازمان ملل."""
    country = await get_player_country(session, db_user)
    if country is None or country.name_en != "UN":
        await call.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    cases = await un_repo.list_court_cases(session)
    if not cases:
        await safe_edit(
            call,
            "⚖️ <b>کارتابل قضایی دیوان بین‌المللی دادگستری:</b>\nدر حال حاضر هیچ دادخواست معوقی وجود ندارد.",
            reply_markup=un_main_menu_kb(),
        )
        return

    builder = InlineKeyboardBuilder()
    for cs in cases[:10]:
        cl = await countries_repo.get_country(session, cs.claimant_country_id)
        df = await countries_repo.get_country(session, cs.defendant_country_id)
        cl_name = cl.name_fa if cl else "شاکی"
        df_name = df.name_fa if df else "متهم"
        st_icon = "⏳" if cs.status == "pending" else ("⚖️" if cs.status == "trial" else "✅")
        builder.button(
            text=f"{st_icon} {cs.case_number} ({cl_name} علیه {df_name})",
            callback_data=f"court_admin_view:{cs.id}",
        )
    builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
    builder.adjust(1)

    await safe_edit(call, "⚖️ <b>پرونده‌های دیوان بین‌المللی دادگستری (لاهه):</b>", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("court_admin_view:"))
async def cb_court_admin_view(call: CallbackQuery, session: AsyncSession) -> None:
    """مشاهده مشخصات پرونده توسط دبیرکل."""
    case_id = int(call.data.split(":")[1])
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cl = await countries_repo.get_country(session, cs.claimant_country_id)
    df = await countries_repo.get_country(session, cs.defendant_country_id)

    text = (
        header(f"پرونده دیوان لاهه: {cs.case_number}", "⚖️") + "\n\n"
        f"🔹 شاکی: <b>{cl.flag if cl else ''} {cl.name_fa if cl else ''}</b>\n"
        f"🔹 متهم (خوانده): <b>{df.flag if df else ''} {df.name_fa if df else ''}</b>\n"
        f"🔹 موضوع: <b>{cs.issue_type}</b>\n"
        f"🔹 عنوان: <b>{cs.claim_title}</b>\n"
        f"🔹 غرامت درخواستی: <b>{fa_number(cs.demanded_compensation / 1e6)} میلیون دلار</b>\n\n"
        f"📝 <b>شرح دادخواست:</b>\n{cs.claim_description}\n\n"
        f"وضعیت فعلی: <b>{cs.status.upper()}</b>"
    )
    await safe_edit(
        call,
        text,
        reply_markup=un_court_admin_kb(cs.id, cs.claimant_country_id, cs.defendant_country_id, is_trial=(cs.status == "trial")),
    )


@router.callback_query(F.data.startswith("court_start_trial:"))
async def cb_court_start_trial(call: CallbackQuery, session: AsyncSession) -> None:
    """تشکیل جلسه دادرسی رسمی دادگاه لاهه."""
    case_id = int(call.data.split(":")[1])
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cs.status = "trial"
    cs.current_turn_country_id = cs.claimant_country_id  # نوبت اول با شاکی

    # ثبت طرفین دادگاه
    p1 = CourtParty(case_id=cs.id, country_id=cs.claimant_country_id, role="claimant", can_speak=True)
    p2 = CourtParty(case_id=cs.id, country_id=cs.defendant_country_id, role="defendant", can_speak=False)
    await un_repo.add_court_party(session, p1)
    await un_repo.add_court_party(session, p2)
    await session.flush()

    cl = await countries_repo.get_country(session, cs.claimant_country_id)
    df = await countries_repo.get_country(session, cs.defendant_country_id)

    # اطلاع به شاکی و متهم
    notice = (
        f"🏛 <b>جلسه دادرسی دیوان بین‌المللی دادگستری رسماً آغاز شد:</b>\n"
        f"پرونده: <b>{cs.case_number}</b>\n"
        "طرفین به دادگاه فراخوانده شدند. هم‌اکنون پیام‌های ارسالی شما در جلسه دادگاه بین شاکی، متهم و دبیرکل رله خواهد شد."
    )
    for c in (cl, df):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, notice)
            except Exception:
                pass

    await call.answer("جلسه دادرسی آغاز شد.", show_alert=True)
    await safe_edit(
        call,
        f"🏛 <b>جلسه دادرسی پرونده {cs.case_number} آغاز شد.</b>\nنوبت دفاعیه در ابتدا در اختیار شاکی قرار گرفت.",
        reply_markup=un_court_admin_kb(cs.id, cs.claimant_country_id, cs.defendant_country_id, is_trial=True),
    )


@router.callback_query(F.data.startswith("court_turn:"))
async def cb_court_turn(call: CallbackQuery, session: AsyncSession) -> None:
    """اعطای نوبت دفاعیه در دادگاه لاهه."""
    parts = call.data.split(":")
    case_id = int(parts[1])
    target = parts[2]
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    parties = await un_repo.list_court_parties(session, case_id)
    if target == "all":
        cs.current_turn_country_id = None
        for p in parties:
            p.can_speak = True
        txt = "تریبون آزاد برای کلیه طرفین دادگاه باز شد."
    else:
        cid = int(target)
        cs.current_turn_country_id = cid
        for p in parties:
            p.can_speak = (p.country_id == cid)
        target_c = await countries_repo.get_country(session, cid)
        txt = f"نوبت دفاعیه به کشور {target_c.flag if target_c else ''} {target_c.name_fa if target_c else ''} اعطا شد."

    await session.flush()
    # اطلاع به طرفین
    for p in parties:
        c = await countries_repo.get_country(session, p.country_id)
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, f"🎙 <b>اعلان رئیس دادگاه:</b> {txt}")
            except Exception:
                pass

    await call.answer(txt)


@router.callback_query(F.data.startswith("court_verdict_prompt:"))
async def cb_court_verdict_prompt(call: CallbackQuery) -> None:
    """انتخاب نوع حکم نهایی دادگاه."""
    case_id = int(call.data.split(":")[1])
    await safe_edit(
        call,
        "🔨 <b>صدور حکم نهایی دیوان بین‌المللی دادگستری:</b>\nنوع حکم قضایی را انتخاب نمایید:",
        reply_markup=un_court_verdict_choices_kb(case_id),
    )


@router.callback_query(F.data.startswith("court_v_acquit:"))
async def cb_court_v_acquit(call: CallbackQuery, session: AsyncSession) -> None:
    """حکم تبرئه متهم و رد شکایت."""
    case_id = int(call.data.split(":")[1])
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cs.status = "verdict_issued"
    cs.verdict_type = "acquittal"
    cs.verdict_text = "عدم احراز تخلف و رد دادخواست شاکی به علت فقدان ادله کافی."
    cs.resolved_at = _utcnow()
    await session.flush()

    cl = await countries_repo.get_country(session, cs.claimant_country_id)
    df = await countries_repo.get_country(session, cs.defendant_country_id)

    verdict_msg = (
        f"⚖️ <b>حکم قطعی دیوان بین‌المللی دادگستری (لاهه) — پرونده {cs.case_number}:</b>\n\n"
        f"پس از استماع دفاعیات طرفین، دیوان رأی به <b>تبرئه کامل کشور {df.flag if df else ''} {df.name_fa if df else ''}</b> "
        f"و رد کامل ادعای کشور {cl.flag if cl else ''} {cl.name_fa if cl else ''} صادر نمود."
    )
    for c in (cl, df):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, verdict_msg)
            except Exception:
                pass

    await safe_edit(call, "🟢 حکم تبرئه متهم رسماً صادر و پرونده مختومه شد.", reply_markup=un_main_menu_kb())
    await publish_news(bot, NewsCategory.DIPLOMACY, verdict_msg)


@router.callback_query(F.data.startswith("court_v_fine:"))
async def cb_court_v_fine(call: CallbackQuery, state: FSMContext) -> None:
    """درخواست مبلغ غرامت برای صدور حکم محکومیت مالی."""
    case_id = int(call.data.split(":")[1])
    await state.update_data(case_id=case_id)
    await state.set_state(CourtForm.entering_fine_amount)
    await safe_edit(call, "💸 مبلغ قطعی محکومیت به غرامت را به <b>میلیون دلار</b> وارد کنید (مثلاً عدد 40 برای ۴۰ میلیون دلار):")


@router.message(CourtForm.entering_fine_amount)
async def msg_court_fine_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """اعمال حکم جریمه مالی و کسر از متهم و واریز به شاکی."""
    try:
        val = float(message.text.strip())
        fine = val * 1_000_000.0
    except ValueError:
        fine = 20_000_000.0

    data = await state.get_data()
    await state.clear()
    case_id = data["case_id"]

    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cl = await countries_repo.get_country(session, cs.claimant_country_id)
    df = await countries_repo.get_country(session, cs.defendant_country_id)

    # کسر از متهم و واریز به شاکی
    if df and cl:
        actual_fine = min(df.budget, fine)
        df.budget -= actual_fine
        cl.budget += actual_fine

    cs.status = "verdict_issued"
    cs.verdict_type = "compensation"
    cs.compensation_awarded = fine
    cs.verdict_text = f"محکومیت قطعی به پرداخت مبلغ {fa_number(fine / 1e6)} میلیون دلار غرامت به کشور شاکی."
    cs.resolved_at = _utcnow()
    await session.flush()

    verdict_msg = (
        f"⚖️ <b>حکم قطعی دیوان بین‌المللی دادگستری (لاهه) — پرونده {cs.case_number}:</b>\n\n"
        f"دیوان بین‌المللی دادگستری کشور <b>{df.flag if df else ''} {df.name_fa if df else ''}</b> را در نقض تعهدات بین‌المللی محکوم شناخته "
        f"و به پرداخت <b>{fa_number(fine / 1e6)} میلیون دلار غرامت رسمی</b> در حق کشور <b>{cl.flag if cl else ''} {cl.name_fa if cl else ''}</b> محکوم نمود.\n"
        "مبلغ فوق مستقیماً از خزانه متهم کسر و به حساب شاکی واریز گردید."
    )
    for c in (cl, df):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, verdict_msg)
            except Exception:
                pass

    await message.answer("💸 حکم محکومیت مالی با موفقیت صادر و وجه بین کشورها منتقل شد.")
    await publish_news(bot, NewsCategory.DIPLOMACY, verdict_msg)


@router.callback_query(F.data.startswith("court_v_release:"))
async def cb_court_v_release(call: CallbackQuery, session: AsyncSession) -> None:
    """حکم آزادسازی اموال بلوکه‌شده در تنگه."""
    case_id = int(call.data.split(":")[1])
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cs.status = "verdict_issued"
    cs.verdict_type = "release_cargo"
    cs.verdict_text = "دستور قضایی به رفع توقیف فوری و بدون قیدوشرط کلیه شناورها و بارهای بلوکه‌شده."
    cs.resolved_at = _utcnow()
    await session.flush()

    cl = await countries_repo.get_country(session, cs.claimant_country_id)
    df = await countries_repo.get_country(session, cs.defendant_country_id)

    verdict_msg = (
        f"⚖️ <b>حکم الزام‌آور دیوان بین‌المللی دادگستری — پرونده {cs.case_number}:</b>\n\n"
        f"دیوان لاهه توقیف اموال و شناورهای کشور {cl.flag if cl else ''} {cl.name_fa if cl else ''} توسط {df.flag if df else ''} {df.name_fa if df else ''} را غیرقانونی دانسته "
        "و دستور آزادی فوری و اجازه عبور امن دریایی را صادر نمود."
    )
    for c in (cl, df):
        if c and c.owner_user_id:
            try:
                await bot.send_message(c.owner_user_id, verdict_msg)
            except Exception:
                pass

    await safe_edit(call, "🔓 حکم آزادسازی اموال رسماً صادر گردید.", reply_markup=un_main_menu_kb())
    await publish_news(bot, NewsCategory.DIPLOMACY, verdict_msg)


@router.callback_query(F.data.startswith("court_v_sanction:"))
async def cb_court_v_sanction(call: CallbackQuery, session: AsyncSession) -> None:
    """صدور مجوز تحریم بین‌المللی علیه کشور خاطی."""
    case_id = int(call.data.split(":")[1])
    cs = await un_repo.get_court_case(session, case_id)
    if not cs:
        return

    cs.status = "verdict_issued"
    cs.verdict_type = "sanction_auth"
    cs.verdict_text = "صدور مجوز وضع تحریم‌های بین‌المللی و انسداد تجاری علیه کشور خاطی."
    cs.resolved_at = _utcnow()
    await session.flush()

    df = await countries_repo.get_country(session, cs.defendant_country_id)

    verdict_msg = (
        f"⚖️ <b>صدور قطعنامه تحریم بین‌المللی دیوان لاهه — پرونده {cs.case_number}:</b>\n\n"
        f"با احراز نقض صلح و امنیت، دیوان بین‌المللی دادگستری مجوز وضع تحریم‌های اقتصادی و تجاری همه‌جانبه "
        f"علیه کشور <b>{df.flag if df else ''} {df.name_fa if df else ''}</b> را برای کلیه کشورهای جهان صادر نمود."
    )
    await safe_edit(call, "🚫 مجوز تحریم‌های بین‌المللی صادر گردید.", reply_markup=un_main_menu_kb())
    await publish_news(bot, NewsCategory.DIPLOMACY, verdict_msg)


# ============================================================
#  🕊 صندوق کمک‌های بشردوستانه سازمان ملل
# ============================================================


@router.callback_query(F.data == "un:humanitarian")
async def cb_un_humanitarian(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """صندوق مالی و کمک‌های بشردوستانه سازمان ملل."""
    un_country = await get_player_country(session, db_user)
    if un_country is None or un_country.name_en != "UN":
        return

    countries = await countries_repo.list_countries(session)
    valid_recipients = [c for c in countries if c.name_en != "UN" and c.is_claimed]

    builder = InlineKeyboardBuilder()
    for c in valid_recipients:
        builder.button(text=f"🎁 {c.flag} {c.name_fa}", callback_data=f"aid_to:{c.id}")
    builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
    builder.adjust(2)

    text = (
        header("صندوق کمک‌های بشردوستانه سازمان ملل متحد", "🕊") + "\n\n"
        f"موجودی فعلی صندوق: <b>{fa_number(un_country.budget / 1e6)} میلیون دلار</b>\n"
        "کشور دریافت‌کننده کمک‌های اضطراری را انتخاب کنید:"
    )
    await safe_edit(call, text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("aid_to:"))
async def cb_aid_to(call: CallbackQuery, state: FSMContext) -> None:
    """دریافت مبلغ کمک بشردوستانه."""
    cid = int(call.data.split(":")[1])
    await state.update_data(recipient_id=cid)
    await state.set_state(HumanitarianForm.entering_aid_amount)
    await safe_edit(call, "💸 مبلغ بسته کمک بشردوستانه را به <b>میلیون دلار</b> وارد کنید (مثلاً عدد 25):")


@router.message(HumanitarianForm.entering_aid_amount)
async def msg_aid_amount(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    """واریز کمک بشردوستانه به کشور مقصد."""
    un_country = await get_player_country(session, db_user)
    if not un_country or un_country.name_en != "UN":
        return

    try:
        val = float(message.text.strip())
        aid = val * 1_000_000.0
    except ValueError:
        await message.answer("لطفاً یک عدد معتبر وارد کنید.")
        return

    if un_country.budget < aid:
        await message.answer("بودجه صندوق بشردوستانه برای این مبلغ کافی نیست.")
        return

    data = await state.get_data()
    await state.clear()

    recip = await countries_repo.get_country(session, data["recipient_id"])
    if not recip:
        return

    un_country.budget -= aid
    recip.budget += aid
    recip.public_satisfaction = min(100.0, recip.public_satisfaction + 5.0)
    await session.flush()

    if recip.owner_user_id:
        try:
            await bot.send_message(
                recip.owner_user_id,
                f"🕊 <b>بسته کمک‌های بشردوستانه سازمان ملل متحد:</b>\n\n"
                f"مبلغ <b>{fa_number(aid / 1e6)} میلیون دلار</b> از صندوق توسعه سازمان ملل به خزانه کشورتان واریز شد.\n"
                f"رضایت عمومی: +۵٪",
            )
        except Exception:
            pass

    await message.answer(
        f"🕊 بسته امدادی به مبلغ <b>{fa_number(aid / 1e6)} میلیون دلار</b> با موفقیت به کشور {recip.flag} {recip.name_fa} ارسال شد."
    )

    await publish_news(
        bot,
        NewsCategory.ECONOMY,
        f"🕊 <b>تخصیص کمک‌های بشردوستانه سازمان ملل:</b>\n"
        f"دبیرکل سازمان ملل با تخصیص بسته حمایتی {fa_number(aid / 1e6)} میلیون دلاری به کشور {recip.flag} {recip.name_fa} موافقت نمود.",
    )
