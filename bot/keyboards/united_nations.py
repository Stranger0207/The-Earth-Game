"""
کیبوردهای اختصاصی سازمان ملل متحد (UN)، مجمع عمومی، آژانس انرژی اتمی (IAEA) و دیوان بین‌المللی دادگستری (ICJ).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import get_settings
from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_NO, STYLE_OK


def un_main_menu_kb() -> InlineKeyboardMarkup:
    """پنل اصلی و اختصاصی دبیرکل سازمان ملل متحد."""
    settings = get_settings()
    builder = InlineKeyboardBuilder()

    builder.button(text="☢️ آژانس انرژی اتمی (IAEA)", callback_data="un:iaea", style=STYLE_MAIN)
    builder.button(text="🏛 مدیریت مجمع عمومی (نیویورک)", callback_data="un:assembly", style=STYLE_MAIN)
    builder.button(text="⚖️ دیوان بین‌المللی دادگستری (ICJ)", callback_data="un:court", style=STYLE_MAIN)
    builder.button(text="📜 صدور قطعنامه و رای‌گیری", callback_data="un:resolutions", style=STYLE_MAIN)
    builder.button(text="🕊 صندوق کمک‌های بشردوستانه", callback_data="un:humanitarian", style=STYLE_MAIN)
    builder.button(text="🤝 نشست در حاشیه سازمان ملل", callback_data="un:sideline", style=STYLE_MAIN)
    builder.button(text="🏛 وضعیت دبیرخانه", callback_data="menu:status", style=STYLE_MAIN)

    # امکانات دیپلماتیک سازمان ملل متحد
    builder.button(text="🎙 بیانیه رسمی دبیرکل", callback_data="dip:speech", style=STYLE_MAIN)
    builder.button(text="🤝 دیدار حضوری (سفر)", callback_data="dip:meeting", style=STYLE_MAIN)
    builder.button(text="📞 تماس تلفنی ۵ دقیقه‌ای", callback_data="dip:call", style=STYLE_MAIN)
    builder.button(text="✉️ ارسال و دریافت نامه", callback_data="dip:letter", style=STYLE_MAIN)

    if settings.webapp_base_url:
        builder.button(
            text="🌍 رادار زنده جهان (نقشه)",
            web_app=WebAppInfo(url=settings.webapp_url),
        )
    else:
        builder.button(
            text="🌍 رادار زنده جهان (نقشه)",
            callback_data="menu:radar_info",
            style=STYLE_OK,
        )

    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


# ============================================================
#  آژانس بین‌المللی انرژی اتمی (IAEA)
# ============================================================


def un_iaea_menu_kb() -> InlineKeyboardMarkup:
    """منوی آژانس انرژی اتمی در پنل دبیرکل."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 اعزام تیم بازرسان به یک کشور", callback_data="un:iaea_send", style=STYLE_MAIN)
    builder.button(text="📋 پرونده‌های باز و گزارش‌ها", callback_data="un:iaea_cases", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def iaea_inspection_action_kb(inspection_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های ارسالی به کشور هدف جهت پذیرش یا رد بازرسی."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تایید ورود بازرسان و ارائه اطلاعات", callback_data=f"iaea_ok:{inspection_id}", style=STYLE_OK)
    builder.button(text="❌ ممانعت از ورود بازرسان", callback_data=f"iaea_no:{inspection_id}", style=STYLE_NO)
    builder.adjust(1)
    return builder.as_markup()


def un_iaea_case_view_kb(target_country_id: int) -> InlineKeyboardMarkup:
    """اقدامات دبیرکل پس از دریافت گزارش بازرسی یا ممانعت کشور."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📞 احضار فوری سفیر کشور (تماس اختصاصی)",
        callback_data=f"iaea_summon:{target_country_id}",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت به آژانس", callback_data="un:iaea")
    builder.adjust(1)
    return builder.as_markup()


def un_iaea_summon_call_kb(target_country_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های تصمیم‌گیری دبیرکل در طول تماس احضار سفیر."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🟢 تبرئه در بحث (بستن پرونده)",
        callback_data=f"iaea_call_acquit:{target_country_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="⚖️ فراخوان به دادگاه بین‌الملل و پایان صحبت",
        callback_data=f"iaea_call_court:{target_country_id}",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


# ============================================================
#  اجلاس مجمع عمومی سازمان ملل (UN General Assembly)
# ============================================================


def un_assembly_admin_kb(
    session_id: int, is_active: bool = False, voting_active: bool = False
) -> InlineKeyboardMarkup:
    """پنل مدیریت اجلاس مجمع عمومی برای دبیرکل سازمان ملل."""
    builder = InlineKeyboardBuilder()
    if not is_active:
        builder.button(
            text="🚀 آغاز رسمی صحن علنی اجلاس",
            callback_data=f"un_asmb_activate:{session_id}",
            style=STYLE_OK,
        )
    else:
        builder.button(
            text="🎙 شروع سخنرانی نفر بعدی",
            callback_data=f"un_asmb_next:{session_id}",
            style=STYLE_OK,
        )
        if voting_active:
            builder.button(
                text="📊 بستن رای‌گیری و اعلام نتایج تابلو",
                callback_data=f"asmb_vote_end:{session_id}",
                style=STYLE_NO,
            )
        else:
            builder.button(
                text="📊 برگزاری رای‌گیری فوری در صحن",
                callback_data=f"un_asmb_vote_prompt:{session_id}",
                style=STYLE_MAIN,
            )
        builder.button(
            text="🏁 پایان اجلاس سالانه",
            callback_data=f"un_asmb_close:{session_id}",
            style=STYLE_NO,
        )

    builder.button(
        text="👥 آمار حاضران و صف سخنرانی",
        callback_data=f"un_asmb_stats:{session_id}",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def assembly_invite_kb(session_id: int) -> InlineKeyboardMarkup:
    """دعوت‌نامه شرکت در اجلاس سالانه مجمع عمومی ارسالی به همه کشورها."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✈️ پذیرش دعوت و پرواز به نیویورک",
        callback_data=f"asmb_fly:{session_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="❌ رد مودبانه دعوت",
        callback_data=f"asmb_decline:{session_id}",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


def assembly_ny_lobby_kb(session_id: int, is_closed: bool = False) -> InlineKeyboardMarkup:
    """محیط بیرونی / لابی شهر نیویورک پس از فرود هواپیما."""
    builder = InlineKeyboardBuilder()
    if not is_closed:
        builder.button(
            text="🏛 ورود به ساختمان تالار مجمع بین‌المللی",
            callback_data=f"asmb_enter_hall:{session_id}",
            style=STYLE_OK,
        )
    builder.button(
        text="🤝 برگزاری نشست در حاشیه سازمان ملل",
        callback_data="un:sideline",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔙 بازگشت به کشور",
        callback_data=f"asmb_return_home:{session_id}",
        style=STYLE_NO,
    )
    builder.adjust(1)
    return builder.as_markup()


def assembly_hall_kb(
    session_id: int, is_speaker: bool = False, voting_active: bool = False
) -> InlineKeyboardMarkup:
    """داخل تالار صحن علنی مجمع عمومی (پنل کشوری در این وضعیت قفل است)."""
    builder = InlineKeyboardBuilder()

    if is_speaker:
        builder.button(
            text="⏹ پایان سخنرانی (واگذاری تریبون)",
            callback_data=f"asmb_end_speech:{session_id}",
            style=STYLE_NO,
        )
    else:
        builder.button(
            text="✋ اعلام حضور (درخواست نوبت سخنرانی)",
            callback_data=f"asmb_req_speech:{session_id}",
            style=STYLE_OK,
        )

    builder.button(
        text="👏 تشویق سخنران",
        callback_data=f"asmb_applaud:{session_id}",
    )
    builder.button(
        text="🚪 خروج از تالار مجمع",
        callback_data=f"asmb_exit_hall:{session_id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🚶‍♂️ ترک اعتراضی تالار (Walkout)",
        callback_data=f"asmb_walkout:{session_id}",
        style=STYLE_NO,
    )

    if voting_active:
        builder.button(text="🟢 موافق", callback_data=f"asmb_v_yes:{session_id}", style=STYLE_OK)
        builder.button(text="🔴 مخالف", callback_data=f"asmb_v_no:{session_id}", style=STYLE_NO)
        builder.button(text="⚪️ ممتنع", callback_data=f"asmb_v_abs:{session_id}")
        builder.adjust(1, 1, 2, 3)
    else:
        builder.adjust(1, 1, 2)

    return builder.as_markup()


def speech_reactions_kb(session_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های واکنش سریع زیر پیام‌های رله‌شده سخنران در صحن مجمع."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👏 تشویق سخنران",
        callback_data=f"asmb_applaud:{session_id}",
    )
    builder.button(
        text="🚪 ترک اعتراضی تالار (Walkout)",
        callback_data=f"asmb_walkout:{session_id}",
        style=STYLE_NO,
    )
    builder.adjust(2)
    return builder.as_markup()


# ============================================================
#  دیوان بین‌المللی دادگستری (دادگاه لاهه - ICJ)
# ============================================================


def court_main_kb() -> InlineKeyboardMarkup:
    """منوی اصلی دادگاه بین‌المللی برای کشورها در بخش دیپلماسی."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚖️ ثبت شکایت در دادگاه بین‌الملل",
        callback_data="court:new_claim",
        style=STYLE_MAIN,
    )
    builder.button(
        text="📋 پرونده‌های جاری من در دیوان",
        callback_data="court:my_cases",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت به دیپلماسی", callback_data="menu:diplomacy")
    builder.adjust(1)
    return builder.as_markup()


def court_issues_kb() -> InlineKeyboardMarkup:
    """انتخاب موضوع دادخواست در فرم ثبت شکایت دادگاه."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚓ توقیف/انهدام غیرقانونی کشتی در تنگه", callback_data="court_issue:strait_block")
    builder.button(text="⚔️ تجاوز نظامی و حمله غیرقانونی", callback_data="court_issue:military_attack")
    builder.button(text="☢️ نقض پادمان هسته‌ای و غنی‌سازی خطرناک", callback_data="court_issue:nuclear_violation")
    builder.button(text="📜 نقض معاهده رسمی بین‌المللی", callback_data="court_issue:treaty_breach")
    builder.button(text="🚫 وضع تحریم ظالمانه و غیرقانونی", callback_data="court_issue:sanction")
    builder.button(text="✍️ موضوع دلخواه و آزاد", callback_data="court_issue:custom")
    builder.button(text="🔙 انصراف", callback_data="court:main")
    builder.adjust(1)
    return builder.as_markup()


