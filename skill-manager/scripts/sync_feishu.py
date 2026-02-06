#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书多维表格同步脚本
将技能和 MCP 服务器数据同步到飞书多维表格（两张表）
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Windows CMD 中文编码修复
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import requests

BASE_URL = "https://open.feishu.cn/open-apis"

# ── 技能表字段定义 ──────────────────────────────────────────────
SKILL_TABLE_NAME = "技能列表"
SKILL_FIELDS = [
    {"field_name": "技能名称", "type": 1},
    {"field_name": "技能描述", "type": 1},
    {"field_name": "技能分类", "type": 1},
    {"field_name": "存放路径", "type": 1},
    {"field_name": "最后更新日期", "type": 1},
    {"field_name": "文件大小", "type": 1},
    {"field_name": "健康状态", "type": 1},
    {"field_name": "同步状态", "type": 1},
    {"field_name": "来源地址", "type": 15},
    {"field_name": "我的仓库", "type": 15},
    {"field_name": "作用域", "type": 1},
    {"field_name": "所属项目", "type": 1},
]

# ── MCP 表字段定义 ──────────────────────────────────────────────
MCP_TABLE_NAME = "MCP 服务器"
MCP_FIELDS = [
    {"field_name": "服务器名称", "type": 1},
    {"field_name": "功能描述", "type": 1},
    {"field_name": "NPM 包名", "type": 1},
    {"field_name": "运行命令", "type": 1},
    {"field_name": "环境变量", "type": 1},
    {"field_name": "分类", "type": 1},
    {"field_name": "同步状态", "type": 1},
    {"field_name": "GitHub地址", "type": 15},
]


# ── 工具函数 ────────────────────────────────────────────────────

def load_env(env_path: Path) -> tuple[str, str]:
    """加载 .env 文件获取飞书凭据"""
    if not env_path.exists():
        print(f"Error: .env 文件不存在: {env_path}", file=sys.stderr)
        print("请创建 .env 文件并添加:", file=sys.stderr)
        print("  FEISHU_APP_ID=你的应用ID", file=sys.stderr)
        print("  FEISHU_APP_SECRET=你的应用密钥", file=sys.stderr)
        sys.exit(1)

    env = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")

    app_id = env.get("FEISHU_APP_ID", "")
    app_secret = env.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("Error: .env 缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET", file=sys.stderr)
        sys.exit(1)

    return app_id, app_secret


def get_token(app_id: str, app_secret: str) -> str:
    """获取飞书 tenant_access_token"""
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        print(f"Error: 获取 token 失败: {data.get('msg')}", file=sys.stderr)
        sys.exit(1)
    return data["tenant_access_token"]


def api_request(method: str, endpoint: str, token: str, **kwargs) -> dict:
    """统一 API 请求，自带认证和错误处理"""
    url = f"{BASE_URL}{endpoint}" if endpoint.startswith("/") else endpoint
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"API 错误 [{data.get('code')}]: {data.get('msg')}")
    return data.get("data", {})


# ── 飞书配置管理 ────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """加载飞书配置"""
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "app_token": None,
        "skill_table_id": None,
        "mcp_table_id": None,
        "bitable_url": None,
        "skill_record_map": {},
        "mcp_record_map": {},
        "last_sync": None,
    }


