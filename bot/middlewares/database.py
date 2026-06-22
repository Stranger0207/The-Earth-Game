"""میدلور تزریق session دیتابیس به هندلرها."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ..database.base import async_session_factory


class DatabaseMiddleware(BaseMiddleware):
    """
    برای هر رویداد یک session تازه می‌سازد، آن را در data["session"] قرار می‌دهد
    و پس از پایان هندلر، در صورت نبود خطا commit و در غیر این صورت rollback می‌کند.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