def un_court_admin_kb(
    case_id: int, claimant_id: int, defendant_id: int, is_trial: bool = False
) -> InlineKeyboardMarkup:
    """پنل اداره جلسه دادگاه برای دبیرکل سازمان ملل (رئیس دیوان)."""
    builder = InlineKeyboardBuilder()
    if not is_trial:
        builder.button(
            text="🏛 تشکیل جلسه رسمی دادگاه و فراخوان طرفین",
            callback_data=f"court_start_trial:{case_id}",
            style=STYLE_OK,
        )
    else:
        builder.button(
            text="🎙 اعطای نوبت دفاعیه به شاکی",
            callback_data=f"court_turn:{case_id}:{claimant_id}",
            style=STYLE_MAIN,
        )
        builder.button(
            text="🎙 اعطای نوبت دفاعیه به متهم",
            callback_data=f"court_turn:{case_id}:{defendant_id}",
            style=STYLE_MAIN,
        )
        builder.button(
            text="🎙 باز کردن صحبت برای همه حاضران",
            callback_data=f"court_turn:{case_id}:all",
            style=STYLE_MAIN,
        )
        builder.button(
            text="🔨 صدور حکم نهایی دادگاه و بستن پرونده",
            callback_data=f"court_verdict_prompt:{case_id}",
            style=STYLE_OK,
        )

    builder.button(text="🔙 بازگشت به کارتابل قضایی", callback_data="un:court")
    builder.adjust(1)
    return builder.as_markup()


