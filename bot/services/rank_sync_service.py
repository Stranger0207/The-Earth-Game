"""
سرویس همگام‌سازی و اتصال به «ربات مقام» (Rank Bot Integration).

قابلیت‌ها:
۱. جمع‌آوری لیست بازیکنان فصل جاری (مالکان فعلی کشورها)
۲. تولید و اعتبارسنجی امضاهای امنیتی HMAC-SHA256
۳. ارسال رویداد پایان فصل (Push) با مکانیزم Retry و Backoff
۴. مدیریت صف برون‌خط (Outbox) برای تضمین عدم گم‌شدن رویدادها در زمان قطعی
۵. وب‌سرور سبک داخلی aiohttp برای سرویس‌دهی به درخواست‌های Pull ربات مقام (/internal/v1/rank-roster)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
from aiohttp import web
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database.base import async_session_factory
from ..database.models import Country, User
from ..database.models.rank_sync import RankSyncOutbox
from ..database.repositories import rank_sync as rank_sync_repo
from ..enums import UserRole
from .news_service import send_log

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """زمان فعلی به‌صورت UTC آگاه از منطقه‌ی زمانی."""
    return datetime.now(timezone.utc)


# ============================================================
#  ۱. جمع‌آوری لیست بازیکنان فعال فصل
# ============================================================
async def collect_season_players(session: AsyncSession) -> list[dict[str, Any]]:
    """
    استخراج لیست بازیکنان فعال فصل جاری:
    کاربرانی که در حال حاضر مالک یک کشور در بازی هستند.

    خروجی مطابق قرارداد API:
    [
        {
            "telegram_id": int,
            "username": str | None,
            "full_name": str,
            "country": str,       # نام فارسی کشور
            "is_staff": bool      # آیا کاربر ادمین/مالک بازی است
        },
        ...
    ]
    """
    settings = get_settings()

    # کوئری هم‌زمان کشور و کاربر مالک
    stmt = (
        select(User, Country)
        .join(Country, Country.owner_user_id == User.telegram_id)
        .where(Country.owner_user_id.is_not(None))
        .order_by(Country.id.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    players: list[dict[str, Any]] = []
    seen_telegram_ids: set[int] = set()

    for user, country in rows:
        if user.telegram_id in seen_telegram_ids:
            continue
        seen_telegram_ids.add(user.telegram_id)

        # تشخیص دسترسی مدیریتی (Staff)
        is_staff = bool(
            getattr(user, "is_admin", False)
            or getattr(user, "is_owner", False)
            or (getattr(user, "role", None) in (UserRole.ADMIN, UserRole.OWNER))
            or settings.is_admin(user.telegram_id)
        )

        # نام نمایشی کاربر
        full_name = (
            user.first_name
            or getattr(user, "president_name", None)
            or (f"@{user.username}" if user.username else str(user.telegram_id))
        )

        players.append({
            "telegram_id": int(user.telegram_id),
            "username": user.username or None,
            "full_name": full_name,
            "country": country.name_fa,
            "is_staff": is_staff,
        })

    logger.info("Collected %d active season player(s) for rank sync.", len(players))
    return players


# ============================================================
#  ۲. امضا و اعتبارسنجی امنیتی HMAC-SHA256
# ============================================================
def sign(secret: str, timestamp: int | str, raw_body: str) -> str:
    """
    تولید امضای HMAC-SHA256 به‌صورت رشته‌ی هگزادسیمال:
    hex(HMAC_SHA256(secret, f"{timestamp}.{raw_body}"))
    """
    message = f"{timestamp}.{raw_body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    timestamp: int | str,
    raw_body: str,
    signature: str,
    max_drift_seconds: int = 300,
) -> tuple[bool, str]:
    """
    بررسی اعتبار امضا و انحراف زمانی (حداکثر ۳۰۰ ثانیه).
    خروجی: (آیا معتبر است, پیام علت خطا).
    """
    if not secret:
        return False, "RANK_SYNC_SECRET is not configured"

    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False, "Invalid timestamp format"

    now = int(time.time())
    drift = abs(now - ts)
    if drift > max_drift_seconds:
        return False, f"Timestamp drift exceeds {max_drift_seconds}s (drift={drift}s)"

    expected_sig = sign(secret, ts, raw_body)
    if not hmac.compare_digest(expected_sig, signature):
        return False, "Invalid signature"

    return True, "OK"


# ============================================================
#  ۳. ارسال رویداد پایان فصل (Push)
# ============================================================
async def push_season_ended(
    event_id: str,
    players: list[dict[str, Any]],
    *,
    season_label: str = "",
    api_url: str | None = None,
    secret: str | None = None,
    max_retries: int = 3,
    timeout_sec: float = 5.0,
) -> tuple[bool, str | None]:
    """
    ارسال رویداد پایان فصل به ربات مقام:
    POST RANK_BOT_API_URL/internal/v1/season-ended
    همراه با ۳ بار تلاش مجدد با وقفه تصاعدی (Backoff).

    خروجی: (موفقیت, پیام خطا در صورت شکست)
    """
    settings = get_settings()
    target_url = (api_url or settings.rank_bot_api_url).rstrip("/") + "/internal/v1/season-ended"
    signing_secret = secret if secret is not None else settings.rank_sync_secret

    payload = {
        "event_id": event_id,
        "event_type": "season_ended",
        "season_label": season_label,
        "occurred_at": _utcnow().isoformat(),
        "players": players,
    }
    raw_body = json.dumps(payload, ensure_ascii=False)

    last_error: str | None = None

    for attempt in range(1, max_retries + 1):
        timestamp = int(time.time())
        signature = sign(signing_secret, timestamp, raw_body)
        headers = {
            "Content-Type": "application/json",
            "X-Rank-Timestamp": str(timestamp),
            "X-Rank-Signature": signature,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as client:
                async with client.post(target_url, data=raw_body, headers=headers) as resp:
                    resp_text = await resp.text()
                    if resp.status == 200:
                        logger.info(
                            "Successfully pushed season_ended event %s to rank bot (attempt %d). Response: %s",
                            event_id,
                            attempt,
                            resp_text[:200],
                        )
                        return True, None

                    last_error = f"HTTP {resp.status}: {resp_text[:300]}"
                    logger.warning(
                        "Rank bot returned non-200 on attempt %d/%d: %s",
                        attempt,
                        max_retries,
                        last_error,
                    )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Attempt %d/%d to push season_ended to rank bot failed: %s",
                attempt,
                max_retries,
                last_error,
            )

        if attempt < max_retries:
            backoff = 0.5 * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)

    return False, last_error


# ============================================================
#  ۴. مدیریت صف برون‌خط (Outbox)
# ============================================================
async def save_to_outbox(
    session: AsyncSession,
    event_id: str,
    players: list[dict[str, Any]],
    last_error: str | None = None,
) -> RankSyncOutbox:
    """ذخیره‌ی رویداد در جدول rank_sync_outbox جهت ارسال مجدد."""
    payload = {
        "event_id": event_id,
        "event_type": "season_ended",
        "season_label": "",
        "occurred_at": _utcnow().isoformat(),
        "players": players,
    }
    outbox = await rank_sync_repo.add_to_outbox(
        session,
        event_id=event_id,
        payload=payload,
        last_error=last_error,
        event_type="season_ended",
    )
    logger.info("Saved season_ended event %s to rank_sync_outbox.", event_id)
    return outbox


async def process_outbox(bot: Bot | None = None) -> int:
    """
    پردازش رکوردهای معلق در rank_sync_outbox توسط زمان‌بند.
    در صورت ارسال موفقیت‌آمیز، رکورد حذف شده و گزارش به گروه لاگ ارسال می‌گردد.
    تعداد رکوردهای ارسال‌شده برمی‌گردد.
    """
    settings = get_settings()
    if not settings.rank_sync_enabled:
        return 0

    success_count = 0
    async with async_session_factory() as session:
        pending_items = await rank_sync_repo.get_pending_outbox(session, limit=10)
        if not pending_items:
            return 0

        for item in pending_items:
            try:
                data = json.loads(item.payload_json)
                players = data.get("players", [])
                event_id = item.event_id
                season_label = data.get("season_label", "")

                ok, err = await push_season_ended(
                    event_id=event_id,
                    players=players,
                    season_label=season_label,
                )

                if ok:
                    await rank_sync_repo.delete_outbox_entry(session, item.id)
                    await session.commit()
                    success_count += 1
                    logger.info("Outbox event %s successfully sent and purged.", event_id)

                    if bot:
                        try:
                            await send_log(
                                bot,
                                f"🎖 <b>همگام‌سازی موفق با ربات مقام</b>\n"
                                f"لیست بازیکنان فصل ({event_id}) از صف تلاش مجدد ارسال شد.\n"
                                f"تعداد بازیکنان: {len(players)}",
                            )
                        except Exception:
                            pass
                else:
                    await rank_sync_repo.update_outbox_failure(session, item.id, err or "Unknown error")
                    await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed processing outbox item %s: %s", item.id, exc)
                try:
                    await rank_sync_repo.update_outbox_failure(session, item.id, str(exc))
                    await session.commit()
                except Exception:
                    pass

    return success_count


# ============================================================
#  ۵. وب‌سرور داخلی API جهت سرویس‌دهی به Pull ربات مقام
# ============================================================
async def handle_rank_roster(request: web.Request) -> web.Response:
    """
    اندپوینت دریافت لیست کامل بازیکنان فصل فعال:
    GET /internal/v1/rank-roster
    """
    settings = get_settings()

    timestamp = request.headers.get("X-Rank-Timestamp")
    signature = request.headers.get("X-Rank-Signature")

    if not timestamp or not signature:
        return web.json_response(
            {"ok": False, "error": "Missing X-Rank-Timestamp or X-Rank-Signature header"},
            status=401,
        )

    # برای متد GET، متن بدنه خالی است
    valid, reason = verify_signature(
        secret=settings.rank_sync_secret,
        timestamp=timestamp,
        raw_body="",
        signature=signature,
    )
    if not valid:
        logger.warning("Unauthorized rank roster pull request: %s", reason)
        return web.json_response({"ok": False, "error": reason}, status=401)

    async with async_session_factory() as session:
        players = await collect_season_players(session)

    response_data = {
        "generated_at": _utcnow().isoformat(),
        "players": players,
    }
    return web.json_response(response_data, status=200)


async def handle_health(request: web.Request) -> web.Response:
    """اندپوینت بررسی سلامت سرور داخلی API."""
    return web.json_response({"status": "ok", "service": "earth_game_rank_api"}, status=200)


def create_rank_api_app() -> web.Application:
    """ساخت اپلیکیشن وب‌سرور داخلی API."""
    app = web.Application()
    app.router.add_get("/internal/v1/rank-roster", handle_rank_roster)
    app.router.add_get("/health", handle_health)
    return app


async def start_rank_api_server(
    host: str = "127.0.0.1", port: int = 8090
) -> web.AppRunner:
    """
    راه‌اندازی سرور داخلی aiohttp به صورت غیرمسدودکننده (فقط روی 127.0.0.1).
    خروجی AppRunner جهت تمیز بسته‌شدن در زمان توقف ربات برمی‌گردد.
    """
    app = create_rank_api_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("🎖 Rank Internal API server started on http://%s:%d", host, port)
    return runner
