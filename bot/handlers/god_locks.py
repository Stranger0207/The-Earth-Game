"""
پنل قفل آپشن‌ها برای مالک بازی (v2.1).

بخش «🔒 غیرفعال‌کردن آپشن» در پنل /god: مالک می‌تواند هر آپشن بازی (ترور،
احداث تأسیسات، سفر، بانک، ...) را برای **یک کشور، چند کشور یا همه‌ی کشورها**
ببندد — بدون اینکه لازم باشد کل ربات را خاموش کند.

جریان کار:
    دسته (نظامی/اقتصاد/دیپلماسی/حاکمیت)
      → آپشن (با نمایش وضعیت فعلی)
        → دامنه: همه‌ی کشورها / چند کشور / رفع قفل

این فایل جدا از godmode.py است تا آن فایل بزرگ‌تر نشود (همان دلیل جداشدن
god_operations.py در v1.10.6).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import FEATURE_CATEGORIES, LOCKABLE_FEATURES
from ..database.repositories import countries as countries_repo
from ..database.repositories import feature_locks as locks_repo
from ..loader import bot
from ..services.news_service import send_log
from ..states import GodLockForm
from ..utils.numbers import fa_number
from ..utils.ui import PICK_OFF, PICK_ON, STYLE_MAIN, STYLE_NO, STYLE_OK, header

logger = logging.getLogger(__name__)
router = Router(name="god_locks")
settings = get_settings()


async def _guard(call: CallbackQuery) -> bool:
    """فقط مالک/مدیر بازی دسترسی دارد."""
    if settings.is_admin(call.from_user.id):
        return True
    await call.answer("⛔️ فقط مالک/مدیر بازی به این بخش دسترسی دارد.", show_alert=True)
    return False


def _feature_index() -> list[str]:
    """
    فهرست کلیدهای آپشن با ترتیب ثابت.

    کال‌بک‌دیتای تلگرام سقف ۶۴ بایت دارد و کلیدها فارسی/طولانی‌اند، پس در
    کال‌بک از **اندیس** استفاده می‌شود، نه از خود کلید.
    """
    return list(LOCKABLE_FEATURES.keys())


def _key_by_index(idx: int) -> str | None:
    keys = _feature_index()
    return keys[idx] if 0 <= idx < len(keys) else None


def _index_of(key: str) -> int:
    return _feature_index().index(key)


# ============================================================
#  منوی دسته‌ها
# ============================================================
def _categories_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat_idx, category in enumerate(FEATURE_CATEGORIES):
        locked = counts.get(category, 0)
        mark = f" ({fa_number(locked)} 🔒)" if locked else ""
        builder.button(
            text=f"{category}{mark}", callback_data=f"godlk_cat:{cat_idx}", style=STYLE_MAIN
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="📋 قفل‌های فعال", callback_data="godlk:list", style=STYLE_NO)
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:home", style=STYLE_MAIN)
    )
    return builder.as_markup()


async def _render_home(call: CallbackQuery, session: AsyncSession) -> None:
    """صفحه‌ی اصلی قفل آپشن‌ها با شمارش قفل هر دسته."""
    locks = await locks_repo.list_locks(session)
    counts: dict[str, int] = {}
    for row in locks:
        entry = LOCKABLE_FEATURES.get(row.feature_key)
        if entry is None:
            continue
        counts[entry[1]] = counts.get(entry[1], 0) + 1

    text = (
        header("غیرفعال‌کردن آپشن‌ها", "🔒") + "\n\n"
        f"🔴 قفل‌های فعال: <b>{fa_number(len(locks))}</b>\n\n"
        "با این پنل می‌توانید هر آپشن بازی را برای یک کشور، چند کشور یا "
        "همه‌ی کشورها موقتاً ببندید.\n\n"
        "<i>مالک و مدیران بازی از قفل‌ها معاف‌اند و می‌توانند همه‌چیز را آزمایش کنند.</i>"
    )
    await call.message.edit_text(text, reply_markup=_categories_kb(counts))


@router.callback_query(F.data == "god:locks")
async def cb_locks_home(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """ورود به پنل قفل آپشن‌ها."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    await _render_home(call, session)


