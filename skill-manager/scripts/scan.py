#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill & MCP Scanner
扫描 Claude Code 技能和 MCP 服务器，生成本地注册表
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Windows CMD 中文编码修复
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import yaml

# ── 分类关键词映射 ──────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "音视频处理": ["audio", "video", "transcri", "download", "下载", "音频", "视频",
                 "字幕", "录音", "播客", "media", "yt-dlp", "whisper", "mp3", "mp4"],
    "开发工具": ["skill", "creator", "code", "develop", "build", "编程", "开发",
               "工具", "init", "package", "validate", "debug", "test", "lint"],
    "文档处理": ["document", "docx", "pdf", "pptx", "xlsx", "markdown", "文档",
               "报告", "word", "excel", "powerpoint"],
    "数据管理": ["data", "analy", "query", "数据", "分析", "统计", "database",
               "sql", "管理", "tracker", "manager"],
    "AI/ML": ["ai", "model", "train", "ml", "machine", "模型", "训练",
             "gpt", "claude", "llm", "agent"],
    "浏览器/自动化": ["browser", "playwright", "puppeteer", "selenium", "automat",
                   "crawl", "scrape", "浏览器", "自动化"],
    "工作流/集成": ["workflow", "n8n", "zapier", "integrat", "webhook", "api",
                 "feishu", "slack", "飞书", "接口"],
    "其他": []
}

# ── MCP 包名到 GitHub 的已知映射 ─────────────────────────────────
KNOWN_MCP_GITHUB = {
    "@playwright/mcp": "https://github.com/microsoft/playwright-mcp",
    "n8n-mcp": "https://github.com/czlonkowski/n8n-mcp",
    "firecrawl-mcp": "https://github.com/firecrawl/firecrawl-mcp-server",
    "@modelcontextprotocol/server-brave-search": "https://github.com/brave/brave-search-mcp-server",
    "@upstash/context7-mcp": "https://github.com/upstash/context7",
}

# ── 已知来源映射（下载的 skill → 原始 GitHub 地址）─────────────────
KNOWN_SKILL_SOURCES = {
    "skill-creator": "https://github.com/anthropics/skills/tree/main/skills/skill-creator",
}

# ── 用户配置（从 .env 加载）────────────────────────────────────
MY_GITHUB_REPO = ""
PROJECT_SCAN_DIRS = []


def load_env_config(env_path: Path = None):
    """从 .env 加载 MY_GITHUB_REPO 和 PROJECT_SCAN_DIRS"""
    global MY_GITHUB_REPO, PROJECT_SCAN_DIRS
    if not env_path or not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            if key.strip() == "MY_GITHUB_REPO":
                MY_GITHUB_REPO = val.rstrip("/")
            elif key.strip() == "PROJECT_SCAN_DIRS":
                PROJECT_SCAN_DIRS = [d.strip() for d in val.split(",") if d.strip()]
    except OSError:
        pass


# ── 工具函数 ────────────────────────────────────────────────────

def find_skill_md(skill_dir: Path):
    """查找 SKILL.md（兼容大小写）"""
    for name in ["SKILL.md", "skill.md", "Skill.md"]:
        p = skill_dir / name
        if p.exists():
            return p
    return None


def parse_frontmatter(skill_md_path: Path):
    """解析 YAML frontmatter"""
    try:
        content = skill_md_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        fm = yaml.safe_load(match.group(1))
        if isinstance(fm, dict):
            return fm
    except yaml.YAMLError:
        pass
    return None


EXCLUDE_PATTERNS = {"data", "__pycache__", ".env", ".git"}


def calc_size(path: Path) -> str:
    """计算目录总大小，排除运行时文件，返回人类可读格式"""
    total = 0
    try:
        for f in path.rglob("*"):
            # 跳过排除的目录/文件
            if any(part in EXCLUDE_PATTERNS for part in f.parts):
                continue
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass

    if total < 1024:
        return f"{total} B"
    elif total < 1024 * 1024:
        return f"{total / 1024:.1f} KB"
    else:
        return f"{total / (1024 * 1024):.1f} MB"


