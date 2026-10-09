"""وضعیت‌های FSM برای فرم‌های گیم‌مود مقاماتی (کابینه دولت آمریکا)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CabinetMemoForm(StatesGroup):
    """فرم ارسال نامه و یادداشت درون‌سازمانی."""

    choosing_recipient = State()
    entering_subject = State()
    entering_body = State()


class CabinetInquiryForm(StatesGroup):
    """فرم استعلام اطلاعات رسمی میان ارگان‌ها."""

    choosing_target = State()
    entering_topic = State()
    entering_question = State()
    answering = State()


class CabinetInspectionForm(StatesGroup):
    """فرم صدور حکم بازرسی ویژه دادستان کل."""

    choosing_target = State()
    entering_reason = State()


class CabinetExecutiveOrderForm(StatesGroup):
    """فرم صدور فرمان اجرایی رئیس‌جمهور."""

    entering_title = State()
    entering_content = State()


class CabinetPressBriefingForm(StatesGroup):
    """فرم انتشار کنفرانس مطبوعاتی و بیانیه رسمی سخنگوی کاخ سفید."""

    entering_text = State()
