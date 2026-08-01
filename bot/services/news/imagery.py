"""
ساخت پرامپت تصویری برای اخبار نظامی (v1.10.6).

واقعیت‌های نبرد را به یک توصیف صحنه‌ی سینمایی تبدیل می‌کند تا Gemini عکس
اختصاصی همان خبر را بسازد. چون صحنه از داده‌ی واقعی نبرد ساخته می‌شود،
عکس هر خبر با خبر قبلی متفاوت است.

نکته‌ی مهم: پرامپت‌ها عمداً «خبری/مستند» و بدون خون و خشونت گرافیکی نوشته
می‌شوند — تصویرِ صحنه‌ی نظامی، نه تصویر تلفات انسانی.
"""

from __future__ import annotations

import random

from ...enums import OperationType, TargetType

# ---------- پایه‌ی سبک تصویر ----------
# همه‌ی عکس‌ها یک زبان بصری مشترک دارند تا کانال یکدست به‌نظر برسد.
_STYLE_BASE = (
    "photorealistic news photograph, documentary war-correspondent style, "
    "shot on a full-frame DSLR with a 35mm lens, natural lighting, "
    "slight motion blur, muted desaturated color grade, high detail, "
    "no text, no watermark, no logos, no gore, no visible casualties"
)

# ---------- صحنه‌ی پایه بر اساس نوع عملیات ----------
_OPERATION_SCENES: dict[OperationType, list[str]] = {
    OperationType.AIR_STRIKE: [
        "military fighter jets streaking across a dark sky, contrails visible, distant flashes on the horizon",
        "night airbase scene, jets taking off with afterburners glowing, ground crew silhouettes",
        "view from a hillside of distant explosions lighting up the night sky over an industrial area",
    ],
    OperationType.GROUND_ASSAULT: [
        "a column of main battle tanks advancing across dry terrain, dust clouds rising behind them",
        "armored vehicles moving through a damaged border checkpoint at dawn, smoke in the distance",
        "infantry fighting vehicles in a defensive line, soldiers taking positions behind earthworks",
    ],
    OperationType.NAVAL_STRIKE: [
        "a naval destroyer at sea firing missiles, muzzle flash reflecting off dark water",
        "warships in formation on open ocean under overcast sky, helicopter on the flight deck",
        "a missile launching from a warship deck at dusk, spray and smoke around the launcher",
    ],
    OperationType.SABOTAGE: [
        "a damaged industrial facility at night, emergency lights flashing, thick smoke rising",
        "burning fuel storage tanks at an industrial site, firefighters silhouetted against flames",
        "a power substation with visible fire damage, technicians inspecting wreckage at night",
    ],
    OperationType.ASSASSINATION: [
        "a cordoned-off city street at night with police vehicles and flashing lights, investigators at work",
        "security forces surrounding an official building, barriers and emergency vehicles at the entrance",
    ],
    OperationType.INTERCEPTION: [
        "a naval patrol vessel intercepting a large cargo ship on open sea, helicopter overhead",
        "coast guard boats surrounding a freighter at dawn, boarding team approaching",
    ],
    OperationType.PATROL: [
        "military patrol vehicles on a remote border road at sunrise, mountains in the background",
        "fighter aircraft on combat air patrol above a coastline, seen from below",
        "a naval patrol boat cutting through calm water at dawn, crew scanning the horizon",
    ],
    OperationType.DRILL: [
        "large-scale military exercise, tanks and artillery firing on a training range, observers watching",
        "joint military parade-ground exercise with armored columns and helicopters overhead",
    ],
}

# ---------- جزئیات هدف ----------
_TARGET_DETAILS: dict[TargetType, str] = {
    TargetType.MILITARY_BASE: "a fortified military base with hangars and radar installations",
    TargetType.CITY: "an urban skyline with damaged buildings and smoke rising between apartment blocks",
    TargetType.OIL_PLATFORM: "an offshore oil platform with flames and black smoke over the water",
    TargetType.FACTORY: "a large industrial factory complex with damaged roofing and smoke stacks",
    TargetType.NUCLEAR_SITE: "a heavily guarded industrial complex behind concrete walls and fences",
    TargetType.AIRPORT: "an airport apron with damaged terminal buildings and emergency vehicles",
    TargetType.PORT: "a commercial seaport with damaged cranes and containers, smoke over the docks",
    TargetType.DEPLOYED_FORCE: "a field encampment of military vehicles and tents in open terrain",
    TargetType.SHIPMENT: "a large cargo freighter at sea being approached by patrol vessels",
}

