"""سرویس منطق رول‌ها و پروژه‌های اقتصادی (آپدیت شماره ۹)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    ECON_PROJECT_HEADER_MAX_LEN,
    ECON_PROJECT_YIELD_INTERVAL_HOURS,
    MAX_ROLE_PAGE_LEN,
)
from ..database.models import Country, EconomicProject, User
from ..database.repositories import countries as countries_repo
from ..database.repositories import economic_projects as proj_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import (
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    EconomicProjectStatus,
    ResourceType,
)
from ..utils.numbers import fa_money, fa_number

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_role_page(text: str) -> tuple[bool, str]:
    """اعتبارسنجی طول هر صفحه رول (دقیقاً ۴۰۰۰ کاراکتر و نه ۴۰۹۶)."""
    length = len(text)
    if length > MAX_ROLE_PAGE_LEN:
        return (
            False,
            f"⚠️ <b>خطای سقف کاراکتر:</b>\n"
            f"طول متن ارسالی شما <b>{fa_number(length)}</b> کاراکتر است که از سقف مجاز "
            f"(<b>{fa_number(MAX_ROLE_PAGE_LEN)}</b> کاراکتر) بیشتر است.\n\n"
            f"💡 ۹۶ کاراکتر باقیمانده مخصوص سربرگ رسمی ربات است. لطفاً متن را کمی کوتاه کرده و مجدداً ارسال کنید.",
        )
    return True, ""


def format_resources_dict(resources: dict[str, float]) -> str:
    """فرمت ذخایر به متن خوانای فارسی (همراه با واحد)."""
    if not resources:
        return "بدون ذخایر"
    parts = []
    for r_key, amt in resources.items():
        try:
            rtype = ResourceType(r_key)
            name = RESOURCE_FA.get(rtype, r_key)
            unit = RESOURCE_UNIT_FA.get(rtype, "")
        except Exception:
            name = r_key
            unit = ""
        parts.append(f"{fa_number(amt)} {unit} {name}".strip())
    return "، ".join(parts)


def build_project_header(
    country: Country,
    project: EconomicProject,
    page_num: int,
    user: User | None = None,
) -> str:
    """
    تولید سربرگ فشرده و رسمی (تضمین طول حداکثر ۹۶ کاراکتر).
    به‌گونه‌ای طراحی شده که همراه با متن ۴۰۰۰ کاراکتری، هرگز از سقف ۴۰۹۶ تلگرام رد نشود.
    """
    flag = country.flag or "🏳"
    c_name = country.name_fa[:14]
    title_short = project.title[:20]
    budget_txt = fa_money(project.proposed_budget)
    p_info = f"ص {fa_number(page_num)}/{fa_number(project.total_pages)}"

    line1 = f"🏗 {flag} {c_name} | {title_short}"
    line2 = f"💰 {budget_txt} | 📄 {p_info}"
    sep = "─" * 16

    header_text = f"{line1}\n{line2}\n{sep}\n"
    if len(header_text) > ECON_PROJECT_HEADER_MAX_LEN:
        header_text = header_text[:ECON_PROJECT_HEADER_MAX_LEN - 1] + "\n"
    return header_text


def render_project_message(
    country: Country,
    project: EconomicProject,
    page_num: int,
    user: User | None = None,
) -> str:
    """رندر کامل پیام رول شامل سربرگ کمتر از ۹۶ کاراکتری + متن صفحه (تا ۴۰۰۰ کاراکتر)."""
    header = build_project_header(country, project, page_num, user)
    body = project.get_page_text(page_num)
    return f"{header}\n{body}"


async def approve_and_launch_project(
    session: AsyncSession,
    project: EconomicProject,
    country: Country,
    admin_user_id: int,
    launch_cash: float,
    launch_resources: dict[str, float],
    yield_cash: float,
    yield_resources: dict[str, float],
) -> dict:
    """
    تأیید رول توسط ادمین:
    اگر کشور در این لحظه بودجه و ذخایر کافی دارد، هزینه کسر و پروژه ACTIVE می‌شود.
    در غیر این صورت، وضعیت APPROVED_AWAITING_LAUNCH می‌شود تا کشور بعداً فعال کند.
    """
    project.reviewed_by = admin_user_id
    project.launch_cost_cash = max(0.0, float(launch_cash))
    project.launch_resources_dict = launch_resources
    project.yield_cash_72h = max(0.0, float(yield_cash))
    project.yield_resources_dict = yield_resources

    # ۱. بررسی نقدینگی کافی
    has_cash = country.budget >= project.launch_cost_cash

    # ۲. بررسی ذخایر کافی
    missing_res: dict[str, float] = {}
    for r_key, amt in launch_resources.items():
        if amt <= 0:
            continue
        has_res = await reserves_repo.has_enough(session, country.id, r_key, amt)
        if not has_res:
            res_obj = await reserves_repo.get_reserve(session, country.id, r_key)
            cur = res_obj.amount if res_obj else 0.0
            missing_res[r_key] = amt - cur

    now = _utcnow()
    if has_cash and not missing_res:
        # کسر نقدینگی
        country.budget -= project.launch_cost_cash
        # کسر ذخایر
        for r_key, amt in launch_resources.items():
            if amt > 0:
                await reserves_repo.add_amount(session, country.id, r_key, -amt)

        project.status = EconomicProjectStatus.ACTIVE.value
        project.last_yield_at = now
        project.next_yield_at = now + timedelta(hours=ECON_PROJECT_YIELD_INTERVAL_HOURS)

        await session.flush()
        return {
            "status": EconomicProjectStatus.ACTIVE.value,
            "launched": True,
            "missing_cash": 0.0,
            "missing_resources": {},
        }
    else:
        # کمبود منابع؛ پروژه در انتظار افتتاح می‌ماند
        project.status = EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value
        missing_cash = max(0.0, project.launch_cost_cash - country.budget)

        await session.flush()
        return {
            "status": EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value,
            "launched": False,
            "missing_cash": missing_cash,
            "missing_resources": missing_res,
        }


async def launch_awaiting_project(
    session: AsyncSession,
    project: EconomicProject,
    country: Country,
) -> dict:
    """افتتاح دستی پروژه تاییدشده توسط بازیکن پس از تأمین بودجه و ذخایر."""
    if project.status != EconomicProjectStatus.APPROVED_AWAITING_LAUNCH.value:
        return {"success": False, "error": "پروژه در وضعیت انتظار افتتاح نیست."}

    # بررسی نقدینگی
    if country.budget < project.launch_cost_cash:
        missing_cash = project.launch_cost_cash - country.budget
        return {
            "success": False,
            "error": f"بودجه کشور کافی نیست (کسری: {fa_money(missing_cash)}).",
        }

    # بررسی ذخایر
    launch_res = project.launch_resources_dict
    missing_res: dict[str, float] = {}
    for r_key, amt in launch_res.items():
        if amt <= 0:
            continue
        has_res = await reserves_repo.has_enough(session, country.id, r_key, amt)
        if not has_res:
            res_obj = await reserves_repo.get_reserve(session, country.id, r_key)
            cur = res_obj.amount if res_obj else 0.0
            missing_res[r_key] = amt - cur

    if missing_res:
        return {
            "success": False,
            "error": f"ذخایر کافی نیست: {format_resources_dict(missing_res)}",
        }

    # کسر هزینه‌ها و فعال‌سازی
    country.budget -= project.launch_cost_cash
    for r_key, amt in launch_res.items():
        if amt > 0:
            await reserves_repo.add_amount(session, country.id, r_key, -amt)

    now = _utcnow()
    project.status = EconomicProjectStatus.ACTIVE.value
    project.last_yield_at = now
    project.next_yield_at = now + timedelta(hours=ECON_PROJECT_YIELD_INTERVAL_HOURS)

    await session.flush()
    return {"success": True}


async def reject_project(
    session: AsyncSession,
    project: EconomicProject,
    admin_user_id: int,
    reason: str,
) -> None:
    """رد پروژه توسط ادمین همراه با ثبت دلیل."""
    project.status = EconomicProjectStatus.REJECTED.value
    project.reviewed_by = admin_user_id
    project.rejection_reason = reason.strip()
    await session.flush()


async def process_project_payout(
    session: AsyncSession,
    project: EconomicProject,
    country: Country,
    now: datetime,
) -> dict:
    """واریز سود ۷۲ ساعته (دلاری و ذخایری) یک پروژه فعال."""
    # واریز سود دلاری
    if project.yield_cash_72h > 0:
        country.budget += project.yield_cash_72h

    # واریز سود ذخایری
    yield_res = project.yield_resources_dict
    for r_key, amt in yield_res.items():
        if amt > 0:
            await reserves_repo.ensure_reserve(session, country.id, r_key)
            await reserves_repo.add_amount(session, country.id, r_key, amt)

    project.last_yield_at = now
    project.next_yield_at = now + timedelta(hours=ECON_PROJECT_YIELD_INTERVAL_HOURS)

    await session.flush()
    return {
        "cash": project.yield_cash_72h,
        "resources": yield_res,
    }
