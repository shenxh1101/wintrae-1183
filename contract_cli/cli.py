"""命令行接口入口"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .storage import ContractStore
from .importer import ContractImporter
from .reviewer import ContractReviewer
from .comparer import ContractComparer
from .summarizer import ContractSummarizer
from .models import (
    Contract, ReviewStatus, RiskLevel,
    ContractVersion, Issue
)


console = Console()
ERROR_STYLE = "bold red"
SUCCESS_STYLE = "bold green"
INFO_STYLE = "bold blue"
WARN_STYLE = "bold yellow"


def get_store(base_path: str = ".") -> ContractStore:
    """获取存储实例"""
    return ContractStore(base_path)


def status_style(status: ReviewStatus) -> str:
    """状态样式映射"""
    mapping = {
        ReviewStatus.PENDING: "[yellow]待审阅[/yellow]",
        ReviewStatus.IN_PROGRESS: "[cyan]审阅中[/cyan]",
        ReviewStatus.NEEDS_REVISION: "[magenta]待修改[/magenta]",
        ReviewStatus.APPROVED: "[green]已通过[/green]",
        ReviewStatus.REJECTED: "[red]已拒绝[/red]",
    }
    return mapping.get(status, status.value)


def risk_style(risk: RiskLevel) -> str:
    """风险样式映射"""
    mapping = {
        RiskLevel.LOW: "[green]低[/green]",
        RiskLevel.MEDIUM: "[yellow]中[/yellow]",
        RiskLevel.HIGH: "[magenta]高[/magenta]",
        RiskLevel.CRITICAL: "[bold red]严重[/bold red]",
    }
    return mapping.get(risk, risk.value)


def show_warning(msg: str) -> None:
    console.print(f"⚠️  [{WARN_STYLE}]{msg}[/{WARN_STYLE}]")


def show_error(msg: str) -> None:
    console.print(f"❌ [{ERROR_STYLE}]错误: {msg}[/{ERROR_STYLE}]")


def show_success(msg: str) -> None:
    console.print(f"✅ [{SUCCESS_STYLE}]{msg}[/{SUCCESS_STYLE}]")


def show_info(msg: str) -> None:
    console.print(f"ℹ️  [{INFO_STYLE}]{msg}[/{INFO_STYLE}]")


# =============================================================================
# CLI 主组
# =============================================================================

@click.group(help="法务合同审阅管理命令行工具 - 整理合同审阅任务和版本往来")
@click.version_option("1.0.0", prog_name="contract-cli")
def main():
    pass


# =============================================================================
# init 命令组
# =============================================================================

@main.group(help="初始化工作区和项目管理")
def init():
    pass


@init.command("workspace", help="在当前目录初始化合同管理工作区")
@click.option("--force", "-f", is_flag=True, help="强制重新初始化")
def init_workspace(force: bool):
    store = get_store()
    if store.is_initialized() and not force:
        show_warning("当前目录已初始化，使用 --force 强制重新初始化")
        return
    try:
        store.initialize()
        show_success(f"工作区初始化成功！数据目录: {store.data_dir}")
        console.print(Panel(
            "[green]可用命令:\n"
            "  contract-cli import dir <目录>   批量导入合同\n"
            "  contract-cli review list         查看合同列表\n"
            "  contract-cli compare diff <id>   比对版本差异\n"
            "  contract-cli summary all         生成汇总报告[/green]",
            title="下一步", border_style="green"
        ))
    except Exception as e:
        show_error(str(e))


@init.command("project", help="创建或查看项目")
@click.argument("name", required=False)
@click.option("--description", "-d", default="", help="项目描述")
def init_project(name: Optional[str], description: str):
    store = get_store()
    if not name:
        projects = store.get_projects()
        if not projects:
            show_warning("暂无项目，请先创建")
            return
        table = Table(title="项目列表", box=box.ROUNDED)
        table.add_column("项目名称", style="bold")
        table.add_column("合同数", justify="right")
        table.add_column("创建时间")
        table.add_column("描述")
        for p in projects:
            table.add_row(p.name, str(p.contract_count), p.created_at, p.description)
        console.print(table)
        return

    if store.add_project(name, description):
        show_success(f"项目 '{name}' 创建成功")
    else:
        show_warning(f"项目 '{name}' 已存在")


# =============================================================================
# import 命令组
# =============================================================================

@main.group(help="批量导入合同文件")
def import_cmd():
    pass


@import_cmd.command("dir", help="从目录批量导入合同文件")
@click.argument("directory")
@click.option("--project", "-p", default=None, help="指定项目名称")
@click.option("--no-recursive", is_flag=True, help="不递归子目录")
@click.option("--assignee", "-a", default=None, help="指派负责人")
@click.option("--due", "-D", default=None, help="截止日期 YYYY-MM-DD")
@click.option("--tag", "-t", multiple=True, help="添加标签")
def import_directory(directory, project, no_recursive, assignee, due, tag):
    store = get_store()
    if not store.is_initialized():
        show_error("当前目录未初始化，请先运行: contract-cli init workspace")
        return
    importer = ContractImporter(store)
    tags = list(tag) if tag else None
    try:
        results, errors = importer.import_directory(
            directory=directory,
            project=project,
            recursive=not no_recursive,
            assignee=assignee,
            due_date=due,
            tags=tags,
        )
    except Exception as e:
        show_error(str(e))
        return

    new_count = sum(1 for _, is_new, _ in results if is_new)
    skip_count = sum(1 for _, is_new, _ in results if not is_new)
    updated_count = sum(1 for _, is_new, _ in results if is_new and "版本更新" in (_[2] if len(_) > 2 else ""))

    ok_count = sum(1 for _, _, ext in results if ext == "完整提取")
    partial_count = sum(1 for _, _, ext in results if "部分" in ext)
    fail_count = sum(1 for _, _, ext in results if "失败" in ext or "非文本" in ext)

    table = Table(title=f"导入结果 (共{len(results)}份)", box=box.ROUNDED)
    table.add_column("#", justify="right")
    table.add_column("导入状态")
    table.add_column("提取状态")
    table.add_column("ID")
    table.add_column("合同标题", style="bold")
    table.add_column("项目")
    table.add_column("版本")

    for idx, (contract, is_new, ext_status) in enumerate(results, 1):
        if is_new and "版本" in ext_status:
            import_text = "[cyan]版本更新[/cyan]"
        elif is_new:
            import_text = "[green]新导入[/green]"
        else:
            import_text = "[dim]跳过[/dim]"
        if ext_status == "完整提取":
            ext_display = f"[green]{ext_status}[/green]"
        elif "部分" in ext_status:
            ext_display = f"[yellow]{ext_status}[/yellow]"
        elif "失败" in ext_status or "非文本" in ext_status:
            ext_display = f"[red]{ext_status}[/red]"
        else:
            ext_display = ext_status
        table.add_row(
            str(idx), import_text, ext_display, contract.id,
            contract.title[:30], contract.project,
            f"v{contract.current_version}"
        )
    console.print(table)

    parts = []
    if new_count:
        parts.append(f"[green]新导入/更新 {new_count} 份[/green]")
    if skip_count:
        parts.append(f"[dim]跳过 {skip_count} 份[/dim]")
    show_success("导入完成: " + "，".join(parts))

    if ok_count or partial_count or fail_count:
        ext_parts = []
        if ok_count:
            ext_parts.append(f"[green]完整提取 {ok_count} 份[/green]")
        if partial_count:
            ext_parts.append(f"[yellow]部分提取 {partial_count} 份[/yellow]")
        if fail_count:
            ext_parts.append(f"[red]提取失败 {fail_count} 份[/red]")
        show_info("文本提取: " + "，".join(ext_parts))

    if errors:
        show_warning(f"有 {len(errors)} 个文件导入失败:")
        for err in errors[:5]:
            console.print(f"  - {err}")


@import_cmd.command("file", help="导入单个合同文件")
@click.argument("file")
@click.option("--project", "-p", "project_arg", default=None, help="指定项目")
@click.option("--assignee", "-a", default=None, help="指派负责人")
@click.option("--due", "-D", default=None, help="截止日期")
@click.option("--tag", "-t", multiple=True, help="添加标签")
def import_file(file, project_arg, assignee, due, tag):
    store = get_store()
    if not store.is_initialized():
        show_error("当前目录未初始化")
        return
    importer = ContractImporter(store)
    tags = list(tag) if tag else None
    path = Path(file).resolve()
    if not path.exists():
        show_error(f"文件不存在: {file}")
        return
    if not path.is_file():
        show_error(f"不是有效文件: {file}")
        return
    try:
        contract, is_new, ext_status = importer.import_file(
            path, project=project_arg, assignee=assignee,
            due_date=due, tags=tags
        )
    except Exception as e:
        show_error(str(e))
        return

    status_text = "新导入" if is_new else "跳过(无变化)"
    ext_display = f" ({ext_status})" if ext_status else ""
    table = Table(box=box.ROUNDED, title="导入成功")
    table.add_column("ID")
    table.add_column("标题")
    table.add_column("项目")
    table.add_column("版本")
    table.add_column("提取状态")
    table.add_row(contract.id, contract.title, contract.project,
                  f"v{contract.current_version} ({status_text})",
                  ext_status or "-")
    console.print(table)


# =============================================================================
# review 命令组
# =============================================================================

@main.group(help="审阅管理：状态、风险、负责人、问题清单")
def review():
    pass


@review.command("list", help="查看合同列表")
@click.option("--project", "-p", default=None, help="按项目筛选")
@click.option("--status", "-s", default=None,
              type=click.Choice([s.value for s in ReviewStatus]), help="按状态筛选")
@click.option("--assignee", "-a", default=None, help="按负责人筛选")
@click.option("--risk", "-r", default=None,
              type=click.Choice([r.value for r in RiskLevel]), help="按风险筛选")
@click.option("--overdue", is_flag=True, help="只显示逾期")
@click.option("--limit", "-n", default=50, help="显示数量上限")
def review_list(project, status, assignee, risk, overdue, limit):
    store = get_store()
    reviewer = ContractReviewer(store)
    contracts = store.get_all_contracts()
    if project:
        contracts = [c for c in contracts if c.project == project]
    if status:
        contracts = [c for c in contracts if c.status.value == status]
    if assignee:
        contracts = [c for c in contracts if c.assignee == assignee]
    if risk:
        contracts = [c for c in contracts if c.risk_level.value == risk]
    if overdue:
        today = datetime.now().strftime("%Y-%m-%d")
        contracts = [
            c for c in contracts
            if c.due_date and c.due_date < today
            and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]
        ]
    contracts = contracts[:limit]

    if not contracts:
        show_warning("没有找到符合条件的合同")
        return

    table = Table(title=f"合同列表 ({len(contracts)}份)", box=box.ROUNDED)
    table.add_column("ID")
    table.add_column("标题", style="bold")
    table.add_column("项目")
    table.add_column("状态")
    table.add_column("风险")
    table.add_column("负责人")
    table.add_column("截止日期")
    table.add_column("问题")

    today = datetime.now().strftime("%Y-%m-%d")
    for c in contracts:
        issue_count = len([i for i in c.issues if i.status == "待确认"])
        issue_str = f"[yellow]{issue_count}⚠[/yellow]" if issue_count > 0 else "0"
        due_str = c.due_date or "-"
        if (c.due_date and c.due_date < today
                and c.status not in [ReviewStatus.APPROVED, ReviewStatus.REJECTED]):
            due_str = f"[red]{due_str}⚠[/red]"
        elif c.due_date and c.due_date == today:
            due_str = f"[yellow]{due_str}📅[/yellow]"
        table.add_row(
            c.id, c.title[:28], c.project,
            status_style(c.status), risk_style(c.risk_level),
            c.assignee or "-", due_str, issue_str
        )
    console.print(table)


@review.command("show", help="查看合同详情")
@click.argument("contract_id")
def review_show(contract_id):
    store = get_store()
    contract = store.get_contract(contract_id)
    if not contract:
        show_error(f"未找到合同 ID: {contract_id}")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    info = (
        f"[bold]合同标题:[/bold] {contract.title}\n"
        f"[bold]ID:[/bold] {contract.id}\n"
        f"[bold]项目:[/bold] {contract.project}\n"
        f"[bold]状态:[/bold] {status_style(contract.status)}\n"
        f"[bold]风险:[/bold] {risk_style(contract.risk_level)}\n"
        f"[bold]版本:[/bold] v{contract.current_version} / 共 {len(contract.versions)} 个历史版本\n"
        f"[bold]负责人:[/bold] {contract.assignee or '未指派'}\n"
        f"[bold]截止日期:[/bold] {contract.due_date or '未设定'}\n"
        f"[bold]创建:[/bold] {contract.created_at}\n"
        f"[bold]更新:[/bold] {contract.updated_at}\n"
        f"[bold]标签:[/bold] {', '.join(contract.tags) or '无'}"
    )
    console.print(Panel(info.strip(), title="合同基本信息", border_style="blue"))

    ki = contract.key_info
    key_table = Table(title="关键信息", box=box.SIMPLE_HEAD)
    key_table.add_column("字段", style="cyan")
    key_table.add_column("内容")
    key_table.add_row("合同类型", ki.contract_type or "[grey]待填充[/grey]")
    key_table.add_row("甲方", ki.party_a or "[grey]待填充[/grey]")
    key_table.add_row("乙方", ki.party_b or "[grey]待填充[/grey]")
    key_table.add_row("合同金额", ki.contract_amount or "[grey]待填充[/grey]")
    key_table.add_row("开始日期", ki.start_date or "[grey]待填充[/grey]")
    key_table.add_row("结束日期", ki.end_date or "[grey]待填充[/grey]")
    key_table.add_row("签订地点", ki.signing_location or "[grey]待填充[/grey]")
    console.print(key_table)

    if ki.placeholders:
        ph_table = Table(title="关键条款占位", box=box.SIMPLE_HEAD)
        ph_table.add_column("条款", style="magenta")
        ph_table.add_column("状态")
        for k, v in sorted(ki.placeholders.items()):
            color = "green" if v not in ("待提取", "待审核", "待填充") else "yellow"
            ph_table.add_row(k, f"[{color}]{v}[/{color}]")
        console.print(ph_table)

    if contract.issues:
        issue_table = Table(title=f"问题清单 ({len(contract.issues)})", box=box.SIMPLE_HEAD)
        issue_table.add_column("ID", style="cyan")
        issue_table.add_column("描述")
        issue_table.add_column("状态")
        issue_table.add_column("指派")
        issue_table.add_column("创建时间")
        for i in contract.issues:
            color = "yellow" if i.status == "待确认" else "green"
            issue_table.add_row(
                i.id, i.description[:40], f"[{color}]{i.status}[/{color}]",
                i.assignee or "-", i.created_at
            )
        console.print(issue_table)

    if contract.review_notes:
        notes = "\n".join(f"  • {n}" for n in contract.review_notes[-5:])
        console.print(Panel(notes, title="最近审阅备注", border_style="grey"))


@review.command("status", help="更新审阅状态")
@click.argument("contract_id")
@click.argument("status_value", type=click.Choice([s.value for s in ReviewStatus]))
def review_status(contract_id, status_value):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        status_enum = ReviewStatus(status_value)
        contract = reviewer.update_status(contract_id, status_enum)
        show_success(f"状态已更新为: {status_style(contract.status)}")
    except Exception as e:
        show_error(str(e))


@review.command("risk", help="更新风险等级")
@click.argument("contract_id")
@click.argument("risk_value", type=click.Choice([r.value for r in RiskLevel]))
def review_risk(contract_id, risk_value):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        risk_enum = RiskLevel(risk_value)
        contract = reviewer.update_risk_level(contract_id, risk_enum)
        show_success(f"风险已更新为: {risk_style(contract.risk_level)}")
    except Exception as e:
        show_error(str(e))


@review.command("assign", help="指派负责人")
@click.argument("contract_id")
@click.argument("assignee_name")
def review_assign(contract_id, assignee_name):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        reviewer.assign_to(contract_id, assignee_name)
        show_success(f"已指派给 {assignee_name}")
    except Exception as e:
        show_error(str(e))


@review.command("due", help="设置截止日期")
@click.argument("contract_id")
@click.argument("due_date")
def review_due(contract_id, due_date):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        reviewer.set_due_date(contract_id, due_date)
        show_success(f"截止日期已设为 {due_date}")
    except Exception as e:
        show_error(str(e))


@review.command("project", help="变更合同所属项目")
@click.argument("contract_id")
@click.argument("project_name")
def review_project(contract_id, project_name):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        reviewer.change_project(contract_id, project_name)
        show_success(f"已变更到项目: {project_name}")
    except Exception as e:
        show_error(str(e))


@review.command("tag", help="添加或移除标签")
@click.argument("contract_id")
@click.argument("tags", nargs=-1, required=True)
@click.option("--remove", "-r", is_flag=True, help="移除标签")
def review_tag(contract_id, tags, remove):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        if remove:
            reviewer.remove_tags(contract_id, list(tags))
            show_success(f"已移除标签: {', '.join(tags)}")
        else:
            reviewer.add_tags(contract_id, list(tags))
            show_success(f"已添加标签: {', '.join(tags)}")
    except Exception as e:
        show_error(str(e))


@review.command("info", help="更新合同关键信息")
@click.argument("contract_id")
@click.option("--party-a", default=None, help="甲方名称")
@click.option("--party-b", default=None, help="乙方名称")
@click.option("--amount", default=None, help="合同金额")
@click.option("--start", default=None, help="开始日期")
@click.option("--end", default=None, help="结束日期")
@click.option("--type", "contract_type", default=None, help="合同类型")
@click.option("--location", default=None, help="签订地点")
@click.option("--ph", nargs=2, multiple=True, help="更新占位条款 (名称 值)")
def review_info(contract_id, party_a, party_b, amount, start, end,
                contract_type, location, ph):
    store = get_store()
    reviewer = ContractReviewer(store)
    kwargs = {}
    if party_a:
        kwargs["party_a"] = party_a
    if party_b:
        kwargs["party_b"] = party_b
    if amount:
        kwargs["contract_amount"] = amount
    if start:
        kwargs["start_date"] = start
    if end:
        kwargs["end_date"] = end
    if contract_type:
        kwargs["contract_type"] = contract_type
    if location:
        kwargs["signing_location"] = location
    for name, value in ph:
        kwargs[f"ph_{name}"] = value
    if not kwargs:
        show_warning("未提供任何需要更新的信息")
        return
    try:
        reviewer.update_key_info(contract_id, **kwargs)
        show_success("关键信息已更新")
    except Exception as e:
        show_error(str(e))


# ----- 问题子命令 -----

@review.group("issue", help="问题清单管理")
def review_issue():
    pass


@review_issue.command("add", help="添加待确认问题")
@click.argument("contract_id")
@click.argument("description")
@click.option("--assignee", "-a", default=None, help="指派给某人")
def issue_add(contract_id, description, assignee):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        issue = reviewer.add_issue(contract_id, description, assignee)
        show_success(f"问题已添加 [{issue.id}] {issue.description}")
    except Exception as e:
        show_error(str(e))


@review_issue.command("resolve", help="标记问题已解决")
@click.argument("contract_id")
@click.argument("issue_id")
@click.option("--note", "-n", default=None, help="解决说明")
def issue_resolve(contract_id, issue_id, note):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        if reviewer.resolve_issue(contract_id, issue_id, note):
            show_success(f"问题 {issue_id} 已标记为已解决")
        else:
            show_error(f"未找到问题 ID: {issue_id}")
    except Exception as e:
        show_error(str(e))


@review_issue.command("delete", help="删除问题")
@click.argument("contract_id")
@click.argument("issue_id")
def issue_delete(contract_id, issue_id):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        if reviewer.delete_issue(contract_id, issue_id):
            show_success(f"问题 {issue_id} 已删除")
        else:
            show_error(f"未找到问题 ID: {issue_id}")
    except Exception as e:
        show_error(str(e))


@review_issue.command("list", help="列出合同的问题清单")
@click.argument("contract_id")
def issue_list(contract_id):
    store = get_store()
    contract = store.get_contract(contract_id)
    if not contract:
        show_error(f"未找到合同 ID: {contract_id}")
        return
    if not contract.issues:
        show_warning("暂无问题记录")
        return
    table = Table(title=f"问题清单 - {contract.title}", box=box.ROUNDED)
    table.add_column("ID", style="bold cyan")
    table.add_column("状态")
    table.add_column("描述")
    table.add_column("指派")
    table.add_column("创建")
    table.add_column("说明")
    for issue in contract.issues:
        color = "yellow" if issue.status == "待确认" else "green"
        table.add_row(
            issue.id, f"[{color}]{issue.status}[/{color}]",
            issue.description, issue.assignee or "-",
            issue.created_at, (issue.note or "")[:30]
        )
    console.print(table)


# ----- 审阅备注 -----

@review.command("note", help="添加审阅备注")
@click.argument("contract_id")
@click.argument("note_text")
def review_note(contract_id, note_text):
    store = get_store()
    reviewer = ContractReviewer(store)
    try:
        reviewer.add_review_note(contract_id, note_text)
        show_success("审阅备注已添加")
    except Exception as e:
        show_error(str(e))


# ----- 批量操作 -----

@review.command("batch-status", help="批量更新状态")
@click.argument("contract_ids", nargs=-1, required=True)
@click.argument("status_value", type=click.Choice([s.value for s in ReviewStatus]))
def review_batch_status(contract_ids, status_value):
    store = get_store()
    reviewer = ContractReviewer(store)
    success, failed = reviewer.batch_update_status(list(contract_ids), ReviewStatus(status_value))
    show_success(f"成功: {success}, 失败: {failed}")


@review.command("batch-assign", help="批量指派负责人")
@click.argument("contract_ids", nargs=-1, required=True)
@click.argument("assignee_name")
def review_batch_assign(contract_ids, assignee_name):
    store = get_store()
    reviewer = ContractReviewer(store)
    success, failed = reviewer.batch_assign(list(contract_ids), assignee_name)
    show_success(f"成功: {success}, 失败: {failed}")


# ----- 截止日期提醒 -----

@review.command("remind", help="查看即将到期/逾期的合同")
@click.option("--days", "-d", default=7, help="未来N天内")
def review_remind(days):
    store = get_store()
    reviewer = ContractReviewer(store)
    overdue = reviewer.get_overdue_contracts()
    upcoming = reviewer.get_upcoming_deadlines(days)

    if overdue:
        table = Table(title=f"⚠️  逾期合同 ({len(overdue)})", box=box.ROUNDED, border_style="red")
        table.add_column("ID")
        table.add_column("标题", style="bold")
        table.add_column("项目")
        table.add_column("截止日期", style="red")
        table.add_column("负责人")
        table.add_column("状态")
        for c in overdue:
            table.add_row(c.id, c.title[:30], c.project, c.due_date or "-",
                          c.assignee or "-", status_style(c.status))
        console.print(table)

    if upcoming:
        table = Table(title=f"📅  {days} 天内到期 ({len(upcoming)})", box=box.ROUNDED, border_style="yellow")
        table.add_column("ID")
        table.add_column("标题", style="bold")
        table.add_column("项目")
        table.add_column("截止日期")
        table.add_column("负责人")
        table.add_column("状态")
        for c in upcoming:
            table.add_row(c.id, c.title[:30], c.project, c.due_date or "-",
                          c.assignee or "-", status_style(c.status))
        console.print(table)

    if not overdue and not upcoming:
        show_info(f"未来 {days} 天内暂无到期合同，也无逾期合同 🎉")


# ----- 统计 -----

@review.command("stats", help="审阅统计概览")
def review_stats():
    store = get_store()
    reviewer = ContractReviewer(store)
    stats = reviewer.get_statistics()

    status_table = Table(title="状态分布", box=box.SIMPLE_HEAD)
    status_table.add_column("状态")
    status_table.add_column("数量", justify="right")
    for k, v in stats["by_status"].items():
        color = {"待审阅": "yellow", "审阅中": "cyan", "待修改": "magenta",
                 "已通过": "green", "已拒绝": "red"}.get(k, "white")
        status_table.add_row(f"[{color}]{k}[/{color}]", str(v))

    risk_table = Table(title="风险分布", box=box.SIMPLE_HEAD)
    risk_table.add_column("风险等级")
    risk_table.add_column("数量", justify="right")
    for k, v in stats["by_risk"].items():
        color = {"低": "green", "中": "yellow", "高": "magenta", "严重": "red"}.get(k, "white")
        risk_table.add_row(f"[{color}]{k}[/{color}]", str(v))

    console.print(f"[bold]📊  合同总数: {stats['total']} 份[/bold]")
    console.print(f"[bold yellow]待确认问题: {stats['pending_issues']} 个[/bold yellow]")
    if stats["overdue"]:
        console.print(f"[bold red]逾期合同: {stats['overdue']} 份[/bold red]")

    grid = Table.grid(expand=True)
    grid.add_column()
    grid.add_column()
    grid.add_row(status_table, risk_table)
    console.print(grid)

    if stats["by_project"]:
        proj_table = Table(title="项目统计", box=box.SIMPLE_HEAD)
        proj_table.add_column("项目", style="bold")
        proj_table.add_column("合同数", justify="right")
        for k, v in sorted(stats["by_project"].items(), key=lambda x: -x[1]):
            proj_table.add_row(k, str(v))
        console.print(proj_table)

    if stats["by_assignee"]:
        asg_table = Table(title="负责人统计", box=box.SIMPLE_HEAD)
        asg_table.add_column("负责人", style="bold")
        asg_table.add_column("合同数", justify="right")
        for k, v in sorted(stats["by_assignee"].items(), key=lambda x: -x[1]):
            asg_table.add_row(k, str(v))
        console.print(asg_table)


# =============================================================================
# compare 命令组
# =============================================================================

@main.group(help="版本差异比对")
def compare():
    pass


@compare.command("versions", help="列出合同所有版本")
@click.argument("contract_id")
def compare_versions(contract_id):
    store = get_store()
    comparer = ContractComparer(store)
    try:
        versions = comparer.list_versions(contract_id)
    except Exception as e:
        show_error(str(e))
        return

    table = Table(title=f"版本历史 - {contract_id}", box=box.ROUNDED)
    table.add_column("版本号", justify="right")
    table.add_column("文件名")
    table.add_column("导入时间")
    table.add_column("校验和")
    table.add_column("备注")
    for v in versions:
        exists = Path(v.file_path).exists()
        file_display = v.file_name if exists else f"[red]{v.file_name} (文件缺失)[/red]"
        table.add_row(f"v{v.version_number}", file_display, v.imported_at, v.checksum, v.note)
    console.print(table)


@compare.command("diff", help="比对两个版本的差异")
@click.argument("contract_id")
@click.option("--old", "old_ver", type=int, default=None, help="旧版本号")
@click.option("--new", "new_ver", type=int, default=None, help="新版本号")
@click.option("--html", "html_out", default=None, help="导出HTML报告")
def compare_diff(contract_id, old_ver, new_ver, html_out):
    store = get_store()
    comparer = ContractComparer(store)
    try:
        result = comparer.compare_versions(contract_id, old_ver, new_ver)
    except Exception as e:
        show_error(str(e))
        return

    console.print(Panel(result.summary, title="比对摘要", border_style="blue"))

    if not result.old_file_exists:
        show_warning("旧版本文件不存在，可能已移动或删除")
    if not result.new_file_exists:
        show_warning("新版本文件不存在，可能已移动或删除")

    has_changes = any(len(s.lines) > 0 for s in result.sections)
    total_lines = sum(len(s.lines) for s in result.sections)

    if has_changes:
        diff_table = Table(title="差异详情", box=box.ROUNDED, show_lines=True)
        diff_table.add_column("旧行", justify="right", style="dim")
        diff_table.add_column("新行", justify="right", style="dim")
        diff_table.add_column("差异内容", overflow="fold")
        diff_table.add_column("类型")

        shown = 0
        for section in result.sections:
            if not section.lines:
                continue
            diff_table.add_row(
                f"[bold cyan]--- {section.section_name} ---[/bold cyan]",
                "", "", ""
            )
            for line in section.lines:
                if shown >= 200:
                    break
                if line.change_type == "added":
                    prefix = "[green]+ [/green]"
                    style = "green"
                elif line.change_type == "removed":
                    prefix = "[red]- [/red]"
                    style = "red"
                else:
                    prefix = "[yellow]~ [/yellow]"
                    style = "yellow"
                type_label = {"added": "新增", "removed": "删除", "modified": "修改"}.get(line.change_type, "")
                content = line.content if line.content else "(空行)"
                content_display = prefix + (content[:150] if len(content) > 150 else content)
                diff_table.add_row(
                    str(line.line_number_old or ""),
                    str(line.line_number_new or ""),
                    f"[{style}]{content_display}[/{style}]",
                    f"[{style}]{type_label}[/{style}]"
                )
                shown += 1
            if shown >= 200:
                break

        console.print(diff_table)
        if total_lines > 200:
            show_info("差异行过多，仅显示前 200 行，使用 --html 导出完整报告")

    if html_out:
        try:
            path = comparer.export_diff_html(result, html_out)
            show_success(f"HTML 报告已导出: {path}")
        except Exception as e:
            show_error(str(e))


@compare.command("list", help="列出所有可比对的合同")
def compare_list():
    store = get_store()
    comparer = ContractComparer(store)
    contracts = comparer.find_all_comparable()
    if not contracts:
        show_warning("暂无多版本合同可供比对")
        return

    table = Table(title=f"可比对合同 ({len(contracts)})", box=box.ROUNDED)
    table.add_column("ID")
    table.add_column("标题", style="bold")
    table.add_column("项目")
    table.add_column("版本数", justify="right")
    table.add_column("负责人")
    for c in contracts:
        table.add_row(c.id, c.title[:35], c.project,
                      str(len(c.versions)), c.assignee or "-")
    console.print(table)


# =============================================================================
# summary 命令组
# =============================================================================

@main.group(help="批量生成摘要、导出交接说明")
def summary():
    pass


@summary.command("one", help="生成单个合同摘要")
@click.argument("contract_id")
@click.option("--output", "-o", default=None, help="输出文件路径")
def summary_one(contract_id, output):
    store = get_store()
    summarizer = ContractSummarizer(store)
    contract = store.get_contract(contract_id)
    if not contract:
        show_error(f"未找到合同 ID: {contract_id}")
        return
    text = summarizer.generate_single_summary(contract)
    console.print(text)
    if output:
        try:
            path = summarizer.save_summary_to_file(text, output)
            show_success(f"摘要已保存: {path}")
        except Exception as e:
            show_error(str(e))


@summary.command("all", help="批量生成所有合同摘要")
@click.option("--project", "-p", default=None, help="按项目筛选")
@click.option("--status", "-s", default=None,
              type=click.Choice([s.value for s in ReviewStatus]), help="按状态筛选")
@click.option("--assignee", "-a", default=None, help="按负责人筛选")
@click.option("--output", "-o", default=None, help="输出文件路径")
@click.option("--markdown", "-m", "md_out", default=None, help="导出Markdown汇总")
def summary_all(project, status, assignee, output, md_out):
    store = get_store()
    summarizer = ContractSummarizer(store)
    status_enum = ReviewStatus(status) if status else None
    text = summarizer.generate_batch_summary(
        project=project, status=status_enum, assignee=assignee
    )

    if len(text) > 3000:
        console.print(text[:3000] + "\n...")
        show_info("内容过长，已截断显示，使用 --output 查看完整内容")
    else:
        console.print(text)

    if output:
        try:
            path = summarizer.save_summary_to_file(text, output)
            show_success(f"批量摘要已保存: {path}")
        except Exception as e:
            show_error(str(e))

    if md_out:
        try:
            contracts = store.get_all_contracts()
            if project:
                contracts = [c for c in contracts if c.project == project]
            if status_enum:
                contracts = [c for c in contracts if c.status == status_enum]
            if assignee:
                contracts = [c for c in contracts if c.assignee == assignee]
            path = summarizer.export_markdown_summary(contracts, md_out, project)
            show_success(f"Markdown 报告已导出: {path}")
        except Exception as e:
            show_error(str(e))


@summary.command("handover", help="生成交接说明")
@click.option("--project", "-p", default=None, help="指定项目")
@click.option("--output", "-o", required=True, help="输出文件路径")
def summary_handover(project, output):
    store = get_store()
    summarizer = ContractSummarizer(store)
    note = store.generate_handover_note(project)
    try:
        path = summarizer.export_handover_note(note, output)
        show_success(f"交接说明已生成: {path}")

        panel_text = (
            f"[bold]合同总数:[/bold] {note.total_contracts}\n"
            f"[bold]待审阅:[/bold] {note.pending_review}\n"
            f"[bold]审阅中:[/bold] {note.in_progress}\n"
            f"[bold]已通过:[/bold] {note.approved}\n"
            f"[bold red]逾期合同:[/bold red] {note.overdue_count} ⚠️\n"
            f"[bold]高风险:[/bold] {note.high_risk_count}\n"
            f"[bold yellow]未解决问题:[/bold yellow] {note.open_issues}"
        )
        console.print(Panel(panel_text, title="交接概览", border_style="green"))
    except Exception as e:
        show_error(str(e))


@summary.command("package", help="导出完整交接包（交接说明+合同明细+版本历史+问题清单+周会总览+Markdown汇总）")
@click.option("--project", "-p", default=None, help="按项目筛选")
@click.option("--assignee", "-a", default=None, help="按负责人筛选")
@click.option("--output", "-o", required=True, help="输出目录路径")
def summary_package(project, assignee, output):
    store = get_store()
    summarizer = ContractSummarizer(store)
    try:
        path = summarizer.export_handover_package(output, project=project, assignee=assignee)
        show_success(f"交接包已导出到: {path}")

        contracts = store.get_all_contracts()
        if project:
            contracts = [c for c in contracts if c.project == project]
        if assignee:
            contracts = [c for c in contracts if c.assignee == assignee]

        files = list(Path(path).glob("*"))
        table = Table(title="交接包内容", box=box.ROUNDED)
        table.add_column("文件", style="bold")
        table.add_column("大小", justify="right")
        for f in sorted(files):
            size = f.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            table.add_row(f.name, size_str)
        console.print(table)
        show_info(f"共 {len(contracts)} 份合同，{len(files)} 个文件")
    except Exception as e:
        show_error(str(e))


@summary.command("weekly", help="生成周会同步总览")
@click.option("--project", "-p", default=None, help="按项目筛选")
@click.option("--assignee", "-a", default=None, help="按负责人筛选")
@click.option("--output", "-o", default=None, help="输出文件路径")
def summary_weekly(project, assignee, output):
    store = get_store()
    summarizer = ContractSummarizer(store)
    try:
        text = summarizer.generate_weekly_brief(project=project, assignee=assignee)
        console.print(text)
        if output:
            path = summarizer.save_summary_to_file(text, output)
            show_success(f"周会总览已保存: {path}")
    except Exception as e:
        show_error(str(e))


if __name__ == "__main__":
    main()
