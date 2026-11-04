"""
سرویس برنامه‌ی توسعه‌ی هسته‌ای (v1.10.4) — فقط کشورهای VIP.

منطق مستقل از تلگرام: تحقیقات، ساخت تأسیسات، تولید سانتریفیوژ، غنی‌سازی (مدل SWU)،
مونتاژ کلاهک، آزمایش هسته‌ای، شاخص افشا و بازدارندگی.
پردازش‌های زمان‌دار در scheduler/jobs.py صدا زده می‌شوند.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    CENTRIFUGE_BATCH_ALUMINUM,
    CENTRIFUGE_BATCH_COST_USD,
    CENTRIFUGE_BATCH_HOURS,
    CENTRIFUGE_BATCH_SIZE,
    CENTRIFUGE_BATCH_STEEL,
    CENTRIFUGE_SWU_PER_UNIT_PER_24H,
    CONVERSION_UF6_PER_24H,
    CONVERSION_YELLOWCAKE_INTAKE_PER_24H,
    ENRICHMENT_TIERS,
    MILL_URANIUM_INTAKE_PER_24H,
    MILL_YELLOWCAKE_PER_24H,
    NUCLEAR_BUILD_LIMIT,
    NUCLEAR_CIVILIAN_COVER_EXPOSURE_CUT,
    NUCLEAR_CIVILIAN_COVER_TIER,
    NUCLEAR_COUNTERINTEL_COST_USD,
    NUCLEAR_COUNTERINTEL_EXPOSURE_DROP,
    NUCLEAR_DAY_HOURS,
    NUCLEAR_DETERRENCE_DEFENSE_PER_WARHEAD,
    NUCLEAR_DETERRENCE_MAX_DEFENSE,
    NUCLEAR_DETERRENCE_POWER_PER_WARHEAD,
    NUCLEAR_EXPOSURE_PER_PHASE,
    NUCLEAR_FACILITIES,
    NUCLEAR_FACILITY_RESOURCES,
    NUCLEAR_TECHS,
    NUCLEAR_TEST_COST_USD,
    NUCLEAR_TEST_DAYS,
    NUCLEAR_TEST_EXPOSURE,
    NUCLEAR_TEST_SATISFACTION_GAIN,
    NUCLEAR_TEST_STABILITY_DROP,
    NUCLEAR_UNDERGROUND_COST_MULT,
    NUCLEAR_UNDERGROUND_EXPOSURE_CUT,
    NUCLEAR_UNDERGROUND_TIME_MULT,
    BUILD_LIMIT_WINDOW_HOURS,
    UF6_KG_PER_KG_LEU,
    WARHEAD_ASSEMBLY_COST_USD,
    WARHEAD_ASSEMBLY_DAYS,
    WARHEAD_HEU_REQUIRED_KG,
    WARHEAD_YIELD_KT_RANGE,
)
from ..database.models import Country
from ..database.models.nuclear import (
    NuclearFacility,
    NuclearProgram,
    NuclearTech,
    NuclearTest,
    NuclearWarhead,
)
from ..database.repositories import nuclear as nuc_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import (
    DeliverySystem,
    NuclearFacilityStatus,
    NuclearFacilityType,
    NuclearPhase,
    NuclearTechType,
    ResourceType,
    WarheadStatus,
)


class NuclearError(Exception):
    """خطای منطقی برنامه‌ی هسته‌ای (پیش‌نیاز ناقص، بودجه ناکافی و ...)."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """تاریخ بدون timezone (مثلاً از SQLite) را UTC-دار می‌کند."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def spec_days_to_hours(days: float) -> float:
    """تبدیل «روزِ اسپک» به ساعت واقعی بازی (مقیاس نیم‌روز)."""
    return days * NUCLEAR_DAY_HOURS


# ============================================================
#  دسترسی و برنامه
# ============================================================


def require_vip(country: Country) -> None:
    """فقط کشورهای VIP به پنل هسته‌ای دسترسی دارند."""
    if not country.is_vip:
        raise NuclearError("فقط کشورهای VIP به برنامه‌ی توسعه‌ی هسته‌ای دسترسی دارند.")


async def ensure_program(session: AsyncSession, country: Country) -> NuclearProgram:
    """برنامه‌ی هسته‌ای کشور را برمی‌گرداند؛ اگر نبود می‌سازد."""
    require_vip(country)
    program = await nuc_repo.get_program(session, country.id)
    if program is None:
        program = await nuc_repo.create_program(session, country.id)
    return program


