"""
هندلر سیستم سرمایه‌گذاری (v1.9): داخلی (روی خود) و خارجی (روی کشور دیگر).
سود نقدی هر ۲۴ ساعت به سرمایه‌گذار می‌رسد (پردازش در scheduler)؛ سرمایه‌گذاری خارجی
علاوه بر آن اثرات اجتماعی روی کشور هدف دارد و خبرش در کانال اقتصاد منتشر می‌شود.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone

from ..config import get_settings
from ..constants import (
    BUILD_LIMIT_WINDOW_HOURS,
    FOREIGN_INVEST_NEWS_MIN_USD,
    INVESTMENT_ACTIVE_LIMIT,
    INVESTMENT_CATEGORIES,
    INVESTMENT_LIMIT,
)
from ..database.models import Investment, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import investments as inv_repo
from ..keyboards.common import confirm_cancel_kb, countries_kb
from ..keyboards.economy import invest_category_kb, invest_foreign_kb, invest_menu_kb
from ..loader import bot
from ..services.news_service import send_log
from ..states import InvestForm
from ..utils.numbers import fa_money, fa_number, parse_amount
from ..utils.screens import safe_edit
from ..utils.ui import STYLE_MAIN
from .deps import NO_COUNTRY_TEXT, assert_feature, get_player_country

router = Router(name="investment")
settings = get_settings()

# تعداد سرمایه‌گذاری در هر صفحه‌ی فهرست (v1.11.1)
INVEST_PAGE_SIZE = 10


def _back_invest_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:invest", style=STYLE_MAIN)
    ]])


def _invest_page_kb(kind: str, page: int, total: int) -> InlineKeyboardMarkup:
    """ناوبری صفحه‌های فهرست سرمایه‌گذاری (v1.11.1)."""
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ صفحه قبلی", callback_data=f"invpg:{kind}:{page - 1}", style=STYLE_MAIN
        ))
    if page < total - 1:
        nav.append(InlineKeyboardButton(
            text="صفحه بعدی ▶️", callback_data=f"invpg:{kind}:{page + 1}", style=STYLE_MAIN
        ))

    rows: list[list[InlineKeyboardButton]] = []
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="econ:invest", style=STYLE_MAIN)
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cat_fa_pct(key: str) -> tuple[str, float]:
    fa, pct = INVESTMENT_CATEGORIES.get(key, (key, 0.0))
    return fa, pct


async def _invest_limit_exceeded(session: AsyncSession, country_id: int) -> bool:
    """آیا کشور به سقف سرمایه‌گذاری در پنجره‌ی ۱۲ ساعته رسیده است؟ (v1.11)"""
    since = datetime.now(timezone.utc) - timedelta(hours=BUILD_LIMIT_WINDOW_HOURS)
    recent = await inv_repo.count_by_investor_since(session, country_id, since)
    return recent >= INVESTMENT_LIMIT


async def _invest_cap_reached(session: AsyncSession, country_id: int) -> bool:
    """
    آیا کشور به سقف تعداد سرمایه‌گذاری‌های **فعال** رسیده است؟ (v1.11.1)

    برخلاف سقف ۱۲ساعته، این سقف با گذر زمان آزاد نمی‌شود؛ بازیکن باید
    سرمایه‌گذاری فعال داشته باشد و بیشتر از این نمی‌تواند اضافه کند.
    """
    active = await inv_repo.count_active_by_investor(session, country_id)
    return active >= INVESTMENT_ACTIVE_LIMIT


_INVEST_LIMIT_TEXT = (
    f"⏳ شما در هر {BUILD_LIMIT_WINDOW_HOURS} ساعت حداکثر {INVESTMENT_LIMIT} "
    "سرمایه‌گذاری می‌توانید ثبت کنید. لطفاً بعداً تلاش کنید."
)

_INVEST_CAP_TEXT = (
    f"🚫 <b>به سقف سرمایه‌گذاری رسیده‌اید</b>\n\n"
    f"هر کشور حداکثر می‌تواند {INVESTMENT_ACTIVE_LIMIT} سرمایه‌گذاری فعال "
    "هم‌زمان داشته باشد.\n\n"
    "<i>برای ثبت سرمایه‌گذاری جدید باید یکی از سرمایه‌گذاری‌های فعلی پایان یابد.</i>"
)


# ============================================================
#  منوی سرمایه‌گذاری
# ============================================================
@router.callback_query(F.data == "econ:invest")
async def cb_invest(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call,
        "📈 <b>سرمایه‌گذاری</b>\n\n"
        "می‌توانید روی توسعه‌ی کشور خودتان یا یک کشور خارجی سرمایه‌گذاری کنید.\n"
        "سود سرمایه هر ۲۴ ساعت به خزانه‌ی شما واریز می‌شود.",
        reply_markup=invest_menu_kb(),
    )


# ----- داخلی: روی کشور خودم -----
@router.callback_query(F.data == "inv:internal")
async def cb_invest_internal(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.investment"):
        return
    if await _invest_cap_reached(session, country.id):
        await safe_edit(call, _INVEST_CAP_TEXT, reply_markup=invest_menu_kb())
        return
    if await _invest_limit_exceeded(session, country.id):
        await safe_edit(call,_INVEST_LIMIT_TEXT, reply_markup=invest_menu_kb())
        return
    await state.set_state(InvestForm.choosing_category)
    await state.update_data(scope="self", target_id=country.id)
    await safe_edit(call,
        "🏠 <b>سرمایه‌گذاری داخلی</b>\n\nدسته‌ی موردنظر را انتخاب کنید "
        "(درصد جلوی هر مورد = سود ۲۴ساعته):",
        reply_markup=invest_category_kb(back_data="econ:invest"),
    )


# ----- خارجی: منو -----
@router.callback_query(F.data == "inv:foreign")
async def cb_invest_foreign(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call,
        "🌍 <b>سرمایه‌گذاری خارجی</b>\n\nیک گزینه را انتخاب کنید:",
        reply_markup=invest_foreign_kb(),
    )


@router.callback_query(F.data == "inv:mine")
async def cb_invest_mine(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست سرمایه‌گذاری‌های من — صفحه‌ی اول (v1.11.1)."""
    await call.answer()
    await _show_invest_page(call, session, db_user, kind="mine", page=0)


