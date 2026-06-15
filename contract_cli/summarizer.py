"""合同摘要与导出模块"""
import os
import shutil
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

        latest_ver = max(contract.versions, key=lambda v: v.version_number)
        if latest_ver.extraction_status and latest_ver.extraction_status != "未提取":
            lines.append(f"  文本提取:    {latest_ver.extraction_status}")
            if latest_ver.extraction_note:
                lines.append(f"  提取说明:    {latest_ver.extraction_note}")

        lines.append("")
        lines.append("--- 关键信息 ---")
        ki = contract.key_info
        conf = ki.field_confidence
        info_items = [
            ("合同类型", ki.contract_type, "contract_type"),
            ("甲方", ki.party_a, "party_a"),
            ("乙方", ki.party_b, "party_b"),
            ("合同金额", ki.contract_amount, "contract_amount"),
            ("开始日期", ki.start_date, "start_date"),
            ("结束日期", ki.end_date, "end_date"),
            ("签订地点", ki.signing_location, "signing_location"),
        ]
        for label, value, fkey in info_items:
            c_label = conf.get(fkey, "")
            conf_tag = f" [{c_label}]" if c_label else ""
            lines.append(f"  {label}: {value or '[待填充]'}{conf_tag}")

        if ki.placeholders:
            lines.append("")
            lines.append("--- 关键条款 ---")
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
            ext_status = ""
            if v.extraction_status and v.extraction_status != "未提取":
                ext_status = f" [{v.extraction_status}]"
            lines.append(f"  v{v.version_number}{marker}: {v.file_name}{ext_status}")
            lines.append(f"        导入于 {v.imported_at} | 校验 {v.checksum[:8]}")
            if v.note:
                lines.append(f"        备注: {v.note}")
            if v.extraction_note:
                lines.append(f"        提取: {v.extraction_note}")

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

    def generate_weekly_brief(
        self,
        project: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> str:
        """生成周会同步总览摘要"""
        contracts = self.store.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]
        if assignee:
            contracts = [c for c in contracts if c.assignee == assignee]

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")

        lines = []
        lines.append("=" * 60)
        lines.append(f"  法务合同审阅 周会同步总览")
        lines.append(f"  日期: {today} (回看最近7天)")
        lines.append("=" * 60)
        lines.append("")

        total = len(contracts)
        pending = [c for c in contracts if c.status == ReviewStatus.PENDING]
        in_progress = [c for c in contracts if c.status == ReviewStatus.IN_PROGRESS]
        needs_rev = [c for c in contracts if c.status == ReviewStatus.NEEDS_REVISION]
        approved = [c for c in contracts if c.status == ReviewStatus.APPROVED]
        rejected = [c for c in contracts if c.status == ReviewStatus.REJECTED]
        high_risk = [c for c in contracts if c.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]]
        overdue = [c for c in contracts if c.due_date and c.due_date < today
                   and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]]
        recent = [c for c in contracts if c.created_at >= week_ago or c.updated_at >= week_ago]

        lines.append("--- 本周概览 ---")
        lines.append(f"  合同总数:     {total}")
        lines.append(f"  待审阅:       {len(pending)} 份")
        lines.append(f"  审阅中:       {len(in_progress)} 份")
        lines.append(f"  待修改:       {len(needs_rev)} 份")
        lines.append(f"  已通过:       {len(approved)} 份")
        lines.append(f"  已拒绝:       {len(rejected)} 份")
        lines.append(f"  高/严重风险:  {len(high_risk)} 份")
        lines.append(f"  逾期合同:     {len(overdue)} 份 ⚠️")
        lines.append(f"  近7天变动:    {len(recent)} 份")
        lines.append("")

        all_issues = []
        for c in contracts:
            all_issues.extend([i for i in c.issues if i.status == "待确认"])
        lines.append(f"  待确认问题:   {len(all_issues)} 个")
        lines.append("")

        if overdue:
            lines.append("--- ⚠️ 逾期合同 ---")
            for c in overdue:
                lines.append(f"  • [{c.id}] {c.title}")
                lines.append(f"    项目: {c.project} | 负责人: {c.assignee or '未指派'} | 截止: {c.due_date}")
                lines.append("")

        if high_risk:
            lines.append("--- 高风险合同 ---")
            for c in high_risk:
                lines.append(f"  • [{c.id}] {c.title} - {c.risk_level.value}风险 | {c.status.value}")
                lines.append("")

        if in_progress:
            lines.append("--- 审阅中合同 ---")
            for c in in_progress:
                ki = c.key_info
                conf = ki.field_confidence
                party_info = ""
                if ki.party_a or ki.party_b:
                    pa_conf = conf.get("party_a", "")
                    pb_conf = conf.get("party_b", "")
                    pa_tag = f"({pa_conf})" if pa_conf in ("沿用旧稿", "待确认") else ""
                    pb_tag = f"({pb_conf})" if pb_conf in ("沿用旧稿", "待确认") else ""
                    party_info = f" | {ki.party_a or '?'}{pa_tag} ↔ {ki.party_b or '?'}{pb_tag}"
                amount_info = ""
                if ki.contract_amount:
                    amt_conf = conf.get("contract_amount", "")
                    amt_tag = f"({amt_conf})" if amt_conf in ("沿用旧稿", "待确认") else ""
                    amount_info = f" | 金额: {ki.contract_amount}{amt_tag}"
                lines.append(f"  • [{c.id}] {c.title}{party_info}{amount_info}")
                lines.append(f"    负责人: {c.assignee or '未指派'} | 截止: {c.due_date or '未设定'}")
                pending_i = len([i for i in c.issues if i.status == "待确认"])
                if pending_i:
                    lines.append(f"    待确认问题: {pending_i} 个")
                _FIELD_LABELS = {
                    "party_a": "甲方", "party_b": "乙方", "contract_amount": "金额",
                    "start_date": "开始日期", "end_date": "结束日期",
                    "contract_type": "合同类型", "signing_location": "签订地点",
                    "ph_付款方式": "付款方式", "ph_违约责任": "违约责任",
                    "ph_保密条款": "保密条款", "ph_知识产权": "知识产权",
                    "ph_争议解决": "争议解决", "ph_不可抗力": "不可抗力",
                    "ph_解除条款": "解除条款", "ph_续约条款": "续约条款",
                    "ph_合同编号": "合同编号",
                }
                pending_fields = [_FIELD_LABELS.get(k, k) for k, v in conf.items() if v == "待确认"]
                old_fields = [_FIELD_LABELS.get(k, k) for k, v in conf.items() if v == "沿用旧稿"]
                if pending_fields:
                    lines.append(f"    待确认字段: {', '.join(pending_fields)}")
                if old_fields:
                    lines.append(f"    沿用旧稿: {', '.join(old_fields)}")
                lines.append("")

        if pending:
            lines.append("--- 待审阅合同 ---")
            for c in pending[:20]:
                ext = ""
                if c.versions:
                    lv = max(c.versions, key=lambda v: v.version_number)
                    if lv.extraction_status and lv.extraction_status != "未提取":
                        ext = f" [{lv.extraction_status}]"
                lines.append(f"  • [{c.id}] {c.title} ({c.project}){ext}")
            if len(pending) > 20:
                lines.append(f"  ... 及其他 {len(pending) - 20} 份")
            lines.append("")

        if recent:
            lines.append("--- 近7天变动 ---")
            for c in recent:
                action = "新建" if c.created_at >= week_ago else "更新"
                lines.append(f"  • [{c.id}] {c.title} - {action} ({c.updated_at})")
            lines.append("")

        lines.append("=" * 60)
        lines.append("  周会总览生成完毕")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _describe_filters(
        self,
        project: Optional[str],
        status: Optional[ReviewStatus],
        assignee: Optional[str],
    ) -> str:
        filters = []
        if project:
            filters.append(f"项目={project}")
        if status:
            filters.append(f"状态={status.value}")
        if assignee:
            filters.append(f"负责人={assignee}")
        return ", ".join(filters) if filters else "无（全部合同）"

    def _generate_summary_toc(self, contracts: List[Contract]) -> str:
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

    def save_summary_to_file(self, content: str, output_path: str) -> str:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return str(out)

    def export_handover_note(self, note: HandoverNote, output_path: str) -> str:
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
            lines.append(f"   负责人: {c.get('assignee') or '未指派'} | 截止: {c.get('due_date') or '未设定'}")
            lines.append(f"   待确认问题: {c.get('open_issues', 0)} 个")
            lines.append(f"   版本数: {c.get('version_count', 1)} | 最新提取: {c.get('extraction_status', '-')}")
            if c.get('party_a') or c.get('party_b'):
                lines.append(f"   甲方: {c.get('party_a', '-')} | 乙方: {c.get('party_b', '-')}")
            if c.get('contract_amount'):
                lines.append(f"   金额: {c['contract_amount']}")
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

    def export_handover_package(
        self,
        output_dir: str,
        project: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> str:
        """导出完整交接包（摘要+明细+版本+问题+周会总览）"""
        out = Path(output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)

        contracts = self.store.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]
        if assignee:
            contracts = [c for c in contracts if c.assignee == assignee]

        handover_path = out / "交接说明.txt"
        note = self.store.generate_handover_note(project, assignee)
        self.export_handover_note(note, str(handover_path))

        detail_path = out / "合同明细.txt"
        batch_text = self.generate_batch_summary(contracts=contracts)
        self.save_summary_to_file(batch_text, str(detail_path))

        weekly_path = out / "周会总览.txt"
        weekly_text = self.generate_weekly_brief(project=project, assignee=assignee)
        self.save_summary_to_file(weekly_text, str(weekly_path))

        md_path = out / "合同汇总.md"
        self.export_markdown_summary(contracts, str(md_path), project)

        issues_path = out / "待确认问题清单.txt"
        issues_text = self._generate_issues_list(contracts)
        self.save_summary_to_file(issues_text, str(issues_path))

        versions_path = out / "版本历史汇总.txt"
        versions_text = self._generate_versions_summary(contracts)
        self.save_summary_to_file(versions_text, str(versions_path))

        return str(out)

    def export_batch_packages(
        self,
        output_base_dir: str,
        project: Optional[str] = None,
        assignees: Optional[List[str]] = None,
    ) -> List[str]:
        """为多个负责人分别导出交接包"""
        contracts = self.store.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]

        if not assignees:
            assignees = sorted(set(c.assignee for c in contracts if c.assignee))

        base = Path(output_base_dir).resolve()
        base.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in assignees:
            safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            pkg_dir = base / safe_name
            self.export_handover_package(str(pkg_dir), project=project, assignee=name)
            paths.append(str(pkg_dir))
        return paths

    def _generate_issues_list(self, contracts: List[Contract]) -> str:
        """生成待确认问题清单"""
        lines = []
        lines.append("=" * 60)
        lines.append("  待确认问题清单")
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        lines.append("")

        total_pending = 0
        total_resolved = 0
        for c in contracts:
            pending = [i for i in c.issues if i.status == "待确认"]
            resolved = [i for i in c.issues if i.status == "已解决"]
            total_pending += len(pending)
            total_resolved += len(resolved)
            if c.issues:
                lines.append(f"【{c.title}】({c.id}) - 项目: {c.project}")
                lines.append(f"  负责人: {c.assignee or '未指派'} | 截止: {c.due_date or '未设定'}")
                for i in c.issues:
                    marker = "⚠️ " if i.status == "待确认" else "✅ "
                    assign_str = f" → {i.assignee}" if i.assignee else ""
                    lines.append(f"  {marker}[{i.id}] {i.description}{assign_str}")
                    lines.append(f"      状态: {i.status} | 创建: {i.created_at}")
                    if i.note:
                        lines.append(f"      说明: {i.note}")
                lines.append("")

        lines.append(f"合计: 待确认 {total_pending} 个, 已解决 {total_resolved} 个")
        return "\n".join(lines)

    def _generate_versions_summary(self, contracts: List[Contract]) -> str:
        """生成版本历史汇总"""
        lines = []
        lines.append("=" * 60)
        lines.append("  合同版本历史汇总")
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        lines.append("")

        multi_ver = [c for c in contracts if len(c.versions) >= 2]
        single_ver = [c for c in contracts if len(c.versions) == 1]

        if multi_ver:
            lines.append("--- 多版本合同 ---")
            for c in multi_ver:
                lines.append(f"【{c.title}】({c.id}) - 共 {len(c.versions)} 个版本")
                for v in sorted(c.versions, key=lambda x: x.version_number):
                    marker = " ★当前" if v.version_number == c.current_version else ""
                    ext = f" [{v.extraction_status}]" if v.extraction_status and v.extraction_status != "未提取" else ""
                    lines.append(f"  v{v.version_number}{marker}: {v.file_name}{ext}")
                    lines.append(f"      导入: {v.imported_at} | 校验: {v.checksum[:8]}")
                    if v.extraction_note:
                        lines.append(f"      提取说明: {v.extraction_note}")
                lines.append("")

        if single_ver:
            lines.append("--- 单版本合同 ---")
            for c in single_ver:
                v = c.versions[0]
                ext = f" [{v.extraction_status}]" if v.extraction_status and v.extraction_status != "未提取" else ""
                lines.append(f"  • [{c.id}] {c.title} - v1{ext} ({v.imported_at})")
            lines.append("")

        lines.append(f"合计: 多版本 {len(multi_ver)} 份, 单版本 {len(single_ver)} 份")
        return "\n".join(lines)

    def export_markdown_summary(
        self,
        contracts: List[Contract],
        output_path: str,
        project: Optional[str] = None,
    ) -> str:
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
        lines.append("| # | 标题 | 项目 | 状态 | 风险 | 负责人 | 截止日期 | 甲方 | 乙方 | 金额 | 问题 |")
        lines.append("|---|------|------|------|------|--------|----------|------|------|------|------|")

        for idx, c in enumerate(contracts, 1):
            open_issues = len([i for i in c.issues if i.status == "待确认"])
            issue_str = f"**{open_issues}**⚠️" if open_issues > 0 else "-"
            due_str = f"**{c.due_date}**⚠️" if (
                c.due_date
                and c.due_date < datetime.now().strftime("%Y-%m-%d")
                and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]
            ) else (c.due_date or "-")
            ki = c.key_info
            lines.append(
                f"| {idx} | {c.title} | {c.project} | {c.status.value} | "
                f"{c.risk_level.value} | {c.assignee or '-'} | {due_str} | "
                f"{ki.party_a or '-'} | {ki.party_b or '-'} | {ki.contract_amount or '-'} | {issue_str} |"
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
