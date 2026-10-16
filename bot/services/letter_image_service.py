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
import random
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from ..utils.numbers import to_fa_digits

logger = logging.getLogger(__name__)

# رنگ‌بندی استاندارد اسناد رسمی
COLOR_BG = "#FCFBF7"          # پس‌زمینه کاغذی و عاجی دیپلماتیک
COLOR_NAVY = "#0A192F"        # سرمه‌ای سلطنتی رسمی
COLOR_GOLD = "#C5A059"        # طلایی رسمی
COLOR_BOX_BG = "#F4EFE6"      # پس‌زمینه کادر مشخصات
COLOR_TEXT_MAIN = "#1E293B"   # رنگ دودی تیره برای متون
COLOR_TEXT_MUTED = "#64748B"  # رنگ خاکستری ملایم

# رنگ‌بندی ویژه معاهدات بین‌المللی (v2.9)
COLOR_PARCHMENT = "#FDFBF7"   # کاغذ عتیقه و عاجی معاهدات
COLOR_BRONZE = "#3D2B1F"      # برنزی اشرافی برای کادربندی
COLOR_INK = "#0E2442"         # جوهر سرمه‌ای سیر امضاها
COLOR_WAX_BORDER = "#8B1E1E"  # حاشیه زرشکی مهر مومی
COLOR_WAX_FILL = "#FCF5F5"    # زمینه ملایم مهر مومی

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


# ============================================================
#  سرویس تصویرسازی معاهدات و توافق‌نامه‌های رسمی بین‌المللی (v2.9)
# ============================================================

def _draw_ink_signature(
    draw: ImageDraw.ImageDraw,
    x_center: int,
    y_center: int,
    seed_text: str,
    ink_color: str = COLOR_INK,
) -> None:
    """
    رسم امضای جوهری خوش‌نویسی شده و واقع‌گرایانه با خطوط روان بر اساس مشخصات کشور/رهبر.
    تولید منحنی‌ها به صورت قطعی (Deterministic) بر اساس seed_text انجام می‌پذیرد.
    """
    seed_val = sum(ord(c) for c in (seed_text or "DefaultTreatySign")) + len(seed_text or "")
    rng = random.Random(seed_val)

    # ۱. حلقه بزرگ اولیه قلم (Flourish loop)
    start_x = x_center - 110 + rng.randint(-5, 5)
    start_y = y_center + rng.randint(0, 8)

    loop_top_x = start_x + 18 + rng.randint(0, 8)
    loop_top_y = y_center - 26 - rng.randint(4, 10)
    loop_mid_x = start_x + 36 + rng.randint(0, 8)
    loop_mid_y = y_center + 10 + rng.randint(0, 8)

    pts: list[tuple[float, float]] = []
    for step in range(9):
        t = step / 8.0
        bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * loop_top_x + t**2 * loop_mid_x
        by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * loop_top_y + t**2 * loop_mid_y
        pts.append((bx, by))

    # ۲. نوسانات سریع کلمات خط شکسته (Cursive waves)
    curr_x = loop_mid_x
    wave_count = rng.randint(5, 7)
    for _ in range(wave_count):
        dx = rng.randint(12, 18)
        # قله موج
        curr_x += dx * 0.5
        peak_y = y_center - rng.randint(10, 20)
        pts.append((curr_x, peak_y))
        # فرود موج
        curr_x += dx * 0.5
        trough_y = y_center + rng.randint(2, 10)
        pts.append((curr_x, trough_y))

    # ۳. انتهای پرتابی قلم
    end_x = curr_x + rng.randint(18, 30)
    end_y = y_center - rng.randint(4, 10)
    pts.append((end_x, end_y))

    # رسم خطوط متصل امضا با ضخامت متغیر
    for i in range(len(pts) - 1):
        w = 3 if (i % 3 == 0 or i == 0) else 2
        draw.line([pts[i], pts[i + 1]], fill=ink_color, width=w)

    # ۴. خط افقی سریع زیر امضا با انحنای ملایم (Underline flourish)
    u_start_x = start_x + 5
    u_start_y = y_center + 18
    u_ctrl_x = x_center + rng.randint(-10, 10)
    u_ctrl_y = y_center + 24 + rng.randint(0, 5)
    u_end_x = end_x + 15
    u_end_y = y_center + 14

    u_pts: list[tuple[float, float]] = []
    for step in range(11):
        t = step / 10.0
        ux = (1 - t) ** 2 * u_start_x + 2 * (1 - t) * t * u_ctrl_x + t**2 * u_end_x
        uy = (1 - t) ** 2 * u_start_y + 2 * (1 - t) * t * u_ctrl_y + t**2 * u_end_y
        u_pts.append((ux, uy))
    for i in range(len(u_pts) - 1):
        draw.line([u_pts[i], u_pts[i + 1]], fill=ink_color, width=2)