# ============================================================
#  فهرست آپشن‌های یک دسته
# ============================================================
@router.callback_query(F.data.startswith("godlk_cat:"))
async def cb_locks_category(call: CallbackQuery, session: AsyncSession) -> None:
    """نمایش آپشن‌های یک دسته با وضعیت قفل هرکدام."""
    if not await _guard(call):
        return
    await call.answer()
    cat_idx = int(call.data.split(":")[1])
    if not 0 <= cat_idx < len(FEATURE_CATEGORIES):
        await _render_home(call, session)
        return
    await _render_category(call, session, cat_idx)


async def _render_category(call: CallbackQuery, session: AsyncSession, cat_idx: int) -> None:
    category = FEATURE_CATEGORIES[cat_idx]
    builder = InlineKeyboardBuilder()
    lines = [header(f"آپشن‌های {category}", "🔒"), ""]

    for key, (name_fa, cat) in LOCKABLE_FEATURES.items():
        if cat != category:
            continue
        rows = await locks_repo.list_locks_for_feature(session, key)
        is_global = any(r.country_id is None for r in rows)
        per_country = len([r for r in rows if r.country_id is not None])

        if is_global:
            status = "🔴 قفل سراسری"
        elif per_country:
            status = f"🟠 قفل برای {fa_number(per_country)} کشور"
        else:
            status = "🟢 باز"

        lines.append(f"{name_fa} — {status}")
        builder.button(
            text=f"{'🔴' if is_global else ('🟠' if per_country else '🟢')} {name_fa}",
            callback_data=f"godlk_f:{_index_of(key)}",
            style=STYLE_NO if (is_global or per_country) else STYLE_MAIN,
        )

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:locks", style=STYLE_MAIN)
    )
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


# ============================================================
#  صفحه‌ی یک آپشن: انتخاب دامنه‌ی قفل
# ============================================================
def _feature_kb(key: str, *, is_global: bool, has_any: bool) -> InlineKeyboardMarkup:
    idx = _index_of(key)
    cat_idx = FEATURE_CATEGORIES.index(LOCKABLE_FEATURES[key][1])
    builder = InlineKeyboardBuilder()
    if not is_global:
        builder.button(
            text="🌍 قفل برای همه‌ی کشورها",
            callback_data=f"godlk_all:{idx}",
            style=STYLE_NO,
        )
    builder.button(
        text="🎯 قفل برای یک/چند کشور",
        callback_data=f"godlk_pick:{idx}",
        style=STYLE_NO,
    )
    if has_any:
        builder.button(
            text="♻️ رفع کامل قفل این آپشن",
            callback_data=f"godlk_un:{idx}",
            style=STYLE_OK,
        )
    builder.button(
        text="🔙 بازگشت", callback_data=f"godlk_cat:{cat_idx}", style=STYLE_MAIN
    )
    builder.adjust(1)
    return builder.as_markup()


async def _render_feature(call: CallbackQuery, session: AsyncSession, key: str) -> None:
    name_fa, category = LOCKABLE_FEATURES[key]
    rows = await locks_repo.list_locks_for_feature(session, key)
    is_global = any(r.country_id is None for r in rows)
    locked_ids = [r.country_id for r in rows if r.country_id is not None]

    lines = [header(name_fa, "🔒"), "", f"دسته: {category}", f"کلید: <code>{key}</code>", ""]
    if is_global:
        lines.append("🔴 <b>وضعیت: قفل سراسری</b> — همه‌ی کشورها از این آپشن محروم‌اند.")
    elif locked_ids:
        names = []
        for cid in locked_ids:
            country = await countries_repo.get_country(session, cid)
            if country:
                names.append(f"{country.flag} {country.name_fa}")
        lines.append(
            f"🟠 <b>وضعیت: قفل برای {fa_number(len(locked_ids))} کشور</b>\n"
            f"{'، '.join(names) or '—'}"
        )
    else:
        lines.append("🟢 <b>وضعیت: باز</b> — همه‌ی کشورها می‌توانند استفاده کنند.")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_feature_kb(key, is_global=is_global, has_any=bool(rows)),
    )