def save_config(config: dict, config_path: Path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 多维表格操作 ────────────────────────────────────────────────

def create_bitable(token: str) -> tuple[str, str]:
    """创建多维表格应用，返回 (app_token, url)"""
    data = api_request("POST", "/bitable/v1/apps", token,
                       json={"name": "Claude Code 资源管理"})
    app = data.get("app", {})
    return app.get("app_token", ""), app.get("url", "")


def create_table(token: str, app_token: str, table_name: str, fields: list) -> str:
    """创建数据表，返回 table_id"""
    data = api_request("POST", f"/bitable/v1/apps/{app_token}/tables", token,
                       json={"table": {
                           "name": table_name,
                           "default_view_name": "默认视图",
                           "fields": fields,
                       }})
    return data.get("table_id", "")


def list_tables(token: str, app_token: str) -> list:
    """列出已有数据表"""
    data = api_request("GET", f"/bitable/v1/apps/{app_token}/tables", token)
    return data.get("items", [])


def delete_table(token: str, app_token: str, table_id: str):
    """删除数据表"""
    try:
        api_request("DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}", token)
    except Exception:
        pass


def find_table_by_name(tables: list, name: str) -> str | None:
    """在已有表列表中按名称查找 table_id"""
    for tbl in tables:
        if tbl.get("name") == name:
            return tbl.get("table_id")
    return None


def list_fields(token: str, app_token: str, table_id: str) -> list:
    """获取表的所有字段"""
    data = api_request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", token)
    return data.get("items", [])


def add_field(token: str, app_token: str, table_id: str, field_name: str, field_type: int):
    """添加单个字段到表"""
    api_request("POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", token,
                json={"field_name": field_name, "type": field_type})


def ensure_fields(token: str, app_token: str, table_id: str, expected_fields: list):
    """确保表中存在所有期望字段，缺失的自动添加"""
    existing = list_fields(token, app_token, table_id)
    existing_names = {f.get("field_name") for f in existing}

    for field_def in expected_fields:
        fname = field_def["field_name"]
        if fname not in existing_names:
            print(f"  自动添加缺失字段: {fname}")
            try:
                add_field(token, app_token, table_id, fname, field_def["type"])
            except Exception as e:
                print(f"  添加字段失败 [{fname}]: {e}", file=sys.stderr)


def ensure_tables(token: str, config: dict, config_path: Path) -> dict:
    """确保多维表格和数据表存在，支持复用已有多维表格"""
    app_token = config.get("app_token")

    # 没有 app_token → 创建新多维表格
    if not app_token:
        print("  创建多维表格...")
        app_token, url = create_bitable(token)
        config["app_token"] = app_token
        config["bitable_url"] = url
        save_config(config, config_path)

    # 验证 app_token 可用并获取已有表
    try:
        existing_tables = list_tables(token, app_token)
    except Exception:
        print("  app_token 失效，重新创建...", file=sys.stderr)
        config["app_token"] = None
        config["skill_table_id"] = None
        config["mcp_table_id"] = None
        config["skill_record_map"] = {}
        config["mcp_record_map"] = {}
        return ensure_tables(token, config, config_path)

    changed = False

    # 技能表：优先使用配置中的 ID，否则按名称查找，最后新建
    if not config.get("skill_table_id"):
        found = find_table_by_name(existing_tables, SKILL_TABLE_NAME)
        if found:
            print(f"  复用已有技能表: {found}")
            config["skill_table_id"] = found
        else:
            print("  创建技能表...")
            config["skill_table_id"] = create_table(token, app_token, SKILL_TABLE_NAME, SKILL_FIELDS)
            time.sleep(0.5)
        changed = True

    # MCP 表：同上
    if not config.get("mcp_table_id"):
        found = find_table_by_name(existing_tables, MCP_TABLE_NAME)
        if found:
            print(f"  复用已有 MCP 表: {found}")
            config["mcp_table_id"] = found
        else:
            print("  创建 MCP 服务器表...")
            config["mcp_table_id"] = create_table(token, app_token, MCP_TABLE_NAME, MCP_FIELDS)
        changed = True

    if changed:
        save_config(config, config_path)

    # 检查字段完整性，自动添加缺失字段
    ensure_fields(token, app_token, config["skill_table_id"], SKILL_FIELDS)
    ensure_fields(token, app_token, config["mcp_table_id"], MCP_FIELDS)

    return config


# ── 记录操作 ────────────────────────────────────────────────────

def list_records(token: str, app_token: str, table_id: str) -> list:
    """获取表中所有记录"""
    all_items = []
    page_token = None

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        data = api_request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                           token, params=params)
        items = data.get("items", [])
        all_items.extend(items)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token")

    return all_items


def batch_create(token: str, app_token: str, table_id: str, records: list[dict]) -> list[str]:
    """批量创建记录，返回 record_id 列表"""
    if not records:
        return []

    record_ids = []
    # 每批最多 500 条
    for i in range(0, len(records), 500):
        batch = records[i:i + 500]
        data = api_request("POST",
                           f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                           token, json={"records": [{"fields": r} for r in batch]})
        for item in data.get("records", []):
            record_ids.append(item.get("record_id", ""))
        if i + 500 < len(records):
            time.sleep(0.5)

    return record_ids


def update_record(token: str, app_token: str, table_id: str, record_id: str, fields: dict):
    """更新单条记录"""
    api_request("PUT", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                token, json={"fields": fields})


# ── 数据转换 ────────────────────────────────────────────────────

def skill_to_fields(entry: dict) -> dict:
    """技能注册表条目 → 飞书字段"""
    fields = {
        "技能名称": entry.get("name", ""),
        "技能描述": entry.get("description_zh", ""),
        "技能分类": entry.get("category", ""),
        "存放路径": entry.get("path", ""),
        "最后更新日期": entry.get("last_modified", ""),
        "文件大小": entry.get("size", ""),
        "健康状态": entry.get("health", {}).get("status", ""),
        "同步状态": "已同步",
    }

    source = entry.get("github_source_url", "")
    if source:
        fields["来源地址"] = {"text": source, "link": source}

    my_url = entry.get("github_my_url", "")
    if my_url:
        fields["我的仓库"] = {"text": my_url, "link": my_url}

    fields["作用域"] = "项目级" if entry.get("scope") == "project" else "全局"
    fields["所属项目"] = entry.get("project", "")

    return fields


def mcp_to_fields(entry: dict) -> dict:
    """MCP 注册表条目 → 飞书字段"""
    fields = {
        "服务器名称": entry.get("name", ""),
        "功能描述": entry.get("description_zh", ""),
        "NPM 包名": entry.get("npm_package", ""),
        "运行命令": entry.get("command", ""),
        "环境变量": ", ".join(entry.get("env_vars", [])),
        "分类": entry.get("category", ""),
        "同步状态": "已同步",
    }

    gh = entry.get("github_url", "")
    if gh:
        fields["GitHub地址"] = {"text": gh, "link": gh}

    return fields