def un_court_verdict_choices_kb(case_id: int) -> InlineKeyboardMarkup:
    """انواع احکام نهایی قابل صدور در دیوان بین‌المللی دادگستری."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🟢 تبرئه متهم و رد شکایت",
        callback_data=f"court_v_acquit:{case_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="💸 محکومیت به پرداخت غرامت مالی",
        callback_data=f"court_v_fine:{case_id}",
        style=STYLE_MAIN,
    )
    builder.button(
        text="🔓 حکم آزادی فوری اموال بلوکه‌شده در تنگه",
        callback_data=f"court_v_release:{case_id}",
        style=STYLE_OK,
    )
    builder.button(
        text="🚫 صدور مجوز تحریم بین‌المللی علیه متهم",
        callback_data=f"court_v_sanction:{case_id}",
        style=STYLE_NO,
    )
    builder.button(text="🔙 بازگشت به جلسه دادگاه", callback_data=f"court_admin_view:{case_id}")
    builder.adjust(1)
    return builder.as_markup()


# ============================================================
#  قطعنامه‌ها و رای‌گیری
# ============================================================


def un_resolutions_menu_kb() -> InlineKeyboardMarkup:
    """منوی قطعنامه‌ها در پنل دبیرکل سازمان ملل."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✍️ تدوین و انتشار پیش‌نویس قطعنامه جدید",
        callback_data="un_res_create",
        style=STYLE_OK,
    )
    builder.button(
        text="📋 فهرست قطعنامه‌های بین‌المللی",
        callback_data="un_res_list",
        style=STYLE_MAIN,
    )
    builder.button(text="🔙 بازگشت به پنل دبیرکل", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def resolution_vote_kb(res_id: int) -> InlineKeyboardMarkup:
    """کیبورد رای‌گیری کشورهای جهان به قطعنامه."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 موافق (Yes)", callback_data=f"res_vote:{res_id}:yes", style=STYLE_OK)
    builder.button(text="🔴 مخالف (No)", callback_data=f"res_vote:{res_id}:no", style=STYLE_NO)
    builder.button(text="⚪️ ممتنع (Abstain)", callback_data=f"res_vote:{res_id}:abstain")
    builder.adjust(3)
    return builder.as_markup()


def resolution_admin_kb(res_id: int) -> InlineKeyboardMarkup:
    """کیبورد مدیریت قطعنامه برای دبیرکل سازمان ملل جهت بستن رای‌گیری."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🏁 بستن رای‌گیری و صدور قطعنامه نهایی",
        callback_data=f"res_close:{res_id}",
        style=STYLE_NO,
    )
    builder.button(text="🔙 بازگشت به قطعنامه‌ها", callback_data="un_res_list")
    builder.adjust(1)
    return builder.as_markup()


