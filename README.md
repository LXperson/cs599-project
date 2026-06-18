# CodeSage — 智能代码工程师 Agent

## 项目简介
CodeSage 是一个基于 AI Agent 的**智能代码工程师助手**，面向软件开发全生命周期，提供以下核心能力：

| 能力 | 命令 | 说明 |
|---|---|---|
| **代码审查** | `review` | 规则引擎 + LLM 双引擎，覆盖安全/质量/性能 |
| **Bug 修复** | `fix` | LLM 分析 → 自动生成修复代码 → 写回源文件（自动备份） |
| **单元测试生成** | `test` | LLM 为源文件生成高质量 pytest 单元测试 |
| **Git 变更审查** | `diff` | 审查 Git 暂存区变更，LLM 深度分析 + 规则辅助 |
| **代码重构建议** | `refactor` | LLM 深度分析代码异味、设计模式、SOLID 原则 |
| **目录统计** | `stats` | 递归扫描文件数/行数/语言分布 |
| **交互式对话** | `interactive` | Claude Code 风格 REPL，纯自然语言驱动 |

**核心特色**：用户只需输入自然语言（如 "帮我审查这个项目"），LLM 路由器自动判断意图并执行对应操作。

## 方向
**方向一：Agentic AI 原生开发**

## 技术栈
| 类别 | 技术 |
|---|---|
| AI IDE | Trae CN |
| LLM | DeepSeek API (OpenAI 兼容) |
| Agent 框架 | LangGraph (8 节点状态图) |
| 工具调用 | Function Calling (FileReader / GitParser) |
| 记忆机制 | ConversationMemory (JSON 持久化 + 审查历史 + 文件操作追踪) |
| 可观测性 | LangSmith Tracing (可选) |
| CLI 框架 | argparse + Rich |
| 包管理 | pyproject.toml (pip install -e .) |

## 目录结构
```
cs599-project/
├── pyproject.toml                  # 包配置 (codesage 命令注册)
├── .env.example                    # 环境变量模板
├── .gitignore                      # 过滤 .codesage/ 备份/测试文件
├── src/
│   ├── main.py                     # CLI 入口 (argparse 子命令 + 交互 REPL)
│   ├── agent/
│   │   ├── state.py                # AgentState TypedDict 定义
│   │   ├── nodes.py                # 8 个 LangGraph 节点
│   │   └── graph.py                # 状态图编译 (condition 路由)
│   ├── config/
│   │   ├── settings.py             # 配置管理 (16 个环境变量)
│   │   └── prompts.py              # 7 个 Prompt 模板 (含路由器)
│   ├── tools/
│   │   ├── file_reader.py          # 文件读写 + 模糊搜索 + 集中备份
│   │   └── git_parser.py           # Git diff 解析
│   ├── review/
│   │   ├── rules.py                # 9 条内建审查规则 (安全/质量/性能/实践)
│   │   ├── reviewer.py             # 双引擎审查器 (规则 + LLM + 重试)
│   │   └── reporter.py             # 报告生成 + 评分体系 + 导出
│   └── memory/
│       └── memory_manager.py       # ConversationMemory (持久化 + 上下文)
├── docs/
│   ├── architecture.md             # Product/Architecture/API Spec (SDD)
│   └── CS599_大作业报告.md         # 期末项目报告
└── LICENSE                         # Apache 2.0
```

## 安装与使用

### 方式一：安装后全局使用（推荐）
```bash
git clone <repo-url> && cd cs599-project
python -m venv .venv
.venv\Scripts\Activate.ps1     # Windows
pip install -e .
cp .env.example .env           # 填入 DEEPSEEK_API_KEY

codesage review src/           # 审查目录
codesage fix src/main.py       # 修复 Bug → 自动写回
codesage test src/utils.py     # 生成单测
codesage interactive           # 交互 REPL
```

### 方式二：直接运行（无需安装）
```bash
cd cs599-project
.venv\Scripts\Activate.ps1
python src/main.py review src/
python src/main.py fix src/main.py
python src/main.py interactive
```

## CLI 命令一览
```bash
codesage review <path>           # 审查文件或目录 (递归 → 10 文件上限)
codesage review <path> -o out.md # 审查并导出报告
codesage fix <path>              # Bug 修复 → 自动写回 (自动备份)
codesage fix <path> -- "指令"    # 带自定义指令的修复
codesage test <path>             # 生成单元测试 → test_*.py
codesage diff                    # Git 变更审查
codesage interactive             # 交互 REPL (自然语言优先)
codesage rules                   # 列出 9 条内建审查规则
codesage version                 # 版本信息
```

## 交互模式
纯自然语言驱动，命令为可选补充。LLM 路由器自动识别 8 种意图并执行。

