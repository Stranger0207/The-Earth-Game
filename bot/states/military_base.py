"""وضعیت‌های FSM مربوط به مدیریت پایگاه‌های نظامی."""

from aiogram.fsm.state import State, StatesGroup


class MilitaryBaseForm(StatesGroup):
    """فرم احداث و مدیریت پایگاه نظامی."""

    choosing_type = State()
    choosing_host = State()
    entering_name = State()
    entering_location = State()
    confirming_build = State()

    # حالت‌های انتقال تجهیزات
    choosing_base_for_transfer = State()
    choosing_asset_to_transfer = State()
    entering_transfer_count = State()