def _bump_phase(program: NuclearProgram, phase: NuclearPhase) -> None:
    """فاز برنامه را (فقط رو به جلو) ارتقا می‌دهد و کف ریسک افشای آن فاز را اعمال می‌کند.

    ریسک افشای هر فاز طبق اسپک یک «سطح» است (۱۰٪/۲۵٪/۵۰٪/۷۵٪/۱۰۰٪)، نه مقداری انباشتی؛
    بنابراین شاخص افشا حداقل به سطح فاز جاری می‌رسد و اگر از قبل بالاتر بود دست‌نخورده می‌ماند.
    اقدامات جداگانه (ساخت، غنی‌سازی، مونتاژ) روی این کف، افشای انباشتی اضافه می‌کنند.
    """
    if program.phase < phase.value:
        program.phase = phase.value
        floor = NUCLEAR_EXPOSURE_PER_PHASE.get(phase.value, 0.0)
        # پوشش صلح‌آمیز کفِ افشا را هم پایین می‌آورد
        if program.civilian_cover:
            floor *= NUCLEAR_CIVILIAN_COVER_EXPOSURE_CUT
        program.exposure = min(100.0, max(program.exposure, floor))


# ============================================================
#  شاخص افشا
# ============================================================


def add_exposure(program: NuclearProgram, amount: float) -> None:
    """افزایش شاخص افشا با درنظرگرفتن پوشش صلح‌آمیز (سقف ۱۰۰)."""
    if amount <= 0:
        return
    if program.civilian_cover:
        amount *= NUCLEAR_CIVILIAN_COVER_EXPOSURE_CUT
    program.exposure = min(100.0, program.exposure + amount)


async def run_counterintel(session: AsyncSession, country: Country) -> float:
    """
    عملیات ضدجاسوسی: با پرداخت هزینه، شاخص افشا کاهش می‌یابد (هر ۲۴ ساعت یک‌بار).
    خروجی: مقدار کاهش اعمال‌شده.
    """
    program = await ensure_program(session, country)
    now = _utcnow()
    last = _aware(program.last_counterintel_at)
    if last is not None and (now - last) < timedelta(hours=24):
        remain = timedelta(hours=24) - (now - last)
        raise NuclearError(
            f"عملیات ضدجاسوسی هر ۲۴ ساعت یک‌بار ممکن است. باقی‌مانده: {int(remain.total_seconds() // 3600)} ساعت."
        )
    if country.budget < NUCLEAR_COUNTERINTEL_COST_USD:
        raise NuclearError(
            f"بودجه کافی نیست. هزینه‌ی عملیات ضدجاسوسی {NUCLEAR_COUNTERINTEL_COST_USD / 1e9:.0f} میلیارد دلار است."
        )
    country.budget -= NUCLEAR_COUNTERINTEL_COST_USD
    drop = min(program.exposure, NUCLEAR_COUNTERINTEL_EXPOSURE_DROP)
    program.exposure -= drop
    program.last_counterintel_at = now
    await session.flush()
    return drop


# ============================================================
#  تحقیقات و فناوری
# ============================================================


async def research_tech(
    session: AsyncSession, country: Country, tech_type: NuclearTechType
) -> NuclearTech:
    """شروع تحقیق یک فناوری: بررسی پیش‌نیاز زنجیره‌ای + کسر بودجه."""
    program = await ensure_program(session, country)

    existing = await nuc_repo.get_tech(session, country.id, tech_type)
    if existing is not None:
        if existing.is_done:
            raise NuclearError("این فناوری قبلاً تکمیل شده است.")
        raise NuclearError("تحقیق این فناوری در جریان است.")

    name_fa, cost, days, prereq = NUCLEAR_TECHS[tech_type]
    if prereq is not None and not await nuc_repo.has_tech(session, country.id, prereq):
        prereq_fa = NUCLEAR_TECHS[prereq][0]
        raise NuclearError(f"پیش‌نیاز این فناوری تکمیل نشده است: «{prereq_fa}»")

    if country.budget < cost:
        raise NuclearError(f"بودجه کافی نیست. هزینه‌ی تحقیق {cost / 1e9:.0f} میلیارد دلار است.")

    country.budget -= cost
    tech = NuclearTech(
        country_id=country.id,
        tech_type=tech_type.value,
        cost_usd=cost,
        started_at=_utcnow(),
    )
    tech = await nuc_repo.create_tech(session, tech)

    # شروع اولین تحقیق = ورود رسمی به مسیر هسته‌ای
    if program.phase == NuclearPhase.NONE.value:
        _bump_phase(program, NuclearPhase.MINING)

    await session.flush()
    return tech


def tech_done_at(tech: NuclearTech) -> datetime:
    """زمان اتمام تحقیق یک فناوری."""
    tech_type = NuclearTechType(tech.tech_type)
    days = NUCLEAR_TECHS[tech_type][2]
    started = _aware(tech.started_at) or _utcnow()
    return started + timedelta(hours=spec_days_to_hours(days))


