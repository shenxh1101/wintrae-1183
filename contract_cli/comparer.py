"""合同版本比对模块"""
import os
import difflib
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from .models import Contract, ContractVersion
from .storage import ContractStore


@dataclass
class DiffLine:
    """差异行"""
    line_number_old: Optional[int]
    line_number_new: Optional[int]
    content: str
    change_type: str  # 'added', 'removed', 'modified', 'unchanged'


@dataclass
class DiffSection:
    """差异区块"""
    section_name: str
    lines: List[DiffLine]
    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass
class ComparisonResult:
    """比对结果"""
    contract_id: str
    contract_title: str
    old_version: int
    new_version: int
    old_file: str
    new_file: str
    old_file_exists: bool
    new_file_exists: bool
    total_lines_old: int
    total_lines_new: int
    lines_added: int
    lines_removed: int
    lines_modified: int
    similarity_ratio: float
    sections: List[DiffSection]
    summary: str


class ContractComparer:
    """合同版本比对器"""

    def __init__(self, store: ContractStore):
        self.store = store

    def list_versions(self, contract_id: str) -> List[ContractVersion]:
        """列出合同所有版本"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")
        return sorted(contract.versions, key=lambda v: v.version_number)

    def _read_file_lines(self, file_path: str) -> List[str]:
        """读取文件行"""
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return [line.rstrip("\n") for line in lines]
        except Exception:
            return []

    def _read_any_contract_lines(self, file_path: str, file_name: str,
                                  content_snapshot: Optional[str] = None) -> List[str]:
        """读取合同文件行，优先使用快照内容"""
        if content_snapshot is not None:
            return content_snapshot.splitlines()
        lines = self._read_file_lines(file_path)
        if lines:
            return lines
        return [f"[{file_name}] - 无法直接比对（非纯文本格式，请使用原文对照审阅）"]

    def compare_versions(
        self,
        contract_id: str,
        old_version: Optional[int] = None,
        new_version: Optional[int] = None,
    ) -> ComparisonResult:
        """比对合同两个版本"""
        contract = self.store.get_contract(contract_id)
        if not contract:
            raise ValueError(f"未找到合同 ID: {contract_id}")

        versions = sorted(contract.versions, key=lambda v: v.version_number)
        if len(versions) < 2:
            raise ValueError("合同版本不足，无法进行比对（至少需要2个版本）")

        if new_version is None:
            new_ver = versions[-1]
        else:
            new_ver = next((v for v in versions if v.version_number == new_version), None)
            if not new_ver:
                raise ValueError(f"未找到新版本号: {new_version}")

        if old_version is None:
            new_idx = versions.index(new_ver)
            if new_idx > 0:
                old_ver = versions[new_idx - 1]
            else:
                raise ValueError("指定的新版本已是最早版本，无前置版本可比对")
        else:
            old_ver = next((v for v in versions if v.version_number == old_version), None)
            if not old_ver:
                raise ValueError(f"未找到旧版本号: {old_version}")

        old_lines = self._read_any_contract_lines(
            old_ver.file_path, old_ver.file_name, old_ver.content_snapshot
        )
        new_lines = self._read_any_contract_lines(
            new_ver.file_path, new_ver.file_name, new_ver.content_snapshot
        )

        diff_sections, added, removed, modified = self._compute_diff(old_lines, new_lines)

        similarity = difflib.SequenceMatcher(None, old_lines, new_lines).ratio()

        summary = self._generate_summary(
            contract, old_ver, new_ver,
            len(old_lines), len(new_lines),
            added, removed, modified, similarity
        )

        return ComparisonResult(
            contract_id=contract.id,
            contract_title=contract.title,
            old_version=old_ver.version_number,
            new_version=new_ver.version_number,
            old_file=old_ver.file_path,
            new_file=new_ver.file_path,
            old_file_exists=Path(old_ver.file_path).exists(),
            new_file_exists=Path(new_ver.file_path).exists(),
            total_lines_old=len(old_lines),
            total_lines_new=len(new_lines),
            lines_added=added,
            lines_removed=removed,
            lines_modified=modified,
            similarity_ratio=similarity,
            sections=diff_sections,
            summary=summary,
        )

    def _compute_diff(
        self,
        old_lines: List[str],
        new_lines: List[str],
    ) -> Tuple[List[DiffSection], int, int, int]:
        """计算差异"""
        sm = difflib.SequenceMatcher(None, old_lines, new_lines)
        opcodes = sm.get_opcodes()

        sections: List[DiffSection] = []
        current_section: Optional[DiffSection] = None
        lines_added = 0
        lines_removed = 0
        lines_modified = 0

        old_line_num = 0
        new_line_num = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                old_line_num = i2
                new_line_num = j2
                continue

            section_lines: List[DiffLine] = []

            if tag in ("replace", "delete"):
                for idx in range(i1, i2):
                    change = "modified" if tag == "replace" else "removed"
                    if tag == "replace":
                        lines_modified += 1
                    else:
                        lines_removed += 1
                    section_lines.append(DiffLine(
                        line_number_old=idx + 1,
                        line_number_new=None,
                        content=old_lines[idx],
                        change_type="removed" if tag == "delete" else "modified",
                    ))

            if tag in ("replace", "insert"):
                for idx in range(j1, j2):
                    change = "modified" if tag == "replace" else "added"
                    if tag == "insert":
                        lines_added += 1
                    section_lines.append(DiffLine(
                        line_number_old=None,
                        line_number_new=idx + 1,
                        content=new_lines[idx],
                        change_type="added" if tag == "insert" else "modified",
                    ))

            if section_lines:
                section = DiffSection(
                    section_name=self._guess_section_name(old_lines, new_lines, i1, j1),
                    lines=section_lines,
                    old_start=i1 + 1,
                    old_end=i2,
                    new_start=j1 + 1,
                    new_end=j2,
                )
                sections.append(section)

            old_line_num = i2
            new_line_num = j2

        if not sections:
            sections.append(DiffSection(
                section_name="两版本内容一致",
                lines=[],
                old_start=0, old_end=0,
                new_start=0, new_end=0,
            ))

        return sections, lines_added, lines_removed, lines_modified

    def _guess_section_name(
        self,
        old_lines: List[str],
        new_lines: List[str],
        old_idx: int,
        new_idx: int,
    ) -> str:
        """猜测差异所在章节名称"""
        section_keywords = [
            "第", "条", "章", "节", "款", "Clause", "Article",
            "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、",
            "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.",
            "甲方", "乙方", "权利", "义务", "责任", "违约", "保密",
            "付款", "交付", "验收", "质保", "争议", "管辖", "解除",
            "终止", "生效", "续签", "补充", "附件",
        ]

        search_range = range(max(0, old_idx - 15), old_idx)
        for idx in reversed(list(search_range)):
            line = old_lines[idx].strip()
            if line:
                for kw in section_keywords:
                    if kw in line:
                        return f"第{idx + 1}行附近: {line[:40]}"
                if idx == old_idx - 1:
                    return f"第{idx + 1}行: {line[:40]}"

        search_range2 = range(max(0, new_idx - 15), new_idx)
        for idx in reversed(list(search_range2)):
            line = new_lines[idx].strip()
            if line:
                for kw in section_keywords:
                    if kw in line:
                        return f"新文件第{idx + 1}行: {line[:40]}"

        return f"位置 {old_idx + 1} - {new_idx + 1}"

    def _generate_summary(
        self,
        contract: Contract,
        old_ver: ContractVersion,
        new_ver: ContractVersion,
        old_lines: int,
        new_lines: int,
        added: int,
        removed: int,
        modified: int,
        similarity: float,
    ) -> str:
        """生成比对摘要"""
        total_changes = added + removed + modified
        lines = []
        lines.append(f"【{contract.title}】版本差异摘要")
        lines.append(f"  合同编号: {contract.id}")
        lines.append(f"  比对版本: v{old_ver.version_number} → v{new_ver.version_number}")
        lines.append(f"  导入时间: {old_ver.imported_at} → {new_ver.imported_at}")
        lines.append(f"  文件行数: {old_lines} 行 → {new_lines} 行 (Δ {new_lines - old_lines:+d})")
        lines.append(f"  内容相似度: {similarity:.1%}")
        lines.append("")
        lines.append("变更统计:")
        lines.append(f"  新增: {added} 行")
        lines.append(f"  删除: {removed} 行")
        lines.append(f"  修改: {modified} 处")
        lines.append(f"  总计: {total_changes} 处变更")
        if new_ver.note:
            lines.append(f"  新版本备注: {new_ver.note}")

        return "\n".join(lines)

    def export_diff_html(self, result: ComparisonResult, output_path: str) -> str:
        """导出比对结果为HTML"""
        html_parts = ["""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>合同版本比对 - {title}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", sans-serif; margin: 20px; color: #333; }}
