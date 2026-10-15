"""
سرویس تولید تصویر اسناد رسمی دیپلماتیک (v2.7).

این سرویس نامه‌های دیپلماتیک میان کشورها را به یک تصویر گرافیکی شکیل با
ابعاد داینامیک، سربرگ سرمه‌ای و طلایی، مشخصات فرستنده و گیرنده، شماره سند،
متن نامه و مهر رسمی تبدیل می‌کند.

تولید کاملاً در حافظه‌ی رم (In-Memory) انجام شده و به هیچ عنوان فایلی روی دیسک ذخیره نمی‌شود.
"""

from __future__ import annotations

import io
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from ..utils.numbers import to_fa_digits

logger = logging.getLogger(__name__)

# رنگ‌بندی استاندارد سند رسمی
COLOR_BG = "#FCFBF7"          # پس‌زمینه کاغذی و عاجی دیپلماتیک
COLOR_NAVY = "#0A192F"        # سرمه‌ای سلطنتی رسمی
COLOR_GOLD = "#C5A059"        # طلایی رسمی
COLOR_BOX_BG = "#F4EFE6"      # پس‌زمینه کادر مشخصات
COLOR_TEXT_MAIN = "#1E293B"   # رنگ دودی تیره برای متون
COLOR_TEXT_MUTED = "#64748B"  # رنگ خاکستری ملایم

# الگوی حذف ایموجی‌ها جهت جلوگیری از افتادن مربع توخالی در Pillow
EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe0f]",
    flags=re.UNICODE,
)

# مسیر فونت‌های پروژه
_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fonts"
_FONT_REGULAR_PATH = _FONTS_DIR / "Vazirmatn-Regular.ttf"
_FONT_BOLD_PATH = _FONTS_DIR / "Vazirmatn-Bold.ttf"

_URL_REGULAR = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Regular.ttf"
_URL_BOLD = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf/Vazirmatn-Bold.ttf"


def clean_emojis(text: str) -> str:
    """حذف ایموجی‌ها از رشته متنی برای جلوگیری از رسم کادر مربع توخالی در Pillow."""
    if not text:
        return ""
    return EMOJI_PATTERN.sub("", text)


def prepare_rtl(text: str) -> str:
    """اتصال صحیح حروف فارسی و جهت‌دهی راست به چپ (RTL)."""
    cleaned = clean_emojis(text).strip()
    if not cleaned:
        return ""
    return get_display(arabic_reshaper.reshape(cleaned))


def _ensure_fonts() -> tuple[str, str]:
    """بررسی وجود فونت‌های استاندارد فارسی در data/fonts و دانلود خودکار در صورت نیاز."""
    try:
        _FONTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create fonts directory: %s", exc)

    if not _FONT_REGULAR_PATH.exists():
        try:
            logger.info("Downloading Vazirmatn-Regular font...")
            urllib.request.urlretrieve(_URL_REGULAR, str(_FONT_REGULAR_PATH))
        except Exception as exc:
            logger.warning("Failed to download Vazirmatn-Regular: %s", exc)

    if not _FONT_BOLD_PATH.exists():
        try:
            logger.info("Downloading Vazirmatn-Bold font...")
            urllib.request.urlretrieve(_URL_BOLD, str(_FONT_BOLD_PATH))
        except Exception as exc:
            logger.warning("Failed to download Vazirmatn-Bold: %s", exc)

    reg_str = str(_FONT_REGULAR_PATH) if _FONT_REGULAR_PATH.exists() else ""
    bold_str = str(_FONT_BOLD_PATH) if _FONT_BOLD_PATH.exists() else ""

    # فالبک به فونت‌های ویندوز
    if not reg_str:
        for win_font in ["C:\\Windows\\Fonts\\tahoma.ttf", "C:\\Windows\\Fonts\\arial.ttf"]:
            if os.path.exists(win_font):
                reg_str = win_font
                bold_str = win_font
                break

    return reg_str, bold_str


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """
    شکستن پاراگراف‌های متن به خطوط مجزا بر اساس عرض واقعی پیکسل‌ها.
    سپس هر خط جداگانه RTL می‌شود تا ترتیب جملات از بالا به پایین برعکس نشود.
    """
    lines = []
    for paragraph in text.splitlines():
        p = paragraph.strip()
        if not p:
            lines.append("")
            continue
        words = p.split()
        current_words: list[str] = []
        for w in words:
            test_line = " ".join(current_words + [w])
            bbox = font.getbbox(prepare_rtl(test_line))
            line_w = bbox[2] - bbox[0]
            if line_w <= max_width:
                current_words.append(w)
            else:
                if current_words:
                    lines.append(" ".join(current_words))
                    current_words = [w]
                else:
                    lines.append(w)
                    current_words = []
        if current_words:
            lines.append(" ".join(current_words))
    return lines


