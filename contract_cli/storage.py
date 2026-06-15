"""数据存储模块"""
import json
import os
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .models import Contract, Project, ReviewStatus, RiskLevel, HandoverNote


class ContractStore:
    """合同数据存储"""

    DATA_DIR_NAME = ".contract_data"
    CONTRACTS_FILE = "contracts.json"
    PROJECTS_FILE = "projects.json"
    CONFIG_FILE = "config.json"

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path).resolve()
        self.data_dir = self.base_path / self.DATA_DIR_NAME
        self.contracts_file = self.data_dir / self.CONTRACTS_FILE
        self.projects_file = self.data_dir / self.PROJECTS_FILE
        self.config_file = self.data_dir / self.CONFIG_FILE

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self.data_dir.exists() and self.contracts_file.exists()

    def initialize(self) -> bool:
        """初始化存储结构"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if not self.contracts_file.exists():
                self._write_json(self.contracts_file, [])
            if not self.projects_file.exists():
                self._write_json(self.projects_file, [{"name": "未分类", "description": "默认项目", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "contract_count": 0}])
            if not self.config_file.exists():
                self._write_json(self.config_file, {
                    "initialized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "base_path": str(self.base_path),
                    "default_assignee": None,
                    "auto_reminder_days": 3,
                })
            return True
        except Exception as e:
            raise RuntimeError(f"初始化失败: {e}")

    def _read_json(self, filepath: Path) -> Any:
        """读取JSON文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, filepath: Path, data: Any) -> None:
        """写入JSON文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_initialized(self) -> None:
        """确保已初始化"""
        if not self.is_initialized():
            raise RuntimeError("当前目录未初始化，请先运行 init 命令")

    @staticmethod
    def compute_checksum(file_path: str) -> str:
        """计算文件校验和"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()[:16]

    def get_all_contracts(self) -> List[Contract]:
        """获取所有合同"""
        self._ensure_initialized()
        data = self._read_json(self.contracts_file)
        return [Contract.from_dict(c) for c in data]

    def save_contracts(self, contracts: List[Contract]) -> None:
        """保存合同列表"""
        self._ensure_initialized()
        data = [c.to_dict() for c in contracts]
        self._write_json(self.contracts_file, data)

    def add_contract(self, contract: Contract) -> None:
        """添加合同"""
        contracts = self.get_all_contracts()
        contracts.append(contract)
        self.save_contracts(contracts)
        self._increment_project_count(contract.project)

    def update_contract(self, contract: Contract) -> None:
        """更新合同"""
        contracts = self.get_all_contracts()
        old_project = None
        for i, c in enumerate(contracts):
            if c.id == contract.id:
                old_project = c.project
                contract.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                contracts[i] = contract
                break
        self.save_contracts(contracts)
        if old_project and old_project != contract.project:
            self._decrement_project_count(old_project)
            self._increment_project_count(contract.project)

    def get_contract(self, contract_id: str) -> Optional[Contract]:
        """根据ID获取合同"""
        contracts = self.get_all_contracts()
        for c in contracts:
            if c.id == contract_id:
                return c
        return None

    def delete_contract(self, contract_id: str) -> bool:
        """删除合同"""
        contracts = self.get_all_contracts()
        contract = None
        for i, c in enumerate(contracts):
            if c.id == contract_id:
                contract = c
                contracts.pop(i)
                break
        if contract:
            self.save_contracts(contracts)
            self._decrement_project_count(contract.project)
            return True
        return False

    def get_contracts_by_project(self, project: str) -> List[Contract]:
        """按项目获取合同"""
        contracts = self.get_all_contracts()
        return [c for c in contracts if c.project == project]

    def get_contracts_by_status(self, status: ReviewStatus) -> List[Contract]:
        """按状态获取合同"""
        contracts = self.get_all_contracts()
        return [c for c in contracts if c.status == status]

    def get_contracts_by_assignee(self, assignee: str) -> List[Contract]:
        """按负责人获取合同"""
        contracts = self.get_all_contracts()
        return [c for c in contracts if c.assignee == assignee]

    def get_overdue_contracts(self) -> List[Contract]:
        """获取逾期合同"""
        contracts = self.get_all_contracts()
        today = datetime.now().strftime("%Y-%m-%d")
        overdue = []
        for c in contracts:
            if c.due_date and c.due_date < today and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]:
                overdue.append(c)
        return overdue

    def get_projects(self) -> List[Project]:
        """获取所有项目"""
        self._ensure_initialized()
        data = self._read_json(self.projects_file)
        return [Project(**p) for p in data]

    def add_project(self, name: str, description: str = "") -> bool:
        """添加项目"""
        projects = self.get_projects()
        for p in projects:
            if p.name == name:
                return False
        projects.append(Project(name=name, description=description))
        self._write_json(self.projects_file, [asdict_project(p) for p in projects])
        return True

    def _increment_project_count(self, project_name: str) -> None:
        """增加项目合同计数"""
        projects = self.get_projects()
        found = False
        for p in projects:
            if p.name == project_name:
                p.contract_count += 1
                found = True
                break
        if not found:
            projects.append(Project(name=project_name, contract_count=1))
        self._write_json(self.projects_file, [asdict_project(p) for p in projects])

    def _decrement_project_count(self, project_name: str) -> None:
        """减少项目合同计数"""
        projects = self.get_projects()
        for i, p in enumerate(projects):
            if p.name == project_name and p.contract_count > 0:
                p.contract_count -= 1
                break
        self._write_json(self.projects_file, [asdict_project(p) for p in projects])

    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        self._ensure_initialized()
        return self._read_json(self.config_file)

    def update_config(self, **kwargs) -> None:
        """更新配置"""
        config = self.get_config()
        config.update(kwargs)
        config["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write_json(self.config_file, config)

    def generate_handover_note(self, project: Optional[str] = None) -> HandoverNote:
        """生成交接说明"""
        contracts = self.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]

        note = HandoverNote(project=project or "全部项目")
        note.total_contracts = len(contracts)

        today = datetime.now().strftime("%Y-%m-%d")
        assignee_map: Dict[str, int] = {}

        for c in contracts:
            if c.status == ReviewStatus.PENDING:
                note.pending_review += 1
            elif c.status == ReviewStatus.IN_PROGRESS:
                note.in_progress += 1
            elif c.status == ReviewStatus.APPROVED:
                note.approved += 1

            if c.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                note.high_risk_count += 1

            note.open_issues += len([i for i in c.issues if i.status == "待确认"])

            if c.due_date and c.due_date < today and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]:
                note.overdue_count += 1

            if c.assignee:
                assignee_map[c.assignee] = assignee_map.get(c.assignee, 0) + 1

            note.contracts.append({
                "id": c.id,
                "title": c.title,
                "status": c.status.value,
                "risk_level": c.risk_level.value,
                "assignee": c.assignee,
                "due_date": c.due_date,
                "project": c.project,
                "open_issues": len([i for i in c.issues if i.status == "待确认"]),
                "summary": c.summary or "未生成摘要",
                "version_count": len(c.versions),
                "extraction_status": max(c.versions, key=lambda v: v.version_number).extraction_status if c.versions else "未提取",
                "party_a": c.key_info.party_a,
                "party_b": c.key_info.party_b,
                "contract_amount": c.key_info.contract_amount,
            })

        note.assignee_summary = assignee_map
        return note


def asdict_project(project: Project) -> Dict[str, Any]:
    """转换Project为字典"""
    return {
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at,
        "contract_count": project.contract_count,
    }