h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
h2 {{ color: #34495e; margin-top: 30px; }}
.summary {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0; }}
.stat-box {{ display: inline-block; padding: 8px 16px; margin: 5px; border-radius: 4px; font-weight: bold; }}
.added {{ background: #d4edda; color: #155724; }}
.removed {{ background: #f8d7da; color: #721c24; }}
.modified {{ background: #fff3cd; color: #856404; }}
.unchanged {{ background: #e9ecef; color: #495057; }}
.diff-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
.diff-table th {{ background: #343a40; color: white; padding: 10px; text-align: left; }}
.diff-table td {{ padding: 6px 10px; border-bottom: 1px solid #dee2e6; vertical-align: top; font-family: Consolas, monospace; white-space: pre-wrap; word-break: break-all; }}
.line-num {{ color: #868e96; width: 60px; text-align: right; user-select: none; }}
.section-title {{ background: #e3f2fd; padding: 8px 12px; border-radius: 4px; margin: 15px 0 5px; font-weight: bold; color: #1565c0; }}
.missing {{ color: #dc3545; font-style: italic; }}
</style>
</head>
<body>
""".format(title=result.contract_title)]

        html_parts.append(f"<h1>合同版本比对报告</h1>")
        html_parts.append(f"<h2>{result.contract_title} <small>({result.contract_id})</small></h2>")

        html_parts.append("<div class='summary'>")
        html_parts.append(f"<p><strong>比对版本:</strong> v{result.old_version} → v{result.new_version}</p>")
        html_parts.append(f"<p><strong>旧文件:</strong> {result.old_file}")
        if not result.old_file_exists:
            html_parts.append(" <span class='missing'>(文件不存在)</span>")
        html_parts.append("</p>")
        html_parts.append(f"<p><strong>新文件:</strong> {result.new_file}")
        if not result.new_file_exists:
            html_parts.append(" <span class='missing'>(文件不存在)</span>")
        html_parts.append("</p>")
        html_parts.append(f"<p><strong>内容相似度:</strong> {result.similarity_ratio:.1%}</p>")
        html_parts.append("<div>")
        html_parts.append(f"<span class='stat-box added'>新增 {result.lines_added} 行</span>")
        html_parts.append(f"<span class='stat-box removed'>删除 {result.lines_removed} 行</span>")
        html_parts.append(f"<span class='stat-box modified'>修改 {result.lines_modified} 处</span>")
        html_parts.append("</div>")
        html_parts.append("</div>")

        html_parts.append("<h2>差异详情</h2>")

        for section in result.sections:
            html_parts.append(f"<div class='section-title'>{section.section_name}</div>")
            if not section.lines:
                html_parts.append("<p style='color:#6c757d; padding-left:15px;'>（无内容差异）</p>")
                continue

            html_parts.append("<table class='diff-table'>")
            html_parts.append("<tr><th>旧行号</th><th>新行号</th><th>内容</th><th>类型</th></tr>")

            for line in section.lines:
                cls = line.change_type
                old_num = line.line_number_old or ""
                new_num = line.line_number_new or ""
                type_label = {"added": "新增", "removed": "删除", "modified": "修改", "unchanged": "未变"}[line.change_type]
                escaped_content = (line.content
                                   .replace("&", "&amp;")
                                   .replace("<", "&lt;")
                                   .replace(">", "&gt;"))
                html_parts.append(
                    f"<tr class='{cls}'>"
                    f"<td class='line-num'>{old_num}</td>"
                    f"<td class='line-num'>{new_num}</td>"
                    f"<td>{escaped_content or '&nbsp;'}</td>"
                    f"<td>{type_label}</td>"
                    f"</tr>"
                )

            html_parts.append("</table>")

        html_parts.append("</body></html>")

        out_path = Path(output_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        return str(out_path)

    def find_all_comparable(self) -> List[Contract]:
        """查找所有可比对的合同（2个版本及以上）"""
        contracts = self.store.get_all_contracts()
        return [c for c in contracts if len(c.versions) >= 2]
