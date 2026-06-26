"""تعریف گروه‌های وضعیت (StatesGroup) برای فرم‌های مختلف بازی."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ClaimForm(StatesGroup):
    """فرم کشورگیری: انتخاب کشور و نام رئیس‌جمهور."""

    choosing_country = State()
    entering_president_name = State()
    entering_note = State()
    confirming = State()  # تأیید نهایی کشورگیری (v1.8)


class FacilityForm(StatesGroup):
    """فرم احداث تأسیسات (معدن/کارخانه/سکو)."""

    choosing_type = State()       # نوع تأسیسات
    choosing_resource = State()   # نوع منبع (برای معدن)
    entering_location = State()   # محل احداث
    confirming = State()          # تأیید نهایی


class SaleForm(StatesGroup):
    """فرم فروش ذخیره به کشور دیگر."""

    choosing_resource = State()
    entering_amount = State()
    choosing_buyer = State()
    entering_price = State()
    confirming = State()


class LetterForm(StatesGroup):
    """فرم ارسال نامه به کشور دیگر."""

    choosing_target = State()
    writing_body = State()


class CallForm(StatesGroup):
    """فرم درخواست تماس تلفنی."""

    choosing_target = State()
    in_call = State()  # حین تماس، پیام‌ها رد و بدل می‌شوند


class MeetingForm(StatesGroup):
    """فرم درخواست دیدار حضوری."""

    choosing_target = State()        # دیدار دوجانبه: انتخاب کشور مقصد
    selecting_members = State()       # دیدار چندجانبه: انتخاب چند کشور
    entering_group_title = State()    # دیدار چندجانبه: عنوان نشست


class ContractForm(StatesGroup):
    """فرم پر کردن قرارداد در دیدار حضوری."""

    entering_title = State()
    entering_body = State()
    confirming = State()


class AttackForm(StatesGroup):
    """فرم حمله نظامی."""

    choosing_type = State()       # نوع حمله
    choosing_target = State()     # کشور هدف
    describing = State()          # شرح تجهیزات و هدف حمله
    confirming_fuel = State()     # تأیید مصرف سوخت


class MilitaryFactoryForm(StatesGroup):
    """فرم احداث کارخانه‌ی نظامی (v1.7)."""

    choosing_type = State()      # نوع کارخانه (جنگنده/تانک/...)
    choosing_asset = State()     # قلم تجهیزات قابل‌بازتولید
    entering_location = State()  # محل احداث
    confirming = State()         # تأیید نهایی هزینه‌ها


class MilitarySaleForm(StatesGroup):
    """فرم فروش تجهیزات نظامی به کشور دیگر (v1.7)."""

    choosing_category = State()  # دسته‌ی تجهیزات
    choosing_asset = State()     # قلم تجهیزات
    entering_count = State()     # تعداد
    entering_price = State()     # قیمت
    choosing_buyer = State()     # کشور خریدار


class AdvisorForm(StatesGroup):
    """فرم پرسش از مشاور AI."""

    choosing_domain = State()
    asking = State()


class TariffForm(StatesGroup):
    """فرم تعیین تعرفه توسط آمریکا (v1.5)."""

    entering_percent = State()


class SanctionForm(StatesGroup):
    """فرم وضع تحریم (v1.5)."""

    choosing_type = State()


class SpeechForm(StatesGroup):
    """فرم سخنرانی رئیس‌جمهور (v1.5)."""

    entering_text = State()
    entering_photo = State()
    quoting = State()


class GodForm(StatesGroup):
    """فرم پنل گاد مود ادمین برای ویرایش مقادیر کشور (v1.8)."""

    entering_value = State()  # وارد کردن مقدار جدید (اقتصاد/ذخیره/تجهیزات)
