"""
مدل عملیات نظامی (v1.10.6) — جایگزین مدل قدیمی Battle.

یک ردیف Operation کل چرخه‌ی عمر یک عملیات تهاجمی را نگه می‌دارد:
از ثبت درخواست و تأیید مالک، تا نتایج محاسبه‌شده‌ی موتور نبرد و فازهای خبری.

نکته‌ی مهم: نتایج نبرد توسط موتور محاسباتی (`services/combat`) پر می‌شوند،
نه توسط هوش مصنوعی. AI فقط از روی همین اعداد، متن خبر را می‌نویسد.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Operation(Base):
    """یک عملیات نظامی (حمله زمینی/هوایی/دریایی، خرابکاری، ترور، رهگیری)."""

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- طرفین ---
    attacker_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )
    defender_country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id"), nullable=False, index=True
    )

    # --- مشخصات عملیات (مقادیر OperationType / TargetType) ---
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="military_base", nullable=False)
    # شناسه‌ی هدف مشخص (پایگاه، تأسیسات، محموله، فرمانده) در صورت وجود
    target_ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # برچسب خوانا‌ی هدف برای نمایش در خبر و پنل
    target_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    # تجهیزات اعزامی: [{"name","count","branch","category","unit"}]
    committed_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    # شرح تاکتیکی اختیاری بازیکن (برای عملیات مخفیانه معنادار است)
    tactical_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # --- تنظیمات عملیات مخفیانه ---
    claim_responsibility: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_exposed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- وضعیت (مقادیر OperationStatus) ---
    status: Mapped[str] = mapped_column(
        String(32), default="pending_owner", nullable=False, index=True
    )
    # آیا عملیات (به‌خصوص مخفیانه) موفق بود؟
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # دلیل رد/شکست (امکان‌سنجی نشد، پدافند خنثی کرد، ...)
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # --- هزینه‌ها ---
    fuel_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    budget_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # --- نتایج محاسبه‌شده توسط موتور نبرد ---
    intensity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    intercept_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    attacker_losses_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    defender_losses_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    civilian_casualties: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    infra_damage_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    econ_effects_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    outcome: Mapped[str] = mapped_column(String(96), default="", nullable=False)

    # --- فازهای خبری ---
    # واقعیت‌های خام هر فاز (ورودی خبرنویس AI) — {"phase1": "...", ...}
    phase_facts_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # آرکه‌تایپ‌های خبری استفاده‌شده تا حالا (برای تکرارنشدن سبک خبر)
    used_archetypes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    current_phase: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_phases: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    phase_interval_min: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_phase_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # آیا این عملیات در کانال نظامی منتشر شد؟ (فیلتر VIP + شدت)
    published_to_channel: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- زمان‌ها ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Operation {self.operation_type} {self.attacker_country_id}"
            f"->{self.defender_country_id} status={self.status} intensity={self.intensity}>"
        )