def render_diplomatic_letter_image(
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
    رندر کردن تصویر گرافیکی سند رسمی دیپلماتیک در حافظه RAM و بازگرداندن بایت‌های PNG.

    ویژگی‌ها:
    - ابعاد داینامیک با عرض ۱۰۰۰ پیکسل و حداقل ارتفاع ۷۵۰ پیکسل.
    - سربرگ رسمی وزارت امور خارجه با رنگ‌بندی سرمه‌ای و طلایی.
    - جدول مشخصات فرستنده، رهبر، گیرنده، نوع سند، شماره ثبت و تاریخ.
    - خط‌بندی دقیق فارسی (RTL) بدون تداخل و بدون حروف برعکس.
    - کادر مهر و امضای رسمی وزارت امور خارجه فرستنده و پاورقی ثبت دبیرخانه.
    """
    font_reg_path, font_bold_path = _ensure_fonts()

    # بارگذاری فونت‌ها در اندازه‌های متناسب
    if font_reg_path and font_bold_path:
        font_title = ImageFont.truetype(font_bold_path, 23)
        font_sub = ImageFont.truetype(font_reg_path, 12)
        font_meta_bold = ImageFont.truetype(font_bold_path, 16)
        font_meta_reg = ImageFont.truetype(font_reg_path, 15)
        font_body_bold = ImageFont.truetype(font_bold_path, 18)
        font_body = ImageFont.truetype(font_reg_path, 18)
        font_seal_bold = ImageFont.truetype(font_bold_path, 14)
        font_seal_reg = ImageFont.truetype(font_reg_path, 10)
        font_foot = ImageFont.truetype(font_reg_path, 13)
    else:
        # فالبک به فونت دیفالت Pillow در صورت عدم دسترسی به فایل فونت
        font_title = font_sub = font_meta_bold = font_meta_reg = ImageFont.load_default()
        font_body_bold = font_body = font_seal_bold = font_seal_reg = font_foot = ImageFont.load_default()

    # پاکسازی ایموجی‌ها از متون جهت جلوگیری از مربع توخالی
    clean_sender_country = clean_emojis(sender_country_name).strip()
    clean_sender_leader = clean_emojis(sender_leader_name).strip() if sender_leader_name else None
    clean_recipient_country = clean_emojis(recipient_country_name).strip()

    # فرمت‌بندی فرستنده
    if clean_sender_leader:
        sender_display = f"{clean_sender_country} (رهبر: {clean_sender_leader})"
    else:
        sender_display = clean_sender_country

    # فرمت‌بندی گیرنده
    if is_all:
        recipient_display = "تمامی کشورهای جهان"
    elif is_allies:
        recipient_display = f"اعضای اتحاد — {clean_recipient_country}"
    else:
        recipient_display = clean_recipient_country

    # تعیین موضوع و نوع سند
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

    # خط‌بندی متن اصلی نامه (عرض محتوا: ۸۷۰ پیکسل)
    lines = _wrap_text(clean_emojis(body), font_body, max_width=870)

    # محاسبه داینامیک ارتفاع بوم تصویر
    box_y = 115
    has_reply = parent_id is not None
    box_height = 195 if has_reply else 165

    body_label_y = box_y + box_height + 22
    body_start_y = body_label_y + 32
    line_height = 34
    body_total_height = max(len(lines) * line_height, 90)

    seal_y = body_start_y + body_total_height + 25
    seal_height = 105
    required_height = seal_y + seal_height + 65
    canvas_height = max(750, required_height)
    canvas_width = 1000

    # ساخت تصویر
    im = Image.new("RGB", (canvas_width, canvas_height), COLOR_BG)
    draw = ImageDraw.Draw(im)

    # ۱. کادربندی دوگانه برگه
    draw.rectangle([16, 16, canvas_width - 16, canvas_height - 16], outline=COLOR_NAVY, width=4)
    draw.rectangle([24, 24, canvas_width - 24, canvas_height - 24], outline=COLOR_GOLD, width=2)

    # ۲. نوار سربرگ سرمه‌ای و طلایی
    draw.rectangle([16, 16, canvas_width - 16, 95], fill=COLOR_NAVY)
    draw.line([16, 95, canvas_width - 16, 95], fill=COLOR_GOLD, width=3)

    title_text = prepare_rtl("وزارت امور خارجه — سند رسمی مکاتبات دیپلماتیک")
    b_title = font_title.getbbox(title_text)
    draw.text(((canvas_width - (b_title[2] - b_title[0])) // 2, 28), title_text, fill=COLOR_GOLD, font=font_title)

    sub_text = "OFFICIAL DIPLOMATIC CORRESPONDENCE — THE EARTH GAME"
    b_sub = font_sub.getbbox(sub_text)
    draw.text(((canvas_width - (b_sub[2] - b_sub[0])) // 2, 65), sub_text, fill="#94A3B8", font=font_sub)

    # ۳. کادر مشخصات سند دیپلماتیک
    draw.rectangle([45, box_y, 955, box_y + box_height], fill=COLOR_BOX_BG, outline=COLOR_GOLD, width=2)

    meta_rows = [
        (f"فرستنده (از طرف): {sender_display}", font_meta_bold, COLOR_NAVY),
        (f"گیرنده (به مقصد): {recipient_display}", font_meta_bold, COLOR_NAVY),
        (f"نوع سند: {letter_type}", font_meta_bold, COLOR_NAVY),
        (f"شماره سند: #{to_fa_digits(letter_id)}   |   تاریخ و ساعت ارسال: {date_str}", font_meta_reg, "#475569"),
    ]
    if has_reply:
        meta_rows.append(
            (f"در پاسخ به نامه شماره #{to_fa_digits(parent_id)}", font_meta_bold, COLOR_GOLD)
        )

    row_y = box_y + 14
    for row_text, f, col in meta_rows:
        t_rtl = prepare_rtl(row_text)
        bb = f.getbbox(t_rtl)
        draw.text((935 - (bb[2] - bb[0]), row_y), t_rtl, fill=col, font=f)
        row_y += 32

    # ۴. عنوان و خطوط متن اصلی نامه
    lbl_text = prepare_rtl("متن رسمی نامه:")
    b_lbl = font_body_bold.getbbox(lbl_text)
    draw.text((935 - (b_lbl[2] - b_lbl[0]), body_label_y), lbl_text, fill=COLOR_NAVY, font=font_body_bold)

    cur_y = body_start_y
    for line in lines:
        if line.strip():
            l_rtl = prepare_rtl(line)
            bb = font_body.getbbox(l_rtl)
            draw.text((935 - (bb[2] - bb[0]), cur_y), l_rtl, fill=COLOR_TEXT_MAIN, font=font_body)
        cur_y += line_height

    # ۵. کادر مهر و امضای رسمی وزارت امور خارجه
    seal_x1, seal_x2 = 585, 945
    seal_width = seal_x2 - seal_x1
    draw.rectangle([seal_x1, seal_y, seal_x2, seal_y + seal_height], fill="#FFFFFF", outline=COLOR_GOLD, width=2)

    s1 = prepare_rtl("مهر و امضای رسمی وزارت امور خارجه")
    b_s1 = font_seal_bold.getbbox(s1)
    draw.text((seal_x1 + (seal_width - (b_s1[2] - b_s1[0])) // 2, seal_y + 12), s1, fill=COLOR_NAVY, font=font_seal_bold)

    s2 = prepare_rtl(clean_sender_country)
    b_s2 = font_seal_bold.getbbox(s2)
    draw.text((seal_x1 + (seal_width - (b_s2[2] - b_s2[0])) // 2, seal_y + 37), s2, fill=COLOR_NAVY, font=font_seal_bold)

    s3 = "MINISTRY OF FOREIGN AFFAIRS - OFFICIAL SEAL"
    b_s3 = font_seal_reg.getbbox(s3)
    draw.text((seal_x1 + (seal_width - (b_s3[2] - b_s3[0])) // 2, seal_y + 63), s3, fill=COLOR_GOLD, font=font_seal_reg)

    s4 = "DIPLOMATIC MISSION & STATE DISPATCH"
    b_s4 = font_seal_reg.getbbox(s4)
    draw.text((seal_x1 + (seal_width - (b_s4[2] - b_s4[0])) // 2, seal_y + 80), s4, fill=COLOR_TEXT_MUTED, font=font_seal_reg)

    # ۶. پاورقی ثبت دبیرخانه دیپلماسی جهانی
    foot_text = prepare_rtl("ثبت‌شده در دبیرخانه دیپلماسی جهانی (The Earth Game)")
    b_foot = font_foot.getbbox(foot_text)
    draw.text(((canvas_width - (b_foot[2] - b_foot[0])) // 2, canvas_height - 38), foot_text, fill=COLOR_TEXT_MUTED, font=font_foot)

    # ذخیره تصویر در بافر حافظه RAM به صورت PNG
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
