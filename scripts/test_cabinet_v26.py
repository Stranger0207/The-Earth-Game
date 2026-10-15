"""تست جامع و یکپارچه مگاآپدیت v2.6 گیم‌مود مقاماتی (کابینه دولت ایالات متحده آمریکا)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys

os.environ["PYTHONUTF8"] = "1"
os.environ["BOT_TOKEN"] = "123456:ABC-test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test"
os.environ["OWNER_IDS"] = "111"
os.environ["ADMIN_IDS"] = "111"

from sqlalchemy import text
from bot.database.base import _COLUMN_MIGRATIONS, async_session_factory, engine, init_db
from bot.database.models import Country, User
from bot.database.models.cabinet import (
    CabinetAgenda,
    CabinetBudgetRequest,
    CabinetCrisis,
    CabinetLeak,
    CabinetMember,
    CabinetOperation,
)
from bot.database.repositories import cabinet as cabinet_repo, users as users_repo
from bot.enums import (
    CabinetBudgetStatus,
    CabinetCrisisStatus,
    CabinetOperationStatus,
    CabinetRole,
)
from bot.services import season_service
from bot.services.cabinet_service import (
    approve_or_reject_budget_request,
    claim_agenda_reward,
    conduct_press_briefing,
    execute_completed_operation,
    generate_new_crisis,
    get_defcon_level,
    get_usa_country,
    issue_executive_order,
    leak_confidential_info,
    lobby_senate,
    perform_doge_audit,
    process_crisis_expiration,
    request_department_budget,
    resolve_crisis_step,
    scan_leak_hunter,
    set_defcon_level,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def run_v26_tests() -> None:
    print("============================================================")
    print("🚀 آغاز تست‌های جامع مگاآپدیت v2.6 گیم‌مود مقاماتی (کابینه آمریکا)")
    print("============================================================")

    # فعال‌سازی کنترل کلیدهای خارجی در SQLite
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
    print("✅ PRAGMA foreign_keys = ON برقرار شد.")

    # ۱. مقداردهی اولیه پایگاه داده و مهاجرت‌ها
    await init_db()
    print("✅ تست ۱: ساخت جداول و اجرای مهاجرت ستون‌های جدید _COLUMN_MIGRATIONS با موفقیت انجام شد.")

    async with async_session_factory() as session:
        # ساخت کشور آمریکا برای تست‌ها
        usa = Country(
            id=1,
            name_en="United States",
            name_fa="ایالات متحده آمریکا",
            flag="🇺🇸",
            region="North America",
            budget=1000000.0,
            public_satisfaction=75.0,
            stability=80.0,
            economic_power=90.0,
            inflation=2.5,
        )
        session.add(usa)
        await session.commit()

        # ۲. ساخت کاربران و تصدی هر ۱۵ سمت کابینه
        roles = list(CabinetRole)
        role_users: dict[str, User] = {}
        for idx, role in enumerate(roles, start=1):
            u = await users_repo.get_or_create_user(
                session,
                telegram_id=1000 + idx,
                username=f"user_{role.value}",
                first_name=f"Official_{role.value}",
            )
            role_users[role.value] = u
            ok = await cabinet_repo.claim_member_role(session, role.value, u.telegram_id)
            assert ok is True, f"Failed to claim {role.value}"

        await session.commit()
        members = await cabinet_repo.list_members(session)
        assert len(members) == 15
        for m in members:
            assert m.political_capital == 50, f"Expected 50 capital, got {m.political_capital}"
            assert m.efficiency_score == 80, f"Expected 80 efficiency, got {m.efficiency_score}"
            assert m.leak_suspicion == 0, f"Expected 0 suspicion, got {m.leak_suspicion}"
            assert m.allocated_budget > 0, f"Expected positive budget for {m.role_key}"

        print("✅ تست ۲: تصدی هر ۱۵ سمت کابینه و تایید مقادیر پیش‌فرض شاخص‌های قدرت v2.6 تایید شد.")

        # ============================================================
        # ۳. تست کامل هر ۵ زنجیره بوروکراتیک (CabinetOperation)
        # ============================================================

        # زنجیره ۱: عملیات و استقرار نظامی (ستاد مشترک -> خزانه‌داری -> دفاع -> سنتکام)
        op1 = await cabinet_repo.create_operation(
            session,
            op_type="military_deployment",
            title="عملیات استقرار ناوگروه در خلیج فارس",
            initiator_role=CabinetRole.JOINT_CHIEFS.value,
            steps=[
                {"step": 1, "role": CabinetRole.JOINT_CHIEFS.value, "title": "طراحی مسیر"},
                {"step": 2, "role": CabinetRole.TREASURY_SECRETARY.value, "title": "تایید بودجه"},
                {"step": 3, "role": CabinetRole.SECRETARY_DEFENSE.value, "title": "مجوز پنتاگون"},
                {"step": 4, "role": CabinetRole.CENTCOM_COMMANDER.value, "title": "فرمان حرکت میدانی"},
            ],
            budget_cost=2500.0,
        )
        await session.commit()

        # امضای گام ۱ توسط ستاد مشترک
        _, comp = await cabinet_repo.sign_operation_step(session, op1.id, CabinetRole.JOINT_CHIEFS.value, 1000 + 14)
        assert comp is False
        assert op1.current_step == 2
        await cabinet_repo.modify_capital(session, CabinetRole.JOINT_CHIEFS.value, 5)

        # امضای گام ۲ توسط خزانه‌داری
        _, comp = await cabinet_repo.sign_operation_step(session, op1.id, CabinetRole.TREASURY_SECRETARY.value, 1000 + 9)
        assert comp is False
        assert op1.current_step == 3

        # امضای گام ۳ توسط وزیر دفاع
        _, comp = await cabinet_repo.sign_operation_step(session, op1.id, CabinetRole.SECRETARY_DEFENSE.value, 1000 + 4)
        assert comp is False
        assert op1.current_step == 4

        # امضای گام ۴ توسط سنتکام
        _, comp = await cabinet_repo.sign_operation_step(session, op1.id, CabinetRole.CENTCOM_COMMANDER.value, 1000 + 5)
        assert comp is True
        assert op1.status == "COMPLETED"

        # اجرای نهایی عملیات
        ok_exec, msg_exec = await execute_completed_operation(session, op1.id)
        assert ok_exec is True
        await session.commit()
        print("✅ تست ۳.۱: زنجیره اول (استقرار نظامی) به طور کامل تا پایان طی و اجرا شد.")

        # زنجیره ۲: معاهدات و تحریم (خارجه -> امنیت ملی -> خزانه‌داری -> رئیس‌جمهور) + تست فریز DOGE و شکستن قفل
        op2 = await cabinet_repo.create_operation(
            session,
            op_type="diplomatic_economic",
            title="بسته تحریم جامع فلزات سنگین",
            initiator_role=CabinetRole.SECRETARY_STATE.value,
            steps=[
                {"step": 1, "role": CabinetRole.SECRETARY_STATE.value, "title": "پیش‌نویس تحریم"},
                {"step": 2, "role": CabinetRole.NATIONAL_SECURITY.value, "title": "پیوست امنیتی"},
                {"step": 3, "role": CabinetRole.TREASURY_SECRETARY.value, "title": "ارزیابی مالی"},
                {"step": 4, "role": CabinetRole.PRESIDENT.value, "title": "توشیح نهایی"},
            ],
            budget_cost=1000.0,
        )
        await session.commit()

        # فریز توسط DOGE
        frozen_op = await cabinet_repo.freeze_operation_doge(session, op2.id, CabinetRole.TECH_EFFICIENCY.value)
        assert frozen_op is not None and frozen_op.status == "DOGE_FROZEN"

        # امضا در حالت فریز باید ناموفق باشد
        _, fail_sign = await cabinet_repo.sign_operation_step(session, op2.id, CabinetRole.SECRETARY_STATE.value, 1000 + 3)
        assert fail_sign is False

        # شکستن قفل توسط رئیس‌جمهور
        unfrozen_op = await cabinet_repo.unfreeze_operation(session, op2.id, CabinetRole.PRESIDENT.value)
        assert unfrozen_op is not None and unfrozen_op.status == "PENDING"

        # تکمیل مراحل ۲ تا ۴
        await cabinet_repo.sign_operation_step(session, op2.id, CabinetRole.SECRETARY_STATE.value, 1000 + 3)
        await cabinet_repo.sign_operation_step(session, op2.id, CabinetRole.NATIONAL_SECURITY.value, 1000 + 15)
        await cabinet_repo.sign_operation_step(session, op2.id, CabinetRole.TREASURY_SECRETARY.value, 1000 + 9)
        _, comp2 = await cabinet_repo.sign_operation_step(session, op2.id, CabinetRole.PRESIDENT.value, 1000 + 1)
        assert comp2 is True
        assert op2.status == "COMPLETED"
        await execute_completed_operation(session, op2.id)
        await session.commit()
        print("✅ تست ۳.۲: زنجیره دوم (دیپلماتیک/اقتصادی) با تست فریز DOGE و شکستن قفل توسط رئیس‌جمهور با موفقیت تکمیل شد.")

        # زنجیره ۳: صنایع دفاعی و هوافضا + تست تعلیق قضایی DOJ و شکستن قفل توسط معاون رئیس‌جمهور
        op3 = await cabinet_repo.create_operation(
            session,
            op_type="aerospace_rd",
            title="پرتاب ماهواره شناسایی نسل پنجم Keyhole",
            initiator_role=CabinetRole.AEROSPACE_DEFENSE.value,
            steps=[
                {"step": 1, "role": CabinetRole.AEROSPACE_DEFENSE.value, "title": "تعریف پروژه"},
                {"step": 2, "role": CabinetRole.TECH_EFFICIENCY.value, "title": "ممیزی DOGE"},
                {"step": 3, "role": CabinetRole.TREASURY_SECRETARY.value, "title": "آزادسازی بودجه"},
                {"step": 4, "role": CabinetRole.AEROSPACE_DEFENSE.value, "title": "کلید پرتاب"},
            ],
            budget_cost=3500.0,
        )
        await session.commit()

        # تعلیق قضایی توسط دادستان کل
        susp_op = await cabinet_repo.suspend_operation_doj(session, op3.id, CabinetRole.ATTORNEY_GENERAL.value)
        assert susp_op is not None and susp_op.status == "DOJ_SUSPENDED"

        # شکستن قفل توسط معاون رئیس‌جمهور
        unfrozen_vp = await cabinet_repo.unfreeze_operation(session, op3.id, CabinetRole.VICE_PRESIDENT.value)
        assert unfrozen_vp is not None and unfrozen_vp.status == "PENDING"

        # تکمیل امضاها
        await cabinet_repo.sign_operation_step(session, op3.id, CabinetRole.AEROSPACE_DEFENSE.value, 1000 + 12)
        await cabinet_repo.sign_operation_step(session, op3.id, CabinetRole.TECH_EFFICIENCY.value, 1000 + 10)
        await cabinet_repo.sign_operation_step(session, op3.id, CabinetRole.TREASURY_SECRETARY.value, 1000 + 9)
        _, comp3 = await cabinet_repo.sign_operation_step(session, op3.id, CabinetRole.AEROSPACE_DEFENSE.value, 1000 + 12)
        assert comp3 is True
        assert op3.status == "COMPLETED"
        await execute_completed_operation(session, op3.id)
        await session.commit()
        print("✅ تست ۳.۳: زنجیره سوم (هوافضا) با تست تعلیق قضایی DOJ و شکستن قفل توسط معاون رئیس‌جمهور تکمیل شد.")

        # زنجیره ۴: عملیات اطلاعاتی و امنیت مشترک (سیا -> امنیت داخلی -> دادستان کل)
        op4 = await cabinet_repo.create_operation(
            session,
            op_type="intel_security",
            title="رهگیری و انهدام شبکه جاسوسی در واشنگتن",
            initiator_role=CabinetRole.CIA_DIRECTOR.value,
            steps=[
                {"step": 1, "role": CabinetRole.CIA_DIRECTOR.value, "title": "گشایش پرونده"},
                {"step": 2, "role": CabinetRole.HOMELAND_SECURITY.value, "title": "پیوست امنیت داخلی"},
                {"step": 3, "role": CabinetRole.ATTORNEY_GENERAL.value, "title": "مجوز قضایی"},
            ],
            budget_cost=1500.0,
        )
        await session.commit()
        await cabinet_repo.sign_operation_step(session, op4.id, CabinetRole.CIA_DIRECTOR.value, 1000 + 6)
        await cabinet_repo.sign_operation_step(session, op4.id, CabinetRole.HOMELAND_SECURITY.value, 1000 + 7)
        _, comp4 = await cabinet_repo.sign_operation_step(session, op4.id, CabinetRole.ATTORNEY_GENERAL.value, 1000 + 11)
        assert comp4 is True
        assert op4.status == "COMPLETED"
        await execute_completed_operation(session, op4.id)
        await session.commit()
        print("✅ تست ۳.۴: زنجیره چهارم (اطلاعاتی/امنیتی) به طور کامل تایید و اجرا شد.")

        # زنجیره ۵: لوایح کنگره + تست وتوی رسمی رئیس‌جمهور
        op5_veto = await cabinet_repo.create_operation(
            session,
            op_type="congressional_bill",
            title="لایحه افزایش مالیات بر بخش فناوری",
            initiator_role=CabinetRole.SECRETARY_STATE.value,
            steps=[
                {"step": 1, "role": "any", "title": "ثبت لایحه"},
                {"step": 2, "role": CabinetRole.VICE_PRESIDENT.value, "title": "لابی سنا"},
                {"step": 3, "role": CabinetRole.ATTORNEY_GENERAL.value, "title": "انطباق قانون اساسی"},
                {"step": 4, "role": CabinetRole.PRESIDENT.value, "title": "امضا یا وتو"},
            ],
            budget_cost=5000.0,
        )
        await session.commit()
        veto_res = await cabinet_repo.veto_operation(session, op5_veto.id, CabinetRole.PRESIDENT.value)
        assert veto_res is not None and veto_res.status == "VETOED"

        # لایحه کنگره دیگر که تا آخر تصویب می‌شود
        op5 = await cabinet_repo.create_operation(
            session,
            op_type="congressional_bill",
            title="لایحه بودجه اضطراری زیرساخت‌های فدرال",
            initiator_role=CabinetRole.HEALTH_CRISIS.value,
            steps=[
                {"step": 1, "role": "any", "title": "ثبت لایحه"},
                {"step": 2, "role": CabinetRole.VICE_PRESIDENT.value, "title": "لابی سنا"},
                {"step": 3, "role": CabinetRole.ATTORNEY_GENERAL.value, "title": "انطباق قانون اساسی"},
                {"step": 4, "role": CabinetRole.PRESIDENT.value, "title": "امضا یا وتو"},
            ],
            budget_cost=5000.0,
        )
        await session.commit()
        await cabinet_repo.sign_operation_step(session, op5.id, CabinetRole.HEALTH_CRISIS.value, 1000 + 13)
        await cabinet_repo.sign_operation_step(session, op5.id, CabinetRole.VICE_PRESIDENT.value, 1000 + 2)
        await cabinet_repo.sign_operation_step(session, op5.id, CabinetRole.ATTORNEY_GENERAL.value, 1000 + 11)
        _, comp5 = await cabinet_repo.sign_operation_step(session, op5.id, CabinetRole.PRESIDENT.value, 1000 + 1)
        assert comp5 is True
        assert op5.status == "COMPLETED"
        await execute_completed_operation(session, op5.id)
        await session.commit()
        print("✅ تست ۳.۵: زنجیره پنجم (لوایح کنگره) با تست وتوی رئیس‌جمهور و تصویب کامل تایید شد.")

        # ============================================================
        # ۴. تست کارتابل و درخواست‌های بودجه وزارتخانه‌ها (CabinetBudgetRequest)
        # ============================================================

        # درخواست اول: تایید کامل
        ok_b1, _ = await request_department_budget(session, CabinetRole.SECRETARY_STATE.value, 4000.0, "توسعه سفارتخانه‌ها")
        assert ok_b1 is True
        reqs, _ = await cabinet_repo.list_budget_requests(session, role_key=CabinetRole.SECRETARY_STATE.value)
        assert len(reqs) == 1
        req1 = reqs[0]
        ok_ap1, _ = await approve_or_reject_budget_request(session, req1.id, "approve")
        assert ok_ap1 is True
        assert req1.status == CabinetBudgetStatus.APPROVED.value

        # درخواست دوم: تایید تعدیل‌شده (۵۰٪)
        ok_b2, _ = await request_department_budget(session, CabinetRole.HEALTH_CRISIS.value, 3000.0, "خرید تجهیزات FEMA")
        assert ok_b2 is True
        reqs_h, _ = await cabinet_repo.list_budget_requests(session, role_key=CabinetRole.HEALTH_CRISIS.value)
        req2 = reqs_h[0]
        ok_ap2, _ = await approve_or_reject_budget_request(session, req2.id, "half")
        assert ok_ap2 is True
        assert req2.status == CabinetBudgetStatus.ADJUSTED.value
        assert req2.amount == 1500.0

        # درخواست سوم: رد درخواست
        ok_b3, _ = await request_department_budget(session, CabinetRole.CENTCOM_COMMANDER.value, 10000.0, "تسلیحات سنگین")
        reqs_c, _ = await cabinet_repo.list_budget_requests(session, role_key=CabinetRole.CENTCOM_COMMANDER.value)
        req3 = reqs_c[0]
        ok_ap3, _ = await approve_or_reject_budget_request(session, req3.id, "reject")
        assert ok_ap3 is True
        assert req3.status == CabinetBudgetStatus.REJECTED.value

        await session.commit()
        print("✅ تست ۴: کارتابل تخصیص بودجه (تایید کامل، نصف کردن و رد درخواست) با موفقیت بررسی شد.")

        # ============================================================
        # ۵. تست موتور بحران‌های فدرال (CabinetCrisis)
        # ============================================================

        # تولید بحران جدید
        crisis1 = await generate_new_crisis(session)
        assert crisis1 is not None
        assert crisis1.status == "ACTIVE"
        assert len(json.loads(crisis1.options_json)) == 3

        # حل بحران دوامضایی
        ok_s1, _ = await resolve_crisis_step(session, crisis1.id, crisis1.primary_role, 0)
        assert ok_s1 is True
        assert crisis1.status == "ACTIVE"  # هنوز مسئول دوم تایید نکرده

        ok_s2, _ = await resolve_crisis_step(session, crisis1.id, crisis1.secondary_role, 0)
        assert ok_s2 is True
        assert crisis1.status == "RESOLVED"  # اکنون حل شد

        # بحران منقضی‌شده و اعمال جریمه‌ها
        crisis_exp = await cabinet_repo.create_crisis(
            session,
            title="بحران تستی منقضی‌شده",
            description="بحرانی که وقت آن به پایان رسیده است.",
            category="سایبری",
            primary_role=CabinetRole.SECRETARY_DEFENSE.value,
            secondary_role=CabinetRole.TECH_EFFICIENCY.value,
            severity=3,
            options=[{"title": "گزینه", "cost_val": 10}],
            expires_at=_utcnow() - timedelta(minutes=5),
        )
        await session.commit()

        failed_ids = await process_crisis_expiration(session, bot=None)
        assert crisis_exp.id in failed_ids
        assert crisis_exp.status == "FAILED"

        # بررسی کسر سرمایه سیاسی و امتیاز کارآمدی مسئولین
        def_m = await cabinet_repo.get_member_by_role(session, CabinetRole.SECRETARY_DEFENSE.value)
        assert def_m.efficiency_score < 80

        await session.commit()
        print("✅ تست ۵: موتور بحران (حل دوامضایی بحران و پیامدهای انقضای زمان FAILED) با موفقیت تایید شد.")

        # ============================================================
        # ۶. تست افشاگری رسانه‌ای (CabinetLeak) و اسکن Leak Hunter
        # ============================================================

        # مدیر سیا علیه وزیر خزانه‌داری افشاگری می‌کند
        treas_before = await cabinet_repo.get_member_by_role(session, CabinetRole.TREASURY_SECRETARY.value)
        t_cap_before = treas_before.political_capital

        ok_leak, _ = await leak_confidential_info(
            session,
            leaker_role=CabinetRole.CIA_DIRECTOR.value,
            target_role=CabinetRole.TREASURY_SECRETARY.value,
            headline="رسوایی هدررفت میلیاردها دلار در خزانه‌داری",
            content="اسناد فاش‌شده نشان می‌دهد وزیر خزانه‌داری در تخصیص بودجه اعمال سلیقه کرده است.",
        )
        assert ok_leak is True
        await session.commit()

        # بررسی اثر: سرمایه خزانه‌داری کسر شد، مظنونیت سیا بالا رفت
        treas_after = await cabinet_repo.get_member_by_role(session, CabinetRole.TREASURY_SECRETARY.value)
        cia_member = await cabinet_repo.get_member_by_role(session, CabinetRole.CIA_DIRECTOR.value)
        assert treas_after.political_capital == t_cap_before - 10
        assert cia_member.leak_suspicion == 30

        # اسکن ضدجاسوسی فدرال توسط امنیت داخلی
        ok_scan, scan_rep = await scan_leak_hunter(session)
        assert ok_scan is True
        assert "سیا" in scan_rep or "cia_director" in scan_rep
        # تایید جریمه شدن افشاگر
        cia_after_scan = await cabinet_repo.get_member_by_role(session, CabinetRole.CIA_DIRECTOR.value)
        assert cia_after_scan.leak_suspicion == 0  # ریست پس از بازرسی
        assert cia_after_scan.political_capital < 50

        await session.commit()
        print("✅ تست ۶: سیستم افشاگری رسانه‌ای و ردیابی توسط اسکن ضدجاسوسی Leak Hunter با موفقیت تست شد.")

        # ============================================================
        # ۷. تست اهداف محرمانه (CabinetAgenda)
        # ============================================================

        agenda = await cabinet_repo.create_agenda(
            session,
            role_key=CabinetRole.CENTCOM_COMMANDER.value,
            title="هدف تستی محرمانه",
            description="شرح هدف تستی",
            target_type="sign_op",
            target_value=2,
        )
        await session.commit()

        # پیشرفت و تکمیل
        agenda.current_progress = 2
        agenda.is_completed = True
        await session.commit()

        # دریافت پاداش
        c_cap_before = (await cabinet_repo.get_member_by_role(session, CabinetRole.CENTCOM_COMMANDER.value)).political_capital
        ok_rew, _ = await claim_agenda_reward(session, agenda.id)
        assert ok_rew is True
        c_cap_after = (await cabinet_repo.get_member_by_role(session, CabinetRole.CENTCOM_COMMANDER.value)).political_capital
        assert c_cap_after == c_cap_before + 15

        await session.commit()
        print("✅ تست ۷: ماموریت‌های محرمانه ۲۴ ساعته و دریافت پاداش (+۱۵ سرمایه سیاسی) تایید شد.")

        # ============================================================
        # ۸. تست ابزارهای اختصاصی ۱۵ مقام
        # ============================================================

        # ۱. رئیس‌جمهور: صدور فرمان اجرایی
        pres_m = await cabinet_repo.get_member_by_role(session, CabinetRole.PRESIDENT.value)
        pres_m.political_capital = 50
        ok_eo, _ = await issue_executive_order(session, CabinetRole.PRESIDENT.value, "فرمان فوری تامین سوخت", "تامین سوخت ناوگان پنتاگون")
        assert ok_eo is True
        assert pres_m.political_capital == 25  # کسر ۲۵ واحد سرمایه سیاسی

        # ۲. معاون رئیس‌جمهور: لابی‌گری در سنا
        ok_lobby, _ = await lobby_senate(session, CabinetRole.VICE_PRESIDENT.value, "لایحه اعتبارات دفاعی")
        assert ok_lobby is True

        # ۳. وزیر دفاع: تغییر وضعیت DEFCON
        set_defcon_level(2)
        assert get_defcon_level() == 2
        set_defcon_level(5)

        # ۴. سخنگوی کاخ سفید: کنفرانس مطبوعاتی
        ok_press, _ = await conduct_press_briefing(session, CabinetRole.PRESS_SECRETARY.value, "مواضع دولت در قبال تحولات اخیر")
        assert ok_press is True

        # ۵. DOGE: ممیزی کارآمدی
        audit_res = perform_doge_audit("military")
        assert audit_res["savings"] > 0
        assert audit_res["efficiency_gain"] > 0

        print("✅ تست ۸: عملکرد ابزارهای اختصاصی مقامات با موفقیت راستی‌آزمایی شد.")

        # ============================================================
        # ۹. تست ریست فصل (/endseason) و حفاظت از Foreign Keys
        # ============================================================

        assert len((await cabinet_repo.list_operations(session))[0]) > 0
        assert len((await cabinet_repo.list_crises(session))[0]) > 0
        assert len((await cabinet_repo.list_budget_requests(session))[0]) > 0
        assert len((await cabinet_repo.list_leaks(session))[0]) > 0

        # اجرای ریست فصل
        deleted_counts = await season_service.reset_season(session)
        await session.commit()

        # بررسی پاک شدن کامل تمام جداول مربوط به کابینه
        ops_after = await session.execute(text("SELECT count(*) FROM cabinet_operations;"))
        assert ops_after.scalar() == 0
        crises_after = await session.execute(text("SELECT count(*) FROM cabinet_crises;"))
        assert crises_after.scalar() == 0
        budgets_after = await session.execute(text("SELECT count(*) FROM cabinet_budget_requests;"))
        assert budgets_after.scalar() == 0
        agendas_after = await session.execute(text("SELECT count(*) FROM cabinet_agendas;"))
        assert agendas_after.scalar() == 0
        leaks_after = await session.execute(text("SELECT count(*) FROM cabinet_leaks;"))
        assert leaks_after.scalar() == 0

        # سمت‌های اعضای کابینه نیز باید آزاد شده باشند (user_id = None)
        members_reset = await cabinet_repo.list_members(session)
        for m in members_reset:
            assert m.user_id is None

        print("✅ تست ۹: اجرای reset_season با PRAGMA foreign_keys=ON با موفقیت ۱۰۰٪ و بدون هیچ‌گونه Foreign Key Violation انجام شد.")

    print("============================================================")
    print("🎉 تمامی تست‌های جامع v2.6 با موفقیت ۱۰۰٪ پاس شدند!")
    print("============================================================")


if __name__ == "__main__":
    asyncio.run(run_v26_tests())
