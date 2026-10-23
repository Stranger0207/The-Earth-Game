"""
تجمیع وضعیت لحظه‌ای ژئوپلیتیک جهان برای اندپوینت /api/radar-state مینی‌اپ رادار زنده.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..constants import FLIGHT_DURATION_MINUTES
from ..database.models import (
    Alliance,
    AllianceMember,
    Country,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    MilitarySale,
    ResourceSale,
    User,
)
from ..database.repositories import countries as countries_repo
from ..database.repositories import feature_locks as locks_repo
from ..database.repositories import straits as straits_repo
from ..database.repositories import united_nations as un_repo
from ..database.repositories import users as users_repo
from ..enums import (
    DiplomacyStatus,
    RESOURCE_FA,
    RESOURCE_UNIT_FA,
    ResourceType,
    TradeStatus,
    TransportMode,
)
from ..services import geo_service as geo
from ..utils.numbers import fa_number

logger = logging.getLogger(__name__)
settings = get_settings()


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_radar_state(
    session: AsyncSession,
    viewer_user_id: int | None = None,
) -> dict[str, Any]:
    """
    تولید وضعیت کامل و یکپارچه لحظه‌ای نقشه استراتژیک جهان.
    شامل احراز هویت بیننده، فیلتر محرمانگی بارنامه‌ها و محاسبه مسیرهای دریایی و هوایی.
    """
    now = datetime.now(timezone.utc)

    # ۱. مشخصات بیننده
    viewer_user: User | None = None
    viewer_country: Country | None = None
    is_admin = False

    if viewer_user_id:
        viewer_user = await users_repo.get_user(session, viewer_user_id)
        viewer_country = await countries_repo.get_country_by_owner(session, viewer_user_id)
        is_admin = settings.is_admin(viewer_user_id)

    # بررسی قفل بودن رادار
    is_locked = False
    if not is_admin:
        cid = viewer_country.id if viewer_country else None
        is_locked = await locks_repo.is_locked(session, "live_radar_map", cid)

    # ۲. استعلام ۳۹ کشور
    all_countries = await countries_repo.list_countries(session)
    country_map: dict[int, Country] = {c.id: c for c in all_countries}
    country_en_map: dict[str, Country] = {c.name_en: c for c in all_countries}

    # دریافت اطلاعات اتحادها
    alliance_res = await session.execute(
        select(Alliance.name, AllianceMember.country_id).join(
            AllianceMember, Alliance.id == AllianceMember.alliance_id
        )
    )
    country_alliance: dict[int, str] = {cid: name for name, cid in alliance_res.all()}

    # دریافت کاربران مالکان برای اسامی رهبران
    owners_res = await session.execute(
        select(User).where(User.telegram_id.in_([c.owner_user_id for c in all_countries if c.owner_user_id]))
    )
    user_map: dict[int, User] = {u.telegram_id: u for u in owners_res.scalars().all()}

    countries_data: list[dict[str, Any]] = []
    for c in all_countries:
        geo_data = geo.get_geo(c.name_en) or {}
        coords = geo_data.get("coords", [0.0, 0.0])

        leader_name = None
        if c.owner_user_id and c.owner_user_id in user_map:
            u = user_map[c.owner_user_id]
            leader_name = u.president_name or u.first_name or u.username

        countries_data.append({
            "id": c.id,
            "name_en": c.name_en,
            "name_fa": c.name_fa,
            "flag": c.flag,
            "coords": coords,
            "is_claimed": c.is_claimed,
            "is_vip": c.is_vip,
            "leader_name": leader_name,
            "alliance": country_alliance.get(c.id),
            "economic_power": c.economic_power,
        })

    # ۳. پروازهای دیپلماتیک (دیدارهای دوجانبه و چندجانبه در حال پرواز)
    diplomatic_flights: list[dict[str, Any]] = []

    # دوجانبه
    meetings_res = await session.execute(
        select(Meeting).where(Meeting.status == DiplomacyStatus.ACTIVE)
    )
    for m in meetings_res.scalars().all():
        eta = _ensure_aware(m.travel_eta)
        if eta and eta > now and not m.start_announced:
            traveler = country_map.get(m.traveler_country)
            host = country_map.get(m.host_country)
            if not traveler or not host:
                continue

            started = _ensure_aware(m.created_at) or (eta - timedelta(minutes=FLIGHT_DURATION_MINUTES))
            total_sec = max(1.0, (eta - started).total_seconds())
            elapsed_sec = max(0.0, (now - started).total_seconds())
            progress = min(100.0, (elapsed_sec / total_sec) * 100.0)

            waypoints = geo.get_air_waypoints(traveler.name_en, host.name_en)

            diplomatic_flights.append({
                "id": f"meet_{m.id}",
                "type": "bilateral",
                "title": f"پرواز رسمی دیپلماتیک: سفر هیئت {traveler.name_fa} به {host.name_fa}",
                "from_country": {
                    "id": traveler.id,
                    "name_en": traveler.name_en,
                    "name_fa": traveler.name_fa,
                    "flag": traveler.flag,
                    "coords": waypoints[0],
                },
                "to_country": {
                    "id": host.id,
                    "name_en": host.name_en,
                    "name_fa": host.name_fa,
                    "flag": host.flag,
                    "coords": waypoints[-1],
                },
                "waypoints": waypoints,
                "started_at": started.isoformat(),
                "arrives_at": eta.isoformat(),
                "progress_pct": round(progress, 1),
            })

    # چندجانبه
    grp_parts_res = await session.execute(
        select(GroupMeetingParticipant, GroupMeeting)
        .join(GroupMeeting, GroupMeetingParticipant.meeting_id == GroupMeeting.id)
        .where(
            GroupMeetingParticipant.response == DiplomacyStatus.ACTIVE,
            GroupMeeting.status.in_([DiplomacyStatus.PENDING, DiplomacyStatus.ACTIVE]),
        )
    )
    for part, grp in grp_parts_res.all():
        eta = _ensure_aware(part.travel_eta)
        if eta and eta > now:
            guest = country_map.get(part.country_id)
            host = country_map.get(grp.host_country)
            if not guest or not host:
                continue

            started = _ensure_aware(grp.created_at) or (eta - timedelta(minutes=FLIGHT_DURATION_MINUTES))
            total_sec = max(1.0, (eta - started).total_seconds())
            elapsed_sec = max(0.0, (now - started).total_seconds())
            progress = min(100.0, (elapsed_sec / total_sec) * 100.0)

            waypoints = geo.get_air_waypoints(guest.name_en, host.name_en)

            diplomatic_flights.append({
                "id": f"grp_{part.id}",
                "type": "multilateral",
                "title": f"عزیمت هیئت {guest.name_fa} به نشست «{grp.title}» در {host.name_fa}",
                "from_country": {
                    "id": guest.id,
                    "name_en": guest.name_en,
                    "name_fa": guest.name_fa,
                    "flag": guest.flag,
                    "coords": waypoints[0],
                },
                "to_country": {
                    "id": host.id,
                    "name_en": host.name_en,
                    "name_fa": host.name_fa,
                    "flag": host.flag,
                    "coords": waypoints[-1],
                },
                "waypoints": waypoints,
                "started_at": started.isoformat(),
                "arrives_at": eta.isoformat(),
                "progress_pct": round(progress, 1),
            })

    # پروازهای مجمع عمومی سازمان ملل متحد به نیویورک و وضعیت مقر UN
    active_un_session = await un_repo.get_active_session(session)
    speaker_dict = None
    in_hall_countries: list[dict[str, Any]] = []
    in_ny_countries: list[dict[str, Any]] = []

    if active_un_session:
        un_participants = await un_repo.list_participants(session, active_un_session.id)
        un_c = country_en_map.get("UN")
        un_to_country = {
            "id": un_c.id if un_c else 0,
            "name_en": "UN",
            "name_fa": "سازمان ملل متحد",
            "flag": "🇺🇳",
            "coords": [40.7489, -73.9680],
        }

        for part in un_participants:
            c = country_map.get(part.country_id)
            if not c:
                continue

            p_summary = {
                "id": c.id,
                "name_en": c.name_en,
                "name_fa": c.name_fa,
                "flag": c.flag,
            }
            if part.status == "inside_hall":
                in_hall_countries.append(p_summary)
            elif part.status == "in_new_york":
                in_ny_countries.append(p_summary)
            elif part.status == "in_flight":
                eta = _ensure_aware(part.travel_eta)
                if eta and eta > now:
                    started = _ensure_aware(part.created_at) or (eta - timedelta(minutes=40))
                    total_sec = max(1.0, (eta - started).total_seconds())
                    elapsed_sec = max(0.0, (now - started).total_seconds())
                    progress = min(100.0, (elapsed_sec / total_sec) * 100.0)

                    waypoints = geo.get_air_waypoints(c.name_en, "UN")
                    diplomatic_flights.append({
                        "id": f"un_flight_{part.id}",
                        "type": "un_assembly",
                        "title": f"پرواز رسمی هیئت {c.name_fa} به مقر سازمان ملل متحد (نیویورک)",
                        "from_country": {
                            "id": c.id,
                            "name_en": c.name_en,
                            "name_fa": c.name_fa,
                            "flag": c.flag,
                            "coords": waypoints[0],
                        },
                        "to_country": un_to_country,
                        "waypoints": waypoints,
                        "started_at": started.isoformat(),
                        "arrives_at": eta.isoformat(),
                        "progress_pct": round(progress, 1),
                    })

        if active_un_session.current_speaker_country_id:
            sc = country_map.get(active_un_session.current_speaker_country_id)
            if sc:
                speaker_dict = {
                    "id": sc.id,
                    "name_en": sc.name_en,
                    "name_fa": sc.name_fa,
                    "flag": sc.flag,
                }

    un_hq_data = {
        "coords": [40.7489, -73.9680],
        "name_fa": "مقر سازمان ملل متحد (نیویورک)",
        "is_assembly_active": bool(active_un_session and active_un_session.status == "active"),
        "session_id": active_un_session.id if active_un_session else None,
        "session_title": active_un_session.title if active_un_session else None,
        "current_speaker": speaker_dict,
        "speech_ends_at": active_un_session.speech_ends_at.isoformat() if (active_un_session and active_un_session.speech_ends_at) else None,
        "voting_active": bool(active_un_session and active_un_session.voting_active),
        "countries_in_hall": in_hall_countries,
        "countries_in_ny": in_ny_countries,
    }

    # ۴. محموله‌های در حال حرکت (منابع طبیعی و تجهیزات نظامی)
    shipments: list[dict[str, Any]] = []

    # محموله‌های منابع (شامل محموله‌های فعال و همچنین موارد درگیری/انهدام/توقیف تا ۱ ساعت پیش)
    one_hour_ago = now - timedelta(hours=1)
    sales_res = await session.execute(
        select(ResourceSale).where(
            or_(
                ResourceSale.status.in_([TradeStatus.IN_TRANSIT, TradeStatus.HELD_AT_STRAIT]),
                and_(
                    ResourceSale.strait_status.in_(["DESTROYED", "CONFISCATED"]),
                    ResourceSale.held_since >= one_hour_ago,
                ),
            )
        )
    )
    for sale in sales_res.scalars().all():
        seller = country_map.get(sale.seller_country)
        buyer = country_map.get(sale.buyer_country)
        if not seller or not buyer:
            continue

        started = _ensure_aware(sale.created_at)
        eta = _ensure_aware(sale.ship_eta)

        mode = (sale.transport_mode or TransportMode.SEA.value).upper()
        if mode == TransportMode.SEA.value:
            base_waypoints = geo.get_maritime_waypoints(seller.name_en, buyer.name_en)
        else:
            base_waypoints = geo.get_air_waypoints(seller.name_en, buyer.name_en)

        standoff_action = getattr(sale, "standoff_action", "SAILING") or "SAILING"
        warning_count = getattr(sale, "warning_count", 0) or 0
        strait_status = getattr(sale, "strait_status", "NONE") or "NONE"
        held_strait_id = sale.held_at_strait_id

        anchorage_coords = None
        strait_name_fa = ""
        if held_strait_id:
            s_def = geo.get_strait_def(held_strait_id)
            strait_name_fa = s_def["name_fa"] if s_def else held_strait_id
            p_info = geo.get_strait_transit_progress(base_waypoints, held_strait_id)
            if p_info:
                anchorage_coords = p_info["approach_coords"]
            else:
                anchorage_coords = geo.get_strait_coords(held_strait_id)

        is_conflict = strait_status in ("DESTROYED", "CONFISCATED")
        has_warning_halo = bool(
            not is_conflict
            and (
                warning_count > 0
                or strait_status == "HELD_AT_STRAIT"
                or standoff_action in ("STANDOFF", "HOLD", "RUNNING")
            )
        )

        if is_conflict and anchorage_coords:
            waypoints = [anchorage_coords, anchorage_coords]
            to_country_dict = {
                "id": buyer.id,
                "name_en": buyer.name_en,
                "name_fa": buyer.name_fa,
                "flag": buyer.flag,
                "coords": anchorage_coords,
            }
        elif standoff_action == "RETURNING":
            waypoints = list(reversed(base_waypoints))
            to_country_dict = {
                "id": seller.id,
                "name_en": seller.name_en,
                "name_fa": seller.name_fa,
                "flag": seller.flag,
                "coords": base_waypoints[0],
            }
        else:
            waypoints = base_waypoints
            to_country_dict = {
                "id": buyer.id,
                "name_en": buyer.name_en,
                "name_fa": buyer.name_fa,
                "flag": buyer.flag,
                "coords": waypoints[-1],
            }

        # قانون محرمانگی بارنامه و رویدادهای درگیری
        if is_conflict:
            # رویدادهای درگیری برای همه کشورها علنی است
            is_confidential = False
            if strait_status == "DESTROYED":
                cargo_desc = f"💥 کشتی در {strait_name_fa} مورد اصابت موشک قرار گرفت و غرق شد"
            else:
                cargo_desc = f"🚨 کشتی در {strait_name_fa} توقیف و بار آن مصادره شد"
        else:
            is_owner_or_admin = (
                is_admin
                or (viewer_country and viewer_country.id in (sale.seller_country, sale.buyer_country))
            )

            if is_owner_or_admin:
                try:
                    rtype = ResourceType(sale.resource)
                    r_name = RESOURCE_FA.get(rtype, sale.resource)
                    r_unit = RESOURCE_UNIT_FA.get(rtype, "")
                except Exception:
                    r_name = sale.resource
                    r_unit = ""
                cargo_desc = f"{fa_number(sale.amount)} {r_unit} {r_name}"
                is_confidential = False
            else:
                cargo_desc = "🔒 محرمانه (بارنامه طبقه‌بندی‌شده)"
                is_confidential = True

        shipments.append({
            "id": sale.id,
            "sale_type": "resource",
            "transport_mode": mode,
            "status": sale.status,
            "strait_status": strait_status,
            "standoff_action": standoff_action,
            "warning_count": warning_count,
            "held_at_strait_id": held_strait_id,
            "anchorage_coords": anchorage_coords,
            "is_conflict": is_conflict,
            "has_warning_halo": has_warning_halo,
            "content": cargo_desc,
            "is_confidential": is_confidential,
            "has_escort": False,
            "escort_label": "",
            "can_intercept": False,
            "from_country": {
                "id": seller.id,
                "name_en": seller.name_en,
                "name_fa": seller.name_fa,
                "flag": seller.flag,
                "coords": waypoints[0],
            },
            "to_country": to_country_dict,
            "waypoints": waypoints,
            "started_at": started.isoformat() if started else None,
            "eta": eta.isoformat() if eta else None,
        })

    # محموله‌های تسلیحاتی
    mil_res = await session.execute(
        select(MilitarySale).where(MilitarySale.status == TradeStatus.IN_TRANSIT)
    )
    for msale in mil_res.scalars().all():
        seller = country_map.get(msale.seller_country)
        buyer = country_map.get(msale.buyer_country)
        if not seller or not buyer:
            continue

        started = _ensure_aware(msale.created_at)
        eta = _ensure_aware(msale.ship_eta)

        mode = TransportMode.AIR.value  # فروش نظامی منحصراً هوایی است
        waypoints = geo.get_air_waypoints(seller.name_en, buyer.name_en)

        is_owner_or_admin = (
            is_admin
            or (viewer_country and viewer_country.id in (msale.seller_country, msale.buyer_country))
        )

        if is_owner_or_admin:
            cargo_desc = f"{fa_number(msale.count)} {msale.unit} {msale.name}"
            is_confidential = False
        else:
            cargo_desc = "🔒 محرمانه (بارنامه طبقه‌بندی‌شده)"
            is_confidential = True

        shipments.append({
            "id": msale.id,
            "sale_type": "military",
            "transport_mode": mode,
            "status": msale.status,
            "held_at_strait_id": None,
            "content": cargo_desc,
            "is_confidential": is_confidential,
            "has_escort": False,
            "escort_label": "",
            "can_intercept": False,
            "from_country": {
                "id": seller.id,
                "name_en": seller.name_en,
                "name_fa": seller.name_fa,
                "flag": seller.flag,
                "coords": waypoints[0],
            },
            "to_country": {
                "id": buyer.id,
                "name_en": buyer.name_en,
                "name_fa": buyer.name_fa,
                "flag": buyer.flag,
                "coords": waypoints[-1],
            },
            "waypoints": waypoints,
            "started_at": started.isoformat() if started else None,
            "eta": eta.isoformat() if eta else None,
        })

    # ۵. تنگه‌های استراتژیک
    strait_configs = await straits_repo.list_all_strait_configs(session)
    held_counts = {
        s["held_at_strait_id"]: s
        for s in shipments
        if s.get("status") == TradeStatus.HELD_AT_STRAIT and s.get("held_at_strait_id")
    }

    straits_data: list[dict[str, Any]] = []
    for sc in strait_configs:
        s_def = geo.get_strait_def(sc.strait_id) or {}
        coords = geo.get_strait_coords(sc.strait_id) or [0.0, 0.0]
        ctrl_country = country_en_map.get(sc.controller_country_name)

        if sc.is_blocked:
            status = "BLOCKED"
        elif sc.default_toll > 0:
            status = "TOLL"
        else:
            status = "OPEN"

        # شمارش بارهای متوقف در این تنگه
        held_in_this = sum(
            1 for s in shipments
            if s.get("status") == TradeStatus.HELD_AT_STRAIT.value
            and s.get("held_at_strait_id") == sc.strait_id
        )

        straits_data.append({
            "id": sc.strait_id,
            "name_fa": sc.name_fa,
            "name_en": sc.name_en,
            "controller_country": sc.controller_country_name,
            "controller_name_fa": ctrl_country.name_fa if ctrl_country else sc.controller_country_name,
            "controller_flag": ctrl_country.flag if ctrl_country else "🏴",
            "coords": coords,
            "default_toll": sc.default_toll,
            "status": status,
            "description": s_def.get("description", ""),
            "held_cargo_count": held_in_this,
        })

    return {
        "viewer": {
            "telegram_id": viewer_user_id,
            "country_id": viewer_country.id if viewer_country else None,
            "country_name": viewer_country.name_fa if viewer_country else None,
            "country_flag": viewer_country.flag if viewer_country else None,
            "is_admin": is_admin,
            "is_locked": is_locked,
        },
        "bot_username": None,  # توسط سرور با نام ربات پر می‌شود
        "countries": countries_data,
        "diplomatic_flights": diplomatic_flights,
        "shipments": shipments,
        "straits": straits_data,
        "maritime_network": geo.get_all_maritime_corridor_segments(),
        "un_hq": un_hq_data,
        "server_time": now.isoformat(),
    }
