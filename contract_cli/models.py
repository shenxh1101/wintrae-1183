"""数据模型定义"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


class ReviewStatus(str, Enum):
    """审阅状态"""
    PENDING = "待审阅"
    IN_PROGRESS = "审阅中"
    NEEDS_REVISION = "待修改"
    APPROVED = "已通过"
    REJECTED = "已拒绝"


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    CRITICAL = "严重"


@dataclass
class KeyInfo:
    """合同关键信息"""
    party_a: Optional[str] = None
    party_b: Optional[str] = None
    contract_amount: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_type: Optional[str] = None
    signing_location: Optional[str] = None
    placeholders: Dict[str, str] = field(default_factory=dict)


@dataclass
class Issue:
    """待确认问题"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    status: str = "待确认"
    assignee: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    resolved_at: Optional[str] = None
    note: Optional[str] = None


@dataclass
class ContractVersion:
    """合同版本"""
    version_number: int = 1
    file_path: str = ""
    file_name: str = ""
    imported_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    checksum: str = ""
    note: str = ""
    content_snapshot: Optional[str] = None
    extraction_status: str = "未提取"
    extraction_note: str = ""


@dataclass
class Contract:
    """合同"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    project: str = "未分类"
    file_path: str = ""
    file_name: str = ""
    versions: List[ContractVersion] = field(default_factory=list)
    current_version: int = 1
    status: ReviewStatus = ReviewStatus.PENDING
    risk_level: RiskLevel = RiskLevel.MEDIUM
    key_info: KeyInfo = field(default_factory=KeyInfo)
    issues: List[Issue] = field(default_factory=list)
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    review_notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["risk_level"] = self.risk_level.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contract":
        status = ReviewStatus(data.get("status", ReviewStatus.PENDING.value))
        risk_level = RiskLevel(data.get("risk_level", RiskLevel.MEDIUM.value))
        key_info_data = data.get("key_info", {})
        key_info = KeyInfo(
            party_a=key_info_data.get("party_a"),
            party_b=key_info_data.get("party_b"),
            contract_amount=key_info_data.get("contract_amount"),
            start_date=key_info_data.get("start_date"),
            end_date=key_info_data.get("end_date"),
            contract_type=key_info_data.get("contract_type"),
            signing_location=key_info_data.get("signing_location"),
            placeholders=key_info_data.get("placeholders", {}),
        )
        versions = [ContractVersion(**v) for v in data.get("versions", [])]
        issues = [Issue(**i) for i in data.get("issues", [])]
        return cls(
            id=data["id"],
            title=data["title"],
            project=data.get("project", "未分类"),
            file_path=data.get("file_path", ""),
            file_name=data.get("file_name", ""),
            versions=versions,
            current_version=data.get("current_version", 1),
            status=status,
            risk_level=risk_level,
            key_info=key_info,
            issues=issues,
            assignee=data.get("assignee"),
            due_date=data.get("due_date"),
            tags=data.get("tags", []),
            summary=data.get("summary"),
            review_notes=data.get("review_notes", []),
            created_at=data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            updated_at=data.get("updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )


@dataclass
class Project:
    """项目"""
    name: str
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    contract_count: int = 0


@dataclass
class HandoverNote:
    """交接说明"""
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    project: str = ""
    total_contracts: int = 0
    pending_review: int = 0
    in_progress: int = 0
    approved: int = 0
    high_risk_count: int = 0
    open_issues: int = 0
    overdue_count: int = 0
    assignee_summary: Dict[str, int] = field(default_factory=dict)
    contracts: List[Dict[str, Any]] = field(default_factory=list)
