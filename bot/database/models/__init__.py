"""
گردآوری همه‌ی مدل‌های ORM در یک نقطه.
وارد کردن این پکیج باعث می‌شود همه‌ی جدول‌ها در متادیتای Base ثبت شوند.
"""

from .alliance import Alliance, AllianceMember
from .attack import Attack
from .battle import Battle, WarDeclaration
from .bot_state import BotState
from .claim import ClaimRequest
from .commander import Commander
from .cooldown import Cooldown
from .country import Country
from .deployment import Deployment
from .drill import Drill
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
from .governance import Law, Protest, VisaRequirement
from .investment import Investment
from .joint_request import JointBuildRequest
from .letter import Letter
from .military import MilitaryAsset
from .military_base import BaseEquipment, MilitaryBase
from .military_factory import MilitaryFactory
from .military_sale import MilitarySale
from .news_fingerprint import NewsFingerprint
from .nuclear import (
    NuclearFacility,
    NuclearInspection,
    NuclearProgram,
    NuclearTech,
    NuclearTest,
    NuclearWarhead,
)
from .operation import Operation
from .patrol import Patrol
from .reserves import Reserve
from .satellite import Satellite
from .tariff import TariffRate
from .trade import ResourceSale
from .user import User

__all__ = [
    "Alliance",
    "AllianceMember",
    "Attack",
    "BaseEquipment",
    "Battle",
    "BotState",
    "ClaimRequest",
    "Commander",
    "Contract",
    "Cooldown",
    "Country",
    "Deployment",
    "Drill",
    "Facility",
    "Investment",
    "JointBuildRequest",
    "Law",
    "Letter",
    "GroupMeeting",
    "GroupMeetingParticipant",
    "Meeting",
    "MilitaryAsset",
    "MilitaryBase",
    "MilitaryFactory",
    "MilitarySale",
    "NewsFingerprint",
    "NuclearFacility",
    "NuclearInspection",
    "NuclearProgram",
    "NuclearTech",
    "NuclearTest",
    "NuclearWarhead",
    "Operation",
    "Patrol",
    "PhoneCall",
    "PhoneCallMessage",
    "Protest",
    "Reserve",
    "ResourceSale",
    "Sanction",
    "Satellite",
    "Speech",
    "TariffRate",
    "User",
    "VisaRequirement",
    "WarDeclaration",
]
