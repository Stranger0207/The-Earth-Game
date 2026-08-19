"""
تست‌های آپدیت v2.1 (بدون نیاز به PostgreSQL/توکن/AI):

۱) قدرت اطلاعاتی کشورها: پوشش کامل، رده‌بندی، شانس جاسوسی، مسدودسازی.
۲) ترور: ضریب رده‌ای فرمانده و شانس رئیس‌جمهور + مسدودسازی سمت سرور.
۳) قفل آپشن‌ها: مدل/repo/گارد + پوشش همه‌ی کلیدها در هندلرها.
۴) غیرفعال‌بودن حمله نظامی و خرابکاری + ارجاع به پشتیبانی.
۵) نامه به تمام کشورها.
۶) انجماد پلیرها (/freeze) و تعلیق خودکار کشورگیر جدید.
۷) احیای رئیس‌جمهور و رفع بحران رهبری.

اجرا:
    python -m scripts.test_update_v21
"""
from __future__ import annotations

import asyncio
import inspect
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.constants import (
    ASSASSINATION_BASE_SUCCESS_PCT,
    DISABLED_OPERATIONS,
    ESPIONAGE_COOLDOWN_HOURS,
    ESPIONAGE_COST_USD,
    FEATURE_CATEGORIES,
    INTEL_BLOCK_GAP,
    INTEL_POWER,
    INTEL_POWER_DEFAULT,
    LOCKABLE_FEATURES,
    OPERATION_DISABLED_TEXT,
    SUPPORT_USERNAME,
)
from bot.database.base import _COLUMN_MIGRATIONS, async_session_factory, init_db
from bot.database.models import BotState, Country, FeatureLock
from bot.database.repositories import feature_locks as locks_repo
from bot.enums import OperationType
from bot.services import assassination_service as assn
from bot.services import espionage_service as spy
from bot.services import intel_power_service as ip

ROOT = Path(__file__).resolve().parent.parent

# ── چک‌های کوچک ─────────────────────────────────────────────
_CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _CHECKS.append((name, bool(ok), detail))


def _mk(name_en: str, name_fa: str, vip: bool = False) -> Country:
    return Country(
        name_en=name_en, name_fa=name_fa, flag="🏳", region="r",
        population=1_000, is_vip=vip, budget=50_000_000_000.0,
    )


def _handlers_source() -> str:
    """سورس همه‌ی هندلرها در یک رشته (برای بررسی پوشش گاردها و مسیرها)."""
    out = ""
    for path in (ROOT / "bot" / "handlers").glob("*.py"):
        out += io.open(path, encoding="utf-8").read()
    return out


