"""وضعیت‌های FSM مربوط به ثبت نبرد و اعلان جنگ."""

from aiogram.fsm.state import State, StatesGroup


class BattleForm(StatesGroup):
    """فرم ثبت حمله نظامی جدید."""

    choosing_attack_type = State()
    choosing_target_country = State()
    choosing_target_type = State()
    entering_payload = State()
    choosing_sabotage_claim = State()