def _draw_wax_seal(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int = 38,
) -> None:
    """رسم مهر رسمی دیپلماتیک دایره‌ای با نشان مومی برجسته بین‌المللی."""
    # ۱. دایره بیرونی مومی
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=COLOR_WAX_FILL,
        outline=COLOR_WAX_BORDER,
        width=3,
    )
    # ۲. حلقه داخلی طلایی
    r_inner = radius - 5
    draw.ellipse(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        outline=COLOR_GOLD,
        width=2,
    )
    # ۳. حلقه مرکزی مومی
    r_center = radius - 13
    draw.ellipse(
        [cx - r_center, cy - r_center, cx + r_center, cy + r_center],
        fill="#FAF0E6",
        outline=COLOR_WAX_BORDER,
        width=1,
    )

    # ستاره و نشان دیپلماتیک متقاطع طلایی و زرشکی
    draw.line([cx - 10, cy, cx + 10, cy], fill=COLOR_GOLD, width=2)
    draw.line([cx, cy - 10, cx, cy + 10], fill=COLOR_GOLD, width=2)
    draw.line([cx - 7, cy - 7, cx + 7, cy + 7], fill=COLOR_WAX_BORDER, width=1)
    draw.line([cx - 7, cy + 7, cx + 7, cy - 7], fill=COLOR_WAX_BORDER, width=1)
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=COLOR_WAX_BORDER)


