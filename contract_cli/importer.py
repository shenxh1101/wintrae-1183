"""合同导入模块"""
import os
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

from .models import Contract, ContractVersion, KeyInfo, ReviewStatus, RiskLevel
from .storage import ContractStore


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".docx", ".doc", ".pdf",
    ".rtf", ".odt", ".html", ".htm"
}


class ContractImporter:
    """合同文件导入器"""

    def __init__(self, store: ContractStore):
        self.store = store

    def scan_directory(self, directory: str, recursive: bool = True) -> List[Path]:
        """扫描目录中的合同文件"""
        dir_path = Path(directory).resolve()
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {directory}")
        if not dir_path.is_dir():
            raise NotADirectoryError(f"不是有效的目录: {directory}")

        files = []
        pattern = "**/*" if recursive else "*"
        for file_path in dir_path.glob(pattern):
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                if file_path.name.startswith("~$"):
                    continue
                files.append(file_path)
        return sorted(files)

    def extract_title_from_filename(self, filename: str) -> str:
        """从文件名提取合同标题"""
        stem = Path(filename).stem
        title = stem.replace("_", " ").replace("-", " ").replace(".", " ")
        return title.strip() or filename

    def infer_project_from_path(self, file_path: Path, base_dir: Optional[Path] = None) -> str:
        """从路径推断项目名称"""
        if base_dir:
            try:
                rel_path = file_path.relative_to(base_dir)
                parts = rel_path.parts
                if len(parts) > 1:
                    return parts[0]
            except ValueError:
                pass
        else:
            parent = file_path.parent
            if parent.name and parent.name != parent.root:
                return parent.name
        return "未分类"

    def extract_key_info_from_text(self, text: str) -> KeyInfo:
        """从文本中提取关键信息（占位模式）"""
        info = KeyInfo()
        info.placeholders = {
            "合同编号": "待提取",
            "签订地点": "待提取",
            "签订日期": "待提取",
            "生效日期": "待提取",
            "终止日期": "待提取",
            "合同金额": "待提取",
            "付款方式": "待提取",
            "违约责任": "待审核",
            "保密条款": "待审核",
            "知识产权": "待审核",
            "争议解决": "待审核",
            "不可抗力": "待审核",
            "解除条款": "待审核",
            "续约条款": "待审核",
        }
        return info

    def read_file_text(self, file_path: Path) -> str:
        """读取文件文本内容"""
        try:
            suffix = file_path.suffix.lower()
            if suffix in {".txt", ".md", ".html", ".htm", ".rtf", ".odt"}:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            elif suffix == ".csv":
                with open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    return f.read()
            else:
                return f"[二进制文件 {file_path.suffix}，内容需手动审阅]"
        except Exception:
            return f"[无法读取文件内容]"

    def read_file_lines(self, file_path: Path) -> List[str]:
        """读取文件行列表"""
        text = self.read_file_text(file_path)
        return text.splitlines()

    def import_file(
        self,
        file_path: Path,
        project: Optional[str] = None,
        base_dir: Optional[Path] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Tuple[Contract, bool]:
        """导入单个合同文件"""
        checksum = self.store.compute_checksum(str(file_path))
        str_path = str(file_path)
        file_text = self.read_file_text(file_path)

        existing_same_content = self._find_contract_by_checksum(checksum)
        if existing_same_content:
            return existing_same_content, False

        existing_same_path = self._find_contract_by_file_path(str_path)

        version = ContractVersion(
            version_number=1,
            file_path=str_path,
            file_name=file_path.name,
            checksum=checksum,
            note="初始导入版本",
            content_snapshot=file_text,
        )

        if existing_same_path:
            latest_version = max(existing_same_path.versions, key=lambda v: v.version_number)
            new_version_num = latest_version.version_number + 1
            version.version_number = new_version_num
            version.note = f"新版本导入 (v{new_version_num})"
            version.content_snapshot = file_text
            existing_same_path.versions.append(version)
            existing_same_path.current_version = new_version_num
            existing_same_path.file_path = str_path
            existing_same_path.file_name = file_path.name

            if project and project != existing_same_path.project:
                existing_same_path.project = project
            if assignee and not existing_same_path.assignee:
                existing_same_path.assignee = assignee
            if due_date and not existing_same_path.due_date:
                existing_same_path.due_date = due_date
            if tags:
                for tag in tags:
                    if tag not in existing_same_path.tags:
                        existing_same_path.tags.append(tag)

            self.store.update_contract(existing_same_path)
            return existing_same_path, True

        contract_title = self.extract_title_from_filename(file_path.name)
        inferred_project = project or self.infer_project_from_path(file_path, base_dir)
        file_text = self.read_file_text(file_path)
        key_info = self.extract_key_info_from_text(file_text)

        contract = Contract(
            title=contract_title,
            project=inferred_project,
            file_path=str(file_path),
            file_name=file_path.name,
            versions=[version],
            current_version=1,
            status=ReviewStatus.PENDING,
            risk_level=RiskLevel.MEDIUM,
            key_info=key_info,
            assignee=assignee,
            due_date=due_date,
            tags=tags or [],
        )

        self.store.add_contract(contract)
        return contract, True

    def import_directory(
        self,
        directory: str,
        project: Optional[str] = None,
        recursive: bool = True,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Tuple[List[Tuple[Contract, bool]], List[str]]:
        """批量导入目录中的合同文件"""
        files = self.scan_directory(directory, recursive)
        base_dir = Path(directory).resolve()

        results: List[Tuple[Contract, bool]] = []
        errors: List[str] = []

        for file_path in files:
            try:
                result = self.import_file(
                    file_path,
                    project=project,
                    base_dir=base_dir,
                    assignee=assignee,
                    due_date=due_date,
                    tags=tags,
                )
                results.append(result)
            except Exception as e:
                errors.append(f"{file_path}: {e}")

        return results, errors

    def _find_contract_by_checksum(self, checksum: str) -> Optional[Contract]:
        """通过校验和查找合同"""
        contracts = self.store.get_all_contracts()
        for c in contracts:
            for v in c.versions:
                if v.checksum == checksum:
                    return c
        return None

    def _find_contract_by_file_path(self, file_path: str) -> Optional[Contract]:
        """通过文件路径查找合同（同一文件内容变化即新版本）"""
        contracts = self.store.get_all_contracts()
        normalized_path = os.path.normcase(os.path.abspath(file_path))
        for c in contracts:
            if os.path.normcase(os.path.abspath(c.file_path)) == normalized_path:
                return c
            for v in c.versions:
                if os.path.normcase(os.path.abspath(v.file_path)) == normalized_path:
                    return c
        return None
