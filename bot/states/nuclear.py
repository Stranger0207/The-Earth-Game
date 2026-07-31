"""وضعیت‌های FSM برنامه‌ی هسته‌ای (v1.10.4)."""

from aiogram.fsm.state import State, StatesGroup


class NuclearForm(StatesGroup):
    """فرم‌های چندمرحله‌ای پنل هسته‌ای."""

    entering_facility_location = State()   # محل احداث تأسیسات
    entering_centrifuge_count = State()    # تعداد سانتریفیوژ برای غنی‌سازی
    entering_warhead_name = State()        # نام کلاهک هنگام مونتاژ
