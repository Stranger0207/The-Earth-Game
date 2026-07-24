"""وضعیت‌های FSM مربوط به مدیریت ماهواره‌های فضایی."""

from aiogram.fsm.state import State, StatesGroup


class SatelliteForm(StatesGroup):
    """فرم پرتاب و رصد ماهواره."""

    entering_satellite_name = State()
    choosing_target_country = State()
