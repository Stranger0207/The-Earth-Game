"""
سرویس رندر گرافیکی تصویر توییت (X Dark Mode) با Pillow.

این سرویس توییت‌های ارسالی کشورها را به تصویری با طراحی Dark Mode توییتر
(مشابه اسکرین‌شات واقعی X)، شامل آواتار دایره‌ای، تیک آبی رسمی (Verified Badge)،
نام و یوزرنیم کشور، متن با قالب‌بندی استاندارد، تاریخ انتشار و نوار آیکون‌های تعاملی
(Reply, Repost, Like, Share) در حافظه RAM تبدیل می‌کند.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .letter_image_service import (
    _ensure_fonts,
    clean_emojis,
    prepare_rtl,
    _wrap_text,
)
from ..utils.numbers import to_fa_digits

logger = logging.getLogger(__name__)

# رنگ‌بندی Dark Mode توییتر / X
COLOR_BG = "#000000"           # پس‌زمینه مشکی خالص
COLOR_CARD_BORDER = "#2F3336"  # کادر بیرونی و خطوط جداکننده خاکستری تیره
COLOR_TEXT_MAIN = "#E7E9EA"    # متن سفید / نقره‌ای روشن
COLOR_TEXT_MUTED = "#71767B"   # خاکستری استاندارد هدر و آیکون‌ها
COLOR_VERIFIED_BLUE = "#1D9BF0"# آبی فیروزه‌ای تیک تایید توییتر
COLOR_WHITE = "#FFFFFF"


def _draw_verified_badge(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int = 11
) -> None:
    """رسم تیک آبی رسمی توییتر (Verified Badge) با دایره فیروزه‌ای و تیک سفید."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=COLOR_VERIFIED_BLUE)
    # رسم خطوط تیک ✓
    p1 = (cx - radius * 0.45, cy - radius * 0.05)
    p2 = (cx - radius * 0.15, cy + radius * 0.35)
    p3 = (cx + radius * 0.45, cy - radius * 0.35)
    draw.line([p1, p2], fill=COLOR_WHITE, width=2)
    draw.line([p2, p3], fill=COLOR_WHITE, width=2)


