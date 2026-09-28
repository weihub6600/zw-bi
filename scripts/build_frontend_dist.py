#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""百嘉瑞BI - 前端产物重建 + 生产包组装（补上仓库里缺失的「发布生产包.cmd」这一环）

背景
----
仓库 `frontend-dist/` 是**手工提交的构建产物**，`npm run build` 的输出**不会**自动进仓库。
`install.sh` / `update.sh` 都假设发布者在 Windows 开发机上先跑过「发布生产包.cmd」，
但该脚本在仓库、git 历史、本机均不存在；`scripts/release_tool.py` 也没有生成 manifest 的命令。
于是「改了前端源码 -> 产物没更新 -> update.sh 装出旧的界面」这个坑反复出现（v15.7.8 就踩了）。

本脚本把这条链补齐：
    1) 在 D 盘临时目录里复制 frontend/ 源码
    2) npm ci + npm run build   -> dist/
    3) 用 dist/ 覆盖组装出新的 frontend-dist/
    4) 按仓库规则重新生成 manifest.json（文本文件 LF 归一化后 sha256）
    5) 打包成可直接丢给 update.sh 的 tar.gz

用法
----
    python build_frontend_dist.py                    # 全流程（构建 + 组装 + 清单 + 打包）
    python build_frontend_dist.py --skip-build       # 复用上次 npm build 结果，只组装+清单+打包
    python build_frontend_dist.py --repo E:/Code/zw-bi --out D:/bi-release

为什么必须在 D 盘构建
--------------------
E 盘（本机）文件系统不支持 npm 的 safe-delete/trash 操作，`npm ci` 会报
`Error during a 'trash' operation: Unknown`；git 也会报 `unable to unlink index.lock: Invalid argument`。
所以脚本强制把构建工作区放在 `WORK`（默认 D:/tmp-bi-build）而不是仓库所在的 E 盘。

