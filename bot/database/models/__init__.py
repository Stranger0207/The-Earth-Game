"""
گردآوری همه‌ی مدل‌های ORM در یک نقطه.
وارد کردن این پکیج باعث می‌شود همه‌ی جدول‌ها در متادیتای Base ثبت شوند.
"""

from .alliance import Alliance, AllianceMember
from .auction import Auction, AuctionBid
from .bank_loan import BankLoan
from .bot_state import BotState
from .claim import ClaimRequest
from .commander import Commander
from .cooldown import Cooldown
from .country import Country
from .deployment import Deployment
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
from .feature_lock import FeatureLock
from .governance import Law, Protest, VisaRequirement
from .investment import Investment
from .joint_request import JointBuildRequest
from .letter import Letter
from .military import MilitaryAsset
from .military_base import BaseEquipment, MilitaryBase
from .military_factory import MilitaryFactory
from .military_sale import MilitarySale
from .nuclear import (
    NuclearFacility,
    NuclearInspection,
    NuclearProgram,
    NuclearTech,
    NuclearTest,
    NuclearWarhead,
)
from .reserves import Reserve
from .satellite import Satellite
from .cabinet import (
    CabinetActionLog,
    CabinetInquiry,
    CabinetInspection,
    CabinetMeeting,
    CabinetMember,
    CabinetMemo,
)
from .tariff import TariffRate
from .trade import ResourceSale
from .user import User

__all__ = [
    "Alliance",
    "AllianceMember",
    "Auction",
    "AuctionBid",
    "BankLoan",
    "BaseEquipment",
    "BotState",
    "CabinetActionLog",
    "CabinetInquiry",
    "CabinetInspection",
    "CabinetMeeting",
    "CabinetMember",
    "CabinetMemo",
    "ClaimRequest",
    "Commander",
    "Contract",
    "Cooldown",
    "Country",
    "Deployment",
    "Facility",
    "FeatureLock",
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
    "NuclearFacility",
    "NuclearInspection",
    "NuclearProgram",
    "NuclearTech",
    "NuclearTest",
    "NuclearWarhead",
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
]
