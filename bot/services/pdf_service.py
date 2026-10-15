"""
سرویس تولید اسناد رسمی PDF دیپلماتیک (v2.7).

این سرویس نامه‌های دیپلماتیک میان کشورها را به اسناد رسمی وزارت امور خارجه
با حاشیه‌بندی سرمه‌ای و طلایی، سربرگ رسمی، مشخصات فرستنده و گیرنده،
شماره ثبت، متن نامه و مهر رسمی تبدیل می‌کند.

تولید کاملاً در حافظه‌ی موقت (In-Memory) انجام شده و به هیچ عنوان فایلی
روی دیسک ذخیره نمی‌شود.
"""

from __future__ import annotations

import io
import logging
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from ..utils.numbers import to_fa_digits

logger = logging.getLogger(__name__)

# رنگ‌بندی استاندارد اسناد دیپلماتیک
COLOR_NAVY = (20, 35, 60)         # سرمه‌ای رسمی (#14233C)
COLOR_GOLD = (185, 145, 65)       # طلایی دیپلماتیک (#B99141)
COLOR_BOX_BG = (248, 250, 252)     # پس‌زمینه ملایم کادر مشخصات (#F8FAFC)
COLOR_BOX_BORDER = (210, 220, 230) # حاشیه کادر مشخصات (#D2DCE6)
COLOR_TEXT_MAIN = (30, 41, 59)     # رنگ متن اصلی دودی تیره (#1E293B)
COLOR_TEXT_MUTED = (100, 116, 139) # رنگ خاکستری متون کم‌رنگ (#64748B)

# مسیر فونت‌های پروژه
_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fonts"
_FONT_REGULAR_PATH = _FONTS_DIR / "Vazirmatn-Regular.ttf"
_FONT_BOLD_PATH = _FONTS_DIR / "Vazirmatn-Bold.ttf"

_URL_REGULAR = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Regular.ttf"
_URL_BOLD = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Bold.ttf"


def _ensure_fonts() -> tuple[str, str]:
    """
    بررسی وجود فونت‌های استاندارد فارسی در پوشه data/fonts.
    در صورت عدم وجود، تلاش برای دانلود و کش آنها یا استفاده از فونت سیستم.
    """
    try:
        _FONTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create fonts directory: %s", exc)

    # دانلود یا بررسی فونت Regular
    if not _FONT_REGULAR_PATH.exists():
        try:
            logger.info("Downloading Vazirmatn-Regular font...")
            urllib.request.urlretrieve(_URL_REGULAR, str(_FONT_REGULAR_PATH))
        except Exception as exc:
            logger.warning("Failed to download Vazirmatn-Regular: %s", exc)

    # دانلود یا بررسی فونت Bold
    if not _FONT_BOLD_PATH.exists():
        try:
            logger.info("Downloading Vazirmatn-Bold font...")
            urllib.request.urlretrieve(_URL_BOLD, str(_FONT_BOLD_PATH))
        except Exception as exc:
            logger.warning("Failed to download Vazirmatn-Bold: %s", exc)

    reg_str = str(_FONT_REGULAR_PATH) if _FONT_REGULAR_PATH.exists() else ""
    bold_str = str(_FONT_BOLD_PATH) if _FONT_BOLD_PATH.exists() else ""

    # در صورت عدم موفقیت دانلود، چک کردن فونت‌های ویندوز
    if not reg_str:
        for win_font in ["C:\\Windows\\Fonts\\tahoma.ttf", "C:\\Windows\\Fonts\\arial.ttf"]:
            if os.path.exists(win_font):
                reg_str = win_font
                bold_str = win_font
                break

    return reg_str, bold_str