为什么 tar 要用 cwd 技巧
----------------------
GNU tar 会把 `D:/xxx` 的参数当成「远程主机 D」并报 `Cannot connect to D: resolve failed`。
脚本用 `shutil.make_archive`（纯 Python）绕开，不调用外部 tar。
"""

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量规则
# ⚠️ 这两组必须与 scripts/release_tool.py 的 MANIFEST_TEXT_SUFFIXES /
#    MANIFEST_TEXT_NAMES **完全一致** —— 它们决定哪些文件做 LF 归一化后再算 sha256。
#    任何不一致都会让生成的 manifest 在部署侧 release_tool.py verify 时报哈希不匹配。
#    脚本启动时会用 _assert_rules_match_release_tool() 做 AST 级比对，漂移即报错。
#
#    这里不直接 import release_tool.py，因为它顶层会 `from app.core.config import
#    settings`（依赖后端 venv），在开发机上导不进来。
MANIFEST_TEXT_SUFFIXES = {
    ".py", ".sql", ".js", ".css", ".html", ".json", ".txt", ".md", ".sh",
    ".vue", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}
MANIFEST_TEXT_NAMES = {"VERSION", "LICENSE", ".env.example", ".gitignore", ".gitattributes"}

# manifest 自身不参与哈希（否则自指）
EXCLUDE_FROM_MANIFEST = {"manifest.json"}
# 不需要进生产包的目录/文件
PACKAGE_EXCLUDES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


def log(msg=""):
    print(msg, flush=True)


def is_text(path: Path) -> bool:
    return path.suffix.lower() in MANIFEST_TEXT_SUFFIXES or path.name in MANIFEST_TEXT_NAMES


def _assert_rules_match_release_tool(repo: Path) -> None:
    """用 AST 读取 release_tool.py 的判定规则，与本脚本比对，防止两边漂移。"""
    rt = repo / "scripts" / "release_tool.py"
    if not rt.is_file():
        log(f"[警告] 找不到 {rt}，跳过规则一致性自检")
        return
    try:
        tree = ast.parse(rt.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        log(f"[警告] 解析 release_tool.py 失败（{exc}），跳过规则一致性自检")
        return

    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in (
                "MANIFEST_TEXT_SUFFIXES", "MANIFEST_TEXT_NAMES"
            ):
                try:
                    found[target.id] = set(ast.literal_eval(node.value))
                except ValueError:
                    pass

    mine = {
        "MANIFEST_TEXT_SUFFIXES": MANIFEST_TEXT_SUFFIXES,
        "MANIFEST_TEXT_NAMES": MANIFEST_TEXT_NAMES,
    }
    problems = []
    for name, local in mine.items():
        remote = found.get(name)
        if remote is None:
            continue
        if remote != local:
            problems.append(
                f"  {name}: 本脚本多出 {sorted(local - remote) or '无'}；"
                f"缺少 {sorted(remote - local) or '无'}"
            )
    if problems:
        sys.exit(
            "[FATAL] 文本文件判定规则与 scripts/release_tool.py 不一致，"
            "生成的 manifest 会在部署侧校验失败：\n" + "\n".join(problems)
        )
    log("    规则自检：与 release_tool.py 一致 ✅")


def sha256_of(path: Path) -> str:
    """文本文件先做 LF 归一化再哈希，二进制按原样。"""
    h = hashlib.sha256()
    text = is_text(path)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            if text:
                chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            h.update(chunk)
    return h.hexdigest()


def run(cmd, cwd=None, check=True):
    log(f"    $ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None)
    if check and r.returncode != 0:
        sys.exit(f"[FATAL] 命令失败（退出码 {r.returncode}）: {' '.join(str(c) for c in cmd)}")
    return r.returncode


# ---------------------------------------------------------------- 步骤 1：构建前端
def build_frontend(repo: Path, work: Path, skip_build: bool) -> Path:
    """返回 vite 的 dist 目录。"""
    src_frontend = repo / "frontend"
    if not (src_frontend / "package.json").is_file():
        sys.exit(f"[FATAL] 找不到前端工程: {src_frontend / 'package.json'}")

    build_dir = work / "frontend"           # 构建工作区（必须在 D 盘等 NTFS 卷上）
    dist = build_dir / "dist"

    if skip_build:
        if not (dist / "index.html").is_file():
            sys.exit(f"[FATAL] --skip-build 但找不到已有产物: {dist / 'index.html'}")
        log(f"[1] 跳过构建，复用现有产物 {dist}")
        return dist

    log(f"[1] 构建前端（工作区 {build_dir}）")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    # node_modules 不复制，交给 npm ci 装
    shutil.copytree(
        src_frontend, build_dir,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".vite"),
    )

    log("    npm ci")
    run(["npm", "ci", "--no-audit", "--no-fund"], cwd=build_dir)
    log("    npm run build")
    run(["npm", "run", "build"], cwd=build_dir)

    if not (dist / "index.html").is_file():
        sys.exit(f"[FATAL] 构建未产出 {dist / 'index.html'}"
                 "（检查 vite.config.js 是否配了自定义 build.outDir）")
    return dist


# ---------------------------------------------------------------- 步骤 2：组装 frontend-dist
def assemble_frontend_dist(dist: Path, old_fd: Path, out_fd: Path) -> None:
    log(f"[2] 组装 frontend-dist -> {out_fd}")
    if out_fd.parent.exists():
        shutil.rmtree(out_fd.parent)
    out_fd.mkdir(parents=True)

    if old_fd.is_dir():
        shutil.copytree(old_fd, out_fd, dirs_exist_ok=True)
    # assets 是带内容哈希的，整目录替换（旧哈希文件必须删掉，否则无限累积）
    if (out_fd / "assets").exists():
        shutil.rmtree(out_fd / "assets")
    shutil.copytree(dist / "assets", out_fd / "assets")
    # dist 根下的其它文件/目录（index.html、templates/、favicon 等）
    for item in sorted(dist.iterdir()):
        if item.name == "assets":
            continue
        dst = out_fd / item.name
        if item.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)

    files = sorted(p for p in out_fd.rglob("*") if p.is_file())
    log(f"    {len(files)} 个文件")
    for p in files:
        log(f"      {p.relative_to(out_fd).as_posix():60s} {p.stat().st_size:>10d}")


def diff_against(old_fd: Path, out_fd: Path) -> None:
    log("[3] 相对仓库旧产物的差异")
    if not old_fd.is_dir():
        log("    （仓库无旧产物，跳过对比）")
        return
    old = {p.relative_to(old_fd).as_posix(): sha256_of(p)
           for p in old_fd.rglob("*") if p.is_file()}
    new = {p.relative_to(out_fd).as_posix(): sha256_of(p)
           for p in out_fd.rglob("*") if p.is_file()}
    changed = False
    for k in sorted(set(old) | set(new)):
        if k not in old:
            log(f"    [新增] {k}"); changed = True
        elif k not in new:
            log(f"    [删除] {k}"); changed = True
        elif old[k] != new[k]:
            log(f"    [变更] {k}"); changed = True
    if not changed:
        log("    ** 无差异 —— 前端产物与仓库一致，本次无需重新发布 **")


# ---------------------------------------------------------------- 步骤 4：生成 manifest
def tracked_files(repo: Path):
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                       capture_output=True)
    if r.returncode != 0:
        sys.exit("[FATAL] git ls-files 失败；请确认 --repo 指向一个 git 仓库")
    names = r.stdout.decode("utf-8", "replace").split("\0")
    return [n for n in names if n and n not in EXCLUDE_FROM_MANIFEST]


def build_manifest(repo: Path, out_fd: Path) -> dict:
    log("[4] 生成 manifest.json")
    _assert_rules_match_release_tool(repo)
    files = {}
    for rel in tracked_files(repo):
        # frontend-dist/ 下的文件从**新组装的目录**读，其余从仓库根读
        path = (out_fd / rel[len("frontend-dist/"):]) if rel.startswith("frontend-dist/") else (repo / rel)
        if path.is_file():
            files[rel] = sha256_of(path)
        else:
            log(f"    [警告] 清单中列出的文件不存在，已跳过: {rel}")
    # 新产物里新增、尚未被 git 跟踪的文件（例如新的 templates/*.xlsx）
    for p in sorted(out_fd.rglob("*")):
        if p.is_file():
            files.setdefault("frontend-dist/" + p.relative_to(out_fd).as_posix(), sha256_of(p))

    version_file = repo / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "0.0.0"

    manifest = {
        "app": "百嘉瑞BI",
        "version": version,
        "files": dict(sorted(files.items())),
    }
    fd_count = sum(1 for k in files if k.startswith("frontend-dist/"))
    log(f"    共 {len(files)} 项（其中 frontend-dist/ {fd_count} 项），版本 {version}")
    return manifest


# ---------------------------------------------------------------- 步骤 5：打包
def pack(repo: Path, out_fd: Path, manifest: dict, out_dir: Path, version: str,
         frontend_only: bool) -> Path:
    log("[5] 组装生产包并压缩")
    pkg = out_dir / "package"
    if pkg.exists():
        shutil.rmtree(pkg)          # 注意：out_fd 必须**不在** pkg 里，否则会被一起删掉
    pkg.mkdir(parents=True)

    # frontend-dist（用新组装的 staged 目录）
    shutil.copytree(out_fd, pkg / "frontend-dist")
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if frontend_only:
        # 补丁式更新载荷：只有 frontend-dist/ + manifest.json，
        # 解包到 NAS 上的 git 工作副本（bjr-bi-update）后直接跑 update.sh 即可。
        log("    模式: 仅前端补丁（frontend-dist/ + manifest.json）")
    else:
        # 完整包：可直接用于 install.sh 全新部署
        for name in ("backend", "templates", "deploy", "scripts"):
            src = repo / name
            if src.is_dir():
                shutil.copytree(src, pkg / name,
                                ignore=shutil.ignore_patterns(*PACKAGE_EXCLUDES))
        for name in ("VERSION", "requirements.txt", "README.md"):
            src = repo / name
            if src.is_file():
                shutil.copy2(src, pkg / name)
        log("    模式: 完整包（含 backend/templates/deploy/scripts）")

    suffix = "-frontend" if frontend_only else ""
    archive = out_dir / f"bi-package-v{version}{suffix}"
    archive_path = Path(shutil.make_archive(str(archive), "gztar", root_dir=str(out_dir),
                                            base_dir="package"))
    log(f"    -> {archive_path}  ({archive_path.stat().st_size} 字节)")
    return archive_path


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="百嘉瑞BI 前端产物重建 + 生产包组装")
    ap.add_argument("--repo", default="E:/Code/zw-bi", help="git 仓库根目录")
    ap.add_argument("--work", default="D:/tmp-bi-build", help="构建工作区（须在 NTFS 卷上，勿用 E 盘）")
    ap.add_argument("--out", default=None, help="生产包输出目录（默认 <work>/release）")
    ap.add_argument("--skip-build", action="store_true", help="复用上次 npm build 的 dist/")
    ap.add_argument("--no-pack", action="store_true", help="只组装 + 生成清单，不压缩")
    ap.add_argument("--frontend-only", action="store_true",
                    help="只打包 frontend-dist/ + manifest.json（补丁式更新载荷，默认打完整包）")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    work = Path(args.work).resolve()
    out_dir = Path(args.out).resolve() if args.out else work / "release"
    if not (repo / "VERSION").is_file():
        sys.exit(f"[FATAL] {repo} 不像百嘉瑞BI 仓库（缺 VERSION 文件）")
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"仓库   : {repo}")
    log(f"工作区 : {work}")
    log(f"输出   : {out_dir}")
    log()

    dist = build_frontend(repo, work, args.skip_build)
    # staged 目录刻意放在 package/ 之外，避免 pack() 重建 package/ 时被连带删除
    staging = out_dir / "staging"
    out_fd = staging / "frontend-dist"
    assemble_frontend_dist(dist, repo / "frontend-dist", out_fd)
    diff_against(repo / "frontend-dist", out_fd)

    manifest = build_manifest(repo, out_fd)
    tmp_manifest = out_dir / "manifest.json"
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    version = manifest["version"]
    if args.no_pack:
        log(f"\n完成。清单: {tmp_manifest}")
    else:
        archive = pack(repo, out_fd, manifest, out_dir, version, args.frontend_only)
        log(f"\n完成。生产包: {archive}")
    log()
    log("交付到 NAS 后，在容器内执行：")
    log("    bash deploy/baota/update.sh /www/wwwroot/bjr-bi")


if __name__ == "__main__":
    main()
