---
name: skill-manager
description: |
  管理 Claude Code 技能和 MCP 服务器。扫描已安装技能和 MCP、自动分类、
  健康检查、同步到飞书多维表格（技能表 + MCP 表）。
  触发场景：(1) 管理技能 (2) 扫描技能/scan skills (3) 同步飞书
  (4) 技能健康检查/health check (5) 搜索技能 (6) 技能列表
  (7) 管理MCP (8) MCP列表 (9) skill-manager (10) 更新技能信息
---

# Skill & MCP Manager

管理本地 Claude Code 技能库和 MCP 服务器，支持扫描、分类、健康检查、飞书同步。

## 路径配置

- 技能目录: `C:\Users\fubai\.claude\skills\`
- MCP 配置: `C:\Users\fubai\.claude.json`
- 项目扫描目录: `D:\CursorCode`（.env 中 PROJECT_SCAN_DIRS 配置）
- 脚本目录: `C:\Users\fubai\.claude\skills\skill-manager\scripts\`
- 数据目录: `C:\Users\fubai\.claude\skills\skill-manager\data\`
- 飞书凭据: `C:\Users\fubai\.claude\skills\skill-manager\.env`

## 首次使用

确认 `.env` 文件存在于技能目录下，包含：
```
FEISHU_APP_ID=应用ID
FEISHU_APP_SECRET=应用密钥
MY_GITHUB_REPO=https://github.com/用户名/仓库名
```
如不存在，提示用户到 https://open.feishu.cn/app 创建应用并获取凭据。
`MY_GITHUB_REPO` 用于自创技能的"我的仓库"链接自动生成。

## 操作模式

根据用户意图选择模式。所有脚本从技能目录运行：
```
cd C:\Users\fubai\.claude\skills\skill-manager
```

### 模式 A: 全量扫描并同步飞书

首次初始化或完整刷新时使用。

```bash
python scripts/scan.py
python scripts/sync_feishu.py --mode full
```

同步后飞书会有两张表：**技能列表** 和 **MCP 服务器**。

### 模式 B: 增量更新单个技能

新安装或修改某个技能后使用。

```bash
python scripts/scan.py --skill-name <技能名>
python scripts/sync_feishu.py --mode incremental --skill-name <技能名>
```

### 模式 C: 搜索技能

按关键词搜索已安装的技能和 MCP 服务器。

```bash
python scripts/scan.py --search <关键词>
```

也可直接读取 `data/registry.json` 查找。

### 模式 D: 健康检查

检查所有技能的结构规范性。

```bash
python scripts/scan.py --health-check
```

检查项：SKILL.md 是否存在、frontmatter 格式、name/description 字段、命名规范等。

### 模式 E: 查看当前状态

直接读取 `data/registry.json` 并以表格形式向用户展示技能和 MCP 信息。

对于 `description_zh` 包含 `[需要翻译]` 前缀的条目，翻译成中文后展示。

## 飞书表格结构

### 技能列表表
| 列 | 说明 |
|---|---|
| 技能名称 | skill 目录名 |
| 技能描述 | 中文描述（英文自动翻译） |
| 技能分类 | 自动分类：音视频处理、开发工具、文档处理等 |
| 存放路径 | 本地绝对路径 |
| 最后更新日期 | YYYY-MM-DD 格式 |
| 文件大小 | 如 4.2 KB |
| 健康状态 | healthy / warning / error |
| 同步状态 | 已同步 / 待同步 |
| 来源地址 | 下载来源的 GitHub 链接（如 anthropics/skills）|
| 我的仓库 | 自创技能推送到的 GitHub 仓库链接 |
| 作用域 | 全局 / 项目级 |
| 所属项目 | 项目文件夹名（项目级 skill 才有值）|

### MCP 服务器表
| 列 | 说明 |
|---|---|
| 服务器名称 | MCP 配置中的 key |
| 功能描述 | 中文描述 |
| NPM 包名 | 如 @playwright/mcp |
| 运行命令 | 完整启动命令 |
| 环境变量 | 使用的环境变量名 |
| 分类 | 自动分类 |
| 同步状态 | 已同步 / 待同步 |
| GitHub地址 | 可点击链接 |

## 注意事项

- skill-manager 自身也会被扫描和管理，size 计算时排除 data/、.env 等运行时文件
- 英文技能描述在同步前由 Claude 翻译为中文，更新到 registry.json 的 description_zh 字段
- 来源地址（下载的 skill）通过 KNOWN_SKILL_SOURCES 映射自动填充
- 我的仓库（自创 skill）通过 .env 中的 MY_GITHUB_REPO 自动拼接
- MCP 的 GitHub 地址通过 KNOWN_MCP_GITHUB 映射 + npm 包名推断
- 飞书表字段变更时会自动迁移（添加缺失字段），无需手动删表重建
- merge 逻辑：重新扫描的值优先，仅在新值为空时保留旧值
- 飞书 API 参考文档: 见 `references/feishu-api.md`