class DiplomaticLetterPDF(FPDF):
    """کلاس سفارشی FPDF برای رسم اسناد رسمی مکاتبات دیپلماتیک."""

    def __init__(self, sender_country: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.sender_country = sender_country
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=26)

    def header(self) -> None:
        """کادر و حاشیه‌بندی صفحات سند."""
        # کادر خارجی ضخیم سرمه‌ای
        self.set_line_width(0.9)
        self.set_draw_color(*COLOR_NAVY)
        self.rect(10, 10, 190, 277)

        # کادر داخلی نازک طلایی
        self.set_line_width(0.35)
        self.set_draw_color(*COLOR_GOLD)
        self.rect(12, 12, 186, 273)

        # سربرگ خلاصه برای صفحات ۲ به بعد
        if self.page_no() > 1:
            self.set_y(15)
            self.set_font("Vazirmatn", "", 8)
            self.set_text_color(*COLOR_TEXT_MUTED)
            self.cell(
                0,
                5,
                f"سند رسمی مکاتبات دیپلماتیک — {self.sender_country} (صفحه {self.page_no()})",
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.ln(2)

    def footer(self) -> None:
        """پاورقی رسمی با درج ثبت دبیرخانه و شماره صفحه."""
        self.set_y(-22)
        self.set_font("Vazirmatn", "", 8)
        self.set_text_color(*COLOR_TEXT_MUTED)
        self.cell(
            0,
            4,
            "ثبت‌شده در دبیرخانه دیپلماسی جهانی (The Earth Game)",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.cell(
            0,
            4,
            f"صفحه {self.page_no()}",
            align="C",
        )


def generate_diplomatic_letter_pdf(
    *,
    letter_id: int,
    sender_country_name: str,
    sender_flag: str = "",
    sender_leader_name: str | None = None,
    recipient_country_name: str,
    recipient_flag: str = "",
    letter_type: str | None = None,
    body: str,
    created_at: datetime | None = None,
    parent_id: int | None = None,
    is_allies: bool = False,
    is_all: bool = False,
) -> bytes:
    """
    تولید فایل PDF رسمی دیپلماتیک در حافظه RAM و بازگرداندن بایت‌های آن.

    پارامترها:
    - letter_id: شناسه رکورد نامه در دیتابیس
    - sender_country_name: نام فارسی کشور فرستنده
    - sender_flag: پرچم فرستنده (اختیاری)
    - sender_leader_name: نام رهبر/رئیس‌جمهور فرستنده در صورت وجود
    - recipient_country_name: نام فارسی کشور گیرنده
    - recipient_flag: پرچم گیرنده (اختیاری)
    - letter_type: عنوان موضوع سند (در صورت ارسال نشدن خودکار تعیین می‌شود)
    - body: متن کامل نامه
    - created_at: زمان ارسال
    - parent_id: شناسه نامه والد در صورت پاسخ بودن
    - is_allies: آیا نامه به اعضای اتحاد است؟
    - is_all: آیا نامه سراسری به تمام کشورهاست؟
    """
    font_reg, font_bold = _ensure_fonts()

    pdf = DiplomaticLetterPDF(sender_country=sender_country_name)

    # فعال‌سازی شکل‌دهی متن راست به چپ (RTL) با HarfBuzz
    shaping_enabled = False
    try:
        pdf.set_text_shaping(True)
        shaping_enabled = True
    except Exception as exc:
        logger.warning("HarfBuzz text shaping unavailable: %s", exc)

    # افزودن فونت‌ها
    if font_reg:
        pdf.add_font("Vazirmatn", "", font_reg)
        pdf.add_font("Vazirmatn", "B", font_bold if font_bold else font_reg)
    else:
        # در صورت نبود فایل فونت، استفاده از فونت داخلی
        pdf.add_font("Vazirmatn", "", "helvetica")
        pdf.add_font("Vazirmatn", "B", "helvetica")

    pdf.add_page()

    # ۱. سربرگ رسمی صفحه اول
    pdf.set_y(17)
    pdf.set_font("Vazirmatn", "B", 15)
    pdf.set_text_color(*COLOR_NAVY)
    pdf.cell(
        0,
        8,
        "سند رسمی مکاتبات دیپلماتیک — وزارت امور خارجه",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_font("Vazirmatn", "", 8)
    pdf.set_text_color(*COLOR_GOLD)
    pdf.cell(
        0,
        5,
        "OFFICIAL DIPLOMATIC CORRESPONDENCE — MINISTRY OF FOREIGN AFFAIRS",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # خط جداکننده طلایی
    pdf.set_draw_color(*COLOR_GOLD)
    pdf.set_line_width(0.5)
    pdf.line(20, 33, 190, 33)

    # ۲. تعیین مقادیر جدول مشخصات نامه
    # فرستنده
    if sender_leader_name and sender_leader_name.strip():
        sender_display = f"{sender_country_name} (رهبر: {sender_leader_name.strip()})"
    else:
        sender_display = sender_country_name

    # گیرنده
    if is_all:
        if recipient_country_name and recipient_country_name != "تمامی کشورهای جهان":
            recipient_display = f"{recipient_country_name} (بیانیه دیپلماتیک سراسری)"
        else:
            recipient_display = "تمامی کشورهای جهان (بیانیه دیپلماتیک سراسری)"
    elif is_allies:
        recipient_display = f"{recipient_country_name} (ابلاغیه اعضای اتحاد)"
    else:
        recipient_display = recipient_country_name

    # نوع سند / موضوع
    if not letter_type:
        if parent_id is not None:
            letter_type = "پاسخ رسمی دیپلماتیک"
        elif is_all:
            letter_type = "نامه دیپلماتیک سراسری"
        elif is_allies:
            letter_type = "نامه به متحدان"
        else:
            letter_type = "نامه رسمی دیپلماتیک"

    # تاریخ و ساعت
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    date_str = to_fa_digits(created_at.strftime("%Y/%m/%d — %H:%M")) + " (UTC)"

    # کادر مشخصات نامه
    box_y = 36
    has_reply = parent_id is not None
    box_height = 43 if has_reply else 38

    pdf.set_fill_color(*COLOR_BOX_BG)
    pdf.set_draw_color(*COLOR_BOX_BORDER)
    pdf.set_line_width(0.3)
    pdf.rect(16, box_y, 178, box_height, style="DF")

    pdf.set_xy(20, box_y + 3)
    pdf.set_font("Vazirmatn", "B", 9.5)
    pdf.set_text_color(*COLOR_NAVY)
    pdf.cell(
        170,
        5.5,
        f"📤 فرستنده (از طرف): {sender_display}",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(20)
    pdf.cell(
        170,
        5.5,
        f"📥 گیرنده (به مقصد): {recipient_display}",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(20)
    pdf.cell(
        170,
        5.5,
        f"📂 موضوع / نوع سند: {letter_type}",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(20)
    pdf.set_font("Vazirmatn", "", 9)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(
        170,
        5.5,
        f"🔢 شماره ثبت: #{to_fa_digits(letter_id)} | تاریخ و ساعت ارسال: {date_str}",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    if has_reply:
        pdf.set_x(20)
        pdf.set_font("Vazirmatn", "B", 9)
        pdf.set_text_color(*COLOR_GOLD)
        pdf.cell(
            170,
            5.5,
            f"↩️ در پاسخ به نامه رسمی شماره #{to_fa_digits(parent_id)}",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    # ۳. بخش متن اصلی نامه (Body)
    body_start_y = box_y + box_height + 4
    pdf.set_y(body_start_y)
    pdf.set_font("Vazirmatn", "B", 10.5)
    pdf.set_text_color(*COLOR_NAVY)
    pdf.cell(0, 6, "📝 متن رسمی نامه:", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    pdf.set_font("Vazirmatn", "", 10.5)
    pdf.set_text_color(*COLOR_TEXT_MAIN)

    cleaned_body = body.strip() if body else "—"

    # در صورت عدم پشتیبانی از HarfBuzz بومی، استفاده از arabic-reshaper + python-bidi به عنوان پشتیبان
    if not shaping_enabled:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            cleaned_body = get_display(arabic_reshaper.reshape(cleaned_body))
        except Exception:
            pass

    pdf.multi_cell(0, 7.5, cleaned_body, align="R")

    # ۴. پاورقی و مهر رسمی (Footer & Official Seal)
    pdf.ln(6)
    # اگر انتهای متن به پایین صفحه خیلی نزدیک است، به صفحه بعد می‌رویم تا مهر به درستی جا شود
    if pdf.get_y() > 215:
        pdf.add_page()

    seal_y = pdf.get_y()
    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*COLOR_GOLD)
    pdf.set_line_width(0.6)

    # کادر مهر رسمی در سمت راست صفحه
    seal_x = 114
    seal_width = 80
    seal_height = 29
    pdf.rect(seal_x, seal_y, seal_width, seal_height, style="DF")

    pdf.set_xy(seal_x + 2, seal_y + 3)
    pdf.set_font("Vazirmatn", "B", 9)
    pdf.set_text_color(*COLOR_NAVY)
    pdf.cell(
        seal_width - 4,
        5,
        "مهر و امضای رسمی وزارت امور خارجه",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(seal_x + 2)
    pdf.cell(
        seal_width - 4,
        5,
        sender_country_name,
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(seal_x + 2)
    pdf.set_font("Vazirmatn", "", 7.5)
    pdf.set_text_color(*COLOR_GOLD)
    pdf.cell(
        seal_width - 4,
        5,
        "MINISTRY OF FOREIGN AFFAIRS - OFFICIAL SEAL",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(seal_x + 2)
    pdf.cell(
        seal_width - 4,
        5,
        "DIPLOMATIC MISSION & STATE DISPATCH",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # بازگرداندن بایت‌های PDF تولید شده در حافظه RAM
    pdf_bytes = pdf.output()
    return bytes(pdf_bytes)