# ============================================================
#  تأسیسات
# ============================================================


async def build_nuclear_facility(
    session: AsyncSession,
    country: Country,
    facility_type: NuclearFacilityType,
    location: str,
    underground: bool,
) -> NuclearFacility:
    """
    احداث یک تأسیسات هسته‌ای: بررسی فناوری پیش‌نیاز، سقف تعداد، سقف ساخت ۱۲ساعته،
    بودجه و منابع؛ ساخت زیرزمینی گران‌تر و کندتر است اما افشای کمتری دارد.
    """
    program = await ensure_program(session, country)

    name_fa, cost, days, prereq_tech, max_count = NUCLEAR_FACILITIES[facility_type]

    if not await nuc_repo.has_tech(session, country.id, prereq_tech):
        prereq_fa = NUCLEAR_TECHS[prereq_tech][0]
        raise NuclearError(f"ابتدا فناوری «{prereq_fa}» را تحقیق کنید.")

    count = await nuc_repo.count_facilities_by_type(session, country.id, facility_type)
    if count >= max_count:
        raise NuclearError(f"حداکثر تعداد مجاز «{name_fa}» ({max_count}) ساخته شده است.")

    builds = await nuc_repo.count_builds_since(session, country.id, BUILD_LIMIT_WINDOW_HOURS)
    if builds >= NUCLEAR_BUILD_LIMIT:
        raise NuclearError(
            f"در هر {BUILD_LIMIT_WINDOW_HOURS} ساعت حداکثر {NUCLEAR_BUILD_LIMIT} تأسیسات هسته‌ای می‌توان ساخت."
        )

    # آسیاب کیک زرد فقط برای کشورهایی که اورانیوم قابل‌استخراج دارند
    if facility_type == NuclearFacilityType.MILL:
        reserve = await reserves_repo.get_reserve(session, country.id, ResourceType.URANIUM)
        if reserve is None or not reserve.can_extract:
            raise NuclearError(
                "کشور شما معادن اورانیوم قابل‌استخراج ندارد. "
                "می‌توانید اورانیوم را از بازار جهانی (WTO) خریداری کنید."
            )

    total_cost = cost * (NUCLEAR_UNDERGROUND_COST_MULT if underground else 1.0)
    if country.budget < total_cost:
        raise NuclearError(f"بودجه کافی نیست. هزینه‌ی احداث {total_cost / 1e9:.0f} میلیارد دلار است.")

    # بررسی و کسر منابع ساخت
    needed = NUCLEAR_FACILITY_RESOURCES.get(facility_type, {})
    for rtype, amount in needed.items():
        if not await reserves_repo.has_enough(session, country.id, rtype, amount):
            from ..enums import RESOURCE_FA, RESOURCE_UNIT_FA

            raise NuclearError(
                f"کمبود {RESOURCE_FA[rtype]}! نیاز: {amount:,.0f} {RESOURCE_UNIT_FA[rtype]}"
            )

    country.budget -= total_cost
    for rtype, amount in needed.items():
        await reserves_repo.add_amount(session, country.id, rtype, -amount)

    facility = NuclearFacility(
        country_id=country.id,
        facility_type=facility_type.value,
        name=name_fa,
        location=location,
        status=NuclearFacilityStatus.BUILDING.value,
        is_underground=underground,
        cost_usd=total_cost,
    )
    facility = await nuc_repo.create_facility(session, facility)

    # ارتقای فاز بر اساس نوع تأسیسات
    if facility_type == NuclearFacilityType.MILL:
        _bump_phase(program, NuclearPhase.MINING)
    elif facility_type == NuclearFacilityType.CONVERSION:
        _bump_phase(program, NuclearPhase.CONVERSION)
    elif facility_type in (NuclearFacilityType.ENRICHMENT_HALL, NuclearFacilityType.CENTRIFUGE_PLANT):
        _bump_phase(program, NuclearPhase.ENRICHMENT)
    elif facility_type == NuclearFacilityType.WEAPONS_LAB:
        _bump_phase(program, NuclearPhase.WEAPONIZATION)

    # اثر افشای اقدام ساخت (علاوه بر افشای فاز) — زیرزمینی کمتر دیده می‌شود
    action_exposure = 4.0 * (NUCLEAR_UNDERGROUND_EXPOSURE_CUT if underground else 1.0)
    add_exposure(program, action_exposure)

    await session.flush()
    return facility


