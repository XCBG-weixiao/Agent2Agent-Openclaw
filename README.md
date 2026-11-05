# Agent2Agent-Openclaw
Improved Version of OpenClaw: Integration of On-Device Intelligence and Cloud-Based Intelligence

OpenClaw relies on the power of cloud-based LLMs to interact with users through apps like instant messengers, and handles all sorts of sophisticated tasks with its extensive agent functionalities. That said, a string of recent events has laid bare its undeniable security flaws. Even with full configuration options and rigid permission controls in place, this lobster still finds all kinds of unexpected ways to "wipe every file off your computer".

In my view, local permission control shouldn’t be managed by these bare-bones config files. This idea comes from my past work and hands-on robotics experience. A powerful on-device intelligence should handle all local sensing and execution, while the robust cloud-based intelligence is there to guide the relatively less capable on-device system. Think of how modern intelligent robots work: a robot can perceive the world around it and take actions completely on its own. If it’s paired with a cloud-based brain, that brain should tell it where to go and how to approach a task — not directly control every single step it takes. What’s more, the robot has every right to refuse to carry out the cloud brain’s commands, either because it lacks the capability to complete them, or for any other legitimate reason.

That’s why I’ve developed this Agent2Agent OpenClaw solution. It has just one critical difference from the conventional version: we’ve added a dedicated on-device agent. This agent picks up commands from the cloud-based agent, and acts as your dedicated "personal butler" — the only entity with the authority to control your privacy-sensitive local devices.

![github画图](https://github.com/user-attachments/assets/3f08aa23-f102-4ff6-b962-8bff4e620fe5)

For this on-device agent, we’ve opted to deploy a Vision Language Model (VLM) locally, and it only needs to handle simple recognition and basic instruction tasks. 

👏👏The project is now in full swing with intensive development, and feel free to reach out and connect if you’re a fellow "lobster farmer" with interest in this work!

### 首版方案：轻量端侧 Agent 与远端 Agent 协同

本项目让资源有限的端侧 Agent 借助远端 Agent 完成更复杂的任务。首版在 macOS 和 Windows 上运行 ZeroClaw。ZeroClaw 自身的推理使用可配置的 OpenAI 兼容接口，端侧负责发现、委托和本地执行。它从 Agent 平台查询已注册、在线且可达的远端 Agent，并通过 A2A 调用其模型能力。

协同有两条路径。第一条由远端 Agent 完成任务并直接返回结果。第二条由远端 Agent 制定结构化计划，端侧检查计划和操作权限，再用本地工具按步骤执行。采用 Plan–Executor 分工后，端侧只需具备可靠的校验和执行能力，就能完成由远端规划的任务。对本地文件的访问和执行决定留在端侧。

首版通过远端代码审查和本地文件报告验证这两条路径，并在 macOS 和 Windows 上建立内存占用与冷启动时间基线。多个远端 Agent 可以独立上线和注册，端侧按需选择和组合它们，为端云协同、Agent 集群和多 Agent 协作提供基础。

#### 启动

安装 Python 3.12、uv 和 [ZeroClaw 0.8.7](https://github.com/zeroclaw-labs/zeroclaw/releases/tag/v0.8.7)。在运行专家的机器上安装已登录的 Codex CLI，以及 Node.js 24.9+ 和 `@deepseek-ai/dsh@0.2.2-rc.1`。本机运行全部服务时执行 `uv sync --all-extras`。只运行端侧时执行 `uv sync --no-dev`。Windows 使用 PowerShell 和同样的 `uv run` 命令。

每个服务启动前，在对应终端或服务管理器配置以下环境变量。模型地址使用 OpenAI 兼容 API 根路径，例如 `https://api.example.com/v1`。在本机联调时可以为三个模型前缀使用同一套服务配置。

| 服务 | 环境变量 |
| --- | --- |
| 全部 | `AGENT_PLATFORM_TOKEN`，使用同一个自生成的高熵值 |
| 端侧与三个专家 | `AGENT_REGISTRY_URL`，本机值为 `http://127.0.0.1:8310` |
| 端侧 | `AGENT_ALLOWED_ORIGINS`，本机值为 `http://127.0.0.1:8311,http://127.0.0.1:8312,http://127.0.0.1:8313` |
| ZeroClaw | `EDGE_MODEL_URL`、`EDGE_MODEL`、`EDGE_MODEL_API_KEY` |
| dsh | `DSH_MODEL_URL`、`DSH_MODEL`、`DSH_MODEL_API_KEY` |
| AgentScope | `AGENTSCOPE_MODEL_URL`、`AGENTSCOPE_MODEL`、`AGENTSCOPE_MODEL_API_KEY` |
| 可执行文件路径 | 可通过 `ZEROCLAW_BIN`、`CODEX_BIN`、`DSH_BIN` 指定 |

在不同终端中先启动目录，再启动三个专家和工作台。将 `./workspace` 换成你授权给端侧执行器的现有目录。

```sh
uv run python -m edge_agents registry
uv run python -m edge_agents worker codex --port 8311 --public-url http://127.0.0.1:8311/a2a
uv run python -m edge_agents worker dsh --port 8312 --public-url http://127.0.0.1:8312/a2a
uv run --extra agentscope python -m edge_agents worker agentscope --port 8313 --public-url http://127.0.0.1:8313/a2a
uv run python -m edge_agents edge --workspace ./workspace
```

打开 <http://127.0.0.1:8300>。端侧进程单独运行 ZeroClaw，默认网关端口为 8301。端侧调用和目录查询使用 Bearer Token，跨主机部署时为目录与专家设置 HTTPS 入口，把实际 A2A 地址填入 `--public-url`，并把对应源站加入端侧的 `AGENT_ALLOWED_ORIGINS`。Codex 适配器沿用 CLI 配置和登录。模型密钥通过进程环境传递。

#### 验证

- 在端侧已启动时启动专家。提交包含边界条件缺陷的代码，检查发现、委托和结果。强制停止专家后，它会在租约到期后从列表消失。
- 在授权目录里放入 UTF-8 的 `.txt` 或 `.md` 文件。选择「按计划在本地执行」，输入源目录和一个新的 Markdown 报告路径。报告所在父目录需已存在。源文件内容只由端侧读取。
- 自动化检查使用 `uv run pytest`。性能测量需要目录、AgentScope 和模型服务已就绪。从与端侧相同的环境运行下方命令。脚本启动独立的端侧进程 30 次，记录入口与网关会话就绪时间，最后一次启动后执行同一个文件统计任务并采样进程树的峰值内存。macOS 报告 RSS，Windows 报告工作集。各平台独立记录结果。

```sh
uv run python -m edge_agents.benchmark --output benchmark-local.json
```

#### 性能基线

| 平台 | 冷启动次数 | 冷启动 P50 / P95 | 就绪内存 P50 | 标准任务峰值内存 |
| --- | ---: | --- | ---: | ---: |
| macOS 26.6.2，Apple Silicon，10 逻辑核，16 GiB | 30 | 653.94 / 716.62 ms | 132.52 MiB RSS | 139.91 MiB RSS |
| Windows x64 | 待实测 | — | — | — |

macOS 测量使用 Python 3.12.13 和 ZeroClaw 0.8.7，标准任务通过远端 AgentScope 获取计划并在本地生成文件报告。