@router.callback_query(F.data.startswith("invpg:"))
async def cb_invest_page(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """ناوبری صفحه‌های فهرست سرمایه‌گذاری (`invpg:{kind}:{page}`)."""
    await call.answer()
    parts = call.data.split(":")
    kind = parts[1] if len(parts) > 1 else "mine"
    try:
        page = int(parts[2])
    except (IndexError, ValueError):
        page = 0
    await _show_invest_page(call, session, db_user, kind=kind, page=page)


async def _show_invest_page(
    call: CallbackQuery, session: AsyncSession, db_user: User, *, kind: str, page: int
) -> None:
    """
    رندر یک صفحه از فهرست سرمایه‌گذاری‌ها (v1.11.1).

    kind: "mine" = سرمایه‌گذاری‌های من | "on_me" = سرمایه‌گذاری‌ها روی کشور من

    پیش‌تر کل فهرست در یک پیام می‌آمد و با زیادشدن سرمایه‌گذاری‌ها از سقف طول
    پیام تلگرام رد می‌شد و پیام اصلاً نمایش داده نمی‌شد.
    """
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call, NO_COUNTRY_TEXT)
        return

    if kind == "on_me":
        items = await inv_repo.list_on_target(session, country.id)
        title, emoji = "سرمایه‌گذاری‌ها روی کشور من", "📥"
        empty = "هیچ کشوری روی کشور شما سرمایه‌گذاری نکرده است."
    else:
        kind = "mine"
        items = await inv_repo.list_by_investor(session, country.id)
        title, emoji = "سرمایه‌گذاری‌های من", "📋"
        empty = "شما هنوز سرمایه‌گذاری‌ای انجام نداده‌اید."

    if not items:
        await safe_edit(call, empty, reply_markup=_back_invest_kb())
        return

    total_pages = max(1, (len(items) + INVEST_PAGE_SIZE - 1) // INVEST_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * INVEST_PAGE_SIZE : (page + 1) * INVEST_PAGE_SIZE]

    total_amount = sum(i.amount for i in items)
    lines = [
        f"{emoji} <b>{title}</b>",
        "",
        f"📊 تعداد: <b>{fa_number(len(items))}</b> از سقف {fa_number(INVESTMENT_ACTIVE_LIMIT)}"
        if kind == "mine"
        else f"📊 تعداد: <b>{fa_number(len(items))}</b>",
        f"💰 مجموع سرمایه: {fa_money(total_amount)}",
        f"📄 صفحه {fa_number(page + 1)} از {fa_number(total_pages)}",
        "",
    ]

    for idx, inv in enumerate(chunk, start=page * INVEST_PAGE_SIZE + 1):
        fa, _pct = _cat_fa_pct(inv.category)
        if kind == "on_me":
            investor = await countries_repo.get_country(session, inv.investor_country)
            who = f"{investor.flag} {investor.name_fa}" if investor else "?"
            lines.append(
                f"{fa_number(idx)}. {fa} — سرمایه‌گذار: {who}\n"
                f"   💵 مبلغ: {fa_money(inv.amount)}"
            )
        else:
            tgt = await countries_repo.get_country(session, inv.target_country)
            where = (
                "🏠 داخلی"
                if not inv.is_foreign
                else (f"{tgt.flag} {tgt.name_fa}" if tgt else "?")
            )
            profit = inv.amount * inv.profit_pct / 100.0
            lines.append(
                f"{fa_number(idx)}. {fa} — {where}\n"
                f"   💵 اصل: {fa_money(inv.amount)} | 📈 سود ۲۴ساعته: {fa_money(profit)}"
            )

    await safe_edit(
        call,
        "\n".join(lines),
        reply_markup=_invest_page_kb(kind, page, total_pages),
    )


@router.callback_query(F.data == "inv:on_me")
async def cb_invest_on_me(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """فهرست سرمایه‌گذاری‌های دیگران روی کشور من — صفحه‌ی اول (v1.11.1)."""
    await call.answer()
    await _show_invest_page(call, session, db_user, kind="on_me", page=0)


@router.callback_query(F.data == "inv:new_foreign")
async def cb_invest_new_foreign(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    if not await assert_feature(call, session, country, "econ.investment"):
        return
    if await _invest_cap_reached(session, country.id):
        await safe_edit(call, _INVEST_CAP_TEXT, reply_markup=invest_foreign_kb())
        return
    if await _invest_limit_exceeded(session, country.id):
        await safe_edit(call,_INVEST_LIMIT_TEXT, reply_markup=invest_foreign_kb())
        return
    await state.set_state(InvestForm.choosing_target)
    await state.update_data(scope="foreign")
    countries = await countries_repo.list_countries(session)
    others = [c for c in countries if c.id != country.id]
    await safe_edit(call,
        "💸 روی کدام کشور می‌خواهید سرمایه‌گذاری کنید؟",
        reply_markup=countries_kb(others, prefix="inv_target", columns=2, back_data="inv:foreign"),
    )


@router.callback_query(InvestForm.choosing_target, F.data.startswith("inv_target:"))
async def cb_invest_target(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await call.answer()
    target = await countries_repo.get_country(session, int(call.data.split(":")[1]))
    if target is None:
        await safe_edit(call,"کشور یافت نشد.", reply_markup=_back_invest_kb())
        return
    await state.update_data(target_id=target.id)
    await state.set_state(InvestForm.choosing_category)
    await safe_edit(call,
        f"💸 سرمایه‌گذاری روی {target.flag} {target.name_fa}\n\nدسته‌ی موردنظر را انتخاب کنید:",
        reply_markup=invest_category_kb(back_data="inv:new_foreign"),
    )


# ----- انتخاب دسته -----
@router.callback_query(InvestForm.choosing_category, F.data.startswith("inv_cat:"))
async def cb_invest_category(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    key = call.data.split(":")[1]
    if key not in INVESTMENT_CATEGORIES:
        await call.answer("دسته نامعتبر.", show_alert=True)
        return
    fa, pct = _cat_fa_pct(key)
    await state.update_data(category=key)
    await state.set_state(InvestForm.entering_amount)
    pct_txt = int(pct) if float(pct).is_integer() else pct
    await safe_edit(call,
        f"📈 دسته: <b>{fa}</b> (سود ۲۴ساعته: {pct_txt}٪)\n\n"
        "مبلغ سرمایه‌گذاری را وارد کنید (به دلار، مثلاً 1b):",
        reply_markup=_back_invest_kb(),
    )


@router.message(InvestForm.entering_amount, F.text)
async def msg_invest_amount(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    amount = parse_amount(message.text)
    if amount is None or amount <= 0:
        await message.answer("لطفاً یک مبلغ معتبر وارد کنید.")
        return
    country = await get_player_country(session, db_user)
    if country is None:
        await state.clear()
        await message.answer(NO_COUNTRY_TEXT)
        return
    if country.budget < amount:
        await message.answer(
            f"⛔️ بودجه‌ی کافی ندارید. موجودی شما {fa_money(country.budget)} است.",
            reply_markup=_back_invest_kb(),
        )
        return
    data = await state.get_data()
    fa, pct = _cat_fa_pct(data["category"])
    profit = amount * pct / 100.0
    await state.update_data(amount=amount)
    await state.set_state(InvestForm.confirming)

    target_id = data.get("target_id")
    scope = data.get("scope", "self")
    if scope == "foreign":
        target = await countries_repo.get_country(session, target_id)
        where = f" روی کشور {target.flag} {target.name_fa}" if target else ""
    else:
        where = " روی کشور خودتان"
    await message.answer(
        f"❓ شما در حال سرمایه‌گذاری {fa_money(amount)} در دسته‌ی «{fa}»{where} هستید.\n"
        f"به ازای هر ۲۴ ساعت {fa_money(profit)} سود می‌کنید.\n\n"
        "آیا تأیید می‌کنید؟",
        reply_markup=confirm_cancel_kb("inv:confirm"),
    )


@router.callback_query(InvestForm.confirming, F.data == "inv:confirm")
async def cb_invest_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await call.answer()
    data = await state.get_data()
    await state.clear()
    country = await get_player_country(session, db_user)
    if country is None:
        await safe_edit(call,NO_COUNTRY_TEXT)
        return
    amount = float(data.get("amount", 0))
    key = data.get("category")
    target_id = data.get("target_id") or country.id
    if amount <= 0 or key not in INVESTMENT_CATEGORIES or country.budget < amount:
        await safe_edit(call,"⛔️ سرمایه‌گذاری انجام نشد (بودجه‌ی ناکافی).", reply_markup=_back_invest_kb())
        return
    # چک نهاییِ محدودیت پیش از کسر بودجه (v1.11)
    if await _invest_limit_exceeded(session, country.id):
        await safe_edit(call,_INVEST_LIMIT_TEXT, reply_markup=_back_invest_kb())
        return
    # چک نهاییِ سقف تعداد فعال پیش از کسر بودجه (v1.11.1)
    if await _invest_cap_reached(session, country.id):
        await safe_edit(call, _INVEST_CAP_TEXT, reply_markup=_back_invest_kb())
        return
    fa, pct = _cat_fa_pct(key)
    # کسر اصل سرمایه از بودجه
    country.budget -= amount
    inv = Investment(
        investor_country=country.id,
        target_country=target_id,
        category=key,
        amount=amount,
        profit_pct=pct,
    )
    await inv_repo.add_investment(session, inv)

    target = await countries_repo.get_country(session, target_id)
    is_foreign = target_id != country.id
    profit = amount * pct / 100.0
    await safe_edit(call,
        f"✅ سرمایه‌گذاری {fa_money(amount)} در «{fa}» ثبت شد.\n"
        f"سود ۲۴ساعته: {fa_money(profit)}\n"
        f"موجودی خزانه: {fa_money(country.budget)}",
        reply_markup=_back_invest_kb(),
    )

    # خبر سرمایه‌گذاری خارجی در کانال اقتصاد (داخلی منتشر نمی‌شود) — v1.9
    if is_foreign and target is not None:
        x = f"{country.flag} {country.name_fa}"   # سرمایه‌گذار
        y = f"{target.flag} {target.name_fa}"      # سرمایه‌گیر
        # v1.10.5: فقط سرمایه‌گذاری‌های ۱۰۰ میلیارد دلار و بیشتر در کانال منتشر می‌شوند
        if amount >= FOREIGN_INVEST_NEWS_MIN_USD and settings.news_economy_channel_id is not None:
            news = (
                "🔰 فووری!!\n\n"
                f"✅ | در خبری جدید کشور {x} اعلام کرده که بزودی قرار است در کشور {y} به مبلغ "
                f"{fa_money(amount)} سرمایه‌گذاری کند! جزئیات بیشتر توسط مقامات کشور {x} بزودی اعلام خواهد شد..."
            )
            try:
                await bot.send_message(settings.news_economy_channel_id, news)
            except Exception:  # noqa: BLE001
                pass
        # اطلاع به کشور هدف (مستقل از سقف خبر کانال)
        if target.owner_user_id:
            try:
                await bot.send_message(
                    target.owner_user_id,
                    f"📈 کشور {x} مبلغ {fa_money(amount)} در دسته‌ی «{fa}» روی کشور شما سرمایه‌گذاری کرد.",
                )
            except Exception:  # noqa: BLE001
                pass

    # لاگ سرمایه‌گذاری به گروه لاگ (داخلی و خارجی)
    where = f"خارجی روی {target.flag} {target.name_fa}" if (is_foreign and target) else "داخلی"
    await send_log(
        bot,
        f"📈 <b>سرمایه‌گذاری ({where})</b>\n"
        f"سرمایه‌گذار: {country.flag} {country.name_fa}\n"
        f"دسته: {fa}\nمبلغ: {fa_money(amount)} | سود ۲۴ساعته: {fa_money(profit)}",
    )