def get_last_modified(path: Path) -> str:
    """获取目录中最新文件的修改日期"""
    latest = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                mtime = f.stat().st_mtime
                if mtime > latest:
                    latest = mtime
    except OSError:
        pass

    if latest <= 0:
        return datetime.now().strftime("%Y-%m-%d")
    return datetime.fromtimestamp(latest).strftime("%Y-%m-%d")


def auto_categorize(name: str, description: str) -> str:
    """基于关键词自动分类"""
    text = f"{name} {description}".lower()
    best_cat = "其他"
    best_score = 0

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if not keywords:
            continue
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat


def is_chinese(text: str) -> bool:
    """检测文本是否包含中文"""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def health_check(skill_dir: Path) -> dict:
    """对单个技能进行健康检查"""
    issues = []

    # 1. SKILL.md 存在性
    md_path = find_skill_md(skill_dir)
    if md_path is None:
        return {"status": "error", "issues": [{"level": "error", "msg": "SKILL.md 不存在"}]}

    # 文件名大小写
    if md_path.name != "SKILL.md":
        issues.append({"level": "warning", "msg": f"文件名应为 SKILL.md，当前为 {md_path.name}"})

    # 2. Frontmatter 解析
    fm = parse_frontmatter(md_path)
    if fm is None:
        return {"status": "error", "issues": [{"level": "error", "msg": "YAML frontmatter 无法解析"}]}

    # 3. 必要字段
    if "name" not in fm:
        issues.append({"level": "error", "msg": "缺少 name 字段"})
    else:
        name = str(fm["name"]).strip()
        if not re.match(r"^[a-z0-9-]+$", name):
            issues.append({"level": "error", "msg": f"name '{name}' 不符合 hyphen-case 规范"})
        if name != skill_dir.name:
            issues.append({"level": "warning", "msg": f"name '{name}' 与目录名 '{skill_dir.name}' 不一致"})

    if "description" not in fm:
        issues.append({"level": "error", "msg": "缺少 description 字段"})
    else:
        desc = str(fm["description"]).strip()
        if len(desc) < 50:
            issues.append({"level": "warning", "msg": f"description 过短（{len(desc)} 字符）"})

    # 4. 多余的 frontmatter 键
    ALLOWED = {"name", "description", "license", "allowed-tools", "metadata"}
    extra = set(fm.keys()) - ALLOWED
    if extra:
        issues.append({"level": "warning", "msg": f"非标准 frontmatter 键: {', '.join(extra)}"})

    # 5. 多余文件
    for bad_file in ["README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md"]:
        if (skill_dir / bad_file).exists():
            issues.append({"level": "warning", "msg": f"存在多余文件: {bad_file}"})

    # 判定状态
    has_error = any(i["level"] == "error" for i in issues)
    if has_error:
        status = "error"
    elif issues:
        status = "warning"
    else:
        status = "healthy"

    return {"status": status, "issues": issues}


# ── 技能扫描 ────────────────────────────────────────────────────