# ── ۱) قدرت اطلاعاتی ────────────────────────────────────────
def _test_intel_power() -> None:
    data = json.load(io.open(ROOT / "data" / "countries.json", encoding="utf-8"))
    names = {c["name_en"] for c in data["countries"]}
    missing = sorted(names - set(INTEL_POWER))
    check(
        "همه‌ی کشورهای countries.json قدرت اطلاعاتی دارند",
        not missing,
        f"جامانده: {missing}",
    )
    extra = sorted(set(INTEL_POWER) - names)
    check("کشور اضافی در INTEL_POWER نیست", not extra, f"اضافه: {extra}")

    # رده‌بندی منطقی
    check("آمریکا از ایران قوی‌تر است", ip.intel_power("USA") > ip.intel_power("Iran"))
    check("ایران از یمن قوی‌تر است", ip.intel_power("Iran") > ip.intel_power("Yemen"))
    check("اسرائیل در رده‌ی نخبه است", ip.tier_label("Israel") == "⭐ نخبه")
    check("بریتانیا در رده‌ی نخبه است", ip.tier_label("Britain") == "⭐ نخبه")
    check("ایران در رده‌ی قوی است", ip.tier_label("Iran") == "🔵 قوی")
    check("افغانستان در رده‌ی ضعیف است", ip.tier_label("Afghanistan") == "🔴 ضعیف")
    check(
        "کشور ناشناس مقدار پیش‌فرض می‌گیرد",
        ip.intel_power("Atlantis") == INTEL_POWER_DEFAULT,
    )

    # اختلاف و شانس
    check("اختلاف آمریکا→یمن مثبت است", ip.gap("USA", "Yemen") > 0)
    check("اختلاف یمن→آمریکا منفی است", ip.gap("Yemen", "USA") < 0)

    pairs = [("USA", "Yemen"), ("Israel", "Syria"), ("Iran", "Israel"), ("Yemen", "USA")]
    in_range = all(5.0 <= ip.espionage_chance(a, b) <= 85.0 for a, b in pairs)
    check("شانس جاسوسی همیشه در بازه‌ی ۵ تا ۸۵ است", in_range)
    check(
        "شانس کشور قوی بیشتر از کشور ضعیف است",
        ip.espionage_chance("USA", "Yemen") > ip.espionage_chance("Iran", "Israel"),
    )

    # مسدودسازی
    check("یمن نمی‌تواند آمریکا را جاسوسی کند", ip.is_blocked("Yemen", "USA"))
    check("افغانستان نمی‌تواند چین را جاسوسی کند", ip.is_blocked("Afghanistan", "China"))
    check("آمریکا می‌تواند یمن را جاسوسی کند", not ip.is_blocked("USA", "Yemen"))
    check("ایران می‌تواند اسرائیل را جاسوسی کند", not ip.is_blocked("Iran", "Israel"))
    check(
        "حد مسدودسازی منفی است (کشور ضعیف محدود می‌شود)", INTEL_BLOCK_GAP < 0
    )
    ok, reason = ip.can_spy_on("Yemen", "USA")
    check("پیام مسدودسازی فارسی و توضیحی است", (not ok) and "توان نفوذ" in reason)

    # کیفیت اطلاعات
    low_s, high_s = ip.quality_range("USA", "Yemen")
    low_w, high_w = ip.quality_range("Iran", "Israel")
    check("کیفیت اطلاعات کشور قوی‌تر بالاتر است", low_s > low_w and high_s > high_w)
    check("بازه‌ی کیفیت معتبر است", 0 <= low_s <= high_s <= 100)