def render_contract_image(
    *,
    contract_id: int,
    title: str,
    country_a_name: str,
    country_a_flag: str = "",
    country_a_leader: str | None = None,
    country_b_name: str,
    country_b_flag: str = "",
    country_b_leader: str | None = None,
    body: str,
    created_at: datetime | None = None,
) -> bytes:
    """
    رندر کردن تصویر گرافیکی سند رسمی معاهده بین‌المللی در حافظه RAM و بازگرداندن بایت‌های PNG.

    ویژگی‌ها:
    - تم کاغذ عتیقه، حاشیه‌بندی کلاسیک برنزی و طلایی و گوشه‌های تزیینی.
    - سربرگ تشریفاتی دوزبانه معاهدات بین‌المللی.
    - جدول جامع مشخصات طرفین، شماره ثبت معاهده و تاریخ UTC.
    - محاسبه پویا و داینامیک ارتفاع بوم در Pillow جهت جلوگیری از بریدگی متن.
    - دو ستون مجزا در پایین سند برای امضای طرفین با خطوط امضای جوهری خوش‌نویسی و مهر موم رسمی دیپلماتیک.
    """
    font_reg_path, font_bold_path = _ensure_fonts()

    if font_reg_path and font_bold_path:
        font_title = ImageFont.truetype(font_bold_path, 22)
        font_sub = ImageFont.truetype(font_reg_path, 11)
        font_meta_bold = ImageFont.truetype(font_bold_path, 15)
        font_meta_reg = ImageFont.truetype(font_reg_path, 14)
        font_body_bold = ImageFont.truetype(font_bold_path, 18)
        font_body = ImageFont.truetype(font_reg_path, 17)
        font_sig_title = ImageFont.truetype(font_bold_path, 14)
        font_sig_meta = ImageFont.truetype(font_reg_path, 13)
        font_sig_small = ImageFont.truetype(font_reg_path, 10)
        font_foot = ImageFont.truetype(font_reg_path, 12)
    else:
        font_title = font_sub = font_meta_bold = font_meta_reg = ImageFont.load_default()
        font_body_bold = font_body = font_sig_title = font_sig_meta = font_sig_small = font_foot = ImageFont.load_default()

    clean_title = clean_emojis(title).strip() or "معاهده دوجانبه"
    clean_a = clean_emojis(country_a_name).strip()
    clean_b = clean_emojis(country_b_name).strip()
    clean_leader_a = clean_emojis(country_a_leader).strip() if country_a_leader else "رهبر رسمی کشور"
    clean_leader_b = clean_emojis(country_b_leader).strip() if country_b_leader else "رهبر رسمی کشور"

    # فرمت‌بندی تاریخ
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    date_str = to_fa_digits(created_at.strftime("%Y/%m/%d — %H:%M")) + " (UTC)"

    # خط‌بندی متن اصلی معاهده (عرض محتوا: ۸۶۰ پیکسل)
    lines = _wrap_text(clean_emojis(body), font_body, max_width=860)

    box_y = 115
    box_height = 160

    body_label_y = box_y + box_height + 22
    body_start_y = body_label_y + 32
    line_height = 32
    body_total_height = max(len(lines) * line_height, 80)

    sig_y = body_start_y + body_total_height + 30
    sig_block_height = 175
    required_height = sig_y + sig_block_height + 65
    canvas_height = max(860, required_height)
    canvas_width = 1000

    im = Image.new("RGB", (canvas_width, canvas_height), COLOR_PARCHMENT)
    draw = ImageDraw.Draw(im)

    # ۱. کادربندی تشریفاتی چندگانه برگه (برنزی و طلایی)
    draw.rectangle([14, 14, canvas_width - 14, canvas_height - 14], outline=COLOR_BRONZE, width=4)
    draw.rectangle([22, 22, canvas_width - 22, canvas_height - 22], outline=COLOR_GOLD, width=2)
    # تزیین گوشه‌های کادر
    for cx_c, cy_c in [
        (22, 22),
        (canvas_width - 22, 22),
        (22, canvas_height - 22),
        (canvas_width - 22, canvas_height - 22),
    ]:
        draw.rectangle([cx_c - 5, cy_c - 5, cx_c + 5, cy_c + 5], fill=COLOR_GOLD, outline=COLOR_BRONZE)

    # ۲. نوار سربرگ معاهده
    draw.rectangle([14, 14, canvas_width - 14, 95], fill="#1E1B18")
    draw.line([14, 95, canvas_width - 14, 95], fill=COLOR_GOLD, width=3)

    title_text = prepare_rtl("معاهده و توافق‌نامه رسمی بین‌المللی")
    b_title = font_title.getbbox(title_text)
    draw.text(((canvas_width - (b_title[2] - b_title[0])) // 2, 26), title_text, fill=COLOR_GOLD, font=font_title)

    sub_text = "OFFICIAL INTERNATIONAL TREATY & AGREEMENT — GLOBAL REGISTRY"
    b_sub = font_sub.getbbox(sub_text)
    draw.text(((canvas_width - (b_sub[2] - b_sub[0])) // 2, 64), sub_text, fill="#D1D5DB", font=font_sub)

    # ۳. جدول مشخصات دیپلماتیک معاهده
    draw.rectangle([45, box_y, 955, box_y + box_height], fill=COLOR_BOX_BG, outline=COLOR_GOLD, width=2)

    party_a_disp = f"{clean_a} (نماینده: {clean_leader_a})"
    party_b_disp = f"{clean_b} (نماینده: {clean_leader_b})"

    meta_rows = [
        (f"موضوع معاهده: {clean_title}", font_meta_bold, COLOR_BRONZE),
        (f"طرفین معاهده: {party_a_disp}   ↔   {party_b_disp}", font_meta_bold, "#1A2332"),
        (f"شماره ثبت بین‌المللی معاهده: #{to_fa_digits(contract_id)}   |   تاریخ و زمان رسمی انعقاد: {date_str}", font_meta_reg, "#475569"),
        ("وضعیت حقوقی: لازم‌الاجرا و نهایی در نظام بین‌الملل (Active & Ratified)", font_meta_bold, "#15803D"),
    ]

    row_y = box_y + 14
    for row_text, f, col in meta_rows:
        t_rtl = prepare_rtl(row_text)
        bb = f.getbbox(t_rtl)
        draw.text((935 - (bb[2] - bb[0]), row_y), t_rtl, fill=col, font=f)
        row_y += 34

    # ۴. متن و بندهای معاهده
    lbl_text = prepare_rtl("متن و مفاد لازم‌الاجرای معاهده:")
    b_lbl = font_body_bold.getbbox(lbl_text)
    draw.text((935 - (b_lbl[2] - b_lbl[0]), body_label_y), lbl_text, fill=COLOR_BRONZE, font=font_body_bold)

    cur_y = body_start_y
    for line in lines:
        if line.strip():
            l_rtl = prepare_rtl(line)
            bb = font_body.getbbox(l_rtl)
            draw.text((935 - (bb[2] - bb[0]), cur_y), l_rtl, fill=COLOR_TEXT_MAIN, font=font_body)
        cur_y += line_height

    # ۵. بخش امضاها و مهر رسمی (دو ستون مجزا + مهر در وسط)
    # کادر طرف دوم (سمت چپ بوم)
    b_x1, b_x2 = 45, 435
    draw.rectangle([b_x1, sig_y, b_x2, sig_y + sig_block_height], fill="#FFFFFF", outline=COLOR_GOLD, width=1)
    # کادر طرف اول (سمت راست بوم)
    a_x1, a_x2 = 565, 955
    draw.rectangle([a_x1, sig_y, a_x2, sig_y + sig_block_height], fill="#FFFFFF", outline=COLOR_GOLD, width=1)

    # اطلاعات طرف اول (راست)
    a_center = (a_x1 + a_x2) // 2
    t_a1 = prepare_rtl(f"طرف اول: {clean_a}")
    b_a1 = font_sig_title.getbbox(t_a1)
    draw.text((a_center - (b_a1[2] - b_a1[0]) // 2, sig_y + 10), t_a1, fill=COLOR_BRONZE, font=font_sig_title)

    t_a2 = prepare_rtl(f"مقام امضاکننده: {clean_leader_a}")
    b_a2 = font_sig_meta.getbbox(t_a2)
    draw.text((a_center - (b_a2[2] - b_a2[0]) // 2, sig_y + 32), t_a2, fill="#475569", font=font_sig_meta)

    # امضای جوهری طرف اول
    _draw_ink_signature(draw, a_center, sig_y + 85, seed_text=f"{clean_a}_{clean_leader_a}_{contract_id}_a")
    # خط امضا
    draw.line([a_x1 + 30, sig_y + 130, a_x2 - 30, sig_y + 130], fill="#CBD5E1", width=1)
    t_a3 = prepare_rtl("امضای رسمی تأییدشده در پروتکل دیپلماتیک")
    b_a3 = font_sig_small.getbbox(t_a3)
    draw.text((a_center - (b_a3[2] - b_a3[0]) // 2, sig_y + 140), t_a3, fill=COLOR_TEXT_MUTED, font=font_sig_small)
    s_a4 = "DIGITALLY SIGNED & RATIFIED"
    b_a4 = font_sig_small.getbbox(s_a4)
    draw.text((a_center - (b_a4[2] - b_a4[0]) // 2, sig_y + 155), s_a4, fill="#94A3B8", font=font_sig_small)

    # اطلاعات طرف دوم (چپ)
    b_center = (b_x1 + b_x2) // 2
    t_b1 = prepare_rtl(f"طرف دوم: {clean_b}")
    b_b1 = font_sig_title.getbbox(t_b1)
    draw.text((b_center - (b_b1[2] - b_b1[0]) // 2, sig_y + 10), t_b1, fill=COLOR_BRONZE, font=font_sig_title)

    t_b2 = prepare_rtl(f"مقام امضاکننده: {clean_leader_b}")
    b_b2 = font_sig_meta.getbbox(t_b2)
    draw.text((b_center - (b_b2[2] - b_b2[0]) // 2, sig_y + 32), t_b2, fill="#475569", font=font_sig_meta)

    # امضای جوهری طرف دوم
    _draw_ink_signature(draw, b_center, sig_y + 85, seed_text=f"{clean_b}_{clean_leader_b}_{contract_id}_b")
    # خط امضا
    draw.line([b_x1 + 30, sig_y + 130, b_x2 - 30, sig_y + 130], fill="#CBD5E1", width=1)
    t_b3 = prepare_rtl("امضای رسمی تأییدشده در پروتکل دیپلماتیک")
    b_b3 = font_sig_small.getbbox(t_b3)
    draw.text((b_center - (b_b3[2] - b_b3[0]) // 2, sig_y + 140), t_b3, fill=COLOR_TEXT_MUTED, font=font_sig_small)
    s_b4 = "DIGITALLY SIGNED & RATIFIED"
    b_b4 = font_sig_small.getbbox(s_b4)
    draw.text((b_center - (b_b4[2] - b_b4[0]) // 2, sig_y + 155), s_b4, fill="#94A3B8", font=font_sig_small)

    # مهر مومی برجسته بین دو ستون (در مختصات وسط)
    seal_cx = 500
    seal_cy = sig_y + 75
    _draw_wax_seal(draw, seal_cx, seal_cy, radius=38)

    t_seal = prepare_rtl("مهر رسمی معاهده")
    b_s = font_sig_small.getbbox(t_seal)
    draw.text((seal_cx - (b_s[2] - b_s[0]) // 2, sig_y + 122), t_seal, fill="#8B1E1E", font=font_sig_small)

    s_seal2 = "TREATY SEAL"
    b_s2 = font_sig_small.getbbox(s_seal2)
    draw.text((seal_cx - (b_s2[2] - b_s2[0]) // 2, sig_y + 138), s_seal2, fill=COLOR_GOLD, font=font_sig_small)

    # ۶. پاورقی دیپلماتیک
    foot_text = prepare_rtl("ثبت‌شده در دیوان بین‌المللی دیپلماسی و معاهدات جهان (The Earth Game)")
    b_foot = font_foot.getbbox(foot_text)
    draw.text(((canvas_width - (b_foot[2] - b_foot[0])) // 2, canvas_height - 38), foot_text, fill=COLOR_TEXT_MUTED, font=font_foot)

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()