```
cs599-project ❯ 审查这个项目
▸ 审查 cs599-project/...
📄 [1/8] src/agent/nodes.py  🔴 3个问题...

cs599-project ❯ 帮我修复刚才那个严重问题
▸ 修复 src/agent/nodes.py...
✅ 文件已修复并写入  💾 备份: .codesage/backups/nodes.py.20260618_...

cs599-project ❯ 回退刚才的修改
✅ 已恢复: src/agent/nodes.py

cs599-project ❯ 统计一下
  语言    文件数    比例
  py      22       100%
总计: 22 文件, 4400 行
```

**快捷命令 (可选)**：
| 命令 | 说明 |
|---|---|
| `/review <path>` | 审查指定文件或目录 (模糊匹配) |
| `/fix <path>` | 修复指定文件 Bug (先备份再写入) |
| `/test <path>` | 为文件生成单元测试 |
| `/diff` | Git 变更审查 |
| `/stats <dir>` | 目录统计 (文件数/行数/语言分布) |
| `/lint <file>` | 快速规则扫描 (仅规则引擎) |
| `/undo <file>` | 回退到上一份 CodeSage 备份 |
| `/backups <file>` | 查看文件的所有备份 |
| `/ls` `/pwd` `/cd` | 文件系统操作 |
| `/help` | 完整帮助 |
| `:q` | 退出 |

## 审查规则
| ID | 级别 | 类别 | 名称 |
|---|---|---|---|
| SEC-001 | 🔴 CRITICAL | security | 硬编码密钥/密码 |
| SEC-002 | 🟡 WARNING | security | SQL 拼接风险 |
| SEC-003 | 🟡 WARNING | security | 调试代码未移除 |
| QUAL-001 | 🔵 SUGGESTION | quality | 函数过长 |
| QUAL-002 | 🔵 SUGGESTION | quality | 魔法数字 |
| QUAL-003 | 🟡 WARNING | quality | 异常处理过于宽泛 |
| BEST-001 | 🔵 SUGGESTION | best_practice | 缺少文档字符串 |
| PERF-001 | 🟡 WARNING | performance | 循环内 I/O 操作 |
| PERF-002 | 🔵 SUGGESTION | performance | 列表拼接性能问题 |

## 评分体系
| 评分区间 | 等级 | 含义 |
|---|---|---|
| 90-100 | 优秀 | 代码质量高，无严重问题 |
| 70-89 | 良好 | 存在少量建议性改进点 |
| 50-69 | 及格 | 有警告级别问题需关注 |
| 0-49 | 需改进 | 存在严重问题必须修复 |

扣分规则: 🔴-15分, 🟡-5分, 🔵-1分 (基准100分)

## 核心技术要素覆盖 (6+)
| 要素 | 实现 | 文件位置 |
|---|---|---|
| SDD 规格驱动开发 | Product + Architecture + API Spec | [docs/architecture.md](docs/architecture.md) |
| 工具使用 / Function Calling | FileReader / GitParser | [src/tools/](src/tools/) |
| 记忆机制 | ConversationMemory + JSON 持久化 + 文件操作追踪 | [src/memory/memory_manager.py](src/memory/memory_manager.py) |
| 状态管理与多步推理 | LangGraph 8 节点 ReAct 工作流 | [src/agent/](src/agent/) |
| 可观测性与评估 | LangSmith Tracing + 综合评分体系 | [src/config/settings.py](src/config/settings.py) |
| MCP 协议 | 预留扩展接口 | [docs/architecture.md](docs/architecture.md) |
| LLM 路由与意图识别 | AGENT_ROUTER_PROMPT (8 种意图) | [src/config/prompts.py](src/config/prompts.py) |

## 环境变量
| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | (必填) | DeepSeek API Key |
| `DEEPSEEK_MODEL` | `deepseek-chat` | LLM 模型 |
| `LLM_RETRIES` | `3` | LLM 调用最大重试次数 |
| `LLM_REQUEST_TIMEOUT` | `120` | LLM 请求超时秒数 |
| `MAX_DIR_FILES` | `10` | 目录审查文件上限 |
| `MAX_FILE_SIZE_KB` | `500` | 单文件最大 KB |
| `MEMORY_MAX_TURNS` | `30` | 对话轮次上限 |
| `MEMORY_MAX_FILE_OPS` | `50` | 文件操作记录上限 |

## 项目状态
- [x] Proposal（选题设计）
- [x] MVP（核心闭环 v0.1）
- [x] Final（最终交付 v1.2.0）

## 学术声明
本项目为 CS599 课程大作业，采用 Apache 2.0 开源协议。
所有 API Key 通过环境变量注入，所有业务常量均可通过 .env 配置，代码中无硬编码。
引用外部开源项目及技术在代码注释中标注来源。