def process_avatar_upload(image_bytes: bytes, target_size: int = 512) -> bytes:
    """
    پردازش و اعتبارسنجی تصویر آواتار آپلودشده:
    - تصحیح جهت EXIF
    - تبدیل مودهای رنگی به RGB با پس‌زمینه سفید
    - کراپ مربعی دقیق ۱:۱ از مرکز به اندازه target_size
    - بازگرداندن بایت‌های PNG
    """
    if not image_bytes:
        raise ValueError("فایل تصویر خالی است.")

    Image.MAX_IMAGE_PIXELS = 25_000_000
    try:
        raw_img = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        raise ValueError("فرمت فایل نامعتبر است یا تصویر آسیب دیده است.") from exc

    w, h = raw_img.size
    if w < 16 or h < 16:
        raise ValueError("ابعاد تصویر بسیار کوچک است (حداقل ۱۶×۱۶ پیکسل).")
    if w > 8000 or h > 8000:
        raise ValueError("ابعاد تصویر بیش از حد بزرگ است (حداکثر ۸۰۰۰×۸۰۰۰ پیکسل).")

    img = ImageOps.exif_transpose(raw_img)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        img = bg
    else:
        img = img.convert("RGB")

    cropped = ImageOps.fit(
        img, (target_size, target_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )

    out_buf = io.BytesIO()
    cropped.save(out_buf, format="PNG", optimize=True)
    return out_buf.getvalue()


def _draw_circular_avatar(
    avatar_image: Image.Image | None, size: int = 80
) -> Image.Image:
    """برش تصویر آواتار به صورت کاملاً دایره‌ای با ماسک شفافیت و supersampling بدون دندانه."""
    if avatar_image is None:
        # فالبک به آواتار پیش‌فرض خاکستری
        im = Image.new("RGBA", (size, size), (47, 51, 54, 255))
        draw = ImageDraw.Draw(im)
        draw.ellipse([0, 0, size, size], fill="#3E4144")
        draw.ellipse([size * 0.25, size * 0.18, size * 0.75, size * 0.58], fill="#71767B")
        draw.ellipse([size * 0.12, size * 0.62, size * 0.88, size * 1.15], fill="#71767B")
        return im

    # اصلاح چرخش EXIF و کراپ مربعی ۱:۱ از مرکز برای جلوگیری از کشیدگی تصاویر مستطیلی قدیمی
    img = ImageOps.exif_transpose(avatar_image)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
        img = bg
    else:
        img = img.convert("RGBA")

    # کراپ دقیق ۱:۱ از مرکز
    square_img = ImageOps.fit(
        img, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )

    # ماسک دایره‌ای با ابرنمونه‌برداری (supersampling 4x) برای لبه‌های کاملاً نرم و صیقلی
    scale = 4
    large_size = size * scale
    mask = Image.new("L", (large_size, large_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse([0, 0, large_size - 1, large_size - 1], fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)

    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(square_img, (0, 0), mask=mask)
    return output


def _draw_reply_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """رسم آیکون کامنت/ریپلای 💬"""
    r = 10
    draw.arc([cx - r, cy - r, cx + r, cy + r - 3], start=45, end=315, fill=COLOR_TEXT_MUTED, width=2)
    # دم حباب گفت‌وگو
    draw.line([cx - r + 3, cy + r - 5, cx - r - 2, cy + r + 1], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - r - 2, cy + r + 1, cx - 2, cy + r - 3], fill=COLOR_TEXT_MUTED, width=2)


def _draw_repost_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """رسم آیکون ریتوییت 🔁"""
    # فلش بالایی (به سمت راست)
    draw.line([cx - 8, cy - 4, cx + 5, cy - 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 2, cy - 7, cx + 5, cy - 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 2, cy - 1, cx + 5, cy - 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - 8, cy - 4, cx - 8, cy - 1], fill=COLOR_TEXT_MUTED, width=2)

    # فلش پایینی (به سمت چپ)
    draw.line([cx + 8, cy + 4, cx - 5, cy + 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - 2, cy + 1, cx - 5, cy + 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - 2, cy + 7, cx - 5, cy + 4], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 8, cy + 4, cx + 8, cy + 1], fill=COLOR_TEXT_MUTED, width=2)


def _draw_heart_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """رسم آیکون قلب/لایک ❤️"""
    # خطوط شکسته فرم قلب
    top_y = cy - 6
    mid_y = cy - 2
    bot_y = cy + 7
    # لوب سمت چپ
    draw.arc([cx - 8, top_y, cx - 1, mid_y + 3], start=140, end=0, fill=COLOR_TEXT_MUTED, width=2)
    # لوب سمت راست
    draw.arc([cx + 1, top_y, cx + 8, mid_y + 3], start=180, end=40, fill=COLOR_TEXT_MUTED, width=2)
    # گوشه‌های پایینی
    draw.line([cx - 8, mid_y, cx, bot_y], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 8, mid_y, cx, bot_y], fill=COLOR_TEXT_MUTED, width=2)


def _draw_share_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """رسم آیکون اشتراک‌گذاری 📤"""
    # سینی پایین
    draw.line([cx - 7, cy + 1, cx - 7, cy + 7], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - 7, cy + 7, cx + 7, cy + 7], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 7, cy + 7, cx + 7, cy + 1], fill=COLOR_TEXT_MUTED, width=2)
    # فلش رو به بالا
    draw.line([cx, cy + 3, cx, cy - 7], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx - 4, cy - 3, cx, cy - 7], fill=COLOR_TEXT_MUTED, width=2)
    draw.line([cx + 4, cy - 3, cx, cy - 7], fill=COLOR_TEXT_MUTED, width=2)


