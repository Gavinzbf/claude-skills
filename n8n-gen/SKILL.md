---
name: n8n-gen
description: "通过研究官方模板生成 n8n 工作流。此技能：(1) 使用 Playwright 从 n8n.io 搜索并下载参考工作流，(2) 向用户确认设计方案与 API 服务商选择，(3) 基于 'n8n AI Agent' 设计指南生成自定义工作流，(4) 通过 MCP 直接部署到 n8n 云端，(5) 将文档以 Sticky Notes 形式嵌入工作流中。"
license: Proprietary
---

# n8n 工作流生成与云端部署

## 概述

此技能使 Claude 能够作为 n8n 解决方案架构师。它自动化了研究现有解决方案、学习官方模板、合成生产级 AI Agent 工作流，并**通过 n8n remote MCP 直接部署到用户的 n8n 云端实例**的整个流程。所有文档以颜色编码的 Sticky Notes 形式嵌入工作流中，方便用户直接查看。

## 工作流程

### 1. 分析与搜索策略

- 分析用户的自然语言请求，理解自动化场景。
- 提取 2-3 个核心英文关键词（例如："Reddit monitoring"、"Video generation"、"WooCommerce sync"）用于搜索 n8n 模板库。
- 准备好搜索查询，用于模板获取步骤。

### 2. 获取参考模板 (Playwright MCP)

使用 Playwright MCP 从官方仓库获取参考资料：
1.  导航到 `https://n8n.io/workflows/`。
2.  处理可能出现的 "Use cookies" 弹窗。
3.  在搜索框中输入生成的关键词并提交。
4.  遍历结果，识别相关的工作流。
5.  对于最相关的 5-10 个工作流，执行以下操作：
    - 点击进入工作流详情页。
    - 找到并点击 **"Use for free"** 按钮。
    - 等待弹出模态框。
    - 点击 **"Copy template to clipboard[JSON]"**。
    - *技术说明：* 拦截剪贴板内容或直接从 DOM 中提取 JSON 数据。
    - 创建一个本地 JSON 文件，文件名与工作流标题一致（经过文件名净化处理）。
    - 粘贴代码并保存到：
      ```
      n8n_references/[sanitized-workflow-name].json
      ```

### 3. 确认设计方案与 API 选择

在生成最终工作流之前，**必须**使用 `AskUserQuestion` 工具向用户确认以下内容：

#### 3.1 流程确认
向用户展示设计的工作流概要，包括：
- 触发方式（定时/Webhook/手动）
- 核心处理步骤
- 预期输出

询问用户：*"以上流程是否符合您的需求？是否需要调整？"*

#### 3.2 API 服务商选择
根据工作流需求，列出可用的 API 服务商选项：

**示例（视频生成场景）**：
| 服务商 | API | 费用估算 | 特点 |
|--------|-----|----------|------|
| fal.ai | Veo 3.1 | ~$0.50/视频 | 速度快，质量高 |
| KIE.AI | Veo 3 | ~$0.30/视频 | 价格便宜 |
| Replicate | Various | 按秒计费 | 选择多样 |

询问用户：
- *"您希望使用哪个 API 服务商？"*
- *"您是否已有该服务的 API Key？"*
- 如果用户没有，提供注册链接或推荐替代方案

#### 3.3 确认后继续
用户确认后，将选择的 API 服务商信息传递给步骤 4，用于生成对应的 HTTP Request 节点配置。

### 4. 生成 n8n 工作流 JSON

1.  读取位于技能目录中的设计提示文件：
    ```
    .claude/skills/n8n-gen/n8n AI Agent工作流设计提示词.md
    ```
    *说明：此文件与技能捆绑，包含 AI Agent 架构逻辑、DeepSeek v3 参数设置和最佳实践。*

2.  合成最终工作流：
    - 结合从下载的参考文件（步骤 2）中学到的结构模式。
    - 应用设计提示（步骤 4.1）中的逻辑和约束。
    - 使用用户在步骤 3 中确认的 API 服务商配置。
    - 确保输出是有效的 n8n JSON 格式，具有正确的 node IDs 和 connections。
    - 根据需要配置特定的 AI Agent 节点和 Loop/Merge 逻辑。

3.  **添加嵌入式文档 Sticky Notes**（详见步骤 5）：
    - 在部署前将所有必需的 Sticky Notes 包含在 `nodes` 数组中。

4.  **通过 MCP 部署到 n8n 云端**：
    - 使用 `mcp__n8n-remote__n8n_create_workflow` 直接部署工作流。
    - 参数：
      - `name`: 工作流名称（例如："TikTok Video Generator with Veo 3.1"）
      - `nodes`: 包含 Sticky Notes 的完整节点数组
      - `connections`: 定义节点关系的连接对象
      - `settings`: `{"executionOrder": "v1"}`
    - **可选**：部署前运行 `mcp__n8n-remote__validate_workflow` 以捕获错误。
    - **成功时**：向用户报告 workflow ID 并确认部署状态。
    - **失败时**：显示错误信息并建议修复方案。