def scan_single_skill(skill_dir: Path, scope: str = "global", project: str = "") -> dict | None:
    """扫描单个技能，返回注册表条目"""
    md_path = find_skill_md(skill_dir)
    if md_path is None:
        return None

    fm = parse_frontmatter(md_path)
    if fm is None:
        return None

    name = fm.get("name", skill_dir.name) if fm else skill_dir.name
    desc = str(fm.get("description", "")).strip() if fm else ""

    # 中文描述处理
    if is_chinese(desc):
        desc_zh = desc
    else:
        desc_zh = f"[需要翻译] {desc}" if desc else "[无描述]"

    # 判断来源：已知下载的 skill 用来源地址，其余视为自创
    is_downloaded = name in KNOWN_SKILL_SOURCES
    source_url = KNOWN_SKILL_SOURCES.get(name, "")
    my_url = "" if is_downloaded else (f"{MY_GITHUB_REPO}/tree/main/{name}" if MY_GITHUB_REPO else "")

    return {
        "name": name,
        "description": desc,
        "description_zh": desc_zh,
        "path": str(skill_dir),
        "last_modified": get_last_modified(skill_dir),
        "category": auto_categorize(name, desc),
        "size": calc_size(skill_dir),
        "github_source_url": source_url,
        "github_my_url": my_url,
        "health": health_check(skill_dir),
        "scope": scope,
        "project": project,
        "sync_status": "pending",
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def scan_all_skills(skills_dir: Path) -> dict:
    """扫描所有技能"""
    skills = {}
    if not skills_dir.exists():
        return skills

    for item in sorted(skills_dir.iterdir()):
        if not item.is_dir():
            continue
        entry = scan_single_skill(item)
        if entry:
            skills[entry["name"]] = entry

    return skills


# ── 项目级技能扫描 ────────────────────────────────────────────────

# 扫描时跳过这些目录
PROJECT_EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", "claude-skills-repo", ".venv", "venv"}


def get_project_name(skill_md_path: Path, scan_root: Path) -> str:
    """从 SKILL.md 路径推断项目文件夹名（scan_root 下的第一级子目录）"""
    try:
        rel = skill_md_path.relative_to(scan_root)
        return rel.parts[0] if rel.parts else ""
    except ValueError:
        return skill_md_path.parent.name


def scan_project_skills(project_dirs: list[str], global_skills_dir: str = "") -> dict:
    """递归扫描项目目录中的 skill，返回 {registry_key: entry}"""
    skills = {}
    seen_names = {}  # name -> [registry_keys] 用于检测重复
    seen_paths = set()  # 避免同一目录重复扫描

    for dir_str in project_dirs:
        scan_root = Path(dir_str)
        if not scan_root.exists():
            continue

        # 用 os.walk 递归，可以在遍历时跳过排除目录（避免 node_modules 深层路径崩溃）
        for dirpath, dirnames, filenames in os.walk(scan_root):
            # 就地修改 dirnames 跳过排除目录
            dirnames[:] = [d for d in dirnames if d not in PROJECT_EXCLUDE_DIRS]

            # 检查当前目录是否有 SKILL.md
            md_name = None
            for candidate in ["SKILL.md", "skill.md", "Skill.md"]:
                if candidate in filenames:
                    md_name = candidate
                    break
            if md_name is None:
                continue

            skill_dir = Path(dirpath)

            # 跳过全局 skills 目录（已在 scan_all_skills 中扫描）
            if global_skills_dir and str(skill_dir).startswith(global_skills_dir):
                continue

            # 跳过已扫描路径
            dir_key = str(skill_dir).lower()
            if dir_key in seen_paths:
                continue
            seen_paths.add(dir_key)

            project_name = get_project_name(skill_dir / md_name, scan_root)

            entry = scan_single_skill(skill_dir, scope="project", project=project_name)
            if entry is None:
                continue

            name = entry["name"]

            # 构建 registry key：同名 skill 用 name@project 区分
            if name in seen_names:
                # 已有同名的，之前的也需要加后缀（如果还没加）
                for old_key in list(seen_names[name]):
                    if old_key == name and old_key in skills:
                        old_entry = skills.pop(old_key)
                        new_key = f"{name}@{old_entry['project']}"
                        skills[new_key] = old_entry
                        seen_names[name].remove(old_key)
                        seen_names[name].append(new_key)
                reg_key = f"{name}@{project_name}"
            else:
                reg_key = name
                seen_names[name] = []

            # 避免重复 key
            if reg_key in skills:
                continue

            seen_names[name].append(reg_key)
            skills[reg_key] = entry

    return skills


# ── MCP 扫描 ────────────────────────────────────────────────────

def extract_npm_package(args: list) -> str:
    """从 MCP 命令参数中提取 npm 包名"""
    for arg in args:
        # 跳过 cmd flags
        if arg in ("/c", "cmd", "npx", "-y", "node"):
            continue
        # 去掉 @latest 等版本后缀
        pkg = re.sub(r"@(latest|next|[\d.]+.*)$", "", arg)
        if pkg and not pkg.startswith("-"):
            return pkg
    return ""


def guess_github_url(package_name: str) -> str:
    """根据 npm 包名猜测 GitHub 地址"""
    if package_name in KNOWN_MCP_GITHUB:
        return KNOWN_MCP_GITHUB[package_name]
    # npm scope 包: @scope/name -> 可能是 github.com/scope/name
    if package_name.startswith("@"):
        parts = package_name.lstrip("@").split("/")
        if len(parts) == 2:
            return f"https://github.com/{parts[0]}/{parts[1]}"
    return ""


def scan_mcp_servers(mcp_settings_path: Path) -> dict:
    """扫描 MCP 服务器配置"""
    servers = {}
    if not mcp_settings_path.exists():
        return servers

    try:
        data = json.loads(mcp_settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return servers

    mcp_servers = data.get("mcpServers", {})
    for name, config in mcp_servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        env_keys = list(config.get("env", {}).keys())

        npm_pkg = extract_npm_package(args)
        github_url = guess_github_url(npm_pkg)

        # 构建完整命令字符串
        full_cmd = f"{cmd} {' '.join(args)}" if args else cmd

        servers[name] = {
            "name": name,
            "npm_package": npm_pkg,
            "command": full_cmd,
            "env_vars": env_keys,
            "github_url": github_url,
            "category": auto_categorize(name, npm_pkg),
            "description_zh": "",  # 由 Claude 填充
            "sync_status": "pending",
            "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    return servers


# ── 注册表管理 ──────────────────────────────────────────────────

def load_registry(path: Path) -> dict:
    """加载已有注册表"""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": "1.0",
        "last_full_scan": "",
        "skills": {},
        "mcp_servers": {},
    }


def save_registry(registry: dict, path: Path):
    """保存注册表"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def merge_skills(old_reg: dict, new_skills: dict) -> dict:
    """合并新扫描结果到现有注册表，新扫描值优先，仅在新值为空时保留旧值"""
    existing = old_reg.get("skills", {})
    for name, entry in new_skills.items():
        if name in existing:
            old = existing[name]
            # GitHub URL: 新值优先，空时回退旧值
            entry["github_source_url"] = entry.get("github_source_url", "") or old.get("github_source_url", "")
            entry["github_my_url"] = entry.get("github_my_url", "") or old.get("github_my_url", "")
            entry["feishu_record_id"] = old.get("feishu_record_id")
            # 中文描述: 保留已翻译的（无 [需要翻译] 前缀），新扫描有中文则用新的
            old_zh = old.get("description_zh", "")
            if entry["description_zh"].startswith("[需要翻译]") and old_zh and not old_zh.startswith("[需要翻译]"):
                entry["description_zh"] = old_zh
            # 检测数据是否有变更
            for key in ("description", "size", "last_modified", "category"):
                if entry.get(key) != old.get(key):
                    entry["sync_status"] = "modified"
                    break
            else:
                entry["sync_status"] = old.get("sync_status", "pending")
        else:
            entry["feishu_record_id"] = None
    return new_skills


def merge_mcp(old_reg: dict, new_servers: dict) -> dict:
    """合并 MCP 扫描结果，新扫描值优先"""
    existing = old_reg.get("mcp_servers", {})
    for name, entry in new_servers.items():
        if name in existing:
            old = existing[name]
            # 新值优先，空时回退旧值
            entry["github_url"] = entry.get("github_url", "") or old.get("github_url", "")
            entry["description_zh"] = entry.get("description_zh", "") or old.get("description_zh", "")
            entry["feishu_record_id"] = old.get("feishu_record_id")
            entry["sync_status"] = old.get("sync_status", "pending")
        else:
            entry["feishu_record_id"] = None
    return new_servers


# ── 搜索 ────────────────────────────────────────────────────────

def search(registry: dict, keyword: str) -> dict:
    """搜索技能和 MCP 服务器"""
    kw = keyword.lower()
    results = {"skills": {}, "mcp_servers": {}}

    for name, entry in registry.get("skills", {}).items():
        searchable = f"{name} {entry.get('description', '')} {entry.get('description_zh', '')} {entry.get('category', '')}".lower()
        if kw in searchable:
            results["skills"][name] = entry

    for name, entry in registry.get("mcp_servers", {}).items():
        searchable = f"{name} {entry.get('npm_package', '')} {entry.get('description_zh', '')} {entry.get('category', '')}".lower()
        if kw in searchable:
            results["mcp_servers"][name] = entry

    return results


# ── 输出格式化 ──────────────────────────────────────────────────

def print_summary(registry: dict):
    """打印扫描摘要"""
    skills = registry.get("skills", {})
    mcps = registry.get("mcp_servers", {})

    print(f"\n{'='*60}")
    print(f"  扫描完成 | 技能: {len(skills)} 个 | MCP 服务器: {len(mcps)} 个")
    print(f"{'='*60}")

    if skills:
        global_skills = {k: v for k, v in skills.items() if v.get("scope", "global") == "global"}
        project_skills = {k: v for k, v in skills.items() if v.get("scope") == "project"}

        if global_skills:
            print(f"\n── 全局技能 ({len(global_skills)}) ──")
            for name, s in global_skills.items():
                health = s.get("health", {}).get("status", "?")
                icon = {"healthy": "OK", "warning": "!!", "error": "XX"}.get(health, "??")
                print(f"  [{icon}] {name:30s} | {s['category']:10s} | {s['size']:>8s} | {s['last_modified']}")
                if health != "healthy":
                    for issue in s.get("health", {}).get("issues", []):
                        print(f"        -> [{issue['level']}] {issue['msg']}")

        if project_skills:
            print(f"\n── 项目级技能 ({len(project_skills)}) ──")
            for name, s in project_skills.items():
                health = s.get("health", {}).get("status", "?")
                icon = {"healthy": "OK", "warning": "!!", "error": "XX"}.get(health, "??")
                proj = s.get("project", "")
                print(f"  [{icon}] {name:30s} | {s['category']:10s} | {s['size']:>8s} | @{proj}")
                if health != "healthy":
                    for issue in s.get("health", {}).get("issues", []):
                        print(f"        -> [{issue['level']}] {issue['msg']}")

    if mcps:
        print(f"\n── MCP 服务器 ──")
        for name, m in mcps.items():
            pkg = m.get("npm_package", "")
            gh = m.get("github_url", "") or "未知"
            print(f"  {name:20s} | 包: {pkg:30s} | GitHub: {gh}")

    print()


# ── 主函数 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Skill & MCP Scanner")
    parser.add_argument("--skills-dir", default=r"C:\Users\fubai\.claude\skills",
                        help="技能目录路径")
    parser.add_argument("--mcp-settings", default=r"C:\Users\fubai\.claude.json",
                        help="MCP 配置文件路径（~/.claude.json）")
    parser.add_argument("--output", default=r"C:\Users\fubai\.claude\skills\skill-manager\data\registry.json",
                        help="注册表输出路径")
    parser.add_argument("--env", default=r"C:\Users\fubai\.claude\skills\skill-manager\.env",
                        help=".env 配置文件路径")
    parser.add_argument("--skill-name", help="仅扫描指定技能（增量模式）")
    parser.add_argument("--search", help="按关键词搜索")
    parser.add_argument("--health-check", action="store_true", help="仅显示健康检查结果")
    args = parser.parse_args()

    # 加载 .env 中的配置
    load_env_config(Path(args.env))

    output_path = Path(args.output)
    registry = load_registry(output_path)

    # 搜索模式
    if args.search:
        results = search(registry, args.search)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    skills_dir = Path(args.skills_dir)

    # 增量扫描单个技能
    if args.skill_name:
        skill_path = skills_dir / args.skill_name
        if not skill_path.exists():
            print(f"Error: 技能目录不存在: {skill_path}", file=sys.stderr)
            sys.exit(1)
        entry = scan_single_skill(skill_path)
        if entry:
            new_skills = merge_skills(registry, {entry["name"]: entry})
            registry["skills"].update(new_skills)
            print(f"已更新技能: {entry['name']}")
    else:
        # 全量扫描：全局 + 项目级
        new_skills = scan_all_skills(skills_dir)

        # 项目级扫描
        if PROJECT_SCAN_DIRS:
            project_skills = scan_project_skills(PROJECT_SCAN_DIRS, str(skills_dir))
            new_skills.update(project_skills)

        registry["skills"] = merge_skills(registry, new_skills)
        registry["last_full_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # MCP 扫描（始终执行）
    new_mcps = scan_mcp_servers(Path(args.mcp_settings))
    registry["mcp_servers"] = merge_mcp(registry, new_mcps)

    # 保存
    save_registry(registry, output_path)

    # 健康检查模式
    if args.health_check:
        print("\n── 健康检查报告 ──")
        for name, s in registry["skills"].items():
            h = s.get("health", {})
            print(f"\n  {name}: {h.get('status', '?')}")
            for issue in h.get("issues", []):
                print(f"    [{issue['level']}] {issue['msg']}")
        return

    # 正常输出
    print_summary(registry)
    print(f"注册表已保存: {output_path}")


if __name__ == "__main__":
    main()
