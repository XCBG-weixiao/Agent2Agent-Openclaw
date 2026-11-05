import os
import stat
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Scan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["scan_text_files"]
    source: Literal["source_directory"]


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["write_markdown_report"]
    target: Literal["report_path"]


class FilePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1"]
    steps: tuple[Scan, Write]


PLAN_INSTRUCTIONS = """Create a JSON plan for a local text-file line-count report.
Use exactly this contract and order:
{"version":"1","steps":[{"action":"scan_text_files","source":"source_directory"},
{"action":"write_markdown_report","target":"report_path"}]}
The edge binds these names to the user's local paths. Return only the JSON object.
The scan counts UTF-8 .txt and .md files directly in the selected directory."""


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def scoped_path(root: Path, value: str, *, missing_leaf: bool = False) -> Path:
    windows = PureWindowsPath(value)
    if not value or windows.drive or windows.root or "\\" in value or "\0" in value:
        raise ValueError("Use a path relative to the configured workspace.")
    if value == ".":
        return root
    parts = value.split("/")
    if any(
        part in {"", ".", ".."} or part.endswith((" ", "."))
        or any(char in part for char in ':*?"<>|')
        or PureWindowsPath(part).is_reserved()
        for part in parts
    ):
        raise ValueError("Invalid path or path outside the workspace.")
    path = root
    for index, part in enumerate(parts):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing_leaf and index == len(parts) - 1:
                return path
            raise ValueError("Local path or its parent does not exist.") from None
        if is_link(info):
            raise ValueError("Symbolic links and junctions are outside the execution policy.")
    return path


def validate_paths(root: Path, source: str, report: str) -> tuple[Path, Path]:
    directory = scoped_path(root, source)
    target = scoped_path(root, report, missing_leaf=True)
    if not directory.is_dir() or not target.parent.is_dir():
        raise ValueError("The source directory and report parent must exist.")
    if target.suffix.lower() != ".md":
        raise ValueError("The report path must end in .md.")
    if target.exists():
        raise FileExistsError("The report already exists.")
    return directory, target


def execute(root: Path, data: dict, source: str, report: str) -> str:
    FilePlan.model_validate(data)
    directory, target = validate_paths(root, source, report)
    rows = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".txt", ".md"}:
            continue
        info = path.lstat()
        if is_link(info):
            raise ValueError("The source contains a linked text file.")
        if stat.S_ISREG(info.st_mode):
            with path.open(encoding="utf-8") as file:
                rows.append((path.name, sum(1 for _ in file)))

    lines = ["# 文件行数报告", "", "| 文件 | 行数 |", "| --- | ---: |"]
    for name, count in rows:
        safe_name = name.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {safe_name} | {count} |")
    lines += ["", f"合计 {len(rows)} 个文件，{sum(count for _, count in rows)} 行。"]
    content = "\n".join(lines) + "\n"
    with NamedTemporaryFile(dir=target.parent, delete=False) as staged:
        temporary = Path(staged.name)
    try:
        temporary.write_text(content, encoding="utf-8")
        # Link commits the complete report atomically and refuses an existing target.
        os.link(temporary, target)
    except FileExistsError:
        raise FileExistsError("The report already exists.") from None
    finally:
        temporary.unlink()
    return content