# ============================================================
#  نشست‌های در حاشیه سازمان ملل متحد (Bilateral & Multilateral)
# ============================================================


def un_sideline_home_kb(back_target: str = "menu:main") -> InlineKeyboardMarkup:
    """منوی اصلی نشست در حاشیه مجمع عمومی سازمان ملل متحد."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤝 نشست دوجانبه در حاشیه UN", callback_data="un_side:bi", style=STYLE_MAIN)
    builder.button(text="🌐 نشست چندجانبه در حاشیه UN", callback_data="un_side:multi", style=STYLE_MAIN)
    builder.button(text="🕘 نشست‌های حاشیه‌ای اخیر / فعال من", callback_data="un_side:recent", style=STYLE_MAIN)
    builder.button(text="🔙 بازگشت به مقر سازمان ملل", callback_data=back_target)
    builder.adjust(1)
    return builder.as_markup()


def un_sideline_countries_kb(
    countries: list,
    mode: str = "bi",
    selected_ids: set[int] | list[int] | None = None,
    busy_map: dict[int, str] | None = None,
    page: int = 1,
    per_page: int = 8,
    back_target: str = "un_side:home",
) -> InlineKeyboardMarkup:
    """کیبورد انتخاب کشورها جهت برگزاری نشست حاشیه سازمان ملل."""
    selected_set = set(selected_ids or [])
    busy_map = busy_map or {}
    builder = InlineKeyboardBuilder()

    total_count = len(countries)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    page_countries = countries[start:end]

    for c in page_countries:
        busy_label = busy_map.get(c.id)
        busy_suffix = " (⛔ مشغول)" if busy_label else ""
        if mode == "bi":
            builder.button(
                text=f"🤝 {c.flag} {c.name_fa}{busy_suffix}",
                callback_data=f"un_side:pick_bi:{c.id}",
            )
        else:
            tick = PICK_ON if c.id in selected_set else PICK_OFF
            builder.button(
                text=f"{tick} {c.flag} {c.name_fa}{busy_suffix}",
                callback_data=f"un_side:toggle_m:{c.id}:{page}",
            )

    # چینش دکمه‌های کشورها در دو ستون
    builder.adjust(2)

    # ردیف‌های کنترلی چندجانبه
    if mode == "multi":
        confirm_btn = InlineKeyboardButton(
            text=f"✅ تأیید و ادامه ({len(selected_set)}/6 کشور)",
            callback_data="un_side:confirm_m",
            style=STYLE_OK,
        )
        builder.row(confirm_btn)

    # ردیف صفحه‌بندی
    nav_row = []
    if page > 1:
        prev_cb = f"un_side:page_{mode}:{page - 1}"
        nav_row.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=prev_cb))
    if total_pages > 1:
        nav_row.append(
            InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="un_side:noop")
        )
    if page < total_pages:
        next_cb = f"un_side:page_{mode}:{page + 1}"
        nav_row.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=next_cb))
    if nav_row:
        builder.row(*nav_row)

    # دکمه بازگشت
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_target))
    return builder.as_markup()


def un_sideline_invite_kb(meeting_id: int, is_group: bool = False) -> InlineKeyboardMarkup:
    """کیبورد دعوت‌نامه نشست در پیوی کشور مدعو."""
    builder = InlineKeyboardBuilder()
    ok_cb = f"un_side:ok_grp:{meeting_id}" if is_group else f"un_side:ok_bi:{meeting_id}"
    no_cb = f"un_side:no_grp:{meeting_id}" if is_group else f"un_side:no_bi:{meeting_id}"
    builder.button(text="✅ پذیرش و ورود به نشست", callback_data=ok_cb, style=STYLE_OK)
    builder.button(text="❌ رد دعوت", callback_data=no_cb, style=STYLE_NO)
    builder.adjust(2)
    return builder.as_markup()


def un_sideline_active_kb(
    meeting_id: int, is_group: bool = False, is_host: bool = True
) -> InlineKeyboardMarkup:
    """کیبورد کنترل و پایان نشست حاشیه‌ای فعال."""
    builder = InlineKeyboardBuilder()
    if is_host:
        end_cb = f"un_side:end_grp:{meeting_id}" if is_group else f"un_side:end_bi:{meeting_id}"
        builder.button(text="🛑 پایان نشست", callback_data=end_cb, style=STYLE_NO)
    elif is_group:
        builder.button(
            text="🚪 خروج از نشست",
            callback_data=f"un_side:leave_grp:{meeting_id}",
            style=STYLE_NO,
        )
    else:
        builder.button(
            text="🛑 پایان نشست",
            callback_data=f"un_side:end_bi:{meeting_id}",
            style=STYLE_NO,
        )

    refresh_cb = f"un_side:status_grp:{meeting_id}" if is_group else f"un_side:status_bi:{meeting_id}"
    builder.button(text="🔄 وضعیت نشست", callback_data=refresh_cb, style=STYLE_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def un_sideline_recent_kb(
    bi_meetings: list, group_meetings: list, my_country_id: int
) -> InlineKeyboardMarkup:
    """کیبورد مشاهده نشست‌های حاشیه‌ای اخیر با قابلیت پایان اضطراری."""
    builder = InlineKeyboardBuilder()
    for m in bi_meetings:
        m_status = getattr(m.status, "value", str(m.status))
        status_sym = "🟢" if m_status == "active" else ("⏳" if m_status == "pending" else "🏁")
        btn_text = f"{status_sym} دوجانبه #{m.id} ({m.topic or 'عمومی'})"
        if m_status == "active":
            builder.button(text=f"🛑 پایان اضطراری دوجانبه #{m.id}", callback_data=f"un_side:force_end:bi:{m.id}", style=STYLE_NO)
            builder.button(text=btn_text, callback_data=f"un_side:status_bi:{m.id}", style=STYLE_MAIN)
        else:
            builder.button(text=btn_text, callback_data=f"un_side:status_bi:{m.id}", style=STYLE_MAIN)

    for gm in group_meetings:
        gm_status = getattr(gm.status, "value", str(gm.status))
        status_sym = "🟢" if gm_status == "active" else ("⏳" if gm_status == "pending" else "🏁")
        btn_text = f"{status_sym} چندجانبه #{gm.id} ({gm.topic or gm.title or 'عمومی'})"
        if gm_status == "active":
            builder.button(text=f"🛑 پایان اضطراری چندجانبه #{gm.id}", callback_data=f"un_side:force_end:grp:{gm.id}", style=STYLE_NO)
            builder.button(text=btn_text, callback_data=f"un_side:status_grp:{gm.id}", style=STYLE_MAIN)
        else:
            builder.button(text=btn_text, callback_data=f"un_side:status_grp:{gm.id}", style=STYLE_MAIN)

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی نشست‌ها", callback_data="un_side:home"))
    return builder.as_markup()