def facility_done_at(facility: NuclearFacility) -> datetime:
    """زمان اتمام ساخت یک تأسیسات."""
    ftype = NuclearFacilityType(facility.facility_type)
    days = NUCLEAR_FACILITIES[ftype][2]
    hours = spec_days_to_hours(days)
    if facility.is_underground:
        hours *= NUCLEAR_UNDERGROUND_TIME_MULT
    created = _aware(facility.created_at) or _utcnow()
    return created + timedelta(hours=hours)


# ============================================================
#  سانتریفیوژ (چرخه‌های موازی در سالن‌های غنی‌سازی)
# ============================================================


@dataclass
class CentrifugeBatchPlan:
    """طرح یا تحلیل امکان‌سنجی شروع چرخه‌های تولید سانتریفیوژ."""

    total_halls: int
    free_halls: list[NuclearFacility]
    running_halls: list[NuclearFacility]
    capacity: int
    used_and_queued: int
    free_capacity: int
    max_by_capacity: int
    max_by_budget: int
    max_by_steel: int
    max_by_aluminum: int
    executable_count: int
    limit_reason: str


@dataclass
class CentrifugeBatchResult:
    """نتیجه‌ی اجرای چرخه‌های تولید سانتریفیوژ."""

    done_at: datetime
    started_cycles: int
    total_halls: int
    plan: CentrifugeBatchPlan

    def __iter__(self):
        return iter((self.done_at, self.started_cycles, self.plan))


