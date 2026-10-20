"""
تست جامع اند-تو-اند اعتبارسنجی و دیباگ کامل سیستم مجمع عمومی و سازمان ملل متحد (UN).
شامل:
۱. بررسی مایگریشن ستون last_vote
۲. ورود و خروج به صحن تالار و اعلان‌های سراسری (broadcast_to_assembly)
۳. عملکرد قفل پنل در صحن تالار (check_hall_lock) و باز شدن در لابی
۴. اعلام حضور و مدیریت صف سخنرانان (asmb_req_speech)
۵. تریبون و شروع سخنرانی بعدی (cb_un_asmb_next)
۶. رله پیام‌های متنی و تصویری سخنران و اتصال کیبورد واکنش سریع
۷. عملکرد تشویق و کول‌داون ۳۰ ثانیه‌ای (cb_asmb_applaud)
۸. ترک اعتراضی تالار (cb_asmb_walkout) و تغییر وضعیت به in_new_york
۹. جاب زمان‌بندی انقضای ۵ دقیقه‌ای و تغییر تریبون در پس‌زمینه (process_un_assembly)
۱۰. رای‌گیری زنده در صحن، ثبت آرا، شمارش و بستن رای‌گیری (cb_asmb_vote_cast / cb_asmb_vote_end)
۱۱. مدیریت قطعنامه‌های رسمی سازمان ملل و شمارش و صدور حکم (cb_res_vote / cb_res_close)
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery

sys.path.insert(0, r"c:\Users\ARASH\earth_game_bot")

from sqlalchemy import delete, select

from bot.database.base import async_session_factory, init_db
from bot.database.models import Country, User
from bot.database.models.united_nations import (
    UNAssemblyParticipant,
    UNAssemblySession,
    UNResolution,
    UNResolutionVote,
    UNSpeechQueue,
)
from bot.database.repositories import countries as countries_repo
from bot.database.repositories import united_nations as un_repo
from bot.handlers.deps import check_hall_lock
from bot.handlers.diplomacy import relay_speech_photo
from bot.handlers.united_nations import (
    _applause_cooldown,
    broadcast_to_assembly,
    cb_asmb_applaud,
    cb_asmb_enter_hall,
    cb_asmb_exit_hall,
    cb_asmb_req_speech,
    cb_asmb_vote_cast,
    cb_asmb_vote_end,
    cb_asmb_walkout,
    cb_res_close,
    cb_res_vote,
    cb_un_asmb_next,
)
from bot.scheduler.jobs import process_un_assembly


async def run_full_test():
    print("=================================================================")
    print("🚀 آغاز تست جامع سیستم سازمان ملل متحد و مجمع عمومی (UN Overhaul)")
    print("=================================================================")
    session_id = None
    res_id = None

    # ۱. اجرای init_db برای اعمال مایگریشن ستون last_vote
    print("\n--- گام ۱: بررسی پایگاه‌داده و مایگریشن ستون‌ها ---")
    await init_db()
    print("✅ init_db بدون خطا اجرا شد.")

    async with async_session_factory() as session:
        # ۲. آماده‌سازی کشورهای تستی
        print("\n--- گام ۲: آماده‌سازی کشورهای تستی (UN، چین، فرانسه، آلمان) ---")
        un_country = await countries_repo.get_country_by_name(session, "UN")
        assert un_country is not None, "کشور UN در دیتابیس یافت نشد!"

        china = await countries_repo.get_country_by_name(session, "China")
        france = await countries_repo.get_country_by_name(session, "France")
        germany = await countries_repo.get_country_by_name(session, "Germany")

        assert china is not None and france is not None and germany is not None, "کشورهای چین، فرانسه یا آلمان یافت نشدند!"

        # اختصاص کاربران تست
        un_user_id = 999999001
        china_user_id = 999999002
        france_user_id = 999999003
        germany_user_id = 999999004

        for uid, uname, c in [
            (un_user_id, "test_un_sec", un_country),
            (china_user_id, "test_china_rep", china),
            (france_user_id, "test_france_rep", france),
            (germany_user_id, "test_germany_rep", germany),
        ]:
            u = (await session.execute(select(User).where(User.telegram_id == uid))).scalars().first()
            if not u:
                u = User(telegram_id=uid, username=uname, first_name=uname)
                session.add(u)
                await session.flush()
            c.owner_user_id = uid
            c.is_claimed = True

        await session.commit()

        un_user = (await session.execute(select(User).where(User.telegram_id == un_user_id))).scalars().first()
        china_user = (await session.execute(select(User).where(User.telegram_id == china_user_id))).scalars().first()
        france_user = (await session.execute(select(User).where(User.telegram_id == france_user_id))).scalars().first()
        germany_user = (await session.execute(select(User).where(User.telegram_id == germany_user_id))).scalars().first()

        print(f"✅ مالکین کشورهای تست تنظیم شدند (UN: {un_user_id}, چین: {china_user_id}, فرانسه: {france_user_id}, آلمان: {germany_user_id})")

    async with async_session_factory() as session:
        # ۳. ایجاد اجلاس مجمع عمومی آزمایشی
        print("\n--- گام ۳: ایجاد اجلاس مجمع عمومی آزمایشی ---")
        session_obj = UNAssemblySession(
            session_number=99,
            status="active",
            title="اجلاس مجمع عمومی دیباگ و تست",
            started_at=datetime.now(timezone.utc),
        )
        session.add(session_obj)
        await session.flush()
        session_id = session_obj.id

        # افزودن شرکت‌کنندگان در لابی نیویورک
        p_china = UNAssemblyParticipant(
            session_id=session_id,
            country_id=china.id,
            status="in_new_york",
        )
        p_france = UNAssemblyParticipant(
            session_id=session_id,
            country_id=france.id,
            status="in_new_york",
        )
        p_germany = UNAssemblyParticipant(
            session_id=session_id,
            country_id=germany.id,
            status="in_new_york",
        )
        session.add_all([p_china, p_france, p_germany])
        await session.commit()
        print(f"✅ اجلاس #{session_id} ایجاد شد و چین، فرانسه و آلمان در لابی مستقر شدند.")

    try:
        # ۴. تست ورود به صحن تالار مجمع (cb_asmb_enter_hall) و برودکست ورود
        print("\n--- گام ۴: تست ورود به صحن تالار و برودکست ورود ---")
        async with async_session_factory() as session:
            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_send:
                china_user = (await session.execute(select(User).where(User.telegram_id == china_user_id))).scalars().first()
                call_enter = AsyncMock()
                call_enter.data = f"asmb_enter_hall:{session_id}"
                call_enter.from_user = MagicMock(id=china_user_id)
                call_enter.message = AsyncMock()

                await cb_asmb_enter_hall(call_enter, session, china_user)
                await session.commit()

                part = await un_repo.get_participant(session, session_id, china.id)
                assert part.status == "inside_hall", f"وضعیت چین باید inside_hall باشد اما {part.status} است!"
                print("✅ چین وارد تالار مجمع شد و وضعیت inside_hall ثبت گردید.")

                # فرانسه هم وارد تالار می‌شود
                france_user = (await session.execute(select(User).where(User.telegram_id == france_user_id))).scalars().first()
                call_enter_fr = AsyncMock()
                call_enter_fr.data = f"asmb_enter_hall:{session_id}"
                call_enter_fr.from_user = MagicMock(id=france_user_id)
                call_enter_fr.message = AsyncMock()

                await cb_asmb_enter_hall(call_enter_fr, session, france_user)
                await session.commit()

                # بررسی اینکه برای ورود فرانسه، پیام اعلان به چین و دبیرکل سازمان ملل ارسال شد
                assert mock_send.called, "پیام اعلان ورود ارسال نشد!"
                print("✅ اعلان ورود فرانسه برای چین و سازمان ملل ارسال شد.")

        # ۵. تست قفل پنل کشور در اثر حضور در صحن مجمع (check_hall_lock)
        print("\n--- گام ۵: تست قفل پنل کشور در اثر حضور در تالار (check_hall_lock) ---")
        async with async_session_factory() as session:
            dummy_call = AsyncMock(spec=CallbackQuery)
            dummy_call.answer = AsyncMock()
            dummy_call.from_user = MagicMock(id=china_user_id)
            dummy_call.message = AsyncMock()

            is_locked = await check_hall_lock(dummy_call, session, china)
            assert is_locked is True, "قفل تالار برای چین که داخل صحن است فعال نشد!"
            dummy_call.answer.assert_called_with("دسترسی به پنل کشور در حین حضور در صحن مجمع قفل است.", show_alert=True)
            print("✅ check_hall_lock با موفقیت دسترسی به پنل کشور را در داخل صحن قفل کرد.")

        # ۶. تست اعلام حضور در صف سخنرانی (cb_asmb_req_speech)
        print("\n--- گام ۶: تست اعلام حضور و صف سخنرانی (cb_asmb_req_speech) ---")
        async with async_session_factory() as session:
            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock):
                call_speech = AsyncMock()
                call_speech.data = f"asmb_req_speech:{session_id}"
                call_speech.from_user = MagicMock(id=china_user_id)

                await cb_asmb_req_speech(call_speech, session, china_user)
                await session.commit()

                q_list = await un_repo.get_speech_queue(session, session_id)
                assert len(q_list) == 1, "چین در صف سخنرانی ثبت نشد!"
                assert q_list[0].country_id == china.id
                print("✅ کشور چین در صف سخنرانی قرار گرفت.")

                # تست ثبت مجدد (عدم ایجاد رکورد تکراری)
                await cb_asmb_req_speech(call_speech, session, china_user)
                q_list_after = await un_repo.get_speech_queue(session, session_id)
                assert len(q_list_after) == 1, "درخواست تکراری در صف ایجاد شد!"
                call_speech.answer.assert_called_with("شما قبلاً در صف سخنرانی مجمع اعلام حضور کرده‌اید.", show_alert=True)
                print("✅ هندلر از ثبت تکراری در صف سخنرانی جلوگیری کرد.")

                # فرانسه هم در صف قرار می‌گیرد
                call_speech_fr = AsyncMock()
                call_speech_fr.data = f"asmb_req_speech:{session_id}"
                call_speech_fr.from_user = MagicMock(id=france_user_id)
                await cb_asmb_req_speech(call_speech_fr, session, france_user)
                await session.commit()
                q_list_2 = await un_repo.get_speech_queue(session, session_id)
                assert len(q_list_2) == 2, "فرانسه در صف اضافه نشد!"
                print("✅ کشور فرانسه به عنوان نفر دوم در صف سخنرانی قرار گرفت.")

        # ۷. تست اعطای تریبون به سخنران بعدی توسط سازمان ملل (cb_un_asmb_next)
        print("\n--- گام ۷: تست شروع سخنرانی بعدی توسط سازمان ملل (cb_un_asmb_next) ---")
        async with async_session_factory() as session:
            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_send_next:
                call_next = AsyncMock()
                call_next.data = f"un_asmb_next:{session_id}"
                call_next.from_user = MagicMock(id=un_user_id)
                call_next.message = AsyncMock()

                await cb_un_asmb_next(call_next, session)
                await session.commit()

                asmb_check = await un_repo.get_session(session, session_id)
                assert asmb_check.current_speaker_country_id == china.id, "چین سخنران فعال نشد!"
                assert asmb_check.speech_ends_at is not None, "تایمر سخنرانی تنظیم نشد!"

                # بررسی اینکه پیام اختصاصی به چین ارسال شد
                speaker_msg_calls = [
                    c for c in mock_send_next.call_args_list if c.args[0] == china_user_id
                ]
                assert len(speaker_msg_calls) > 0, "پیام اختصاصی تریبون به چین ارسال نشد!"
                assert "تریبون در اختیار شماست" in speaker_msg_calls[0].args[1]

                # بررسی اینکه پیام برودکست به فرانسه (داخل صحن) و سازمان ملل ارسال شد
                other_calls = [
                    c for c in mock_send_next.call_args_list if c.args[0] in (france_user_id, un_user_id)
                ]
                assert len(other_calls) > 0, "پیام تغییر تریبون برای سایرین ارسال نشد!"
                print("✅ تریبون به چین واگذار شد، پیام اختصاصی به چین و برودکست رسمی به سایرین رسید.")

        # ۸. تست رله پیام سخنران و اتصال دکمه‌های واکنش سریع (speech_reactions_kb)
        print("\n--- گام ۸: تست رله پیام متنی و تصویری سخنران ---")
        async with async_session_factory() as session:
            from bot.keyboards.united_nations import speech_reactions_kb

            r_kb = speech_reactions_kb(session_id)
            assert any("asmb_applaud" in btn.callback_data for row in r_kb.inline_keyboard for btn in row)
            assert any("asmb_walkout" in btn.callback_data for row in r_kb.inline_keyboard for btn in row)
            print("✅ کیبورد speech_reactions_kb حاوی دکمه‌های تشویق و ترک اعتراضی است.")

            # تست رله عکس
            with patch("bot.handlers.diplomacy.bot.send_photo", new_callable=AsyncMock) as mock_photo:
                msg_photo = AsyncMock()
                msg_photo.photo = [MagicMock(file_id="photo_123")]
                msg_photo.caption = "سند رسمی دفاعی چین"

                await relay_speech_photo(msg_photo, session, china_user)
                assert mock_photo.called, "عکس سخنران برای حاضران ارسال نشد!"
                print("✅ عکس سخنران همراه با دکمه‌های واکنش سریع به تالار رله شد.")

        # ۹. تست تشویق و کول‌داون ۳۰ ثانیه‌ای (cb_asmb_applaud)
        print("\n--- گام ۹: تست تشویق سخنران و کول‌داون (cb_asmb_applaud) ---")
        async with async_session_factory() as session:
            _applause_cooldown.clear()
            call_applaud = AsyncMock()
            call_applaud.data = f"asmb_applaud:{session_id}"
            call_applaud.from_user = MagicMock(id=france_user_id)

            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_applaud_send:
                await cb_asmb_applaud(call_applaud, session, france_user)
                call_applaud.answer.assert_called_with("👏 تشویق شما در تالار ثبت شد.")
                assert mock_applaud_send.called, "پیام تشویق در تالار برودکست نشد!"
                print("✅ تشویق فرانسه با موفقیت در تالار برودکست شد.")

                # تست کول‌داون
                call_applaud_spam = AsyncMock()
                call_applaud_spam.data = f"asmb_applaud:{session_id}"
                call_applaud_spam.from_user = MagicMock(id=france_user_id)
                await cb_asmb_applaud(call_applaud_spam, session, france_user)
                args, kwargs = call_applaud_spam.answer.call_args
                assert "ثانیه دیگر برای تشویق مجدد صبر کنید" in args[0]
                assert kwargs.get("show_alert") is True
                print("✅ کول‌داون ۳۰ ثانیه‌ای تشویق به درستی جلوی اسپم را گرفت.")

        # ۱۰. تست خروج از تالار به لابی نیویورک (cb_asmb_exit_hall) و باز شدن قفل پنل
        print("\n--- گام ۱۰: تست خروج از تالار مجمع به لابی نیویورک (cb_asmb_exit_hall) ---")
        async with async_session_factory() as session:
            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock):
                call_exit = AsyncMock()
                call_exit.data = f"asmb_exit_hall:{session_id}"
                call_exit.from_user = MagicMock(id=france_user_id)

                await cb_asmb_exit_hall(call_exit, session, france_user)
                await session.commit()

            part_fr = await un_repo.get_participant(session, session_id, france.id)
            assert part_fr.status == "in_new_york", f"وضعیت فرانسه باید in_new_york باشد اما {part_fr.status} است!"

            # بررسی باز شدن قفل پنل کشوری
            dummy_call_fr = AsyncMock(spec=CallbackQuery)
            dummy_call_fr.answer = AsyncMock()
            dummy_call_fr.from_user = MagicMock(id=france_user_id)
            is_locked_fr = await check_hall_lock(dummy_call_fr, session, france)
            assert is_locked_fr is False, "قفل پنل پس از خروج از صحن باز نشد!"
            print("✅ فرانسه از تالار خارج شد و قفل پنل کشوری با موفقیت باز گردید.")

        # ۱۱. تست ترک اعتراضی تالار (cb_asmb_walkout)
        print("\n--- گام ۱۱: تست ترک اعتراضی تالار (cb_asmb_walkout) ---")
        async with async_session_factory() as session:
            # آلمان وارد صحن می‌شود
            part_de = await un_repo.get_participant(session, session_id, germany.id)
            part_de.status = "inside_hall"
            await session.commit()

            call_walk = AsyncMock()
            call_walk.data = f"asmb_walkout:{session_id}"
            call_walk.from_user = MagicMock(id=germany_user_id)

            with patch("bot.handlers.united_nations.publish_news", new_callable=AsyncMock) as mock_news, \
                 patch("bot.handlers.united_nations.send_log", new_callable=AsyncMock) as mock_log, \
                 patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_walk_send:

                await cb_asmb_walkout(call_walk, session, germany_user)
                await session.commit()

                part_de_after = await un_repo.get_participant(session, session_id, germany.id)
                assert part_de_after.status == "in_new_york", "وضعیت آلمان باید به in_new_york تغییر کرده باشد!"
                assert part_de_after.walkout is True, "فلگ walkout باید True شده باشد!"
                assert mock_walk_send.called, "پیام ترک اعتراضی برودکست نشد!"
                assert mock_news.called, "خبر ترک اعتراضی در کانال دیپلماسی منتشر نشد!"
                print("✅ ترک اعتراضی آلمان با موفقیت ثبت، برودکست و در اخبار منتشر شد.")

        # ۱۲. تست زمان‌بندی انقضای ۵ دقیقه‌ای سخنرانی و انتقال خودکار تریبون در پس‌زمینه
        print("\n--- گام ۱۲: تست جاب زمان‌بندی انقضای سخنرانی و تغییر تریبون (process_un_assembly) ---")
        async with async_session_factory() as session:
            # چین در حال صحبت بوده و زمانش منقضی می‌شود
            asmb_exp = await un_repo.get_session(session, session_id)
            asmb_exp.speech_ends_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            await session.commit()

        mock_bot = AsyncMock()
        with patch("bot.services.un_speech_service.analyze_and_publish_speech", new_callable=AsyncMock) as mock_ai:
            await process_un_assembly(mock_bot)

        # بررسی وضعیت بعد از اجرای جاب با سشن تازه
        async with async_session_factory() as post_s:
            asmb_post = await un_repo.get_session(post_s, session_id)
            assert asmb_post.current_speaker_country_id == france.id, f"تریبون به فرانسه واگذار نشد! سخنران فعلی: {asmb_post.current_speaker_country_id}"
            assert mock_bot.send_message.called, "پیام تغییر تریبون توسط جاب ارسال نشد!"
            print("✅ تایمر سخنرانی منقضی شد و جاب process_un_assembly به طور خودکار تریبون را به فرانسه واگذار کرد.")

        # ۱۳. تست رای‌گیری زنده در صحن علنی (cb_asmb_vote_cast / cb_asmb_vote_end)
        print("\n--- گام ۱۳: تست رای‌گیری زنده در صحن، ثبت آرا و پایان رای‌گیری ---")
        async with async_session_factory() as session:
            # فعال‌سازی رای‌گیری در اجلاس
            asmb_vote = await un_repo.get_session(session, session_id)
            asmb_vote.voting_active = True
            # چین و آلمان را داخل تالار قرار می‌دهیم
            p_ch = await un_repo.get_participant(session, session_id, china.id)
            p_ch.status = "inside_hall"
            p_ge = await un_repo.get_participant(session, session_id, germany.id)
            p_ge.status = "inside_hall"
            await session.commit()

            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock):
                # چین رای موافق می‌دهد
                call_v1 = AsyncMock()
                call_v1.data = f"asmb_v_yes:{session_id}"
                call_v1.from_user = MagicMock(id=china_user_id)
                await cb_asmb_vote_cast(call_v1, session, china_user)
                await session.commit()

                p_ch_v = await un_repo.get_participant(session, session_id, china.id)
                assert p_ch_v.last_vote == "yes", f"رای موافق چین ذخیره نشد! {p_ch_v.last_vote}"

                # آلمان رای مخالف می‌دهد
                call_v2 = AsyncMock()
                call_v2.data = f"asmb_v_no:{session_id}"
                call_v2.from_user = MagicMock(id=germany_user_id)
                await cb_asmb_vote_cast(call_v2, session, germany_user)
                await session.commit()

            p_ge_v = await un_repo.get_participant(session, session_id, germany.id)
            assert p_ge_v.last_vote == "no", f"رای مخالف آلمان ذخیره نشد! {p_ge_v.last_vote}"
            print("✅ آراء موافق و مخالف در ستون last_vote ثبت شدند.")

            # دبیرکل رای‌گیری را خاتمه می‌دهد
            call_end_vote = AsyncMock()
            call_end_vote.data = f"asmb_vote_end:{session_id}"
            call_end_vote.from_user = MagicMock(id=un_user_id)
            call_end_vote.message = AsyncMock()

            with patch("bot.handlers.united_nations.publish_news", new_callable=AsyncMock) as mock_news_v, \
                 patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_v_send:

                await cb_asmb_vote_end(call_end_vote, session, un_user)
                await session.commit()

                asmb_post_vote = await un_repo.get_session(session, session_id)
                assert asmb_post_vote.voting_active is False, "رای‌گیری غیرفعال نشد!"
                assert mock_v_send.called, "نتایج رای‌گیری برودکست نشد!"
                assert mock_news_v.called, "نتایج رای‌گیری در کانال خبر منتشر نشد!"
                print("✅ رای‌گیری صحن مختومه شد، نتایج شمارش و برای تمام اعضا اعلام گردید.")

        # ۱۴. تست قطعنامه‌های رسمی سازمان ملل (cb_res_vote / cb_res_close)
        print("\n--- گام ۱۴: تست ثبت رای قطعنامه و بستن قطعنامه توسط دبیرکل ---")
        async with async_session_factory() as session:
            test_res = UNResolution(
                resolution_number="RES-DEBUG-101",
                session_id=session_id,
                proposed_by_country_id=un_country.id,
                title="قطعنامه خلع سلاح اتمی و صلح جهانی",
                body="متن آزمایشی قطعنامه سازمان ملل",
                status="voting",
                created_at=datetime.now(timezone.utc),
            )
            session.add(test_res)
            await session.flush()
            res_id = test_res.id
            await session.commit()

            with patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock):
                # چین رای موافق می‌دهد
                call_rv1 = AsyncMock()
                call_rv1.data = f"res_vote:{res_id}:yes"
                call_rv1.from_user = MagicMock(id=china_user_id)
                await cb_res_vote(call_rv1, session, china_user)

                # آلمان رای مخالف می‌دهد
                call_rv2 = AsyncMock()
                call_rv2.data = f"res_vote:{res_id}:no"
                call_rv2.from_user = MagicMock(id=germany_user_id)
                await cb_res_vote(call_rv2, session, germany_user)

                # فرانسه رای موافق می‌دهد
                call_rv3 = AsyncMock()
                call_rv3.data = f"res_vote:{res_id}:yes"
                call_rv3.from_user = MagicMock(id=france_user_id)
                await cb_res_vote(call_rv3, session, france_user)
                await session.commit()

            # بررسی آرا در دیتابیس
            v_counts = await un_repo.get_resolution_votes(session, res_id)
            assert v_counts["yes"] == 2 and v_counts["no"] == 1, f"آمار آرا نادرست است: {v_counts}"
            print(f"✅ آرای قطعنامه با موفقیت ثبت شد: موافق: {v_counts['yes']}، مخالف: {v_counts['no']}")

            # دبیرکل قطعنامه را می‌بندد (cb_res_close)
            call_close_res = AsyncMock()
            call_close_res.data = f"res_close:{res_id}"
            call_close_res.from_user = MagicMock(id=un_user_id)
            call_close_res.message = AsyncMock()

            with patch("bot.handlers.united_nations.publish_news", new_callable=AsyncMock) as mock_news_res, \
                 patch("bot.handlers.united_nations.bot.send_message", new_callable=AsyncMock) as mock_send_res:

                await cb_res_close(call_close_res, session, un_user)
                await session.commit()

                res_closed = await un_repo.get_resolution(session, res_id)
                assert res_closed.status == "passed", f"وضعیت قطعنامه باید passed باشد اما {res_closed.status} است!"
                assert res_closed.closed_at is not None, "زمان بسته شدن قطعنامه ثبت نشد!"
                assert mock_news_res.called, "خبر تصویب قطعنامه در کانال دیپلماسی منتشر نشد!"
                print("✅ قطعنامه توسط دبیرکل بسته شد، حکم «تصویب شد» صادر و به جامعه جهانی مخابره گردید.")

    finally:
        # ۱۵. پاک‌سازی داده‌های تست
        print("\n--- گام ۱۵: پاک‌سازی داده‌های تست ---")
        async with async_session_factory() as session:
            if res_id is not None:
                await session.execute(delete(UNResolutionVote).where(UNResolutionVote.resolution_id == res_id))
                await session.execute(delete(UNResolution).where(UNResolution.id == res_id))
            if session_id is not None:
                await session.execute(delete(UNSpeechQueue).where(UNSpeechQueue.session_id == session_id))
                await session.execute(delete(UNAssemblyParticipant).where(UNAssemblyParticipant.session_id == session_id))
                await session.execute(delete(UNAssemblySession).where(UNAssemblySession.id == session_id))
            await session.commit()
            print("✅ تمام جداول تست با موفقیت تمیز شدند.")

    print("\n=================================================================")
    print("🎉 ۱۰۰٪ تست‌های سیستم مجمع عمومی و سازمان ملل با موفقیت کامل پاس شدند!")
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(run_full_test())