@router.callback_query(F.data.startswith("godlk_f:"))
async def cb_locks_feature(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """صفحه‌ی یک آپشن."""
    if not await _guard(call):
        return
    await call.answer()
    await state.clear()
    key = _key_by_index(int(call.data.split(":")[1]))
    if key is None:
        await _render_home(call, session)
        return
    await _render_feature(call, session, key)


# ============================================================
#  اطلاع‌رسانی به بازیکنان
# ============================================================
async def _notify_countries(session: AsyncSession, key: str, country_ids: list[int] | None, *, locked: bool) -> None:
    """
    اطلاع قفل/رفع‌قفل به مالکان کشورهای درگیر.

    بدون این پیام، بازیکن فکر می‌کند ربات خراب شده است.
    """
    name_fa = LOCKABLE_FEATURES[key][0]
    if locked:
        msg = (
            f"🔒 <b>آپشن «{name_fa}» موقتاً غیرفعال شد.</b>\n\n"
            "این محدودیت توسط مدیریت بازی اعمال شده است."
        )
    else:
        msg = f"🟢 <b>آپشن «{name_fa}» دوباره فعال شد.</b>"

    if country_ids is None:
        countries = await countries_repo.list_countries(session)
        targets = [c for c in countries if c.owner_user_id]
    else:
        targets = []
        for cid in country_ids:
            country = await countries_repo.get_country(session, cid)
            if country and country.owner_user_id:
                targets.append(country)

    for country in targets:
        try:
            await bot.send_message(country.owner_user_id, msg)
        except Exception:  # noqa: BLE001 — خطای ارسال نباید جریان را متوقف کند
            continue


# ============================================================
#  قفل سراسری
# ============================================================
@router.callback_query(F.data.startswith("godlk_all:"))
async def cb_lock_all(call: CallbackQuery, session: AsyncSession) -> None:
    """قفل یک آپشن برای همه‌ی کشورها."""
    if not await _guard(call):
        return
    key = _key_by_index(int(call.data.split(":")[1]))
    if key is None:
        await call.answer("آپشن نامعتبر.", show_alert=True)
        return

    await locks_repo.lock(session, key, None)
    await session.commit()
    await call.answer("قفل سراسری اعمال شد 🔒", show_alert=True)

    name_fa = LOCKABLE_FEATURES[key][0]
    await send_log(
        bot,
        f"🔒 <b>قفل سراسری آپشن</b>\nآپشن: {name_fa} (<code>{key}</code>)\n"
        "دامنه: همه‌ی کشورها\n👤 توسط مدیریت بازی",
    )
    await _notify_countries(session, key, None, locked=True)
    await _render_feature(call, session, key)


# ============================================================
#  رفع کامل قفل
# ============================================================
@router.callback_query(F.data.startswith("godlk_un:"))
async def cb_unlock_feature(call: CallbackQuery, session: AsyncSession) -> None:
    """برداشتن همه‌ی قفل‌های یک آپشن (سراسری و موردی)."""
    if not await _guard(call):
        return
    key = _key_by_index(int(call.data.split(":")[1]))
    if key is None:
        await call.answer("آپشن نامعتبر.", show_alert=True)
        return

    rows = await locks_repo.list_locks_for_feature(session, key)
    affected = [r.country_id for r in rows if r.country_id is not None]
    was_global = any(r.country_id is None for r in rows)

    removed = await locks_repo.unlock(session, key)
    await session.commit()
    await call.answer(f"{removed} قفل برداشته شد ♻️", show_alert=True)

    name_fa = LOCKABLE_FEATURES[key][0]
    await send_log(
        bot,
        f"🟢 <b>رفع قفل آپشن</b>\nآپشن: {name_fa} (<code>{key}</code>)\n"
        f"تعداد قفل برداشته‌شده: {fa_number(removed)}\n👤 توسط مدیریت بازی",
    )
    await _notify_countries(
        session, key, None if was_global else affected, locked=False
    )
    await _render_feature(call, session, key)


# ============================================================
#  قفل برای چند کشور (انتخاب چندتایی)
# ============================================================
def _pick_kb(key: str, countries, selected: set[int], locked_ids: set[int]) -> InlineKeyboardMarkup:
    idx = _index_of(key)
    builder = InlineKeyboardBuilder()
    for country in countries:
        if country.id in locked_ids:
            # از قبل قفل است — با 🔒 نمایش و بدون امکان انتخاب دوباره
            builder.button(
                text=f"🔒 {country.flag} {country.name_fa}",
                callback_data="godlk_noop",
            )
            continue
        chosen = country.id in selected
        builder.button(
            text=f"{PICK_ON if chosen else PICK_OFF} {country.flag} {country.name_fa}",
            callback_data=f"godlk_tg:{country.id}",
            style=STYLE_OK if chosen else STYLE_MAIN,
        )
    builder.adjust(2)
    if selected:
        builder.row(
            InlineKeyboardButton(
                text=f"🔒 اعمال قفل روی {fa_number(len(selected))} کشور",
                callback_data="godlk_apply",
                style=STYLE_NO,
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت", callback_data=f"godlk_f:{idx}", style=STYLE_MAIN
        )
    )
    return builder.as_markup()


async def _render_pick(call: CallbackQuery, session: AsyncSession, key: str, selected: set[int]) -> None:
    countries = await countries_repo.list_countries(session)
    rows = await locks_repo.list_locks_for_feature(session, key)
    locked_ids = {r.country_id for r in rows if r.country_id is not None}
    name_fa = LOCKABLE_FEATURES[key][0]

    text = (
        header(f"قفل «{name_fa}» برای کشورهای منتخب", "🎯") + "\n\n"
        "کشورهایی که می‌خواهید این آپشن برایشان بسته شود را انتخاب کنید.\n"
        "<i>🔒 یعنی از قبل قفل است.</i>"
    )
    await call.message.edit_text(
        text, reply_markup=_pick_kb(key, countries, selected, locked_ids)
    )


@router.callback_query(F.data.startswith("godlk_pick:"))
async def cb_lock_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """شروع انتخاب چندتایی کشورها."""
    if not await _guard(call):
        return
    await call.answer()
    key = _key_by_index(int(call.data.split(":")[1]))
    if key is None:
        await _render_home(call, session)
        return
    await state.set_state(GodLockForm.selecting_countries)
    await state.update_data(lock_key=key, selected=[])
    await _render_pick(call, session, key, set())


@router.callback_query(F.data == "godlk_noop")
async def cb_lock_noop(call: CallbackQuery) -> None:
    """کشوری که از قبل قفل است."""
    await call.answer("این کشور از قبل قفل است. برای برداشتن، «رفع قفل» را بزنید.", show_alert=True)


@router.callback_query(GodLockForm.selecting_countries, F.data.startswith("godlk_tg:"))
async def cb_lock_toggle(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """انتخاب/لغو انتخاب یک کشور."""
    if not await _guard(call):
        return
    await call.answer()
    cid = int(call.data.split(":")[1])
    data = await state.get_data()
    key = data.get("lock_key")
    if key is None:
        await _render_home(call, session)
        return

    selected = set(data.get("selected", []))
    selected.discard(cid) if cid in selected else selected.add(cid)
    await state.update_data(selected=list(selected))

    countries = await countries_repo.list_countries(session)
    rows = await locks_repo.list_locks_for_feature(session, key)
    locked_ids = {r.country_id for r in rows if r.country_id is not None}
    await call.message.edit_reply_markup(
        reply_markup=_pick_kb(key, countries, selected, locked_ids)
    )


@router.callback_query(GodLockForm.selecting_countries, F.data == "godlk_apply")
async def cb_lock_apply(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """اعمال قفل روی کشورهای انتخاب‌شده."""
    if not await _guard(call):
        return
    data = await state.get_data()
    key = data.get("lock_key")
    selected = list(data.get("selected", []))
    await state.clear()

    if key is None or not selected:
        await call.answer("هیچ کشوری انتخاب نشده است.", show_alert=True)
        await _render_home(call, session)
        return

    added = await locks_repo.lock(session, key, selected)
    await session.commit()
    await call.answer(f"{added} قفل ثبت شد 🔒", show_alert=True)

    names = []
    for cid in selected:
        country = await countries_repo.get_country(session, cid)
        if country:
            names.append(f"{country.flag} {country.name_fa}")

    name_fa = LOCKABLE_FEATURES[key][0]
    await send_log(
        bot,
        f"🔒 <b>قفل آپشن برای کشورهای منتخب</b>\n"
        f"آپشن: {name_fa} (<code>{key}</code>)\n"
        f"کشورها ({fa_number(len(selected))}): {'، '.join(names) or '—'}\n"
        "👤 توسط مدیریت بازی",
    )
    await _notify_countries(session, key, selected, locked=True)
    await _render_feature(call, session, key)


# ============================================================
#  فهرست همه‌ی قفل‌های فعال
# ============================================================
@router.callback_query(F.data == "godlk:list")
async def cb_locks_list(call: CallbackQuery, session: AsyncSession) -> None:
    """مرور همه‌ی قفل‌های فعال با امکان رفع سریع."""
    if not await _guard(call):
        return
    await call.answer()

    locks = await locks_repo.list_locks(session)
    builder = InlineKeyboardBuilder()
    lines = [header("قفل‌های فعال", "📋"), ""]

    if not locks:
        lines.append("🟢 هیچ آپشنی قفل نیست؛ همه‌ی بخش‌های بازی باز است.")
    else:
        # گروه‌بندی بر اساس آپشن تا فهرست خوانا بماند
        grouped: dict[str, list[int | None]] = {}
        for row in locks:
            grouped.setdefault(row.feature_key, []).append(row.country_id)

        for key, cids in grouped.items():
            entry = LOCKABLE_FEATURES.get(key)
            name_fa = entry[0] if entry else key
            if None in cids:
                lines.append(f"🔴 {name_fa} — قفل سراسری")
            else:
                names = []
                for cid in cids:
                    country = await countries_repo.get_country(session, cid)
                    if country:
                        names.append(f"{country.flag} {country.name_fa}")
                lines.append(f"🟠 {name_fa} — {'، '.join(names)}")
            if entry is not None:
                builder.button(
                    text=f"♻️ رفع قفل {name_fa}",
                    callback_data=f"godlk_un:{_index_of(key)}",
                    style=STYLE_OK,
                )

        builder.adjust(1)
        builder.row(
            InlineKeyboardButton(
                text="🟢 رفع همه‌ی قفل‌ها", callback_data="godlk:unlock_all", style=STYLE_OK
            )
        )

    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="god:locks", style=STYLE_MAIN)
    )
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "godlk:unlock_all")
async def cb_unlock_all_ask(call: CallbackQuery) -> None:
    """تأیید دومرحله‌ای برداشتن همه‌ی قفل‌ها."""
    if not await _guard(call):
        return
    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🟢 بله، همه را باز کن", callback_data="godlk:unlock_all_ok", style=STYLE_OK
        ),
        InlineKeyboardButton(text="❌ انصراف", callback_data="godlk:list", style=STYLE_NO),
    ]])
    await call.message.edit_text(
        "⚠️ همه‌ی قفل‌های آپشن‌ها برداشته می‌شود و بازی کامل باز می‌گردد. مطمئنید؟",
        reply_markup=kb,
    )


@router.callback_query(F.data == "godlk:unlock_all_ok")
async def cb_unlock_all_do(call: CallbackQuery, session: AsyncSession) -> None:
    """برداشتن همه‌ی قفل‌ها."""
    if not await _guard(call):
        return
    removed = await locks_repo.unlock_all(session)
    await session.commit()
    await call.answer(f"{removed} قفل برداشته شد ♻️", show_alert=True)
    await send_log(
        bot,
        f"🟢 <b>همه‌ی قفل‌های آپشن‌ها برداشته شد</b>\n"
        f"تعداد: {fa_number(removed)}\n👤 توسط مدیریت بازی",
    )
    await _render_home(call, session)