async def plan_centrifuge_production(
    session: AsyncSession, country: Country
) -> CentrifugeBatchPlan:
    """بررسی امکان‌سنجی و برنامه‌ریزی تولید سانتریفیوژ در سالن‌های غنی‌سازی."""
    program = await ensure_program(session, country)

    halls_seq = await nuc_repo.list_active_facilities(
        session, country.id, NuclearFacilityType.ENRICHMENT_HALL
    )
    halls = sorted(list(halls_seq), key=lambda h: h.id)
    if not halls:
        raise NuclearError("سالن غنی‌سازی فعالی ندارید.")

    capacity = await nuc_repo.enrichment_capacity(session, country.id)

    running_halls = [h for h in halls if h.centrifuge_batch_done_at is not None]
    free_halls = [
        h for h in halls if h.centrifuge_batch_done_at is None and h.integrity_pct > 0
    ]

    legacy_running = 1 if program.centrifuge_batch_done_at is not None else 0
    ongoing_batches = len(running_halls) + legacy_running
    used_and_queued = program.centrifuges + (ongoing_batches * CENTRIFUGE_BATCH_SIZE)
    free_capacity = max(0, capacity - used_and_queued)
    max_by_capacity = free_capacity // CENTRIFUGE_BATCH_SIZE

    max_by_budget = int(country.budget // CENTRIFUGE_BATCH_COST_USD)
    steel_res = await reserves_repo.get_reserve(session, country.id, ResourceType.STEEL)
    steel_amount = steel_res.amount if steel_res else 0.0
    aluminum_res = await reserves_repo.get_reserve(session, country.id, ResourceType.ALUMINUM)
    aluminum_amount = aluminum_res.amount if aluminum_res else 0.0
    max_by_steel = int(steel_amount // CENTRIFUGE_BATCH_STEEL)
    max_by_aluminum = int(aluminum_amount // CENTRIFUGE_BATCH_ALUMINUM)

    executable_count = max(
        0,
        min(
            len(free_halls),
            max_by_capacity,
            max_by_budget,
            max_by_steel,
            max_by_aluminum,
        ),
    )

    limit_reason = ""
    if executable_count < len(free_halls):
        if len(free_halls) == 0:
            limit_reason = "تمام سالن‌های غنی‌سازی در حال حاضر دارای چرخه‌ی فعال هستند."
        elif max_by_capacity < len(free_halls) and max_by_capacity <= executable_count:
            limit_reason = "سقف ظرفیت سالن‌های غنی‌سازی تکمیل است."
        elif max_by_budget < len(free_halls) and max_by_budget <= executable_count:
            limit_reason = "کسری بودجه برای شروع چرخه در تمام سالن‌ها."
        elif max_by_steel < len(free_halls) and max_by_steel <= executable_count:
            limit_reason = "کمبود ذخایر فولاد برای شروع چرخه در تمام سالن‌ها."
        elif max_by_aluminum < len(free_halls) and max_by_aluminum <= executable_count:
            limit_reason = "کمبود ذخایر آلومینیوم برای شروع چرخه در تمام سالن‌ها."

    return CentrifugeBatchPlan(
        total_halls=len(halls),
        free_halls=free_halls,
        running_halls=running_halls,
        capacity=capacity,
        used_and_queued=used_and_queued,
        free_capacity=free_capacity,
        max_by_capacity=max_by_capacity,
        max_by_budget=max_by_budget,
        max_by_steel=max_by_steel,
        max_by_aluminum=max_by_aluminum,
        executable_count=executable_count,
        limit_reason=limit_reason,
    )


async def produce_centrifuges(
    session: AsyncSession, country: Country
) -> CentrifugeBatchResult:
    """
    شروع چرخه‌های تولید سانتریفیوژ در سالن‌های غنی‌سازی آزاد (۵۰۰ عدد در ۶ ساعت به ازای هر سالن).
    کسر مستقل بودجه و منابع فولاد و آلومینیوم به ازای هر چرخه.
    """
    program = await ensure_program(session, country)
    plan = await plan_centrifuge_production(session, country)

    if plan.executable_count == 0:
        if not plan.free_halls:
            raise NuclearError("تمام سالن‌های غنی‌سازی در حال حاضر دارای چرخه‌ی فعال هستند.")
        if plan.max_by_capacity <= 0:
            raise NuclearError(
                f"ظرفیت سالن‌های غنی‌سازی تکمیل است (حداکثر {plan.capacity:,} سانتریفیوژ)."
            )
        if plan.max_by_budget <= 0:
            raise NuclearError(
                f"بودجه کافی نیست. هزینه‌ی هر چرخه {CENTRIFUGE_BATCH_COST_USD / 1e6:.1f} میلیون دلار است."
            )
        if plan.max_by_steel <= 0:
            raise NuclearError(f"کمبود فولاد! نیاز هر چرخه: {CENTRIFUGE_BATCH_STEEL:,.0f} تن")
        if plan.max_by_aluminum <= 0:
            raise NuclearError(f"کمبود آلومینیوم! نیاز هر چرخه: {CENTRIFUGE_BATCH_ALUMINUM:,.0f} تن")
        raise NuclearError("امکان شروع چرخه‌ی تولید در هیچ‌یک از سالن‌ها وجود ندارد.")

    started_count = plan.executable_count
    total_cost = started_count * CENTRIFUGE_BATCH_COST_USD
    total_steel = started_count * CENTRIFUGE_BATCH_STEEL
    total_aluminum = started_count * CENTRIFUGE_BATCH_ALUMINUM

    country.budget -= total_cost
    await reserves_repo.add_amount(session, country.id, ResourceType.STEEL, -total_steel)
    await reserves_repo.add_amount(session, country.id, ResourceType.ALUMINUM, -total_aluminum)

    now = _utcnow()
    done_at = now + timedelta(hours=CENTRIFUGE_BATCH_HOURS)

    for hall in plan.free_halls[:started_count]:
        hall.centrifuge_batch_started_at = now
        hall.centrifuge_batch_done_at = done_at

    add_exposure(program, 2.0 * started_count)
    await session.flush()

    return CentrifugeBatchResult(
        done_at=done_at,
        started_cycles=started_count,
        total_halls=len(plan.free_halls),
        plan=plan,
    )


# ============================================================
#  غنی‌سازی (مدل SWU)
# ============================================================


def tier_info(tier_key: str) -> tuple[str, str, float, float, str | None]:
    """اطلاعات یک رده‌ی غنی‌سازی با کلید آن."""
    for tier in ENRICHMENT_TIERS:
        if tier[0] == tier_key:
            return tier
    raise NuclearError("رده‌ی غنی‌سازی نامعتبر است.")


def tier_stock_kg(program: NuclearProgram, tier_key: str) -> float:
    """موجودی فعلی یک رده (کیلوگرم)."""
    return {
        "u235_35": program.leu_35_kg,
        "u235_20": program.leu_20_kg,
        "u235_60": program.heu_60_kg,
        "u235_90": program.heu_90_kg,
    }[tier_key]


def _tier_add(program: NuclearProgram, tier_key: str, kg: float) -> None:
    """افزودن محصول به انبار یک رده."""
    if tier_key == "u235_35":
        program.leu_35_kg += kg
    elif tier_key == "u235_20":
        program.leu_20_kg += kg
    elif tier_key == "u235_60":
        program.heu_60_kg += kg
    elif tier_key == "u235_90":
        program.heu_90_kg += kg


def _tier_take(program: NuclearProgram, tier_key: str, kg: float) -> bool:
    """برداشت از انبار یک رده (False اگر موجودی کافی نباشد)."""
    stock = tier_stock_kg(program, tier_key)
    if stock < kg:
        return False
    _tier_add(program, tier_key, -kg)
    return True


async def start_enrichment(
    session: AsyncSession, country: Country, tier_key: str, centrifuge_count: int
) -> None:
    """
    شروع غنی‌سازی به سمت یک رده: بررسی سالن، سانتریفیوژ، خوراک و رده‌ی پیش‌نیاز.
    خوراک رده‌ی اول UF6 است و رده‌های بالاتر از محصول رده‌ی قبلی تغذیه می‌شوند.
    """
    program = await ensure_program(session, country)
    name_key, name_fa, pct, swu_per_kg, prereq_tier = tier_info(tier_key)

    if program.enrich_tier is not None:
        raise NuclearError("یک فرآیند غنی‌سازی فعال است. ابتدا آن را متوقف کنید.")

    # پوشش صلح‌آمیز: سقف ۲۰٪
    if program.civilian_cover:
        allowed = [t[0] for t in ENRICHMENT_TIERS]
        if allowed.index(tier_key) > allowed.index(NUCLEAR_CIVILIAN_COVER_TIER):
            raise NuclearError(
                "با پوشش صلح‌آمیز فعال، غنی‌سازی بالاتر از ۲۰٪ ممکن نیست. "
                "ابتدا پوشش را در بخش پنهان‌کاری غیرفعال کنید."
            )

    capacity = await nuc_repo.enrichment_capacity(session, country.id)
    if capacity <= 0:
        raise NuclearError("سالن غنی‌سازی فعالی ندارید.")

    if centrifuge_count <= 0 or centrifuge_count > program.centrifuges:
        raise NuclearError(f"تعداد سانتریفیوژ نامعتبر است (موجودی: {program.centrifuges:,}).")
    if centrifuge_count > capacity:
        raise NuclearError(f"ظرفیت سالن‌های شما {capacity:,} سانتریفیوژ است.")

    # بررسی خوراک
    if prereq_tier is None:
        if program.uf6_tons <= 0:
            raise NuclearError("خوراک UF6 ندارید. ابتدا زنجیره‌ی فاز ۱ و ۲ را فعال کنید.")
    else:
        if tier_stock_kg(program, prereq_tier) <= 0:
            prereq_fa = tier_info(prereq_tier)[1]
            raise NuclearError(f"موجودی رده‌ی پیش‌نیاز ({prereq_fa}) صفر است.")

    now = _utcnow()
    program.enrich_tier = tier_key
    program.enrich_centrifuges = centrifuge_count
    program.swu_accumulated = 0.0
    program.enrich_started_at = now
    program.last_enrich_tick_at = now
    _bump_phase(program, NuclearPhase.ENRICHMENT)

    # غنی‌سازی بالای ۲۰٪ افشای سنگین‌تری دارد
    add_exposure(program, 8.0 if pct >= 60 else 4.0)
    await session.flush()


async def stop_enrichment(session: AsyncSession, country: Country) -> None:
    """توقف فرآیند غنی‌سازی فعال."""
    program = await ensure_program(session, country)
    if program.enrich_tier is None:
        raise NuclearError("فرآیند غنی‌سازی فعالی ندارید.")
    program.enrich_tier = None
    program.enrich_centrifuges = 0
    program.swu_accumulated = 0.0
    program.enrich_started_at = None
    program.last_enrich_tick_at = None
    await session.flush()


def enrichment_output_per_24h(program: NuclearProgram) -> float:
    """برآورد تولید ۲۴ساعته‌ی رده‌ی فعال (کیلوگرم محصول)."""
    if program.enrich_tier is None or program.enrich_centrifuges <= 0:
        return 0.0
    swu_per_kg = tier_info(program.enrich_tier)[3]
    swu_24h = program.enrich_centrifuges * CENTRIFUGE_SWU_PER_UNIT_PER_24H
    return swu_24h / swu_per_kg


def enrichment_tick(program: NuclearProgram, now: datetime) -> float:
    """
    یک گام غنی‌سازی: SWU از آخرین تیک انباشته و به محصول تبدیل می‌شود.
    خوراک به نسبت مصرف می‌شود؛ اگر خوراک تمام شود فرآیند متوقف می‌گردد.
    خروجی: کیلوگرم محصول تولیدشده در این گام.
    """
    if program.enrich_tier is None or program.enrich_centrifuges <= 0:
        return 0.0
    last = _aware(program.last_enrich_tick_at) or now
    elapsed_h = max(0.0, (now - last).total_seconds() / 3600.0)
    if elapsed_h <= 0:
        return 0.0

    tier_key, _fa, _pct, swu_per_kg, prereq_tier = tier_info(program.enrich_tier)
    swu_gained = program.enrich_centrifuges * CENTRIFUGE_SWU_PER_UNIT_PER_24H * (elapsed_h / 24.0)
    program.swu_accumulated += swu_gained
    program.last_enrich_tick_at = now

    produced_kg = program.swu_accumulated / swu_per_kg
    if produced_kg <= 0:
        return 0.0

    # محدودیت خوراک: رده‌ی اول از UF6 (هر کیلو محصول = ۹ کیلو UF6)، بقیه ۱:۱ از رده‌ی قبل
    if prereq_tier is None:
        feed_available_kg = (program.uf6_tons * 1000.0) / UF6_KG_PER_KG_LEU
        produced_kg = min(produced_kg, feed_available_kg)
        if produced_kg > 0:
            program.uf6_tons -= (produced_kg * UF6_KG_PER_KG_LEU) / 1000.0
    else:
        feed_available_kg = tier_stock_kg(program, prereq_tier)
        produced_kg = min(produced_kg, feed_available_kg)
        if produced_kg > 0:
            _tier_take(program, prereq_tier, produced_kg)

    if produced_kg > 0:
        _tier_add(program, tier_key, produced_kg)
        program.swu_accumulated -= produced_kg * swu_per_kg

    return produced_kg


# ============================================================
#  کلاهک و آزمایش
# ============================================================


async def assemble_warhead(
    session: AsyncSession, country: Country, name: str
) -> NuclearWarhead:
    """شروع مونتاژ یک کلاهک: نیاز به آزمایشگاه فعال + ۲۵ کیلو HEU + بودجه."""
    program = await ensure_program(session, country)

    labs = await nuc_repo.list_active_facilities(
        session, country.id, NuclearFacilityType.WEAPONS_LAB
    )
    if not labs:
        raise NuclearError("آزمایشگاه تسلیحاتی فعالی ندارید.")

    if not await nuc_repo.has_tech(session, country.id, NuclearTechType.COMP_PHYSICS):
        raise NuclearError("فناوری «فیزیک محاسباتی و طراحی کلاهک» تکمیل نشده است.")

    if program.heu_90_kg < WARHEAD_HEU_REQUIRED_KG:
        raise NuclearError(
            f"اورانیوم ۹۰٪ کافی نیست. نیاز: {WARHEAD_HEU_REQUIRED_KG:.0f} کیلوگرم "
            f"(موجودی: {program.heu_90_kg:.1f} کیلوگرم)."
        )
    if country.budget < WARHEAD_ASSEMBLY_COST_USD:
        raise NuclearError(
            f"بودجه کافی نیست. هزینه‌ی مونتاژ {WARHEAD_ASSEMBLY_COST_USD / 1e9:.0f} میلیارد دلار است."
        )

    country.budget -= WARHEAD_ASSEMBLY_COST_USD
    program.heu_90_kg -= WARHEAD_HEU_REQUIRED_KG

    warhead = NuclearWarhead(
        country_id=country.id,
        name=name,
        status=WarheadStatus.ASSEMBLING.value,
        yield_kt=round(random.uniform(*WARHEAD_YIELD_KT_RANGE), 1),
        heu_used_kg=WARHEAD_HEU_REQUIRED_KG,
    )
    warhead = await nuc_repo.create_warhead(session, warhead)

    _bump_phase(program, NuclearPhase.WEAPONIZATION)
    add_exposure(program, 6.0)
    await session.flush()
    return warhead


def warhead_done_at(warhead: NuclearWarhead) -> datetime:
    """زمان اتمام مونتاژ یک کلاهک."""
    created = _aware(warhead.created_at) or _utcnow()
    return created + timedelta(hours=spec_days_to_hours(WARHEAD_ASSEMBLY_DAYS))


async def mount_warhead(
    session: AsyncSession, country: Country, warhead_id: int, system: DeliverySystem
) -> NuclearWarhead:
    """نصب کلاهک مونتاژشده روی سامانه‌ی حمل (نیاز به فناوری سامانه‌ی حمل)."""
    program = await ensure_program(session, country)

    if not await nuc_repo.has_tech(session, country.id, NuclearTechType.DELIVERY_SYS):
        raise NuclearError("فناوری «سامانه‌ی حمل کلاهک» تکمیل نشده است.")

    warhead = await nuc_repo.get_warhead(session, warhead_id)
    if warhead is None or warhead.country_id != country.id:
        raise NuclearError("کلاهک یافت نشد.")
    if warhead.status != WarheadStatus.ASSEMBLED.value:
        raise NuclearError("فقط کلاهک مونتاژشده‌ی در انبار قابل نصب است.")

    warhead.status = WarheadStatus.MOUNTED.value
    warhead.delivery_system = system.value
    _bump_phase(program, NuclearPhase.DELIVERY)
    add_exposure(program, 5.0)
    await session.flush()
    return warhead


async def schedule_nuclear_test(
    session: AsyncSession, country: Country, warhead_id: int
) -> NuclearTest:
    """
    زمان‌بندی یک آزمایش هسته‌ای: کلاهک مونتاژشده مصرف می‌شود، سایت آزمایش لازم است.
    آزمایش پس از NUCLEAR_TEST_DAYS توسط زمان‌بند اجرا و اعلام عمومی می‌شود.
    """
    program = await ensure_program(session, country)

    sites = await nuc_repo.list_active_facilities(
        session, country.id, NuclearFacilityType.TEST_SITE
    )
    if not sites:
        raise NuclearError("سایت آزمایش هسته‌ای فعالی ندارید.")

    warhead = await nuc_repo.get_warhead(session, warhead_id)
    if warhead is None or warhead.country_id != country.id:
        raise NuclearError("کلاهک یافت نشد.")
    if warhead.status not in (WarheadStatus.ASSEMBLED.value, WarheadStatus.MOUNTED.value):
        raise NuclearError("فقط کلاهک آماده قابل آزمایش است.")

    if country.budget < NUCLEAR_TEST_COST_USD:
        raise NuclearError(
            f"بودجه کافی نیست. هزینه‌ی آزمایش {NUCLEAR_TEST_COST_USD / 1e9:.0f} میلیارد دلار است."
        )

    country.budget -= NUCLEAR_TEST_COST_USD
    warhead.status = WarheadStatus.TESTED.value

    site = sites[0]
    test = NuclearTest(
        country_id=country.id,
        site_name=site.location or site.name,
        yield_kt=warhead.yield_kt,
        warhead_id=warhead.id,
        status="pending",
        scheduled_at=_utcnow() + timedelta(hours=spec_days_to_hours(NUCLEAR_TEST_DAYS)),
    )
    test = await nuc_repo.create_test(session, test)

    _bump_phase(program, NuclearPhase.DELIVERY)
    await session.flush()
    return test


def apply_test_effects(program: NuclearProgram, country: Country) -> None:
    """اثرات اجرای آزمایش: افشای کامل + افتخار ملی + فشار بین‌المللی."""
    program.exposure = NUCLEAR_TEST_EXPOSURE
    program.is_discovered = True
    if program.discovered_at is None:
        program.discovered_at = _utcnow()
    country.public_satisfaction = min(
        100.0, country.public_satisfaction + NUCLEAR_TEST_SATISFACTION_GAIN
    )
    country.stability = max(0.0, country.stability - NUCLEAR_TEST_STABILITY_DROP)


# ============================================================
#  بازدارندگی و خرابکاری (قلاب‌های battle_service)
# ============================================================


async def deterrence_defense_pct(session: AsyncSession, country_id: int) -> float:
    """درصد کاهش شانس موفقیت حمله به این کشور بابت زرادخانه‌ی هسته‌ای."""
    warheads = await nuc_repo.count_ready_warheads(session, country_id)
    return min(
        NUCLEAR_DETERRENCE_MAX_DEFENSE,
        warheads * NUCLEAR_DETERRENCE_DEFENSE_PER_WARHEAD,
    )


async def apply_deterrence_power(session: AsyncSession, country: Country) -> float:
    """سهم زرادخانه در «قدرت نظامی» نمایشی کشور."""
    warheads = await nuc_repo.count_ready_warheads(session, country.id)
    return warheads * NUCLEAR_DETERRENCE_POWER_PER_WARHEAD


async def apply_sabotage_damage(
    session: AsyncSession, target_country_id: int, centrifuge_loss_pct: float
) -> int:
    """
    اعمال خسارت خرابکاری سایبری: درصدی از سانتریفیوژها نابود و غنی‌سازی متوقف می‌شود.
    خروجی: تعداد سانتریفیوژهای نابودشده.
    """
    program = await nuc_repo.get_program(session, target_country_id)
    if program is None or program.centrifuges <= 0:
        return 0
    lost = int(program.centrifuges * centrifuge_loss_pct)
    program.centrifuges = max(0, program.centrifuges - lost)
    # توقف اضطراری غنی‌سازی
    program.enrich_tier = None
    program.enrich_centrifuges = 0
    program.swu_accumulated = 0.0
    program.enrich_started_at = None
    program.last_enrich_tick_at = None
    await session.flush()
    return lost


async def apply_strike_damage(
    session: AsyncSession, facility: NuclearFacility, damage_pct: float
) -> None:
    """اعمال خسارت حمله‌ی هوایی به یک تأسیسات هسته‌ای (زیرزمینی نصف خسارت می‌گیرد)."""
    if facility.is_underground:
        damage_pct *= 0.5
    facility.integrity_pct = max(0.0, facility.integrity_pct - damage_pct)
    if facility.integrity_pct <= 0:
        facility.status = NuclearFacilityStatus.DESTROYED.value
    elif facility.integrity_pct < 60:
        facility.status = NuclearFacilityStatus.DAMAGED.value
    await session.flush()
