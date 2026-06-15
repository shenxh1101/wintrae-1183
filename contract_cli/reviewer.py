"""合同审阅模块"""
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

from .models import Contract, Issue, ReviewStatus, RiskLevel, KeyInfo
from .storage import ContractStore


class ContractReviewer:
    """合同审阅处理器"""

    def __init__(self, store: ContractStore):
        self.store = store

    def update_status(self, contract_id: str, status: ReviewStatus) -> Contract:
        """更新审阅状态"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        contract.status = status
        self.store.update_contract(contract)
        return contract

    def update_risk_level(self, contract_id: str, risk_level: RiskLevel) -> Contract:
        """更新风险等级"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        contract.risk_level = risk_level
        self.store.update_contract(contract)
        return contract

    def assign_to(self, contract_id: str, assignee: str) -> Contract:
        """指派负责人"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        contract.assignee = assignee
        self.store.update_contract(contract)
        return contract

    def set_due_date(self, contract_id: str, due_date: str) -> Contract:
        """设置截止日期"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式错误，请使用 YYYY-MM-DD 格式")
        contract.due_date = due_date
        self.store.update_contract(contract)
        return contract

    def change_project(self, contract_id: str, project: str) -> Contract:
        """变更项目归类"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        contract.project = project
        self.store.update_contract(contract)
        return contract

    def add_tags(self, contract_id: str, tags: List[str]) -> Contract:
        """添加标签"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        for tag in tags:
            if tag not in contract.tags:
                contract.tags.append(tag)
        self.store.update_contract(contract)
        return contract

    def remove_tags(self, contract_id: str, tags: List[str]) -> Contract:
        """移除标签"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        contract.tags = [t for t in contract.tags if t not in tags]
        self.store.update_contract(contract)
        return contract

    def update_key_info(self, contract_id: str, **kwargs) -> Contract:
        """更新关键信息"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")

        valid_fields = {
            "party_a", "party_b", "contract_amount",
            "start_date", "end_date", "contract_type", "signing_location"
        }
        for key, value in kwargs.items():
            if key in valid_fields and value is not None:
                setattr(contract.key_info, key, value)
                contract.key_info.field_confidence[key] = "人工确认"
            elif key.startswith("ph_") and value is not None:
                ph_key = key[3:]
                contract.key_info.placeholders[ph_key] = value
                contract.key_info.field_confidence[f"ph_{ph_key}"] = "人工确认"

        self.store.update_contract(contract)
        return contract

    def add_issue(
        self,
        contract_id: str,
        description: str,
        assignee: Optional[str] = None,
    ) -> Issue:
        """添加待确认问题"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")

        issue = Issue(description=description, assignee=assignee)
        contract.issues.append(issue)
        self.store.update_contract(contract)
        return issue

    def resolve_issue(
        self,
        contract_id: str,
        issue_id: str,
        note: Optional[str] = None,
    ) -> bool:
        """标记问题已解决"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")

        for issue in contract.issues:
            if issue.id == issue_id:
                issue.status = "已解决"
                issue.resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if note:
                    issue.note = note
                self.store.update_contract(contract)
                return True
        return False

    def delete_issue(self, contract_id: str, issue_id: str) -> bool:
        """删除问题"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")

        initial_count = len(contract.issues)
        contract.issues = [i for i in contract.issues if i.id != issue_id]
        if len(contract.issues) < initial_count:
            self.store.update_contract(contract)
            return True
        return False

    def add_review_note(self, contract_id: str, note: str) -> Contract:
        """添加审阅备注"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        contract.review_notes.append(f"[{timestamp}] {note}")
        self.store.update_contract(contract)
        return contract

    def get_upcoming_deadlines(self, days: int = 7) -> List[Contract]:
        """获取即将到期的合同"""
        contracts = self.store.get_all_contracts()
        today = datetime.now()
        deadline_date = today + timedelta(days=days)
        deadline_str = deadline_date.strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        upcoming = []
        for c in contracts:
            if (c.due_date
                    and c.due_date >= today_str
                    and c.due_date <= deadline_str
                    and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]):
                upcoming.append(c)
        upcoming.sort(key=lambda x: x.due_date or "")
        return upcoming

    def batch_update_status(self, contract_ids: List[str], status: ReviewStatus) -> Tuple[int, int]:
        """批量更新状态，返回 (成功数, 失败数)"""
        success = 0
        failed = 0
        for cid in contract_ids:
            try:
                self.update_status(cid, status)
                success += 1
            except Exception:
                failed += 1
        return success, failed

    def batch_assign(self, contract_ids: List[str], assignee: str) -> Tuple[int, int]:
        """批量指派负责人"""
        success = 0
        failed = 0
        for cid in contract_ids:
            try:
                self.assign_to(cid, assignee)
                success += 1
            except Exception:
                failed += 1
        return success, failed

    def get_statistics(self) -> dict:
        """获取审阅统计"""
        contracts = self.store.get_all_contracts()
        stats = {
            "total": len(contracts),
            "by_status": {s.value: 0 for s in ReviewStatus},
            "by_risk": {r.value: 0 for r in RiskLevel},
            "by_project": {},
            "by_assignee": {},
            "pending_issues": 0,
            "overdue": 0,
        }

        today = datetime.now().strftime("%Y-%m-%d")

        for c in contracts:
            stats["by_status"][c.status.value] += 1
            stats["by_risk"][c.risk_level.value] += 1
            stats["by_project"][c.project] = stats["by_project"].get(c.project, 0) + 1
            if c.assignee:
                stats["by_assignee"][c.assignee] = stats["by_assignee"].get(c.assignee, 0) + 1
            stats["pending_issues"] += len([i for i in c.issues if i.status == "待确认"])
            if c.due_date and c.due_date < today and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]:
                stats["overdue"] += 1

        return stats
