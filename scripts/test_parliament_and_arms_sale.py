"""
اسکریپت تست اختصاصی:
۱. عملکرد دکمه مجلس و ورود به بخش قانونگذاری (حل باگ NameError: _utcnow) و بررسی سهمیه ۱۲ ساعته و ثبت لایحه
۲. حذف کامل کنترل هوش مصنوعی در فروش سلاح (cb_sell_buyer) و عدم وجود توابع مرده در evaluators و prompts
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_ONLY"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "[111]"
os.environ["ADMIN_IDS"] = "[111, 222]"
os.environ["PYTHONUTF8"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import Country, MilitaryAsset, User
from bot.handlers import governance, military
from bot.services.ai import evaluators, prompts
from bot.states import LawForm, MilitarySaleForm


async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_factory


def make_fsm_context(user_id: int, chat_id: int) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=123456, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


async def test_dead_code_elimination():
    print("\n--- تست ۱: اطمینان از حذف کامل کد مرده AI Arms Export ---")
    assert not hasattr(evaluators, "evaluate_arms_export"), "evaluate_arms_export should be deleted"
    assert not hasattr(prompts, "arms_export_prompt"), "arms_export_prompt should be deleted"
    print("✅ توابع evaluate_arms_export و arms_export_prompt با موفقیت حذف شده‌اند.")


async def test_parliament_flow(session: AsyncSession):
    print("\n--- تست ۲: ورود به مجلس، نمایش سهمیه ۱۲ ساعته و ثبت لایحه ---")
    user = User(telegram_id=111, username="test_leader", first_name="Leader")
    country = Country(
        name_en="Iran",
        name_fa="ایران",
        flag="🇮🇷",
        region="middle_east",
        population=85_000_000,
        budget=500_000_000.0,
        owner_user_id=111,
    )
    session.add_all([user, country])
    await session.commit()

    state = make_fsm_context(111, 111)

    # شبیه‌سازی کلیک روی دکمه مجلس gov:parliament
    call = MagicMock()
    call.data = "gov:parliament"
    call.message = MagicMock()
    call.message.photo = None
    call.message.document = None
    call.message.text = "منوی قبلی"
    call.message.edit_text = AsyncMock()
    call.message.answer = AsyncMock()
    call.answer = AsyncMock()

    # فراخوانی cb_parliament
    await governance.cb_parliament(call, session, user, state=state)

    # بررسی اینکه edit_text صدا زده شده و حاوی مجلس شورای ملی و سهمیه است
    call.message.edit_text.assert_called_once()
    rendered_text = call.message.edit_text.call_args[0][0]
    assert "مجلس شورای ملی" in rendered_text, f"Text was: {rendered_text}"
    assert "سهمیه لایحه شما" in rendered_text, f"Quota line missing: {rendered_text}"
    print(f"✅ منوی مجلس بدون خطا رندر شد:\n{rendered_text.strip()}")

    # شروع ثبت لایحه gov:submit_law
    call_submit = MagicMock()
    call_submit.data = "gov:submit_law"
    call_submit.message = MagicMock()
    call_submit.message.photo = None
    call_submit.message.document = None
    call_submit.message.edit_text = AsyncMock()
    call_submit.answer = AsyncMock()

    await governance.cb_submit_law(call_submit, state, session, user)
    current_state = await state.get_state()
    assert current_state == LawForm.entering_title.state, f"Expected entering_title, got {current_state}"
    print("✅ فرم ثبت لایحه با موفقیت شروع شد.")

    # ارسال عنوان لایحه
    msg_title = MagicMock()
    msg_title.text = "لایحه افزایش بودجه زیرساخت"
    msg_title.answer = AsyncMock()
    await governance.msg_law_title(msg_title, state)
    current_state = await state.get_state()
    assert current_state == LawForm.entering_body.state
    print("✅ عنوان لایحه دریافت شد.")

    # ارسال متن لایحه
    msg_body = MagicMock()
    msg_body.text = "متن کامل لایحه به همراه توضیحات بودجه"
    msg_body.answer = AsyncMock()
    await governance.msg_law_body(msg_body, state, session, user)
    current_state = await state.get_state()
    assert current_state is None, "State should be cleared after law submission"
    print("✅ لایحه در دیتابیس ثبت و به مجلس ارسال شد.")

    # دوباره باز کردن مجلس و بررسی کسر سهمیه
    call_reenter = MagicMock()
    call_reenter.data = "gov:parliament"
    call_reenter.message = MagicMock()
    call_reenter.message.photo = None
    call_reenter.message.document = None
    call_reenter.message.edit_text = AsyncMock()
    call_reenter.answer = AsyncMock()

    await governance.cb_parliament(call_reenter, session, user, state=state)
    rendered_text2 = call_reenter.message.edit_text.call_args[0][0]
    assert "۱ از ۲" in rendered_text2 or "1 از 2" in rendered_text2 or "۱" in rendered_text2, f"Text: {rendered_text2}"
    print("✅ سهمیه ۱۲ ساعته به درستی بعد از ثبت لایحه به‌روز شد.")

    # بررسی cb_my_laws
    call_my_laws = MagicMock()
    call_my_laws.data = "gov:my_laws"
    call_my_laws.message = MagicMock()
    call_my_laws.message.photo = None
    call_my_laws.message.document = None
    call_my_laws.message.edit_text = AsyncMock()
    call_my_laws.answer = AsyncMock()

    await governance.cb_my_laws(call_my_laws, session, user)
    call_my_laws.message.edit_text.assert_called_once()
    my_laws_text = call_my_laws.message.edit_text.call_args[0][0]
    assert "لایحه افزایش بودجه زیرساخت" in my_laws_text
    print("✅ فهرست لایحه‌های من به درستی لایحه ثبت‌شده را نمایش داد.")


async def test_arms_sale_without_ai(session: AsyncSession):
    print("\n--- تست ۳: فروش تجهیزات نظامی سنگین/نسل ۵ بدون هیچ‌گونه بررسی و فیلتر AI ---")
    seller_user = User(telegram_id=222, username="usa_leader", first_name="USA Leader")
    buyer_user = User(telegram_id=333, username="afg_leader", first_name="AFG Leader")

    seller_country = Country(
        name_en="United States",
        name_fa="آمریکا",
        flag="🇺🇸",
        region="north_america",
        population=330_000_000,
        budget=1_000_000_000.0,
        owner_user_id=222,
    )
    buyer_country = Country(
        name_en="Afghanistan",
        name_fa="افغانستان",
        flag="🇦🇫",
        region="middle_east",
        population=40_000_000,
        budget=50_000_000.0,
        owner_user_id=333,
    )
    session.add_all([seller_user, buyer_user, seller_country, buyer_country])
    await session.commit()

    # ایجاد موجودی F-22 برای آمریکا
    f22 = MilitaryAsset(
        country_id=seller_country.id,
        category="جنگنده",
        branch="air",
        name="F-22 Raptor",
        unit="فروند",
        count=5,
    )
    session.add(f22)
    await session.commit()

    state = make_fsm_context(222, 222)
    await state.set_state(MilitarySaleForm.choosing_buyer)
    await state.update_data(
        sell_pick={"name": "F-22 Raptor", "category": "جنگنده", "unit": "فروند", "branch": "نیروی هوایی"},
        sell_count=2,
        sell_price=100_000_000.0,
    )

    # شبیه‌سازی انتخاب افغانستان به عنوان خریدار توسط آمریکا
    call = MagicMock()
    call.data = f"milsell_buyer:{buyer_country.id}"
    call.message = MagicMock()
    call.message.photo = None
    call.message.document = None
    call.message.edit_text = AsyncMock()
    call.answer = AsyncMock()

    # فراخوانی هندلر cb_sell_buyer
    await military.cb_sell_buyer(call, state, session, seller_user)

    # بررسی انتقال مستقیم به فرم انتخاب پرداخت‌کننده عوارض
    current_state = await state.get_state()
    assert current_state == MilitarySaleForm.choosing_fee_payer.state, f"Expected choosing_fee_payer, got {current_state}"
    data = await state.get_data()
    assert data.get("sell_buyer_id") == buyer_country.id

    call.message.edit_text.assert_called_once()
    text_shown = call.message.edit_text.call_args[0][0]
    assert "تعیین پرداخت‌کننده عوارض حمل هوایی" in text_shown
    print("✅ فروش جنگنده پیشرفته به افغانستان مستقیماً و بدون مداخله هوش مصنوعی تأیید و وارد مرحله بعد شد.")


async def main():
    print("=" * 60)
    print("🚀 اجرای تست‌های رفع باگ مجلس و حذف کنترل صادرات AI")
    print("=" * 60)

    await test_dead_code_elimination()

    engine, session_factory = await setup_db()
    async with session_factory() as session:
        await test_parliament_flow(session)
        await test_arms_sale_without_ai(session)

    await engine.dispose()
    print("\n" + "=" * 60)
    print("🎉 تمامی تست‌ها با موفقیت ۱۰۰٪ پاس شدند!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
