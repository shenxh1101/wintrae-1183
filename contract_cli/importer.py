"""合同导入模块"""
import os
import re
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

from .models import Contract, ContractVersion, KeyInfo, ReviewStatus, RiskLevel
from .storage import ContractStore


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".docx", ".doc", ".pdf",
    ".rtf", ".odt", ".html", ".htm", ".csv"
}

_EXTRACTION_OK = "完整提取"
_EXTRACTION_PARTIAL = "部分提取"
_EXTRACTION_FAILED = "提取失败"
_EXTRACTION_BINARY = "非文本格式"


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

    def read_file_text(self, file_path: Path) -> Tuple[str, str, str]:
        """读取文件文本内容，返回 (正文, 提取状态, 提取说明)"""
        suffix = file_path.suffix.lower()
        try:
            if suffix in {".txt", ".md", ".html", ".htm", ".csv"}:
                encodings = ["utf-8", "gbk", "gb2312", "gb18030", "latin-1"]
                for enc in encodings:
                    try:
                        with open(file_path, "r", encoding=enc) as f:
                            text = f.read()
                        return text, _EXTRACTION_OK, f"纯文本({enc})"
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                return "", _EXTRACTION_FAILED, "无法识别文件编码"

            elif suffix == ".rtf":
                return self._extract_rtf(file_path)

            elif suffix == ".odt":
                return self._extract_odt(file_path)

            elif suffix == ".docx":
                return self._extract_docx(file_path)

            elif suffix == ".doc":
                return self._extract_doc(file_path)

            elif suffix == ".pdf":
                return self._extract_pdf(file_path)

            else:
                return f"[{suffix} 格式文件，内容需手动审阅]", _EXTRACTION_BINARY, "不支持直接提取"

        except Exception as e:
            return "", _EXTRACTION_FAILED, str(e)

    def _extract_rtf(self, file_path: Path) -> Tuple[str, str, str]:
        """提取 RTF 文件文本"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                rtf_text = f.read()
            clean = re.sub(r'\\[a-z]+\d*\s?', ' ', rtf_text)
            clean = re.sub(r'[{}]', '', clean)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) < 20:
                return clean, _EXTRACTION_PARTIAL, "RTF结构解析有限，建议转存为docx"
            return clean, _EXTRACTION_PARTIAL, "RTF简易解析，格式信息有损"
        except Exception as e:
            return "", _EXTRACTION_FAILED, f"RTF解析失败: {e}"

    def _extract_odt(self, file_path: Path) -> Tuple[str, str, str]:
        """提取 ODT 文件文本"""
        try:
            import zipfile
            with zipfile.ZipFile(file_path, "r") as zf:
                if "content.xml" in zf.namelist():
                    raw = zf.read("content.xml").decode("utf-8")
                    clean = re.sub(r'<[^>]+>', ' ', raw)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    return clean, _EXTRACTION_OK, "ODT提取成功"
            return "", _EXTRACTION_PARTIAL, "ODT文件结构异常"
        except Exception as e:
            return "", _EXTRACTION_FAILED, f"ODT解析失败: {e}"

    def _extract_docx(self, file_path: Path) -> Tuple[str, str, str]:
        """提取 DOCX 文件文本"""
        try:
            import zipfile
            paragraphs = []
            with zipfile.ZipFile(file_path, "r") as zf:
                if "word/document.xml" in zf.namelist():
                    raw = zf.read("word/document.xml").decode("utf-8")
                    raw = re.sub(r'<w:p[^/]*/>', '', raw)
                    splits = re.split(r'</w:p>', raw)
                    for seg in splits:
                        seg_clean = re.sub(r'<[^>]+>', '', seg).strip()
                        if seg_clean:
                            paragraphs.append(seg_clean)
            text = "\n".join(paragraphs)
            if not text.strip():
                return "", _EXTRACTION_PARTIAL, "DOCX未提取到文本内容"
            return text, _EXTRACTION_OK, f"DOCX提取成功({len(paragraphs)}段)"
        except zipfile.BadZipFile:
            return "", _EXTRACTION_FAILED, "DOCX文件损坏或非标准格式"
        except Exception as e:
            return "", _EXTRACTION_FAILED, f"DOCX解析失败: {e}"

    def _extract_doc(self, file_path: Path) -> Tuple[str, str, str]:
        """提取 DOC 文件文本"""
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            text_parts = []
            for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    decoded = raw.decode(enc, errors="ignore")
                    clean = re.sub(r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s.,;:!?()\uff08\uff09\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\u201c\u201d\u2018\u2019\u3010\u3011\u300a\u300b/<>%\uffe5$\u20ac\u00a3@#&*+=|~^\-\[\]{}]', ' ', decoded)
                    clean = re.sub(r'\s{3,}', '\n', clean)
                    meaningful = re.findall(r'[\u4e00-\u9fff]{3,}', clean)
                    if meaningful:
                        text_parts = meaningful
                        break
                except Exception:
                    continue
            if text_parts:
                return "\n".join(text_parts), _EXTRACTION_PARTIAL, "DOC格式(旧版Word)有限提取，建议转存docx"
            return "", _EXTRACTION_FAILED, "DOC格式无法有效提取，请转存为docx后重新导入"
        except Exception as e:
            return "", _EXTRACTION_FAILED, f"DOC解析失败: {e}"

    def _extract_pdf(self, file_path: Path) -> Tuple[str, str, str]:
        """提取 PDF 文件文本"""
        try:
            import zipfile
            with zipfile.ZipFile(file_path, "r") as zf:
                if zf.namelist():
                    return "", _EXTRACTION_PARTIAL, "PDF为扫描件/加密文件，需安装pymupdf后重新导入"
        except zipfile.BadZipFile:
            pass
        except Exception:
            pass

        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            text_parts = []
            for enc in ["utf-8", "gbk", "gb18030"]:
                try:
                    decoded = raw.decode(enc, errors="ignore")
                    meaningful = re.findall(r'[\u4e00-\u9fff]{3,}', decoded)
                    if meaningful:
                        text_parts.extend(meaningful[:50])
                        break
                except Exception:
                    continue
            if text_parts:
                return "\n".join(text_parts), _EXTRACTION_PARTIAL, "PDF简易提取(有限)，建议安装pymupdf获得完整支持"
            return "", _EXTRACTION_PARTIAL, "PDF无法提取文本，可能是扫描件或加密，建议安装pymupdf"
        except Exception as e:
            return "", _EXTRACTION_FAILED, f"PDF解析失败: {e}"

    def extract_key_info_from_text(self, text: str) -> KeyInfo:
        """从合同文本中半自动提取关键信息"""
        info = KeyInfo()
        if not text or text.startswith("["):
            info.placeholders = self._default_placeholders()
            return info

        info.party_a = self._extract_party(text, "甲方")
        info.party_b = self._extract_party(text, "乙方")
        info.contract_amount = self._extract_amount(text)
        info.start_date = self._extract_date(text, "生效|开始|起始|签订日期|起算")
        info.end_date = self._extract_date(text, "终止|结束|届满|到期|截止日期")
        info.contract_type = self._extract_contract_type(text)
        info.signing_location = self._extract_signing_location(text)
        info.placeholders = self._extract_clause_placeholders(text)

        return info

    def _default_placeholders(self) -> dict:
        return {
            "合同编号": "待提取",
            "付款方式": "待提取",
            "违约责任": "待审核",
            "保密条款": "待审核",
            "知识产权": "待审核",
            "争议解决": "待审核",
            "不可抗力": "待审核",
            "解除条款": "待审核",
            "续约条款": "待审核",
        }

    def _extract_party(self, text: str, label: str) -> Optional[str]:
        """提取甲/乙方名称"""
        patterns = [
            rf'{label}[：:]\s*([^\n,，、；;（(（\[]{{2,40}})',
            rf'{label}（[^））]*）[：:]\s*([^\n,，、；;（(（\[]{{2,40}})',
            rf'{label}[为是]\s*([^\n,，、；;（(（\[]{{2,40}})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                name = m.group(1).strip()
                name = re.sub(r'\s+', '', name)
                name = name.rstrip("（(").rstrip(",")
                if 2 <= len(name) <= 40:
                    return name
        return None

    def _extract_amount(self, text: str) -> Optional[str]:
        """提取合同金额"""
        patterns = [
            r'(?:合同|总)?金额[为大约：:共计计人民币]*[人民币RMB￥]?\s*([\d,，.]+\s*[万亿]?元)',
            r'[人民币RMB￥]\s*([\d,，.]+\s*[万亿]?元)',
            r'([\d,，.]+\s*[万亿]?元)[（(整正)]',
            r'价款[为大约：:共计]*[人民币RMB￥]?\s*([\d,，.]+\s*[万亿]?元)',
            r'(?:费用|总价|总款)[为大约：:共计]*[人民币RMB￥]?\s*([\d,，.]+\s*[万亿]?元)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                amount = m.group(1).strip()
                amount = amount.replace(",", "").replace("，", "")
                return amount
        return None

    def _extract_date(self, text: str, keywords: str) -> Optional[str]:
        """提取日期"""
        patterns = [
            rf'(?:{keywords})[日期时间：:为自起]*\s*(\d{{4}})\s*年\s*(\d{{1,2}})\s*月\s*(\d{{1,2}})\s*日',
            rf'(\d{{4}})\s*年\s*(\d{{1,2}})\s*月\s*(\d{{1,2}})\s*日.*?(?:{keywords})',
            rf'(\d{{4}})[-/.](\d{{1,2}})[-/.](\d{{1,2}})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    y, mo, d = m.group(1), m.group(2), m.group(3)
                    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                except (ValueError, IndexError):
                    continue
        return None

    def _extract_contract_type(self, text: str) -> Optional[str]:
        """提取合同类型"""
        type_keywords = {
            "采购合同": ["采购", "购买", "购置", "进货"],
            "销售合同": ["销售", "出售", "售卖", "供货"],
            "服务合同": ["服务", "咨询", "顾问", "委托", "代理"],
            "租赁合同": ["租赁", "租借", "承租", "出租"],
            "劳动合同": ["劳动", "雇佣", "聘用", "入职"],
            "技术开发合同": ["技术开发", "软件开发", "系统开发"],
            "保密协议": ["保密", "NDA", "不披露"],
            "合作协议": ["合作", "协作", "联合"],
            "建设工程合同": ["建设", "工程", "施工", "装修"],
            "运输合同": ["运输", "货运", "物流", "配送"],
            "许可合同": ["许可", "授权", "License"],
            "外包合同": ["外包", "委托开发", "外协"],
        }
        title_match = re.search(r'([\u4e00-\u9fff]+合同|[\u4e00-\u9fff]+协议)', text[:200])
        if title_match:
            return title_match.group(1)
        for ctype, keywords in type_keywords.items():
            for kw in keywords:
                if kw in text[:500]:
                    return ctype
        return None

    def _extract_signing_location(self, text: str) -> Optional[str]:
        """提取签订地点"""
        patterns = [
            r'签订地点[：:]\s*([^\n,，；;]{2,20})',
            r'签署地[点：:]\s*([^\n,，；;]{2,20})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                loc = m.group(1).strip()
                loc = re.sub(r'[。，；,;].*$', '', loc)
                return loc
        return None

    def _extract_clause_placeholders(self, text: str) -> dict:
        """提取关键条款占位信息"""
        ph = {}
        clause_map = {
            "付款方式": ["付款", "支付", "结算"],
            "违约责任": ["违约", "赔偿", "违约金"],
            "保密条款": ["保密", "秘密", "不披露"],
            "知识产权": ["知识产权", "专利", "著作权", "商标"],
            "争议解决": ["争议", "仲裁", "管辖", "诉讼"],
            "不可抗力": ["不可抗力", "不可预见"],
            "解除条款": ["解除", "终止", "撤销"],
            "续约条款": ["续签", "续约", "顺延", "延期"],
        }
        for clause_name, keywords in clause_map.items():
            found = False
            for kw in keywords:
                if kw in text:
                    line = self._extract_clause_line(text, kw)
                    if line:
                        ph[clause_name] = line[:60]
                    else:
                        ph[clause_name] = "已包含相关条款"
                    found = True
                    break
            if not found:
                ph[clause_name] = "待确认"

        contract_no_match = re.search(r'(?:合同|编号)[编号：:号]\s*([A-Za-z0-9\u4e00-\u9fff\-_]+)', text[:500])
        if contract_no_match:
            ph["合同编号"] = contract_no_match.group(1).strip()
        else:
            ph["合同编号"] = "待提取"

        return ph

    def _extract_clause_line(self, text: str, keyword: str) -> Optional[str]:
        """提取包含关键词的那一行"""
        for line in text.splitlines():
            if keyword in line:
                return line.strip()
        return None

    def import_file(
        self,
        file_path: Path,
        project: Optional[str] = None,
        base_dir: Optional[Path] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Tuple[Contract, bool, str]:
        """导入单个合同文件，返回 (合同, 是否新增, 提取状态)"""
        checksum = self.store.compute_checksum(str(file_path))
        str_path = str(file_path)
        file_text, extraction_status, extraction_note = self.read_file_text(file_path)

        existing_same_path = self._find_contract_by_file_path(str_path)

        version = ContractVersion(
            version_number=1,
            file_path=str_path,
            file_name=file_path.name,
            checksum=checksum,
            note="初始导入版本",
            content_snapshot=file_text,
            extraction_status=extraction_status,
            extraction_note=extraction_note,
        )

        if existing_same_path:
            latest_version = max(existing_same_path.versions, key=lambda v: v.version_number)
            if latest_version.checksum == checksum:
                return existing_same_path, False, "内容无变化，跳过"

            new_version_num = latest_version.version_number + 1
            version.version_number = new_version_num
            version.note = f"新版本导入 (v{new_version_num})"
            existing_same_path.versions.append(version)
            existing_same_path.current_version = new_version_num
            existing_same_path.file_path = str_path
            existing_same_path.file_name = file_path.name

            if file_text and extraction_status in (_EXTRACTION_OK, _EXTRACTION_PARTIAL):
                new_info = self.extract_key_info_from_text(file_text)
                self._merge_key_info(existing_same_path.key_info, new_info)

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
            return existing_same_path, True, f"版本更新v{new_version_num} ({extraction_status})"

        contract_title = self.extract_title_from_filename(file_path.name)
        inferred_project = project or self.infer_project_from_path(file_path, base_dir)
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
        return contract, True, extraction_status

    def import_directory(
        self,
        directory: str,
        project: Optional[str] = None,
        recursive: bool = True,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Tuple[List[Tuple[Contract, bool, str]], List[str]]:
        """批量导入目录中的合同文件"""
        files = self.scan_directory(directory, recursive)
        base_dir = Path(directory).resolve()

        results: List[Tuple[Contract, bool, str]] = []
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

    def _merge_key_info(self, existing: KeyInfo, new_info: KeyInfo) -> None:
        """合并关键信息：已有值不覆盖，空值用新值填充"""
        if not existing.party_a and new_info.party_a:
            existing.party_a = new_info.party_a
        if not existing.party_b and new_info.party_b:
            existing.party_b = new_info.party_b
        if not existing.contract_amount and new_info.contract_amount:
            existing.contract_amount = new_info.contract_amount
        if not existing.start_date and new_info.start_date:
            existing.start_date = new_info.start_date
        if not existing.end_date and new_info.end_date:
            existing.end_date = new_info.end_date
        if not existing.contract_type and new_info.contract_type:
            existing.contract_type = new_info.contract_type
        if not existing.signing_location and new_info.signing_location:
            existing.signing_location = new_info.signing_location
        for k, v in new_info.placeholders.items():
            if k not in existing.placeholders or existing.placeholders[k] in ("待提取", "待审核", "待确认"):
                existing.placeholders[k] = v

    def _find_contract_by_file_path(self, file_path: str) -> Optional[Contract]:
        """通过文件路径查找合同（同一路径=同一合同，内容变化=新版本）"""
        contracts = self.store.get_all_contracts()
        normalized = os.path.normcase(os.path.abspath(file_path))
        for c in contracts:
            if os.path.normcase(os.path.abspath(c.file_path)) == normalized:
                return c
            for v in c.versions:
                if os.path.normcase(os.path.abspath(v.file_path)) == normalized:
                    return c
        return None
