"""
سرویس عملیات نظامی (v1.10.6).

پل میان هندلرهای تلگرام و موتور نبرد محاسباتی:
- اعتبارسنجی (سقف عملیات، بحران رهبری، اعلام جنگ، منابع)
- جمع‌آوری وضعیت واقعی طرفین (تجهیزات، گشت، پایگاه، فرمانده، بازدارندگی)
- اجرای موتور نبرد و ذخیره‌ی نتیجه
- کسر منابع و اعمال تلفات و اثرات اقتصادی

منطق نبرد اینجا نیست — اینجا فقط داده جمع می‌شود و به `services/combat` داده می‌شود.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import (
    NUCLEAR_DETERRENCE_MAX_PCT,
    OPERATION_LIMIT_EXEMPT,
    OPERATION_LIMIT_PER_WINDOW,
    OPERATION_LIMIT_WINDOW_HOURS,
)
from ..database.models import Country, Operation
from ..database.repositories import commanders as cmd_repo
from ..database.repositories import countries as countries_repo
from ..database.repositories import military as mil_repo
from ..database.repositories import operations as op_repo
from ..database.repositories import patrols as patrol_repo
from ..database.repositories import reserves as reserves_repo
from ..enums import (
    OPEN_WAR_OPERATIONS,
    CommanderRole,
    OperationStatus,
    OperationType,
    PatrolType,
    ResourceType,
    TargetType,
)
from ..services import geo_service as geo
from ..services.combat import BattleInput, BattleResult, CommittedAsset, resolve_battle

logger = logging.getLogger(__name__)


class OperationError(Exception):
    """خطای قابل‌نمایش به بازیکن هنگام ثبت عملیات."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# نگاشت نوع عملیات به تخصص فرمانده‌ای که بونوس می‌دهد
_OPERATION_COMMANDER: dict[OperationType, CommanderRole] = {
    OperationType.GROUND_ASSAULT: CommanderRole.GROUND,
    OperationType.AIR_STRIKE: CommanderRole.AIR,
    OperationType.NAVAL_STRIKE: CommanderRole.NAVAL,
    OperationType.SABOTAGE: CommanderRole.INTELLIGENCE,
    OperationType.ASSASSINATION: CommanderRole.INTELLIGENCE,
    OperationType.INTERCEPTION: CommanderRole.NAVAL,
}

# نگاشت نوع عملیات به نوع گشتی که مدافع را تقویت می‌کند
_OPERATION_PATROL: dict[OperationType, PatrolType] = {
    OperationType.GROUND_ASSAULT: PatrolType.GROUND,
    OperationType.AIR_STRIKE: PatrolType.AIR,
    OperationType.NAVAL_STRIKE: PatrolType.NAVAL,
    OperationType.INTERCEPTION: PatrolType.NAVAL,
}


