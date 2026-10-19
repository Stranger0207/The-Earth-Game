"""
وضعیت‌های ماشین حالت (FSM) برای امور سازمان ملل متحد، مجمع عمومی و دیوان لاهه.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class IAEAForm(StatesGroup):
    """فرم اعزام تیم بازرسان آژانس انرژی اتمی."""
    picking_country = State()


class UNAssemblyForm(StatesGroup):
    """فرم مدیریت صحن مجمع عمومی."""
    entering_vote_topic = State()


class CourtForm(StatesGroup):
    """فرم ثبت دادخواست و صدور حکم در دادگاه لاهه."""
    choosing_defendant = State()
    choosing_issue = State()
    entering_claim_title = State()
    entering_claim_description = State()
    entering_demanded_compensation = State()
    entering_verdict_text = State()
    entering_fine_amount = State()


class ResolutionForm(StatesGroup):
    """فرم تدوین و انتشار قطعنامه بین‌المللی."""
    entering_title = State()
    entering_body = State()


class HumanitarianForm(StatesGroup):
    """فرم ارسال کمک‌های بشردوستانه صندوق سازمان ملل."""
    choosing_recipient = State()
    entering_aid_amount = State()