# ── ۲) ترور ──────────────────────────────────────────────────
def _test_assassination() -> None:
    usa, yem, irn, isr = _mk("USA", "آمریکا"), _mk("Yemen", "یمن"), _mk("Iran", "ایران"), _mk("Israel", "اسرائیل")

    f_strong = ip.assassination_tier_factor("USA", "Yemen")
    f_weak = ip.assassination_tier_factor("Yemen", "USA")
    check("ضریب رده‌ای در بازه‌ی مجاز است", 0.55 <= f_weak <= f_strong <= 1.35)
    check("ضریب کشور قوی بیشتر از ضعیف است", f_strong > f_weak)
    check("ضریب رده‌ی برابر ۱ است", abs(ip.assassination_tier_factor("Iran", "Iran") - 1.0) < 0.01)

    c_strong = assn.commander_chance(usa, yem, 70.0)
    c_weak = assn.commander_chance(irn, isr, 70.0)
    check("ترور فرمانده برای کشور قوی آسان‌تر است", c_strong > c_weak)
    check("شانس ترور فرمانده هرگز از ۹۰٪ بیشتر نمی‌شود",
          assn.commander_chance(usa, yem, 100.0, 500.0) <= 90.0)
    check("کیفیت اطلاعات بالاتر شانس بیشتری می‌دهد",
          assn.commander_chance(usa, yem, 90.0) > assn.commander_chance(usa, yem, 40.0))
    check("شانس پایه‌ی ترور سخت‌تر شد (۲۸٪)", ASSASSINATION_BASE_SUCCESS_PCT == 28.0)

    p_strong = assn.president_chance(usa, yem)
    p_weak = assn.president_chance(irn, isr)
    check("ترور رئیس‌جمهور برای کشور قوی شانس بیشتری دارد", p_strong > p_weak)
    check("شانس ترور رئیس‌جمهور پایین می‌ماند", p_strong < 20.0)

    # مسدودسازی سمت سرور
    blocked = False
    try:
        assn.assert_target_reachable(yem, usa)
    except assn.AssassinationError:
        blocked = True
    check("ترور از کشور ضعیف علیه قدرت‌ها مسدود است", blocked)

    spy_blocked = False
    try:
        spy.assert_target_reachable(yem, usa)
    except spy.EspionageError:
        spy_blocked = True
    check("جاسوسی از کشور ضعیف علیه قدرت‌ها مسدود است", spy_blocked)

    # سخت‌سازی جاسوسی
    check("هزینه‌ی جاسوسی افزایش یافت", ESPIONAGE_COST_USD >= 1_200_000_000.0)
    check("کول‌داون جاسوسی افزایش یافت", ESPIONAGE_COOLDOWN_HOURS >= 8)

    # سرویس در تابع اجرا هم اعتبارسنجی می‌کند (نه فقط هندلر)
    src = inspect.getsource(spy.run_espionage)
    check("run_espionage توان نفوذ را چک می‌کند", "assert_target_reachable" in src)
    check("run_espionage شانس را از قدرت اطلاعاتی می‌گیرد", "espionage_chance" in src)
    check(
        "چک پیش از کسر بودجه انجام می‌شود",
        src.index("assert_target_reachable") < src.index("spy.budget = max"),
    )
    src_assn = inspect.getsource(assn.resolve_assassination)
    check("resolve_assassination توان نفوذ را چک می‌کند", "assert_target_reachable" in src_assn)

    # فهرست اهداف برای کیبورد
    rows = spy.target_rows(yem, [usa, irn])
    check("target_rows وضعیت مسدودی را برمی‌گرداند", all(r["blocked"] for r in rows))
    check("target_rows رده و شانس دارد", all("tier" in r and "chance" in r for r in rows))


async def _test_espionage_cooldown(session) -> None:
    """
    کول‌داون جاسوسی باید در **هر تلاش** ثبت شود، نه فقط تلاش موفق.

    پیش از v2.1 کول‌داون از ردیف‌های CommanderIntel استنباط می‌شد که فقط در
    موفقیت ساخته می‌شوند؛ با سخت‌شدن جاسوسی (شانس تا ۵٪) بازیکن می‌توانست پس از
    هر شکست فوراً دوباره تلاش کند و سختی بی‌اثر می‌شد.
    """
    from bot.database.models import Commander, CommanderIntel
    from bot.database.repositories import commander_intel as intel_repo
    from bot.enums import CommanderRole

    spy_c = _mk("Iran", "ایران")
    target_c = _mk("Israel", "اسرائیل")
    session.add_all([spy_c, target_c])
    await session.flush()

    commander = Commander(
        country_id=target_c.id, name="آزمون", rank_title="سرلشکر",
        role=CommanderRole.AIR.value, bonus_pct=10.0, is_alive=True,
    )
    session.add(commander)
    await session.flush()

    # پیش از هر تلاش، جاسوسی مجاز است
    allowed = True
    try:
        await spy.assert_can_spy(session, spy_c)
    except spy.EspionageError:
        allowed = False
    check("پیش از تلاش، جاسوسی مجاز است", allowed)

    # seed=7 روی ایران→اسرائیل شکست می‌خورد (شانس ~۲۶٪)
    result = await spy.run_espionage(session, spy_c, target_c, commander, seed=7)
    await session.flush()
    check("تلاش آزمایشی ناموفق بود (سناریوی مورد نظر)", not result["success"])
    check(
        "تلاش ناموفق اطلاعاتی نمی‌سازد",
        await intel_repo.get_valid_intel(session, spy_c.id, commander.id) is None,
    )

    # نکته‌ی اصلی: با وجود شکست، کول‌داون باید فعال باشد
    blocked = False
    try:
        await spy.assert_can_spy(session, spy_c)
    except spy.EspionageError as err:
        blocked = "بازسازی" in str(err)
    check("کول‌داون پس از تلاش ناموفق هم فعال است", blocked)

    src = inspect.getsource(spy.run_espionage)
    check("کول‌داون در هر تلاش ثبت می‌شود", "cd_repo.touch" in src)


