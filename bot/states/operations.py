"""وضعیت‌های FSM رهگیری و اسکورت محموله (v1.10.7)."""

from aiogram.fsm.state import State, StatesGroup


class InterceptionForm(StatesGroup):
    """
    فرم رهگیری محموله (v1.10.7).

    جریان: انتخاب محموله → (اگر اسکورت دارد) انتخاب نیرو → تأیید
    """

    choosing_shipment = State()
    selecting_assets = State()
    entering_asset_count = State()
    confirming = State()


class EscortForm(StatesGroup):
    """
    فرم تخصیص اسکورت به یک محموله‌ی در حال ارسال (v1.10.7).
    """

    selecting_assets = State()
    entering_asset_count = State()