# ---------- لایه‌ی فاز خبری ----------
# هر فاز نبرد صحنه‌ی بصری متفاوتی دارد تا عکس‌های یک نبرد هم شبیه هم نباشند.
_PHASE_LAYERS: dict[str, list[str]] = {
    "opening": [
        "the very first moments of the operation, alert sirens and searchlights",
        "launch moment, weapons leaving their platforms",
    ],
    "defense": [
        "air defense systems firing interceptor missiles into the night sky, bright launch trails",
        "surface-to-air missile battery in action, radar dishes rotating, crew at their stations",
    ],
    "damage": [
        "aftermath assessment, rescue crews and damaged structures under grey daylight",
        "smoking wreckage of military equipment being surveyed by personnel",
    ],
    "second_wave": [
        "a second wave of aircraft arriving over the target area, heavier smoke below",
        "renewed engagement, multiple launch flashes across a wide front",
    ],
    "reaction": [
        "an emergency international press briefing, officials at podiums with flags behind them",
        "a diplomatic security council chamber during an urgent session",
    ],
    "summary": [
        "wide aerial view of the affected area at dusk, columns of smoke fading",
        "a quiet battlefield at sunset, damaged equipment scattered across the terrain",
    ],
}

# ---------- شرایط محیطی (تنوع بیشتر) ----------
_CONDITIONS = [
    "at dawn with low golden light",
    "at night under artificial lighting",
    "during overcast grey daylight",
    "at dusk with deep orange sky",
    "in hazy afternoon light with dust in the air",
]


def build_image_prompt(
    facts: dict,
    phase_kind: str,
    *,
    rng: random.Random | None = None,
) -> str:
    """
    یک پرامپت تصویری از واقعیت‌های نبرد می‌سازد.

    ترکیب: صحنه‌ی نوع عملیات + جزئیات هدف + لایه‌ی فاز + شرایط محیطی + سبک پایه.
    انتخاب‌های تصادفی باعث می‌شوند دو خبر مشابه هم عکس یکسان نگیرند.
    """
    generator = rng or random

    try:
        operation = OperationType(facts.get("operation_type", ""))
    except ValueError:
        operation = OperationType.AIR_STRIKE
    try:
        target = TargetType(facts.get("target_type", ""))
    except ValueError:
        target = TargetType.MILITARY_BASE

    scene = generator.choice(
        _OPERATION_SCENES.get(operation, _OPERATION_SCENES[OperationType.AIR_STRIKE])
    )
    target_detail = _TARGET_DETAILS.get(target, _TARGET_DETAILS[TargetType.MILITARY_BASE])
    phase_layer = generator.choice(_PHASE_LAYERS.get(phase_kind, _PHASE_LAYERS["opening"]))
    condition = generator.choice(_CONDITIONS)

    parts = [scene, target_detail, phase_layer, condition]

    # شدت عملیات روی مقیاس صحنه اثر می‌گذارد
    intensity = int(facts.get("intensity", 5) or 5)
    if intensity >= 8:
        parts.append("large-scale operation, multiple simultaneous events, heavy smoke")
    elif intensity <= 3:
        parts.append("limited localized incident, minimal visible damage")

    parts.append(_STYLE_BASE)
    return ", ".join(parts)


def image_slug(facts: dict, phase_kind: str) -> str:
    """نام کوتاه و امن برای فایل عکس تولیدشده."""
    op = str(facts.get("operation_type", "op"))
    return f"{op}-{phase_kind}"


def media_category_for(facts: dict) -> str:
    """
    دسته‌ی بانک عکس محلی که در صورت نبود Gemini استفاده می‌شود.
    (کلیدها هماهنگ با MEDIA_DIRS در services/media.py)
    """
    try:
        operation = OperationType(facts.get("operation_type", ""))
    except ValueError:
        return "military"

    if operation in (OperationType.PATROL, OperationType.DRILL):
        return "military"
    try:
        if TargetType(facts.get("target_type", "")) is TargetType.NUCLEAR_SITE:
            return "nuclear"
    except ValueError:
        pass
    return "military"
