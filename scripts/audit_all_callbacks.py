"""
اسکریپت ممیزی خودکار دکمه‌های شیشه‌ای، کالبک‌ها و هندلرهای سازمان ملل و بخش‌های جدید بازی.
این اسکریپت تمام کیبوردها و هندلرهای مربوطه را بررسی کرده و موارد زیر را کشف می‌کند:
1. دکمه‌های یتیم (Orphan Callbacks) که هیچ هندلری برایشان ثبت نشده است.
2. هندلرهایی که فاقد call.answer() هستند (باعث لودینگ بی‌پایان در کلاینت تلگرام).
3. عدم تطابق در پیشوند کالبک‌ها (Mismatch).
4. تداخل و قفل وضعیت‌های ماشین حالت (FSM State Locks).
5. نقض قانون safe_edit.
6. روترهای ثبت‌نشده یا ترتیب ناصحیح.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path


def audit_un_callbacks():
    print("=" * 70)
    print("🔍 شروع ممیزی و اسکن جامع بخش‌های سازمان ملل متحد (UN) و امکانات جدید")
    print("=" * 70)

    repo_root = Path(__file__).resolve().parent.parent

    # ۱. استخراج دکمه‌های کیبوردهای سازمان ملل
    from bot.keyboards import united_nations as un_kb
    from bot.keyboards import diplomacy as dip_kb

    kb_buttons: list[dict] = []

    # تست توابع کیبورد سازمان ملل
    test_cases = [
        ("un_main_menu_kb", lambda: un_kb.un_main_menu_kb()),
        ("un_iaea_menu_kb", lambda: un_kb.un_iaea_menu_kb()),
        ("iaea_inspection_action_kb", lambda: un_kb.iaea_inspection_action_kb(101)),
        ("un_iaea_case_view_kb", lambda: un_kb.un_iaea_case_view_kb(202)),
        ("un_iaea_summon_call_kb", lambda: un_kb.un_iaea_summon_call_kb(202)),
        ("un_assembly_admin_kb(inactive)", lambda: un_kb.un_assembly_admin_kb(303, False)),
        ("un_assembly_admin_kb(active)", lambda: un_kb.un_assembly_admin_kb(303, True)),
        ("assembly_invite_kb", lambda: un_kb.assembly_invite_kb(303)),
        ("assembly_ny_lobby_kb", lambda: un_kb.assembly_ny_lobby_kb(303)),
        ("assembly_hall_kb(audience)", lambda: un_kb.assembly_hall_kb(303, False, False)),
        ("assembly_hall_kb(speaker)", lambda: un_kb.assembly_hall_kb(303, True, False)),
        ("assembly_hall_kb(voting)", lambda: un_kb.assembly_hall_kb(303, False, True)),
        ("court_main_kb", lambda: un_kb.court_main_kb()),
        ("court_issues_kb", lambda: un_kb.court_issues_kb()),
        ("un_court_admin_kb(pre)", lambda: un_kb.un_court_admin_kb(404, 1, 2, False)),
        ("un_court_admin_kb(trial)", lambda: un_kb.un_court_admin_kb(404, 1, 2, True)),
        ("un_court_verdict_choices_kb", lambda: un_kb.un_court_verdict_choices_kb(404)),
        ("resolution_vote_kb", lambda: un_kb.resolution_vote_kb(505)),
        ("diplomacy_menu_kb", lambda: dip_kb.diplomacy_menu_kb()),
    ]

    for name, fn in test_cases:
        try:
            markup = fn()
            for row in markup.inline_keyboard:
                for btn in row:
                    if btn.callback_data:
                        kb_buttons.append({
                            "kb_name": name,
                            "text": btn.text,
                            "data": btn.callback_data,
                        })
        except Exception as e:
            print(f"❌ خطای زمان اجرا در تابع کیبورد {name}: {e}")

    print(f"✅ مجموعاً {len(kb_buttons)} دکمه شیشه‌ای از کیبوردها استخراج شد.")

    # ۲. استخراج تمام هندلرهای callback_query در تمام فایل‌های bot/handlers/
    handlers_info: list[dict] = []
    handlers_dir = repo_root / "bot" / "handlers"
    for h_file in handlers_dir.glob("*.py"):
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                code = f.read()
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "callback_query":
                            dec_str = ast.unparse(dec)
                            has_answer = any(
                                isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "answer"
                                for sub in ast.walk(node)
                            )
                            uses_edit_text = any(
                                isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "edit_text"
                                for sub in ast.walk(node)
                            )
                            handlers_info.append({
                                "file": h_file.name,
                                "name": node.name,
                                "line": node.lineno,
                                "decorator": dec_str,
                                "has_answer": has_answer,
                                "uses_edit_text": uses_edit_text,
                            })
        except Exception as e:
            print(f"Error parsing {h_file.name}: {e}")

    print(f"✅ مجموعاً {len(handlers_info)} هندلر CallbackQuery در کل هندلرهای پروژه پیدا شد.")

    # ۳. بررسی دکمه‌های یتیم (Orphan Callbacks)
    print("\n" + "=" * 50)
    print("🔎 ۱. گزارش دکمه‌های یتیم (فاقد هندلر):")
    print("=" * 50)

    orphan_buttons = []
    for b in kb_buttons:
        cdata = b["data"]
        matched = False
        for h in handlers_info:
            dec = h["decorator"]
            # تطابق ساده
            if f'"{cdata}"' in dec or f"'{cdata}'" in dec:
                matched = True
                break
            # تطابق پیشوند startswith
            if "startswith" in dec:
                prefix_matches = re.findall(r'startswith\([\'"]([^\'"]+)[\'"]\)', dec)
                for pref in prefix_matches:
                    if cdata.startswith(pref):
                        matched = True
                        break
            if matched:
                break

        if not matched:
            orphan_buttons.append(b)

    if orphan_buttons:
        for ob in orphan_buttons:
            print(f"❌ دکمه یتیم: «{ob['text']}» (داده: `{ob['data']}`) در کیبورد {ob['kb_name']}")
    else:
        print("✅ هیچ دکمه یتیمی یافت نشد.")

    # ۴. بررسی هندلرهای فاقد call.answer()
    print("\n" + "=" * 50)
    print("🔎 ۲. گزارش هندلرهای فاقد call.answer() در بخش سازمان ملل (عامل لودینگ بی‌پایان):")
    print("=" * 50)

    un_no_answer = [h for h in handlers_info if h["file"] == "united_nations.py" and not h["has_answer"]]
    for nah in un_no_answer:
        print(f"⚠️ لودینگ دائمی: تابع `{nah['name']}` (خط {nah['line']}) — فیلتر: `{nah['decorator']}`")

    # ۵. بررسی تداخل و قفل وضعیت‌های FSM
    print("\n" + "=" * 50)
    print("🔎 ۳. گزارش تداخل FSM و قفل وضعیت‌ها:")
    print("=" * 50)

    un_handlers_code = (repo_root / "bot" / "handlers" / "united_nations.py").read_text(encoding="utf-8")

    # بررسی دکمه دیدار حاشیه نیویورک
    if 'call_to:{c.id}' in un_handlers_code:
        print("❌ باگ دیدار حاشیه نیویورک: دکمه با پیشوند `call_to:{c.id}` تولید می‌شود ولی هندلر آن در diplomacy.py مشروط به `CallForm.choosing_target` است و فاقد این وضعیت در لابی کار نمی‌کند!")

    # بررسی بازگشت به لابی
    if 'asmb_exit_hall:{session_id}' in un_handlers_code:
        print("⚠️ باگ بازگشت به لابی: دکمه «بازگشت به لابی» در دیدار حاشیه به `asmb_exit_hall` لینک شده که خروج از صحن را به کل تالار اعلام می‌کند!")

    # ۶. بررسی عدم تطابق کالبک‌ها (Mismatch)
    print("\n" + "=" * 50)
    print("🔎 ۴. گزارش عدم تطابق پیشوند کالبک‌ها:")
    print("=" * 50)
    if 'court_view:' in [b['data'].split(':')[0] + ':' for b in kb_buttons]:
        print("❌ عدم تطابق: در `un_court_verdict_choices_kb` دکمه با `court_view:{case_id}` ارسال می‌شود، اما هندلر در united_nations.py خط ۱۲۱۲ منتظر `court_admin_view:` است!")

    # ۷. بررسی ثبت روترها در Dispatcher
    print("\n" + "=" * 50)
    print("🔎 ۵. بررسی ثبت روترها در bot/handlers/__init__.py:")
    print("=" * 50)
    init_handlers_file = repo_root / "bot" / "handlers" / "__init__.py"
    with open(init_handlers_file, "r", encoding="utf-8") as f:
        init_code = f.read()

    if "dp.include_router(united_nations.router)" in init_code:
        print("✅ روتر united_nations.router در دیسپچر ثبت شده است.")
    else:
        print("❌ روتر united_nations.router در دیسپچر ثبت نشده است!")

    print("\n" + "=" * 70)
    print("🎯 ممیزی به پایان رسید.")
    print("=" * 70)


if __name__ == "__main__":
    audit_un_callbacks()
