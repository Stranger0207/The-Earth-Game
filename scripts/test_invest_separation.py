"""
تست جامع تفکیک و صفحه‌بندی سرمایه‌گذاری‌های خارجی و داخلی (v2.4).
"""

from __future__ import annotations

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.base import Base
from bot.database.models import Country, Investment
from bot.database.repositories import investments as inv_repo
from bot.handlers.investment import INVEST_PAGE_SIZE, _invest_page_kb
from bot.keyboards.economy import invest_foreign_kb


async def run_tests() -> None:
    print("🚀 در حال اجرای تست‌های تفکیک و صفحه‌بندی سرمایه‌گذاری‌ها (v2.4)...")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        # ایجاد کشورهای تستی
        c1 = Country(id=1, name_fa="ایران", name_en="Iran", flag="🇮🇷", region="Asia", budget=1_000_000_000)
        c2 = Country(id=2, name_fa="ژاپن", name_en="Japan", flag="🇯🇵", region="Asia", budget=1_000_000_000)
        c3 = Country(id=3, name_fa="آلمان", name_en="Germany", flag="🇩🇪", region="Europe", budget=1_000_000_000)
        session.add_all([c1, c2, c3])
        await session.flush()

        # ایجاد ۲۵ سرمایه‌گذاری خارجی از طرف c1 روی c2
        for i in range(25):
            inv = Investment(
                investor_country=c1.id,
                target_country=c2.id,
                category="oil",
                amount=10_000_000 + i * 1_000_000,
                profit_pct=5.0,
                active=True,
            )
            await inv_repo.add_investment(session, inv)

        # ایجاد ۵ سرمایه‌گذاری داخلی از طرف c1 روی خودش
        for i in range(5):
            inv = Investment(
                investor_country=c1.id,
                target_country=c1.id,
                category="tech",
                amount=20_000_000,
                profit_pct=4.0,
                active=True,
            )
            await inv_repo.add_investment(session, inv)

        # ایجاد ۳ سرمایه‌گذاری از طرف c3 روی c1
        for i in range(3):
            inv = Investment(
                investor_country=c3.id,
                target_country=c1.id,
                category="mines",
                amount=30_000_000,
                profit_pct=6.0,
                active=True,
            )
            await inv_repo.add_investment(session, inv)

        # ── تست ۱: تفکیک لیست‌ها در ریپازیتوری ──
        print("\n--- تست ۱: تفکیک کوئری‌های ریپازیتوری ---")
        foreign_by_c1 = await inv_repo.list_foreign_by_investor(session, c1.id)
        domestic_by_c1 = await inv_repo.list_domestic_by_investor(session, c1.id)
        all_by_c1 = await inv_repo.list_by_investor(session, c1.id)
        on_c1 = await inv_repo.list_on_target(session, c1.id)

        assert len(foreign_by_c1) == 25, f"Expected 25 foreign investments, got {len(foreign_by_c1)}"
        assert len(domestic_by_c1) == 5, f"Expected 5 domestic investments, got {len(domestic_by_c1)}"
        assert len(all_by_c1) == 30, f"Expected 30 total investments, got {len(all_by_c1)}"
        assert len(on_c1) == 3, f"Expected 3 investments on c1, got {len(on_c1)}"
        print("✅ تست ۱ با موفقیت پاس شد: تفکیک کامل خارجی، داخلی، کل و ورودی.")

        # ── تست ۲: صفحه‌بندی ۱۰تایی ──
        print("\n--- تست ۲: بررسی صفحه‌بندی ۱۰تایی ---")
        total_items = len(foreign_by_c1)
        total_pages = (total_items + INVEST_PAGE_SIZE - 1) // INVEST_PAGE_SIZE
        assert total_pages == 3, f"Expected 3 pages for 25 items, got {total_pages}"

        # صفحه اول: ۱۰ مورد
        chunk0 = foreign_by_c1[0:10]
        kb0 = _invest_page_kb("foreign_mine", 0, total_pages, chunk0, back_data="inv:foreign")
        assert len(chunk0) == 10
        # چک دکمه‌های لغو: ۱۰ دکمه در ۵ سطر ۲تایی
        cancel_btns_0 = [btn for row in kb0.inline_keyboard for btn in row if btn.callback_data.startswith("inv_cancel:")]
        assert len(cancel_btns_0) == 10, f"Expected 10 cancel buttons, got {len(cancel_btns_0)}"
        # چک ناوبری صفحه اول: فقط صفحه بعدی دارد
        nav_btns_0 = [btn for row in kb0.inline_keyboard for btn in row if "صفحه" in btn.text]
        assert len(nav_btns_0) == 1 and "بعدی" in nav_btns_0[0].text
        # چک بازگشت به منوی خارجی
        assert kb0.inline_keyboard[-1][0].callback_data == "inv:foreign"

        # صفحه دوم: ۱۰ مورد
        chunk1 = foreign_by_c1[10:20]
        kb1 = _invest_page_kb("foreign_mine", 1, total_pages, chunk1, back_data="inv:foreign")
        cancel_btns_1 = [btn for row in kb1.inline_keyboard for btn in row if btn.callback_data.startswith("inv_cancel:")]
        assert len(cancel_btns_1) == 10
        nav_btns_1 = [btn for row in kb1.inline_keyboard for btn in row if "صفحه" in btn.text]
        assert len(nav_btns_1) == 2  # قبلی و بعدی

        # صفحه سوم: ۵ مورد
        chunk2 = foreign_by_c1[20:25]
        kb2 = _invest_page_kb("foreign_mine", 2, total_pages, chunk2, back_data="inv:foreign")
        cancel_btns_2 = [btn for row in kb2.inline_keyboard for btn in row if btn.callback_data.startswith("inv_cancel:")]
        assert len(cancel_btns_2) == 5
        nav_btns_2 = [btn for row in kb2.inline_keyboard for btn in row if "صفحه" in btn.text]
        assert len(nav_btns_2) == 1 and "قبلی" in nav_btns_2[0].text
        print("✅ تست ۲ با موفقیت پاس شد: صفحه‌بندی ۱۰ تایی و دکمه‌های ناوبری و لغو دقیق هستند.")

        # ── تست ۳: کیبورد منوی سرمایه‌گذاری خارجی ──
        print("\n--- تست ۳: کیبورد منوی سرمایه‌گذاری خارجی ---")
        f_kb = invest_foreign_kb()
        callbacks = [btn.callback_data for row in f_kb.inline_keyboard for btn in row]
        assert "inv:foreign_mine" in callbacks
        assert "inv:on_me" in callbacks
        assert "inv:new_foreign" in callbacks
        assert "econ:invest" in callbacks
        print("✅ تست ۳ با موفقیت پاس شد: گزینه‌های تفکیک‌شده در منوی خارجی قرار دارند.")

    print("\n🎉 تمام تست‌های تفکیک و صفحه‌بندی سرمایه‌گذاری‌ها با موفقیت ۱۰۰٪ پاس شدند!")


if __name__ == "__main__":
    asyncio.run(run_tests())