### 5. 将文档嵌入为 Sticky Notes

不再创建单独的 markdown 文件，而是将所有文档以**颜色编码的 Sticky Notes** 形式直接嵌入工作流中。这使用户可以直接在 n8n 画布中查看配置指南和工作流说明。

#### Sticky Note JSON 结构

```json
{
  "id": "sticky-[unique-id]",
  "name": "[Note Title]",
  "type": "n8n-nodes-base.stickyNote",
  "position": [x, y],
  "parameters": {
    "color": 5,
    "width": 500,
    "height": 300,
    "content": "# Markdown 内容"
  },
  "typeVersion": 1
}
```

#### 必需的 Sticky Notes（颜色编码区域）

| 颜色代码 | 区域名称 | 位置 | 内容 |
|----------|----------|------|------|
| **5 (紫色)** | 工作流概述 | 左上角，触发器之前 | 项目概述、触发方式、核心流程说明、预期输出 |
| **6 (黄色)** | 配置指南 | 靠近 config/Set 节点 | 需要配置的参数列表、API Key 位置、Sheet ID、凭证设置步骤 |
| **4 (蓝色)** | API 要求 | 靠近 HTTP Request 节点 | 所需 API 服务、注册链接、费用估算、超时设置 |
| **3 (绿色)** | 流程图 | 底部区域 | Mermaid 流程图代码块展示数据流向 |

#### 内容模板

**紫色 (Overview) - 工作流概述**：
```markdown
# [工作流名称]
## 功能概述
[简述此工作流的功能]

## 触发方式
- 定时触发：[计划详情，例如：每天 23:00]
- 或 Webhook 触发：[URL（如适用）]

## 核心流程
1. [步骤 1]
2. [步骤 2]
3. [步骤 3]
```

**黄色 (Configuration) - 配置指南**：
```markdown
# 配置步骤 ⚙️

## 1. 修改配置节点
- `google_sheet_id`: 您的 Google Sheets ID
- `sheet_name`: 工作表名称
- `api_key`: 您的 API 密钥

## 2. 设置凭证
- Google Sheets OAuth2
- [其他所需凭证]

## 3. 激活工作流
配置完成后激活此工作流
```

**蓝色 (API Info) - API 要求**：
```markdown
# API 要求 🔑

## [服务名称] API
- 注册地址: https://...
- 获取密钥: https://...
- 预估费用: $X.XX / 次调用
- 超时设置: XX 分钟
```

**绿色 (Flow Diagram) - 流程图**：
```markdown
# 数据流程图

\`\`\`mermaid
graph LR
    A[Trigger] --> B[Read Data]
    B --> C[Process]
    C --> D[Output]
\`\`\`
```

#### 位置指南

- **Sticky Notes 不应与功能节点重叠**。
- 将 **Overview** 便签放置在 `[-200, 0]` 位置或触发器上方。
- 将 **Configuration** 便签放置在 Set/Config 节点附近。
- 将 **API Info** 便签放置在 HTTP Request 节点附近。
- 将 **Flow Diagram** 放置在工作流底部。
- 使用一致的宽度（500-600px）以保证可读性。

## 技术要求

### 依赖项
- **Playwright MCP**：用于无头浏览器交互，从 `n8n.io` 下载模板。
- **n8n Remote MCP**：用于将工作流直接部署到用户的 n8n 云端实例。
  - 必须配置有效的 n8n 实例 URL 和 API key。
  - 使用 `mcp__n8n-remote__n8n_health_check` 在部署前验证连接。

### 目录结构

```
.claude/skills/n8n-gen/
├── SKILL.md
├── n8n AI Agent工作流设计提示词.md  # (与技能捆绑)
└── ...

project_root/
└── n8n_references/                # (中间产物：下载的模板)
    ├── template-1.json
    └── ...
```

*说明：最终工作流直接部署到 n8n 云端 - 无需本地输出目录。*

### 关键实现说明
- **用户确认**：在生成工作流之前，必须使用 `AskUserQuestion` 向用户确认流程设计和 API 服务商选择。
- **错误处理**：如果 `copy template` 失败或按钮不存在，跳过到下一个模板。
- **JSON 有效性**：生成的 JSON 必须是严格有效的 JSON，具有唯一的 node IDs。
- **参考逻辑**：AI 不应盲目复制参考文件，而应使用它们来理解*如何*为特定领域连接节点，然后使用本地提示文件中定义的逻辑重新构建。
- **部署验证**：调用 `n8n_create_workflow` 后，确认返回了 workflow ID 并向用户报告成功。
- **Sticky Notes**：每个生成的工作流必须至少包含 3 个 Sticky Notes（Overview、Configuration、API Info）。
