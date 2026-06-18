# CodeSage 架构规格文档

## 一、Product Spec（产品规格）

### 1.1 产品定义
CodeSage 是一个基于 AI Agent 的代码审查助手，面向软件开发团队，解决人工代码审查效率低、标准不一致的问题。

### 1.2 核心功能
| 功能 | 描述 | 优先级 |
|---|---|---|
| 单文件审查 | 提交代码文件路径，返回结构化审查报告 | P0 |
| 目录批量审查 | 提交目录路径，批量审查所有源代码文件 | P1 |
| Bug 修复 | 分析代码 Bug 并生成修复方案和补丁代码 | P0 |
| 单测生成 | 为源文件生成高质量 pytest 单元测试 | P0 |
| Git diff 审查 | 解析 Git 仓库变更，只审查增量代码 | P1 |
| 交互式追问 | 用户对审查结果提问，Agent 基于上下文回答 | P2 |
| 报告导出 | 审查报告保存为 Markdown 文件 | P2 |

### 1.3 用户故事
1. 开发者提交 PR 前运行 CodeSage，快速发现潜在问题
2. 代码审查者使用 CodeSage 作为辅助工具，提高审查效率
3. 团队 Leader 使用批量审查功能，了解项目整体代码健康状况

---

## 二、Architecture Spec（架构规格）

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户层                                │
│    CLI (main.py)             交互模式 (while loop)            │
└───────────────┬─────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│                    Agent 核心 (LangGraph)                     │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │parse_input│──▶│collect_  │──▶│ review_  │──▶│ generate_│ │
│  │  (节点1)  │   │ files    │   │  file    │   │ report   │ │
│  │           │   │ (节点2)  │   │ (节点3)  │   │ (节点4)  │ │
│  └──────────┘   └──────────┘   └─────┬────┘   └──────────┘ │
│                                       │                      │
│                              ┌────────▼──────────┐          │
│                              │ interactive       │          │
│                              │ (节点5 - 追问)    │          │
│                              └───────────────────┘          │
└───────────────┬─────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│                      工具层 (Tools)                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ FileReader   │ │StaticAnalyzer│ │  GitParser   │         │
│  │ 文件系统访问  │ │ ruff 集成    │ │ Git 操作     │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
└───────────────┬─────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│                     基础设施层                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │DeepSeek  │ │LangGraph │ │ Memory   │ │LangSmith │       │
│  │  API     │ │Checkpoint│ │ Manager  │ │ Tracing  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Agent 交互流程（多能力路由）

```
User Input → parse_input → 判定任务类型
                             │
              ┌──────────────┼──────────────────────┐
              ▼              ▼              ▼       ▼
        review_file    review_dir    review_diff  fix/test
              │              │              │       │
              │    collect_files (glob)     │  收集目标文件
              │              │              │       │
              └──────────────┼──────────────┘       │
                             ▼                      │
                      review_file              fix_file/test_file
                  ┌────────────────┐         ┌──────────────┐
                  │  规则引擎审查   │         │  LLM 分析/生成│
                  │  +             │         │  规则引擎辅助 │
                  │  LLM 语义审查  │         │              │
                  └───────┬────────┘         └──────┬───────┘
                          └──────────┬─────────────┘
                                     ▼
                              generate_report
                                     │
                            ├──→ END (普通模式)
                            └──→ interactive → END (追问)
```

### 2.3 数据流设计

```
Input: str(path/dir/diff)
  │
  ▼
AgentState ─────────────────────────────────────────────────
  messages:     [HumanMessage, ..., AIMessage]
  target:       审查目标字符串
  target_type:  "file" | "directory" | "diff" | "query"
  issues:       [ReviewIssue dict, ...]
  current_file: 当前正在审查的文件
  files_processed: [path, ...]
  memory_summary: 对话摘要
  done:         bool
  error:        str
  │
  ▼
Output: Markdown Report (stdout + optional file)
```

---

## 三、API Spec（API 规格）

### 3.1 LangGraph 节点接口

| 节点 | 输入状态字段 | 输出状态字段 | 描述 |
|---|---|---|---|
| parse_input | messages | target, target_type, done | 解析用户输入类型 |
| collect_files | target, target_type | current_file, files_processed | 收集待审查文件 |
| review_file | current_file | issues | 执行双引擎审查 |
| generate_report | issues, files_processed | messages, done | 汇总生成报告 |
| interactive | messages, issues | messages, done | 处理用户追问 |

### 3.2 审查规则接口

```python
@dataclass
class ReviewRule:
    rule_id: str          # 规则唯一 ID
    category: Category    # SECURITY | QUALITY | BEST_PRACTICE | PERFORMANCE
    severity: Severity    # CRITICAL | WARNING | SUGGESTION
    title: str            # 规则标题
    description: str      # 问题描述
    suggestion: str       # 修复建议
    patterns: dict[str, str]  # {语言: 正则表达式}
```

### 3.3 审查结果接口

```python
@dataclass
class ReviewIssue:
    severity: Severity    # 严重级别
    category: Category    # 规则类别
    rule_id: str          # 规则 ID
    file_path: str        # 文件路径
    line: int | None      # 行号
    title: str            # 问题标题
    description: str      # 问题详细描述
    suggestion: str       # 修复建议
    source: str           # "rule" | "llm" | "system"
```

---

## 四、MCP 协议扩展设计（加分项预留）

为支持 MCP (Model Context Protocol)，预留以下扩展点：

1. **MCP Server 集成**：将 FileReader / StaticAnalyzer 包装为 MCP Tool
2. **外部工具接入**：通过 MCP 协议接入第三方代码分析服务（SonarQube、CodeQL 等）
3. **MCP 资源提供**：审查规则库作为 MCP Resource 对外暴露

```python
# 预留扩展点示例
class MCPToolAdapter:
    """将内部工具适配为 MCP Tool 接口。"""
    
    @staticmethod
    def to_mcp_tool(tool_instance) -> dict:
        """返回 MCP Tool 描述 schema。"""
        ...
```

---

## 五、可扩展性设计

1. **审查规则可插拔**：新增规则只需在 `rules.py` 中添加 `ReviewRule` 实例
2. **多 LLM 后端**：`ChatOpenAI` 兼容协议，可切换任何 OpenAI-compatible API
3. **多 Agent 协作**：LangGraph 支持子图，可扩展为多 Agent 分工（安全审查 Agent + 质量审查 Agent）
4. **持久化存储**：Checkpoint 可替换为 SQLite/Postgres 后端，支持跨会话记忆

---

最后更新：2026-06-18
