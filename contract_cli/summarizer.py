"""合同摘要与导出模块"""
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .models import (
    Contract, ReviewStatus, RiskLevel, Issue,
    KeyInfo, HandoverNote
)
from .storage import ContractStore


class ContractSummarizer:
    """合同摘要生成器"""

    def __init__(self, store: ContractStore):
        self.store = store

    def generate_single_summary(self, contract: Contract) -> str:
        """生成单个合同的摘要"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"【合同摘要】{contract.title}")
        lines.append("=" * 60)
        lines.append(f"  合同编号:    {contract.id}")
        lines.append(f"  所属项目:    {contract.project}")
        lines.append(f"  当前版本:    v{contract.current_version} (共 {len(contract.versions)} 个版本)")
        lines.append(f"  审阅状态:    {contract.status.value}")
        lines.append(f"  风险等级:    【{contract.risk_level.value}】")
        lines.append(f"  负责人:      {contract.assignee or '未指派'}")
        lines.append(f"  截止日期:    {contract.due_date or '未设定'}")
        if contract.due_date:
            today = datetime.now().strftime("%Y-%m-%d")
            if contract.due_date < today and contract.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]:
                lines.append(f"               ⚠️ 已逾期！")
            elif contract.due_date == today:
                lines.append(f"               📅 今日截止！")

        if contract.tags:
            lines.append(f"  标签:        {', '.join(contract.tags)}")

        lines.append("")
        lines.append("--- 关键信息 ---")
        ki = contract.key_info
        info_items = [
            ("合同类型", ki.contract_type),
            ("甲方", ki.party_a),
            ("乙方", ki.party_b),
            ("合同金额", ki.contract_amount),
            ("开始日期", ki.start_date),
            ("结束日期", ki.end_date),
            ("签订地点", ki.signing_location),
        ]
        for label, value in info_items:
            lines.append(f"  {label}: {value or '[待填充]'}")

        if ki.placeholders:
            lines.append("")
            lines.append("--- 关键条款占位 ---")
            for key, value in sorted(ki.placeholders.items()):
                lines.append(f"  {key}: {value}")

        lines.append("")
        lines.append(f"--- 待确认问题 ({len(contract.issues)}) ---")
        pending = [i for i in contract.issues if i.status == "待确认"]
        resolved = [i for i in contract.issues if i.status == "已解决"]
        if pending:
            lines.append(f"  待确认 ({len(pending)}):")
            for issue in pending:
                lines.append(f"    [{issue.id}] {issue.description}")
                if issue.assignee:
                    lines.append(f"        → 指派: {issue.assignee}")
                lines.append(f"        创建于 {issue.created_at}")
        if resolved:
            lines.append(f"  已解决 ({len(resolved)}):")
            for issue in resolved:
                lines.append(f"    [{issue.id}] {issue.description} (解决于 {issue.resolved_at})")
        if not contract.issues:
            lines.append("  暂无问题记录")

        lines.append("")
        lines.append("--- 版本历史 ---")
        for v in sorted(contract.versions, key=lambda x: x.version_number):
            marker = " ★ 当前" if v.version_number == contract.current_version else ""
            lines.append(f"  v{v.version_number}{marker}: {v.file_name}")
            lines.append(f"        导入于 {v.imported_at} | 校验 {v.checksum[:8]}")
            if v.note:
                lines.append(f"        备注: {v.note}")

        if contract.review_notes:
            lines.append("")
            lines.append("--- 审阅备注 ---")
            for note in contract.review_notes[-10:]:
                lines.append(f"  {note}")

        lines.append("")
        lines.append(f"--- 源文件: {contract.file_path} ---")
        lines.append("")

        return "\n".join(lines)

    def generate_batch_summary(
        self,
        contracts: Optional[List[Contract]] = None,
        project: Optional[str] = None,
        status: Optional[ReviewStatus] = None,
        assignee: Optional[str] = None,
    ) -> str:
        """批量生成合同摘要"""
        if contracts is None:
            contracts = self.store.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]
        if status:
            contracts = [c for c in contracts if c.status == status]
        if assignee:
            contracts = [c for c in contracts if c.assignee == assignee]

        lines = []
        lines.append("#" * 60)
        lines.append("#  合同审阅批量摘要报告")
        lines.append(f"#  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"#  筛选条件: {self._describe_filters(project, status, assignee)}")
        lines.append(f"#  合同总数: {len(contracts)} 份")
        lines.append("#" * 60)
        lines.append("")

        if not contracts:
            lines.append("（没有符合条件的合同）")
            return "\n".join(lines)

        lines.append(self._generate_summary_toc(contracts))
        lines.append("")

        for idx, contract in enumerate(contracts, 1):
            lines.append(self.generate_single_summary(contract))

        lines.append("")
        lines.append("#" * 60)
        lines.append("#  报告结束")
        lines.append("#" * 60)

        return "\n".join(lines)

    def _describe_filters(
        self,
        project: Optional[str],
        status: Optional[ReviewStatus],
        assignee: Optional[str],
    ) -> str:
        """描述筛选条件"""
        filters = []
        if project:
            filters.append(f"项目={project}")
        if status:
            filters.append(f"状态={status.value}")
        if assignee:
            filters.append(f"负责人={assignee}")
        return ", ".join(filters) if filters else "无（全部合同）"

    def _generate_summary_toc(self, contracts: List[Contract]) -> str:
        """生成摘要目录"""
        lines = []
        lines.append("【目录】")
        lines.append(f"{'序号':<6}{'合同标题':<32}{'状态':<10}{'风险':<8}{'负责人':<12}{'截止日期':<14}")
        lines.append("-" * 82)

        for idx, c in enumerate(contracts, 1):
            title = c.title[:30] + ".." if len(c.title) > 30 else c.title
            assignee = c.assignee or "-"
            if len(assignee) > 10:
                assignee = assignee[:9] + "."
            due = c.due_date or "-"
            status = c.status.value
            if len(status) > 8:
                status = status[:7] + "."
            risk = c.risk_level.value
            lines.append(f"{idx:<6}{title:<32}{status:<10}{risk:<8}{assignee:<12}{due:<14}")

        lines.append("-" * 82)

        by_status: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}
        for c in contracts:
            by_status[c.status.value] = by_status.get(c.status.value, 0) + 1
            by_risk[c.risk_level.value] = by_risk.get(c.risk_level.value, 0) + 1

        lines.append("")
        lines.append("【快速统计】")
        lines.append("  按状态: " + ", ".join(f"{k}={v}" for k, v in by_status.items()))
        lines.append("  按风险: " + ", ".join(f"{k}={v}" for k, v in by_risk.items()))

        total_issues = sum(len(c.issues) for c in contracts)
        pending_issues = sum(
            len([i for i in c.issues if i.status == "待确认"])
            for c in contracts
        )
        lines.append(f"  问题总数: {total_issues} (待确认: {pending_issues})")

        return "\n".join(lines)

    def save_summary_to_file(
        self,
        content: str,
        output_path: str,
    ) -> str:
        """保存摘要到文件"""
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return str(out)

    def export_handover_note(
        self,
        note: HandoverNote,
        output_path: str,
    ) -> str:
        """导出交接说明到文件"""
        lines = []
        lines.append("=" * 60)
        lines.append("  法务合同审阅工作交接说明")
        lines.append("=" * 60)
        lines.append(f"  交接日期: {note.generated_at}")
        lines.append(f"  项目范围: {note.project}")
        lines.append("")

        lines.append("--- 总体概况 ---")
        lines.append(f"  合同总数:      {note.total_contracts} 份")
        lines.append(f"  待审阅:        {note.pending_review} 份")
        lines.append(f"  审阅中:        {note.in_progress} 份")
        lines.append(f"  已通过:        {note.approved} 份")
        lines.append(f"  高/严重风险:   {note.high_risk_count} 份")
        lines.append(f"  未解决问题:    {note.open_issues} 个")
        lines.append(f"  逾期合同:      {note.overdue_count} 份 ⚠️")
        lines.append("")

        if note.assignee_summary:
            lines.append("--- 负责人分配 ---")
            for name, count in sorted(note.assignee_summary.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {count} 份")
            lines.append("")

        lines.append("--- 合同明细 ---")
        lines.append("")

        for idx, c in enumerate(note.contracts, 1):
            lines.append(f"{idx}. {c['title']}")
            lines.append(f"   ID: {c['id']} | 项目: {c['project']}")
            lines.append(f"   状态: {c['status']} | 风险: {c['risk_level']}")
            lines.append(f"   负责人: {c['assignee'] or '未指派'} | 截止: {c['due_date'] or '未设定'}")
            lines.append(f"   待确认问题: {c['open_issues']} 个")
            lines.append(f"   摘要: {c['summary']}")
            lines.append("")

        lines.append("")
        lines.append("--- 交接说明 ---")
        lines.append("  1. 请接收方仔细核对以上合同清单的完整性")
        lines.append("  2. 重点关注标注 ⚠️ 的逾期合同和高风险合同")
        lines.append("  3. 每份合同的详细信息请通过 summary 命令查阅")
        lines.append("  4. 待确认问题请通过 review issue list <合同ID> 查看")
        lines.append("  5. 版本差异请通过 compare 命令进行比对")
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"  交接说明生成完成，共 {len(note.contracts)} 份合同")
        lines.append("=" * 60)

        content = "\n".join(lines)
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return str(out)

    def export_markdown_summary(
        self,
        contracts: List[Contract],
        output_path: str,
        project: Optional[str] = None,
    ) -> str:
        """导出 Markdown 格式的汇总报告"""
        lines = []
        lines.append(f"# 合同审阅汇总报告")
        lines.append("")
        lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if project:
            lines.append(f"> 项目: {project}")
        lines.append(f"> 合同总数: {len(contracts)} 份")
        lines.append("")

        status_counts: Dict[str, int] = {}
        risk_counts: Dict[str, int] = {}
        for c in contracts:
            status_counts[c.status.value] = status_counts.get(c.status.value, 0) + 1
            risk_counts[c.risk_level.value] = risk_counts.get(c.risk_level.value, 0) + 1

        lines.append("## 状态统计")
        lines.append("")
        lines.append("| 状态 | 数量 |")
        lines.append("|------|------|")
        for s in ReviewStatus:
            lines.append(f"| {s.value} | {status_counts.get(s.value, 0)} |")
        lines.append("")

        lines.append("## 风险统计")
        lines.append("")
        lines.append("| 风险等级 | 数量 |")
        lines.append("|----------|------|")
        for r in RiskLevel:
            lines.append(f"| {r.value} | {risk_counts.get(r.value, 0)} |")
        lines.append("")

        lines.append("## 合同清单")
        lines.append("")
        lines.append("| # | 标题 | 项目 | 状态 | 风险 | 负责人 | 截止日期 | 问题 |")
        lines.append("|---|------|------|------|------|--------|----------|------|")

        for idx, c in enumerate(contracts, 1):
            open_issues = len([i for i in c.issues if i.status == "待确认"])
            issue_str = f"**{open_issues}**⚠️" if open_issues > 0 else "-"
            due_str = f"**{c.due_date}**⚠️" if (
                c.due_date
                and c.due_date < datetime.now().strftime("%Y-%m-%d")
                and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]
            ) else (c.due_date or "-")
            lines.append(
                f"| {idx} | {c.title} | {c.project} | {c.status.value} | "
                f"{c.risk_level.value} | {c.assignee or '-'} | {due_str} | {issue_str} |"
            )

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*报告由 contract-cli 自动生成*")

        content = "\n".join(lines)
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return str(out)