async def assert_can_operate(session: AsyncSession, country: Country) -> None:
    """
    بررسی اینکه کشور مجاز به ثبت عملیات جدید است.
    در صورت مشکل، OperationError با پیام فارسی پرتاب می‌شود.
    """
    crisis_until = _aware(getattr(country, "leadership_crisis_until", None))
    if crisis_until and crisis_until > _utcnow():
        remaining = int((crisis_until - _utcnow()).total_seconds() // 60)
        raise OperationError(
            f"⚠️ کشور شما در «بحران رهبری» است و تا {remaining} دقیقه‌ی دیگر "
            "نمی‌تواند عملیات نظامی جدید ثبت کند."
        )

    used = await op_repo.count_in_window(
        session,
        country.id,
        OPERATION_LIMIT_WINDOW_HOURS,
        exempt_types=[t.value for t in OPERATION_LIMIT_EXEMPT],
    )
    if used >= OPERATION_LIMIT_PER_WINDOW:
        raise OperationError(
            f"⏳ سقف عملیات شما پر شده است: حداکثر {OPERATION_LIMIT_PER_WINDOW} عملیات "
            f"در هر {OPERATION_LIMIT_WINDOW_HOURS} ساعت. لطفاً بعداً تلاش کنید."
        )


async def assert_war_declared(
    session: AsyncSession, attacker: Country, defender: Country, operation: OperationType
) -> None:
    """حملات علنی نیاز به اعلام جنگ رسمی دارند (خرابکاری و ترور مستثنا)."""
    if operation not in OPEN_WAR_OPERATIONS:
        return

    from ..database.repositories import battles as war_repo

    has_war = await war_repo.has_active_war_declaration(session, attacker.id, defender.id)
    if not has_war:
        raise OperationError(
            f"⚔️ برای حمله‌ی علنی ابتدا باید از بخش دیپلماسی علیه "
            f"{defender.flag} {defender.name_fa} رسماً اعلام جنگ کنید."
        )


async def available_assets(
    session: AsyncSession, country_id: int, operation: OperationType
) -> list[dict]:
    """
    تجهیزات موجود کشور که برای این نوع عملیات قابل‌استفاده‌اند.
    خروجی برای ساخت کیبورد انتخاب قلم‌به‌قلم استفاده می‌شود.
    """
    from ..services.combat.power import allowed_branches_for

    allowed = allowed_branches_for(operation)
    assets = await mil_repo.list_assets(session, country_id)

    result: list[dict] = []
    for asset in assets:
        if asset.count <= 0:
            continue
        if allowed is not None and asset.branch not in allowed:
            continue
        result.append({
            "name": asset.name,
            "count": asset.count,
            "unit": asset.unit,
            "category": asset.category,
            "branch": asset.branch,
        })
    return result


async def _collect_battle_input(
    session: AsyncSession,
    attacker: Country,
    defender: Country,
    operation: OperationType,
    target: TargetType,
    committed: list[CommittedAsset],
    *,
    seed: int | None = None,
) -> BattleInput:
    """وضعیت واقعی طرفین را جمع می‌کند و ورودی موتور نبرد را می‌سازد."""
    defender_assets_raw = await mil_repo.list_assets(session, defender.id)
    defender_assets = [
        CommittedAsset(
            name=a.name, count=a.count, branch=a.branch, category=a.category, unit=a.unit
        )
        for a in defender_assets_raw
        if a.count > 0
    ]

    # بونوس فرماندهان
    role = _OPERATION_COMMANDER.get(operation)
    attacker_bonus = await cmd_repo.bonus_for_role(session, attacker.id, role) if role else 0.0
    defender_bonus = await cmd_repo.bonus_for_role(session, defender.id, role) if role else 0.0

    # گشت فعال مدافع از نوع مرتبط
    patrol_active = False
    patrol_type = _OPERATION_PATROL.get(operation)
    if patrol_type is not None:
        patrol_active = await patrol_repo.has_active_of_type(session, defender.id, patrol_type)

    # پایگاه‌های فعال مدافع (پایگاه‌هایی که در خاک خودش مستقر است)
    base_count = 0
    try:
        from ..database.repositories import military_bases as base_repo

        hosted = await base_repo.list_bases_by_host(session, defender.id)
        base_count = sum(1 for b in hosted if b.owner_country_id == defender.id)
    except Exception as exc:  # noqa: BLE001 — نبود پایگاه نباید نبرد را بشکند
        logger.debug("Could not count defender bases: %s", exc)

    # بازدارندگی هسته‌ای مدافع
    deterrence = 0.0
    try:
        from . import nuclear_service

        deterrence = min(
            await nuclear_service.deterrence_defense_pct(session, defender.id),
            NUCLEAR_DETERRENCE_MAX_PCT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not compute nuclear deterrence: %s", exc)

    # پایگاه پیشرو: آیا مهاجم پایگاهی در خاک کشوری همسایه‌ی هدف (یا خودِ هدف) دارد؟
    has_forward = False
    try:
        from ..database.repositories import military_bases as base_repo

        own_bases = await base_repo.list_bases_by_owner(session, attacker.id)
        neighbors = set(geo.neighbors_of(defender.name_en)) | {defender.name_en}
        for base in own_bases:
            if base.host_country_id == attacker.id:
                continue  # پایگاه داخلی، پایگاه پیشرو نیست
            host = await countries_repo.get_country(session, base.host_country_id)
            if host and host.name_en in neighbors:
                has_forward = True
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not evaluate forward bases: %s", exc)

    return BattleInput(
        operation_type=operation,
        target_type=target,
        attacker_name=f"{attacker.flag} {attacker.name_fa}",
        defender_name=f"{defender.flag} {defender.name_fa}",
        committed=committed,
        defender_assets=defender_assets,
        distance_km=geo.distance_km(attacker.name_en, defender.name_en),
        distance_tier=geo.distance_tier(attacker.name_en, defender.name_en),
        shares_sea=geo.shares_sea(attacker.name_en, defender.name_en),
        attacker_readiness=float(getattr(attacker, "readiness", 0.0) or 0.0),
        defender_readiness=float(getattr(defender, "readiness", 0.0) or 0.0),
        attacker_commander_bonus=attacker_bonus,
        defender_commander_bonus=defender_bonus,
        defender_patrol_active=patrol_active,
        defender_base_count=base_count,
        defender_population=int(defender.population or 0),
        nuclear_deterrence_pct=deterrence,
        has_forward_base=has_forward,
        seed=seed,
    )


async def preview_operation(
    session: AsyncSession,
    attacker: Country,
    defender: Country,
    operation: OperationType,
    target: TargetType,
    committed: list[CommittedAsset],
) -> BattleResult:
    """
    پیش‌نمایش نتیجه‌ی عملیات بدون ثبت آن — برای نمایش امکان‌سنجی و
    هزینه‌ی تخمینی به بازیکن پیش از تأیید نهایی.
    """
    battle_input = await _collect_battle_input(
        session, attacker, defender, operation, target, committed
    )
    return resolve_battle(battle_input)


async def create_operation(
    session: AsyncSession,
    attacker: Country,
    defender: Country,
    operation: OperationType,
    target: TargetType,
    committed: list[CommittedAsset],
    *,
    tactical_note: str = "",
    claim_responsibility: bool = True,
    target_label: str = "",
    target_ref_id: int | None = None,
) -> Operation:
    """
    ثبت یک عملیات جدید با وضعیت «در انتظار تأیید مالک».

    نتیجه‌ی نبرد همین‌جا محاسبه و ذخیره می‌شود (قطعی و بازتولیدپذیر)، ولی
    تا تأیید مالک هیچ اثری اعمال نمی‌شود و خبری منتشر نمی‌گردد.
    """
    if attacker.id == defender.id:
        raise OperationError("نمی‌توانید علیه کشور خودتان عملیات اجرا کنید.")

    await assert_can_operate(session, attacker)
    await assert_war_declared(session, attacker, defender, operation)

    if not committed:
        raise OperationError("هیچ تجهیزاتی برای این عملیات انتخاب نشده است.")

    # اطمینان از کافی‌بودن موجودی واقعی (ممکن است بین انتخاب و تأیید تغییر کرده باشد)
    for item in committed:
        asset = await mil_repo.get_asset_by_name(session, attacker.id, item.name)
        if asset is None or asset.count < item.count:
            available = asset.count if asset else 0
            raise OperationError(
                f"موجودی «{item.name}» کافی نیست (موجودی فعلی: {available})."
            )

    battle_input = await _collect_battle_input(
        session, attacker, defender, operation, target, committed
    )
    result = resolve_battle(battle_input)

    if not result.feasible:
        raise OperationError(result.reject_reason)

    # بررسی سوخت
    has_fuel = await reserves_repo.has_enough(
        session, attacker.id, ResourceType.OIL, result.fuel_cost
    )
    if not has_fuel:
        raise OperationError(
            f"⛽️ سوخت کافی ندارید. این عملیات به {result.fuel_cost:,.2f} میلیون بشکه نفت نیاز دارد."
        )
    if (attacker.budget or 0.0) < result.budget_cost:
        raise OperationError(
            f"💰 بودجه‌ی کافی ندارید. هزینه‌ی این عملیات {result.budget_cost / 1e9:,.2f} میلیارد دلار است."
        )

    operation_row = Operation(
        attacker_country_id=attacker.id,
        defender_country_id=defender.id,
        operation_type=operation.value,
        target_type=target.value,
        target_ref_id=target_ref_id,
        target_label=target_label,
        committed_json=json.dumps([a.to_dict() for a in committed], ensure_ascii=False),
        tactical_note=tactical_note[:2000],
        claim_responsibility=claim_responsibility,
        status=OperationStatus.PENDING_OWNER.value,
        fuel_cost=result.fuel_cost,
        budget_cost=result.budget_cost,
        intensity=result.intensity,
        intercept_pct=result.intercept_pct,
        attacker_losses_json=json.dumps(result.attacker_losses, ensure_ascii=False),
        defender_losses_json=json.dumps(result.defender_losses, ensure_ascii=False),
        civilian_casualties=result.civilian_casualties,
        infra_damage_pct=result.infra_damage_pct,
        econ_effects_json=json.dumps(result.econ_effects, ensure_ascii=False),
        outcome=result.outcome,
        phase_facts_json=json.dumps(result.facts, ensure_ascii=False),
        total_phases=result.total_phases,
        phase_interval_min=result.phase_interval_min,
        created_at=_utcnow(),
    )
    return await op_repo.create_operation(session, operation_row)


async def approve_operation(session: AsyncSession, operation_id: int) -> Operation:
    """
    تأیید عملیات توسط مالک: کسر هزینه‌ها و شروع فازهای خبری.
    نتیجه‌ی نبرد قبلاً محاسبه شده؛ اینجا فقط اعمال می‌شود.
    """
    operation = await op_repo.get_operation(session, operation_id)
    if operation is None:
        raise OperationError("عملیات یافت نشد.")
    if operation.status != OperationStatus.PENDING_OWNER.value:
        raise OperationError("این عملیات دیگر در انتظار تأیید نیست.")

    attacker = await countries_repo.get_country(session, operation.attacker_country_id)
    if attacker is None:
        raise OperationError("کشور مهاجم یافت نشد.")

    # کسر سوخت و بودجه
    if operation.fuel_cost > 0:
        await reserves_repo.add_amount(
            session, attacker.id, ResourceType.OIL, -operation.fuel_cost
        )
    if operation.budget_cost > 0:
        attacker.budget = max(0.0, (attacker.budget or 0.0) - operation.budget_cost)

    operation.status = OperationStatus.IN_PROGRESS.value
    operation.approved_at = _utcnow()
    operation.current_phase = 1
    operation.next_phase_at = _utcnow()
    await session.flush()
    return operation


async def reject_operation(session: AsyncSession, operation_id: int, reason: str = "") -> Operation:
    """رد عملیات توسط مالک (بدون هیچ اثری روی بازی)."""
    operation = await op_repo.get_operation(session, operation_id)
    if operation is None:
        raise OperationError("عملیات یافت نشد.")
    if operation.status != OperationStatus.PENDING_OWNER.value:
        raise OperationError("این عملیات دیگر در انتظار تأیید نیست.")

    operation.status = OperationStatus.REJECTED.value
    operation.failure_reason = reason or "ردشده توسط مدیریت بازی"
    operation.resolved_at = _utcnow()
    await session.flush()
    return operation


async def apply_outcome(session: AsyncSession, operation: Operation) -> None:
    """
    اعمال نتایج نهایی عملیات: کسر تلفات از طرفین و اثرات اقتصادی.
    در پایان آخرین فاز خبری توسط زمان‌بند صدا زده می‌شود.

    هر بخش مستقل در try/except است تا یک خطا کل نتیجه را از بین نبرد.
    """
    attacker = await countries_repo.get_country(session, operation.attacker_country_id)
    defender = await countries_repo.get_country(session, operation.defender_country_id)

    # ---------- تلفات تجهیزات ----------
    try:
        for item in json.loads(operation.attacker_losses_json or "[]"):
            await mil_repo.reduce_count(
                session, operation.attacker_country_id, item.get("name", ""), int(item.get("count", 0))
            )
        for item in json.loads(operation.defender_losses_json or "[]"):
            await mil_repo.reduce_count(
                session, operation.defender_country_id, item.get("name", ""), int(item.get("count", 0))
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to apply operation losses: %s", exc)

    # ---------- اثرات اقتصادی ----------
    try:
        econ = json.loads(operation.econ_effects_json or "{}")

        if defender is not None:
            defender.public_satisfaction = max(0.0, min(100.0, (defender.public_satisfaction or 0.0)
                + float(econ.get("defender_satisfaction_delta", 0.0))))
            defender.stability = max(0.0, min(100.0, (defender.stability or 0.0)
                + float(econ.get("defender_stability_delta", 0.0))))
            defender.inflation = max(0.0, (defender.inflation or 0.0)
                + float(econ.get("defender_inflation_delta", 0.0)))
            defender.budget = max(0.0, (defender.budget or 0.0)
                - float(econ.get("defender_budget_loss", 0.0)))

        if attacker is not None:
            attacker.public_satisfaction = max(0.0, min(100.0, (attacker.public_satisfaction or 0.0)
                + float(econ.get("attacker_satisfaction_delta", 0.0))))
            attacker.stability = max(0.0, min(100.0, (attacker.stability or 0.0)
                + float(econ.get("attacker_stability_delta", 0.0))))
            attacker.inflation = max(0.0, (attacker.inflation or 0.0)
                + float(econ.get("attacker_inflation_delta", 0.0)))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to apply operation economic effects: %s", exc)

    operation.status = OperationStatus.RESOLVED.value
    operation.success = operation.infra_damage_pct >= 25.0
    operation.resolved_at = _utcnow()
    await session.flush()


def parse_committed(operation: Operation) -> list[CommittedAsset]:
    """تجهیزات اعزامی یک عملیات را از JSON بازمی‌خواند."""
    try:
        raw = json.loads(operation.committed_json or "[]")
    except (ValueError, TypeError):
        return []
    return [CommittedAsset.from_dict(item) for item in raw]


def parse_facts(operation: Operation) -> dict:
    """واقعیت‌های خبری یک عملیات را از JSON بازمی‌خواند."""
    try:
        return json.loads(operation.phase_facts_json or "{}")
    except (ValueError, TypeError):
        return {}
