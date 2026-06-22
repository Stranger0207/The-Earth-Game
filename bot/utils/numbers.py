"""توابع کمکی برای نمایش اعداد و واحدها به فارسی."""

from __future__ import annotations

# نگاشت ارقام انگلیسی به فارسی
_EN_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def to_fa_digits(text: str | int | float) -> str:
    """تبدیل ارقام انگلیسی یک رشته/عدد به ارقام فارسی."""
    return str(text).translate(_EN_TO_FA)


def to_en_digits(text: str) -> str:
    """تبدیل ارقام فارسی به انگلیسی (برای parse ورودی کاربر)."""
    return str(text).translate(_FA_TO_EN)


def fa_number(value: float | int | None, decimals: int = 0) -> str:
    """عدد را با جداکننده‌ی هزارگان و ارقام فارسی برمی‌گرداند. مقدار None برابر صفر فرض می‌شود."""
    if value is None:
        value = 0
    if decimals > 0:
        formatted = f"{value:,.{decimals}f}"
    else:
        formatted = f"{int(round(value)):,}"
    return to_fa_digits(formatted)


def fa_money(value: float | None) -> str:
    """نمایش مبلغ دلاری به‌صورت خوانا (با پسوند میلیون/میلیارد/تریلیون)."""
    if value is None:
        value = 0
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    if abs_v >= 1_000_000_000_000:
        return f"{sign}{to_fa_digits(f'{abs_v / 1_000_000_000_000:.2f}')} تریلیون دلار"
    if abs_v >= 1_000_000_000:
        return f"{sign}{to_fa_digits(f'{abs_v / 1_000_000_000:.2f}')} میلیارد دلار"
    if abs_v >= 1_000_000:
        return f"{sign}{to_fa_digits(f'{abs_v / 1_000_000:.2f}')} میلیون دلار"
    return f"{sign}{fa_number(abs_v)} دلار"


def parse_amount(text: str) -> float | None:
    """
    تلاش برای تبدیل ورودی کاربر (با ارقام فارسی/انگلیسی، کاما، پسوند m/b/k) به عدد.
    در صورت ناموفق None برمی‌گرداند.
    """
    if not text:
        return None
    raw = to_en_digits(text.strip().lower()).replace(",", "").replace(" ", "")
    multiplier = 1.0
    if raw.endswith("k"):
        multiplier, raw = 1_000, raw[:-1]
    elif raw.endswith("m"):
        multiplier, raw = 1_000_000, raw[:-1]
    elif raw.endswith("b"):
        multiplier, raw = 1_000_000_000, raw[:-1]
    try:
        return float(raw) * multiplier
    except ValueError:
        return None