def render_tweet_image(
    *,
    country_name: str,
    president_name: str | None = None,
    country_flag: str = "",
    username: str,
    content: str,
    avatar_bytes: bytes | None = None,
    created_at: datetime | None = None,
) -> bytes:
    """
    رندر کردن تصویر توییت با مشخصات رسمی توییتر در رم و بازگرداندن بایت‌های PNG.
    نام حساب به نام مسئول/رئیس‌جمهور تنظیم می‌شود.
    """
    font_reg_path, font_bold_path = _ensure_fonts()

    if font_reg_path and font_bold_path:
        font_name = ImageFont.truetype(font_bold_path, 24)
        font_handle = ImageFont.truetype(font_reg_path, 18)
        font_body = ImageFont.truetype(font_reg_path, 22)
        font_meta = ImageFont.truetype(font_reg_path, 16)
    else:
        font_name = font_handle = font_body = font_meta = ImageFont.load_default()

    display_title = president_name or country_name
    clean_country = clean_emojis(display_title).strip() or "مسئول رسمی"
    clean_handle = username.strip().lstrip("@")
    clean_body = clean_emojis(content).strip()

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    # تاریخ و ساعت به فرمت توییتر
    time_str = to_fa_digits(created_at.strftime("%H:%M · %Y/%m/%d")) + " · The Earth Game"

    # خط‌بندی متن توییت (حداکثر عرض ۸۶۰ پیکسل)
    lines = _wrap_text(clean_body, font_body, max_width=860)
    line_height = 40
    body_height = max(len(lines) * line_height, 60)

    # محاسبه داینامیک ارتفاع بوم
    header_height = 145
    date_height = 40
    icons_height = 65
    canvas_width = 1000
    canvas_height = max(450, header_height + body_height + date_height + icons_height + 30)

    im = Image.new("RGBA", (canvas_width, canvas_height), COLOR_BG)
    draw = ImageDraw.Draw(im)

    # کادر بیرونی ظریف کارت توییت
    draw.rectangle(
        [10, 10, canvas_width - 10, canvas_height - 10],
        outline=COLOR_CARD_BORDER,
        width=2,
    )

    # ۱. آواتار دایره‌ای کاربر
    raw_avatar: Image.Image | None = None
    if avatar_bytes:
        try:
            raw_avatar = Image.open(io.BytesIO(avatar_bytes))
        except Exception as exc:
            logger.warning("Could not parse avatar bytes: %s", exc)

    circ_avatar = _draw_circular_avatar(raw_avatar, size=80)
    im.paste(circ_avatar, (45, 38), mask=circ_avatar)

    # ۲. نام کشور + تیک آبی + یوزرنیم
    name_text = prepare_rtl(clean_country)
    bb_name = font_name.getbbox(name_text)
    name_w = bb_name[2] - bb_name[0]
    draw.text((145, 40), name_text, fill=COLOR_WHITE, font=font_name)

    badge_cx = 145 + name_w + 16
    badge_cy = 40 + 14
    _draw_verified_badge(draw, badge_cx, badge_cy, radius=12)

    handle_disp = f"@{clean_handle}"
    draw.text((145, 82), handle_disp, fill=COLOR_TEXT_MUTED, font=font_handle)

    # لوگوی ظریف X در گوشه راست بالا
    draw.line([(935, 42), (955, 68)], fill="#71767B", width=3)
    draw.line([(955, 42), (935, 68)], fill="#71767B", width=3)

    # ۳. خط جداکننده زیر هدر
    draw.line([(45, 135), (955, 135)], fill=COLOR_CARD_BORDER, width=1)

    # ۴. متن توییت
    cur_y = 155
    for line in lines:
        if line.strip():
            l_rtl = prepare_rtl(line)
            bb = font_body.getbbox(l_rtl)
            line_w = bb[2] - bb_name[0] if bb else 0
            # متون فارسی راست‌چین
            draw.text((955 - (bb[2] - bb[0]), cur_y), l_rtl, fill=COLOR_TEXT_MAIN, font=font_body)
        cur_y += line_height

    # ۵. تاریخ و منبع توییت
    date_y = cur_y + 15
    draw.text((45, date_y), time_str, fill=COLOR_TEXT_MUTED, font=font_meta)

    # ۶. خط جداکننده قبل از نوار ابزار
    bar_div_y = date_y + 35
    draw.line([(45, bar_div_y), (955, bar_div_y)], fill=COLOR_CARD_BORDER, width=1)

    # ۷. نوار آیکون‌های تعاملی توییتر (Reply, Repost, Like, Share)
    icons_y = bar_div_y + 24
    _draw_reply_icon(draw, 160, icons_y)
    _draw_repost_icon(draw, 400, icons_y)
    _draw_heart_icon(draw, 640, icons_y)
    _draw_share_icon(draw, 880, icons_y)

    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
