"""
اسکریپت تحلیلگر جامع دکمه‌ها و کالبک‌های کل ربات (Global Callback & Button Audit).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent

def run_global_audit():
    print("=" * 70)
    print("🔍 اجرای ممیزی سراسری دکمه‌ها و کالبک‌های ربات")
    print("=" * 70)

    # ۱. استخراج الگوهای کالبک از دکمه‌های شیشه‌ای
    # با استفاده از AST روی تمام فایل‌های bot/keyboards/ و bot/handlers/
    kb_files = list((repo_root / "bot" / "keyboards").glob("*.py"))
    handler_files = list((repo_root / "bot" / "handlers").glob("*.py"))

    callbacks_created: list[dict] = []

    for fpath in kb_files + handler_files:
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error parsing {fpath.name}: {e}")
            continue

        for node in ast.walk(tree):
            # بررسی فراخوانی button(...) یا ساخت InlineKeyboardButton(...)
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id

                if func_name in ("button", "InlineKeyboardButton"):
                    cb_data = None
                    for kw in node.keywords:
                        if kw.arg == "callback_data":
                            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                cb_data = kw.value.value
                            elif isinstance(kw.value, ast.JoinedStr):
                                # f-string: استخراج پیشوند قبل از متغیرها
                                parts = []
                                for part in kw.value.values:
                                    if isinstance(part, ast.Constant):
                                        parts.append(str(part.value))
                                    else:
                                        parts.append("{VAR}")
                                cb_data = "".join(parts)

                    if cb_data:
                        callbacks_created.append({
                            "file": fpath.name,
                            "line": node.lineno,
                            "data": cb_data,
                        })

    print(f"📊 مجموعاً {len(callbacks_created)} دکمه/کالبک در کیبوردها و هندلرها شناسایی شد.")

    # ۲. استخراج الگوهای هندلرها
    handlers: list[dict] = []
    edit_text_usages: list[dict] = []

    for fpath in handler_files:
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "callback_query":
                        dec_str = ast.unparse(dec)
                        has_answer = any(
                            isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "answer"
                            for sub in ast.walk(node)
                        )
                        handlers.append({
                            "file": fpath.name,
                            "name": node.name,
                            "line": node.lineno,
                            "dec": dec_str,
                            "has_answer": has_answer,
                        })

            # بررسی استفاده از edit_text
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "edit_text":
                    # چک اینکه آیا روی call.message فراخوانی شده است
                    val = node.func.value
                    if isinstance(val, ast.Attribute) and val.attr == "message":
                        edit_text_usages.append({
                            "file": fpath.name,
                            "line": node.lineno,
                        })

    print(f"📊 مجموعاً {len(handlers)} هندلر CallbackQuery ثبت‌شده پیدا شد.")
    print(f"⚠️ مجموعاً {len(edit_text_usages)} مورد فراخوانی call.message.edit_text پیدا شد.")

    # تطابق دکمه‌ها با هندلرها
    orphans = []
    for cb in callbacks_created:
        raw_data = cb["data"]
        # تبدیل {VAR} به regex
        # پیشوند قبل از اولین متغیر
        prefix = raw_data.split("{VAR}")[0]
        # یا اگر استاتیک است
        is_matched = False
        for h in handlers:
            h_dec = h["dec"]
            if prefix and prefix in h_dec:
                is_matched = True
                break
            # چک startswith
            if "startswith" in h_dec:
                sw_matches = re.findall(r'startswith\([\'"]([^\'"]+)[\'"]\)', h_dec)
                for sw in sw_matches:
                    if prefix.startswith(sw) or sw.startswith(prefix.rstrip(":")):
                        is_matched = True
                        break
            if is_matched:
                break

        if not is_matched:
            # استثناهای شناخته‌شده مثل url یا noop
            if raw_data in ("noop", "sec_noop", "mil_noop") or raw_data.startswith("http"):
                continue
            orphans.append(cb)

    print("\n" + "=" * 50)
    print("🔎 نتایج بررسی دکمه‌های یتیم (احتمال عدم وجود هندلر):")
    print("=" * 50)
    seen = set()
    for o in orphans:
        key = (o["file"], o["data"])
        if key not in seen:
            seen.add(key)
            print(f"❌ {o['file']}:{o['line']} -> {o['data']}")

    print(f"\nتعداد کل موارد مشکوک: {len(seen)}")

    print("\n" + "=" * 50)
    print("🔎 موارد استفاده از call.message.edit_text:")
    print("=" * 50)
    for eu in edit_text_usages:
        print(f"⚠️ {eu['file']}:{eu['line']}")

if __name__ == "__main__":
    run_global_audit()