# ── ۳) قفل آپشن‌ها ───────────────────────────────────────────
def _test_lock_catalog() -> None:
    check("فهرست آپشن‌های قابل‌قفل خالی نیست", len(LOCKABLE_FEATURES) >= 25)
    bad_cat = [k for k, (_, cat) in LOCKABLE_FEATURES.items() if cat not in FEATURE_CATEGORIES]
    check("دسته‌ی همه‌ی آپشن‌ها معتبر است", not bad_cat, f"نامعتبر: {bad_cat}")

    src = _handlers_source()
    unguarded = [k for k in LOCKABLE_FEATURES if f'"{k}"' not in src]
    check(
        "هر آپشن قابل‌قفل در هندلری گارد شده است",
        not unguarded,
        f"بدون گارد: {unguarded}",
    )
    check("هلپر گارد در deps ساخته شده است", "async def assert_feature" in
          io.open(ROOT / "bot" / "handlers" / "deps.py", encoding="utf-8").read())
    # مالک از قفل معاف است تا بتواند آزمایش کند
    from bot.handlers.deps import assert_feature
    check("گارد، مالک/مدیر را معاف می‌کند", "is_admin" in inspect.getsource(assert_feature))


async def _test_lock_repo(session) -> None:
    added = await locks_repo.lock(session, "covert.assassination", None)
    check("ثبت قفل سراسری", added == 1)
    check("قفل سراسری برای کشور دلخواه اعمال می‌شود",
          await locks_repo.is_locked(session, "covert.assassination", 1))
    check("قفل سراسری روی کشور دیگر هم هست",
          await locks_repo.is_locked(session, "covert.assassination", 99))
    check("قفل تکراری دوباره ثبت نمی‌شود",
          await locks_repo.lock(session, "covert.assassination", None) == 0)
    check("آپشن دیگر قفل نیست",
          not await locks_repo.is_locked(session, "econ.bank", 1))

    await locks_repo.lock(session, "econ.bank", [3, 5])
    check("قفل تک‌کشوری فقط روی همان کشور است",
          await locks_repo.is_locked(session, "econ.bank", 3)
          and not await locks_repo.is_locked(session, "econ.bank", 4))
    keys = await locks_repo.locked_keys_for_country(session, 3)
    check("کلیدهای قفل یک کشور درست است",
          {"covert.assassination", "econ.bank"} <= keys)

    # ارتقا به سراسری، قفل‌های موردی را جمع می‌کند
    await locks_repo.lock(session, "econ.bank", None)
    rows = await locks_repo.list_locks_for_feature(session, "econ.bank")
    check("ارتقا به قفل سراسری قفل‌های موردی را حذف می‌کند",
          len(rows) == 1 and rows[0].country_id is None)

    removed = await locks_repo.unlock(session, "econ.bank")
    check("رفع قفل کار می‌کند",
          removed == 1 and not await locks_repo.is_locked(session, "econ.bank", 3))

    await locks_repo.unlock_all(session)
    check("رفع همه‌ی قفل‌ها کار می‌کند", not await locks_repo.list_locks(session))

    # ریست فصل باید این جدول را پاک کند (قاعده‌ی v1.11.3)
    season_src = io.open(ROOT / "bot" / "services" / "season_service.py", encoding="utf-8").read()
    check("ریست فصل جدول قفل‌ها را پاک می‌کند", "delete(FeatureLock)" in season_src)
    check("جدول قفل‌ها بدون مهاجرت ستون ساخته می‌شود",
          FeatureLock.__tablename__ == "feature_locks")


