"""وضعیت‌های FSM سیستم عملیات نظامی (v1.10.6)."""

from aiogram.fsm.state import State, StatesGroup


class OperationForm(StatesGroup):
    """
    فرم ثبت یک عملیات تهاجمی (حمله زمینی/هوایی/دریایی، خرابکاری، ترور، رهگیری).

    جریان: نوع عملیات → کشور هدف → نوع هدف → انتخاب دقیق تجهیزات
            → شرح تاکتیکی → تأیید نهایی
    """

    choosing_type = State()
    choosing_target_country = State()
    choosing_target_type = State()
    # انتخاب قلم‌به‌قلم تجهیزات از موجودی واقعی کشور
    selecting_assets = State()
    entering_asset_count = State()
    # عملیات مخفیانه: پذیرش یا عدم پذیرش مسئولیت
    choosing_claim = State()
    entering_tactical_note = State()
    confirming = State()

    # اهداف ویژه
    choosing_commander = State()   # ترور: انتخاب فرمانده هدف
    choosing_shipment = State()    # رهگیری: انتخاب محموله‌ی عبوری


class PatrolForm(StatesGroup):
    """فرم ثبت گشت دفاعی: نوع گشت → منطقه → تجهیزات → تأیید."""

    choosing_type = State()
    entering_area = State()
    selecting_assets = State()
    entering_asset_count = State()
    confirming = State()


class DrillForm(StatesGroup):
    """فرم برگزاری رزمایش: نوع → عنوان → منطقه → تجهیزات → (شریک) → تأیید."""

    choosing_type = State()
    entering_title = State()
    entering_area = State()
    selecting_assets = State()
    entering_asset_count = State()
    choosing_partner = State()
    confirming = State()
