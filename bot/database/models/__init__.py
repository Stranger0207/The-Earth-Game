"""
گردآوری همه‌ی مدل‌های ORM در یک نقطه.
وارد کردن این پکیج باعث می‌شود همه‌ی جدول‌ها در متادیتای Base ثبت شوند.
"""

from .alliance import Alliance, AllianceMember
from .attack import Attack
from .claim import ClaimRequest
from .cooldown import Cooldown
from .country import Country
from .diplomacy import (
    Contract,
    GroupMeeting,
    GroupMeetingParticipant,
    Meeting,
    PhoneCall,
    PhoneCallMessage,
    Sanction,
    Speech,
)
from .facility import Facility
from .investment import Investment
from .joint_request import JointBuildRequest
from .letter import Letter
from .military import MilitaryAsset
from .military_factory import MilitaryFactory
from .military_sale import MilitarySale
from .reserves import Reserve
from .tariff import TariffRate
from .trade import ResourceSale
from .user import User

__all__ = [
    "Alliance",
    "AllianceMember",
    "Attack",
    "ClaimRequest",
    "Contract",
    "Cooldown",
    "Country",
    "Facility",
    "Investment",
    "JointBuildRequest",
    "Letter",
    "GroupMeeting",
    "GroupMeetingParticipant",
    "Meeting",
    "MilitaryAsset",
    "MilitaryFactory",
    "MilitarySale",
    "PhoneCall",
    "PhoneCallMessage",
    "Reserve",
    "ResourceSale",
    "Sanction",
    "Speech",
    "TariffRate",
    "User",
]