# ── ۴) غیرفعال‌بودن حمله و خرابکاری ─────────────────────────
def _test_disabled_operations() -> None:
    for op in (OperationType.GROUND_ASSAULT, OperationType.AIR_STRIKE,
               OperationType.NAVAL_STRIKE, OperationType.SABOTAGE):
        check(f"{op.value} غیرفعال است", op in DISABLED_OPERATIONS)
    for op in (OperationType.ASSASSINATION, OperationType.INTERCEPTION,
               OperationType.PATROL, OperationType.DRILL):
        check(f"{op.value} دست‌نخورده مانده است", op not in DISABLED_OPERATIONS)

    check("نشانی پشتیبانی در پیام هست", SUPPORT_USERNAME in OPERATION_DISABLED_TEXT)
    check("پیام، ارسال رول را توضیح می‌دهد", "رول" in OPERATION_DISABLED_TEXT)

    from bot.keyboards.command_center import operations_menu_kb
    kb = operations_menu_kb()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("دکمه‌ی حمله به مسیر غیرفعال می‌رود", "op:disabled:attack" in datas)
    check("دکمه‌ی خرابکاری به مسیر غیرفعال می‌رود", "op:disabled:sabotage" in datas)
    check("مسیر قدیمی حمله در منو نیست", "op:attack" not in datas)
    check("مسیر قدیمی خرابکاری در منو نیست", "op:new:sabotage" not in datas)
    check("جاسوسی و ترور در منو مانده است", "op:covert" in datas)
    check("گشت و رزمایش در منو مانده‌اند", "op:patrol" in datas and "op:drill" in datas)

    src = _handlers_source()
    check("هندلر مسیر غیرفعال وجود دارد", 'F.data.startswith("op:disabled:")' in src)

    # راه فرار بسته است: op:new:* هم چک می‌شود
    from bot.handlers.operations import cb_start_operation, cb_attack_menu
    s1 = inspect.getsource(cb_start_operation)
    check("ثبت عملیات، انواع غیرفعال را رد می‌کند", "DISABLED_OPERATIONS" in s1)
    s2 = inspect.getsource(cb_attack_menu)
    check("منوی حمله هم پیام پشتیبانی می‌دهد", "OPERATION_DISABLED_TEXT" in s2)


# ── ۵) نامه به تمام کشورها ──────────────────────────────────
def _test_mail_all() -> None:
    from bot.handlers import mail

    kb = mail._mail_menu_kb()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("دکمه‌ی نامه به تمام کشورها هست", "mail:all" in datas)
    check("گزینه‌های قبلی نامه سر جای خود هستند",
          {"mail:single", "mail:multi", "mail:allies", "mail:inbox"} <= set(datas))

    src = inspect.getsource(mail.cb_mail_all)
    check("نامه‌ی سراسری همه‌ی کشورها را می‌گیرد", "list_countries" in src)
    check("نامه‌ی سراسری مستقیم به نوشتن متن می‌رود", "writing_body" in src)
    check("خود کشور از گیرندگان حذف می‌شود", "c.id != country.id" in src)

    body = inspect.getsource(mail.msg_mail_body)
    check("سرخط نامه‌ی سراسری متمایز است", "نامه سراسری" in body)
    check("نامه به متحدان دست‌نخورده مانده", "نامه به متحدان" in body)
    check("برای نامه‌ی سراسری وقفه‌ی نرخ گذاشته شده", "asyncio.sleep" in body)
    check("خطای ارسال یک کشور جریان را نمی‌شکند", "except Exception" in body)
    check("قفل آپشن نامه اعمال می‌شود",
          "dip.letter" in inspect.getsource(mail.cb_mail))