# ── 同步逻辑 ────────────────────────────────────────────────────

def sync_table(token: str, app_token: str, table_id: str,
               entries: dict, record_map: dict, to_fields_fn,
               name_field: str, skill_name: str = None) -> dict:
    """
    通用表同步逻辑
    返回更新后的 record_map
    """
    # 筛选要同步的条目
    if skill_name:
        if skill_name not in entries:
            print(f"  未找到: {skill_name}")
            return record_map
        to_sync = {skill_name: entries[skill_name]}
    else:
        to_sync = entries

    # 获取已有记录，重建映射
    existing_records = list_records(token, app_token, table_id)
    remote_map = {}
    for item in existing_records:
        fields = item.get("fields", {})
        rname = ""
        name_val = fields.get(name_field, "")
        if isinstance(name_val, list):
            rname = name_val[0].get("text", "") if name_val else ""
        elif isinstance(name_val, str):
            rname = name_val
        if rname:
            remote_map[rname] = item.get("record_id", "")

    # 合并远程映射到本地
    record_map.update(remote_map)

    new_records = []
    new_names = []
    updated = 0

    for name, entry in to_sync.items():
        fields = to_fields_fn(entry)
        rid = record_map.get(name)

        if rid:
            # 已有记录 → 更新
            try:
                update_record(token, app_token, table_id, rid, fields)
                updated += 1
            except Exception as e:
                print(f"  更新失败 [{name}]: {e}", file=sys.stderr)
        else:
            # 新记录
            new_records.append(fields)
            new_names.append(name)

    # 批量创建新记录
    if new_records:
        try:
            new_ids = batch_create(token, app_token, table_id, new_records)
            for nm, rid in zip(new_names, new_ids):
                record_map[nm] = rid
        except Exception as e:
            print(f"  批量创建失败: {e}", file=sys.stderr)

    print(f"  新增: {len(new_records)} | 更新: {updated}")
    return record_map


def update_registry_status(registry: dict, section: str, synced_names: dict):
    """更新注册表中的同步状态和 record_id"""
    for name, rid in synced_names.items():
        if name in registry.get(section, {}):
            registry[section][name]["sync_status"] = "已同步"
            registry[section][name]["feishu_record_id"] = rid


# ── 主函数 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞书多维表格同步")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full",
                        help="同步模式: full=全量, incremental=增量")
    parser.add_argument("--registry",
                        default=r"C:\Users\fubai\.claude\skills\skill-manager\data\registry.json",
                        help="注册表路径")
    parser.add_argument("--env",
                        default=r"C:\Users\fubai\.claude\skills\skill-manager\.env",
                        help=".env 文件路径")
    parser.add_argument("--config",
                        default=r"C:\Users\fubai\.claude\skills\skill-manager\data\feishu_config.json",
                        help="飞书配置路径")
    parser.add_argument("--skill-name", help="增量模式: 指定技能名称")
    parser.add_argument("--mcp-name", help="增量模式: 指定 MCP 名称")
    args = parser.parse_args()

    # 加载注册表
    reg_path = Path(args.registry)
    if not reg_path.exists():
        print("Error: 注册表不存在，请先运行 scan.py", file=sys.stderr)
        sys.exit(1)
    registry = json.loads(reg_path.read_text(encoding="utf-8"))

    # 加载飞书凭据
    env_path = Path(args.env)
    app_id, app_secret = load_env(env_path)

    # 获取 token
    print("认证中...")
    token = get_token(app_id, app_secret)

    # 确保表格存在
    config_path = Path(args.config)
    config = load_config(config_path)
    config = ensure_tables(token, config, config_path)

    # 同步技能表
    print(f"\n同步技能表...")
    skill_name = args.skill_name if args.mode == "incremental" else None
    config["skill_record_map"] = sync_table(
        token, config["app_token"], config["skill_table_id"],
        registry.get("skills", {}), config.get("skill_record_map", {}),
        skill_to_fields, "技能名称", skill_name
    )

    # 同步 MCP 表
    print(f"同步 MCP 服务器表...")
    mcp_name = args.mcp_name if args.mode == "incremental" else None
    config["mcp_record_map"] = sync_table(
        token, config["app_token"], config["mcp_table_id"],
        registry.get("mcp_servers", {}), config.get("mcp_record_map", {}),
        mcp_to_fields, "服务器名称", mcp_name
    )

    # 保存配置
    config["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_config(config, config_path)

    # 更新注册表同步状态
    update_registry_status(registry, "skills", config["skill_record_map"])
    update_registry_status(registry, "mcp_servers", config["mcp_record_map"])
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n同步完成!")
    if config.get("bitable_url"):
        print(f"飞书表格地址: {config['bitable_url']}")


if __name__ == "__main__":
    main()