# ── ۶) انجماد پلیرها ────────────────────────────────────────
def _test_freeze() -> None:
    check("ستون انجماد روی BotState هست", hasattr(BotState, "global_freeze"))
    migration_cols = [(t, c) for t, c, _ in _COLUMN_MIGRATIONS]
    check(
        "ستون انجماد در _COLUMN_MIGRATIONS ثبت شده",
        ("bot_state", "global_freeze") in migration_cols,
    )

    from bot.handlers import maintenance
    src = io.open(ROOT / "bot" / "handlers" / "maintenance.py", encoding="utf-8").read()
    check("کامند /freeze ساخته شده", 'Command("freeze")' in src)
    check("انجماد سراسری هندلر دارد", 'F.data == "frz:freeze_all"' in src)
    check("رفع انجماد سراسری هندلر دارد", 'F.data == "frz:unfreeze_all"' in src)
    check("تعلیق تکی هندلر دارد", 'F.data.startswith("frz_sp:")' in src)
    check("رفع تعلیق تکی هندلر دارد", 'F.data.startswith("frz_un:")' in src)
    check("فهرست معلق‌ها هندلر دارد", 'F.data == "frz:list"' in src)

    freeze_src = inspect.getsource(maintenance.cb_freeze_all)
    check("انجماد، پلیرها را معلق می‌کند", "is_suspended = True" in freeze_src)
    check("انجماد وضعیت سراسری را ذخیره می‌کند", "global_freeze=True" in freeze_src)
    check("انجماد به پلیرها اطلاع می‌دهد", "send_message" in freeze_src)

    owners_src = inspect.getsource(maintenance._owner_users)
    check("مالک/مدیر بازی از انجماد معاف است", "is_admin" in owners_src)

    # تعلیق خودکار کشورگیر جدید در حالت انجماد
    from bot.handlers.admin import cb_approve
    approve_src = inspect.getsource(cb_approve)
    check("تأیید کشورگیری وضعیت انجماد را می‌خواند", "global_freeze" in approve_src)
    check("کشورگیر جدید در حالت انجماد معلق می‌شود", "set_suspended" in approve_src)
    check("به کشورگیرِ معلق پنل داده نمی‌شود", "معلق" in approve_src)

    # کاربر بدون کشور باید بتواند /claim بزند → میدلور فقط معلق‌ها را می‌بندد
    mw = io.open(ROOT / "bot" / "middlewares" / "user.py", encoding="utf-8").read()
    check("میدلور کاربر معلق را مسدود می‌کند", "is_suspended" in mw)


# ── ۷) احیای رئیس‌جمهور ─────────────────────────────────────
async def _test_president_revive(session) -> None:
    from bot.handlers import god_operations as god_ops
    from bot.services import operation_service as op_service

    src = io.open(ROOT / "bot" / "handlers" / "god_operations.py", encoding="utf-8").read()
    check("پنل بحران رهبری هندلر دارد", 'F.data == "god:ops_crisis"' in src)
    check("دکمه‌ی احیای رئیس‌جمهور هندلر دارد", 'F.data.startswith("god_pres_revive:")' in src)
    check("دکمه‌ی بحران رهبری در منوی عملیات هست", "god:ops_crisis" in
          inspect.getsource(god_ops._ops_menu_kb))

    revive_src = inspect.getsource(god_ops.cb_pres_revive)
    check("احیا، بحران رهبری را صفر می‌کند", "leadership_crisis_until = None" in revive_src)
    check("احیا در گروه لاگ ثبت می‌شود", "send_log" in revive_src)
    check("به مالک کشور اطلاع داده می‌شود", "owner_user_id" in revive_src)

    # اثر واقعی: کشور در بحران نمی‌تواند عملیات ثبت کند و بعد از احیا می‌تواند
    country = _mk("Testland", "تستستان")
    session.add(country)
    await session.flush()

    country.leadership_crisis_until = datetime.now(timezone.utc) + timedelta(hours=3)
    blocked = False
    try:
        await op_service.assert_can_operate(session, country)
    except op_service.OperationError:
        blocked = True
    check("کشور در بحران رهبری نمی‌تواند عملیات ثبت کند", blocked)
    check("محاسبه‌ی زمان باقی‌مانده درست است",
          god_ops._crisis_remaining_min(country) > 0)

    country.leadership_crisis_until = None
    released = True
    try:
        await op_service.assert_can_operate(session, country)
    except op_service.OperationError:
        released = False
    check("پس از احیا، عملیات مجاز می‌شود", released)
    check("پس از احیا زمان باقی‌مانده صفر است",
          god_ops._crisis_remaining_min(country) == 0)


# ── ۸) مسیر کال‌بک‌ها و ثبت روترها ──────────────────────────
def _test_wiring() -> None:
    from bot.handlers import register_all_routers
    from bot.handlers.godmode import _home_kb

    datas = [b.callback_data for row in _home_kb().inline_keyboard for b in row]
    check("دکمه‌ی قفل آپشن در پنل /god هست", "god:locks" in datas)

    src = io.open(ROOT / "bot" / "handlers" / "__init__.py", encoding="utf-8").read()
    check("روتر قفل آپشن ثبت شده", "god_locks.router" in src)

    locks_src = io.open(ROOT / "bot" / "handlers" / "god_locks.py", encoding="utf-8").read()
    check("پنل قفل، ورودی god:locks دارد", 'F.data == "god:locks"' in locks_src)
    check("قفل سراسری در پنل هست", 'F.data.startswith("godlk_all:")' in locks_src)
    check("قفل چندکشوری در پنل هست", 'F.data.startswith("godlk_pick:")' in locks_src)
    check("رفع قفل در پنل هست", 'F.data.startswith("godlk_un:")' in locks_src)
    check("قفل‌ها در گروه لاگ ثبت می‌شوند", "send_log" in locks_src)
    check("به کشورهای درگیر اطلاع داده می‌شود", "_notify_countries" in locks_src)
    check("رفع همه‌ی قفل‌ها تأیید دومرحله‌ای دارد",
          "godlk:unlock_all_ok" in locks_src and "مطمئنید" in locks_src)

    # کیبورد اهداف اطلاعاتی
    from bot.keyboards.covert import intel_targets_kb
    usa, yem = _mk("USA", "آمریکا"), _mk("Yemen", "یمن")
    usa.id, yem.id = 1, 2
    rows = spy.target_rows(yem, [usa])
    kb = intel_targets_kb(rows, prefix="spy_country", back_data="op:covert")
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("کشور مسدود مسیر جداگانه دارد", any("spy_country_blocked:" in d for d in datas))
    check("هندلر کشور مسدود وجود دارد",
          'F.data.startswith("spy_country_blocked:")' in _handlers_source())
    check("هندلر کشور مسدود ترور وجود دارد",
          'F.data.startswith("assn_country_blocked:")' in _handlers_source())


async def main() -> None:
    await init_db()

    _test_intel_power()
    _test_assassination()
    _test_lock_catalog()
    _test_disabled_operations()
    _test_mail_all()
    _test_freeze()
    _test_wiring()

    async with async_session_factory() as s:
        await _test_lock_repo(s)
        await _test_president_revive(s)
        await _test_espionage_cooldown(s)
        await s.rollback()

    failed = [c for c in _CHECKS if not c[1]]
    for name, ok, detail in _CHECKS:
        mark = "✅" if ok else "❌"
        print(f"{mark} {name}" + (f" — {detail}" if detail else ""))
    print(f"\n{len(_CHECKS) - len(failed)}/{len(_CHECKS)} بررسی موفق بود")
    if failed:
        print("ناموفق:", [c[0] for c in failed])
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
