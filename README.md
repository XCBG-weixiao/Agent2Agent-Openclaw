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

## 运行指南

**一台机器联调**时，注册目录、三个专家、端侧工作台和 ZeroClaw 都在本机运行。需要分开部署时，可在 Mac 或服务器上运行目录和专家，在 macOS 或 Windows 上只启动端侧。完整链路已在 macOS Apple Silicon 上验证。Windows x64 以下使用原生 PowerShell，整套联调和性能基线待实测。

### 1. macOS 安装

在终端中用 [Homebrew](https://brew.sh/) 安装 Git 和 uv。下载与当前架构匹配的 ZeroClaw 0.8.7，并解压到仓库的本机目录。

```sh
brew install git uv
git clone --branch codex/edge-agent https://github.com/XCBG-weixiao/Agent2Agent-Openclaw.git
cd Agent2Agent-Openclaw
uv python install 3.12

mkdir -p .edge-state/bin .edge-state/demo-workspace
archive="zeroclaw-$(uname -m)-apple-darwin.tar.gz"
curl -fL "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.7/$archive" -o ".edge-state/$archive"
tar -xzf ".edge-state/$archive" -C .edge-state/bin
.edge-state/bin/zeroclaw --version

printf 'alpha\nbeta\n' > .edge-state/demo-workspace/sample.txt
```

在这台 Mac 上运行专家时，再安装 Node.js 24.9 或更高版本、Codex CLI 和 dsh。已有 Codex CLI 和登录可以直接复用。

```sh
brew install node@24
export PATH="$(brew --prefix node@24)/bin:$PATH"
node --version
npm install -g @deepseek-ai/dsh@0.2.2-rc.1
dsh --profile headless --help

# 仅首次安装 Codex CLI 时执行
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

新终端中也要能找到 Node、dsh 和 Codex。若 Node 由上面的 `node@24` 提供，把对应的 `export PATH=…` 加到 shell 配置，或在启动 dsh 的终端再执行一次。首次使用 Codex 时运行 `codex login`，用 `codex login status` 检查登录。 [Codex CLI 安装与登录](https://learn.chatgpt.com/docs/codex/cli)

### 2. Windows x64 安装

在 PowerShell 中安装 Git 和 uv。安装后打开一个新的 PowerShell，再下载项目和 ZeroClaw。

```powershell
winget install --exact --id Git.Git
winget install --exact --id astral-sh.uv
```

```powershell
git clone --branch codex/edge-agent https://github.com/XCBG-weixiao/Agent2Agent-Openclaw.git
Set-Location Agent2Agent-Openclaw
uv python install 3.12

New-Item -ItemType Directory -Force .edge-state/bin, .edge-state/demo-workspace | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.7/zeroclaw-x86_64-pc-windows-msvc.zip' -OutFile .edge-state/zeroclaw.zip
Expand-Archive -Path .edge-state/zeroclaw.zip -DestinationPath .edge-state/bin -Force
& ./.edge-state/bin/zeroclaw.exe --version

@('alpha', 'beta') | Set-Content -Encoding ascii .edge-state/demo-workspace/sample.txt
```

在 Windows 同机联调时，先从 [Node.js 官网](https://nodejs.org/en/download) 安装 Node.js 24.9 或更高版本，并从 [Codex 官方 Windows 安装说明](https://learn.chatgpt.com/docs/enterprise/windows-deployment#choose-an-installation-method) 安装原生 CLI。重新打开 PowerShell，确认 Codex 和 dsh 可用。只运行 Windows 端侧时，在专家所在机器上安装这些工具即可。

```powershell
node --version
npm.cmd install -g @deepseek-ai/dsh@0.2.2-rc.1
dsh.cmd --profile headless --help
codex login
codex login status
```

### 3. 安装 Python 依赖并配置模型

在仓库根目录运行。macOS 和 Windows 使用相同命令。

```sh
# 同机运行全部服务，或在专家主机上安装
uv sync --frozen --all-extras

# 只运行端侧时，用这条代替上一条
uv sync --frozen --no-dev
```

用以下命令生成一个注册平台令牌。目录、专家和端侧使用同一个值。

```sh
uv run --no-sync python -c "import secrets; print(secrets.token_urlsafe(32))"
```

在仓库根目录创建名为 `.env` 的 UTF-8 文件，填入下面的内容并替换占位值。macOS 可以用任意文本编辑器，Windows 可用 `notepad .env`。确认文件名为 `.env`。Git 已忽略这个文件，密钥放在这里或运行环境中。

```dotenv
AGENT_PLATFORM_TOKEN=替换为上一步生成的值
AGENT_REGISTRY_URL=http://127.0.0.1:8310
AGENT_ALLOWED_ORIGINS=http://127.0.0.1:8311,http://127.0.0.1:8312,http://127.0.0.1:8313

# macOS 用此路径，Windows 在文件名末尾加 .exe
ZEROCLAW_BIN=.edge-state/bin/zeroclaw

EDGE_MODEL_URL=https://api.example.com/v1
EDGE_MODEL=替换为模型ID
EDGE_MODEL_API_KEY=替换为密钥

DSH_MODEL_URL=https://api.example.com/v1
DSH_MODEL=替换为模型ID
DSH_MODEL_API_KEY=替换为密钥

AGENTSCOPE_MODEL_URL=https://api.example.com/v1
AGENTSCOPE_MODEL=替换为模型ID
AGENTSCOPE_MODEL_API_KEY=替换为密钥
```

- 模型地址填服务的 OpenAI 兼容 API 根路径。若已有 dsh 模型配置，可以把同一套 URL、API 密钥和模型 ID 分别填到 `EDGE_`、`DSH_`、`AGENTSCOPE_` 三组。项目的 dsh 适配器通过这些变量配置 headless 进程。ZeroClaw 的模型需要支持工具调用。
- Codex 使用当前用户已有的 CLI 配置和登录。若终端找不到可执行文件，可在 `.env` 里设置 `CODEX_BIN`、`DSH_BIN` 或 `ZEROCLAW_BIN`。手动指定 Codex 或 dsh 时使用绝对路径。有空格的路径可用双引号包住。Windows 路径建议在 `.env` 中使用正斜杠。
- 只运行端侧时，填写 `AGENT_PLATFORM_TOKEN`、`AGENT_REGISTRY_URL`、`AGENT_ALLOWED_ORIGINS`、`ZEROCLAW_BIN` 和三项 `EDGE_MODEL_*`。目录进程只需要平台令牌。专家进程还需要目录地址，dsh 和 AgentScope 各需要自己的三项模型变量。

### 4. 启动服务

同机联调时打开五个终端标签页，每个都进入仓库根目录。**先运行第 1 条**，等目录开始监听，再分别运行其余四条。每条命令占用一个终端，macOS 和 Windows 均可使用。

| 终端 | 服务 | 命令 |
| --- | --- | --- |
| 1 | 注册目录，端口 8310 | `uv run --no-sync --env-file .env python -m edge_agents registry` |
| 2 | Codex，端口 8311 | `uv run --no-sync --env-file .env python -m edge_agents worker codex --port 8311 --public-url http://127.0.0.1:8311/a2a` |
| 3 | dsh，端口 8312 | `uv run --no-sync --env-file .env python -m edge_agents worker dsh --port 8312 --public-url http://127.0.0.1:8312/a2a` |
| 4 | AgentScope，端口 8313 | `uv run --no-sync --env-file .env python -m edge_agents worker agentscope --port 8313 --public-url http://127.0.0.1:8313/a2a` |
| 5 | 端侧工作台，端口 8300；ZeroClaw 网关，端口 8301 | `uv run --no-sync --env-file .env python -m edge_agents edge --workspace .edge-state/demo-workspace` |

打开 [本地工作台](http://127.0.0.1:8300/)。左侧列出会话，中间可以连续向 ZeroClaw 提问，右侧任务面板显示当前轮的目标、专家任务、执行阶段和工具结果。窄屏上用右上角按钮打开任务面板。会话记录保存在当前浏览器，ZeroClaw 的上下文默认保存在本机的 `.edge-state/gateway-8301/`。也可以用下面的命令检查就绪状态和在线专家。在 Windows PowerShell 上将 `curl` 写作 `curl.exe`。

```sh
curl -fsS http://127.0.0.1:8300/api/ready
curl -fsS http://127.0.0.1:8300/api/agents
```

就绪接口应返回 `{"ready":true}`。在线列表应包含 `codex`、`dsh`、`agentscope`。停止时，在各服务终端按 `Ctrl+C`。停止端侧进程也会停止它启动的 ZeroClaw 网关。专家停机后，目录最长约 15 秒移除其注册记录。

### 5. 端侧与专家分开部署

例如，在另一台 Mac 或服务器运行目录和专家，在 Windows 原生 PowerShell 启动工作台。

1. 在专家主机执行第 3 步的全量依赖安装，并安装已登录的 Codex CLI 和 dsh。为目录与各专家配置端侧可访问的 HTTPS 入口，分别转发到它们实际监听的端口。
2. 在专家主机运行第 4 步中的前四个服务。各专家的 `AGENT_REGISTRY_URL` 指向可达的目录地址，`--public-url` 改为端侧可达的完整 A2A URL，例如 `https://codex.example.com/a2a`。目录和专家使用同一个平台令牌。
3. 在端侧配置文件里，将 `AGENT_REGISTRY_URL` 改为目录 HTTPS 地址，将 `AGENT_ALLOWED_ORIGINS` 改为专家的 HTTPS 源站，用逗号分隔，例如 `https://codex.example.com,https://dsh.example.com,https://agentscope.example.com`。源站填写协议、主机和可选端口。
4. 在端侧只运行第 4 步的第 5 条命令。工作台、ZeroClaw 和文件执行器在端侧运行，目录与专家通过网络访问。

### 6. 验证两条任务链路

**获取远端结果**。在输入框左下角选择「对话」，提交下面的示例，然后在右侧任务面板查看发现、委托和返回结果。三个专家在线时，可核对 Codex 的初审、dsh 的复审以及 AgentScope 的测试建议。

```text
请让 Codex 和 dsh 分别检查空输入，再让 AgentScope 设计测试。

def first(items):
    return items[0]
```

**按计划在本地执行**。在输入框左下角选择「本地执行」。源目录填 `.`，新报告路径填 `file-summary.md`。使用前面的示例工作目录时，报告会写入 `.edge-state/demo-workspace/file-summary.md`，其中 `sample.txt` 应统计为 2 行。再次执行请换一个报告名。用 `../outside.md` 作为报告路径应得到拒绝。

### 7. 排错与性能测量

| 现象 | 检查 |
| --- | --- |
| `uv` 或专家 CLI 找不到 | 安装后打开新终端，检查 PATH。已知可执行文件路径时可设置相应的 `*_BIN`。 |
| 端侧未就绪 | 检查端侧终端的启动日志，确认 `ZEROCLAW_BIN` 指向 0.8.7，并确认 8300 和 8301 可用。端侧可通过 `--port` 和 `--gateway-port` 指定端口。 |
| 专家列表为空 | 确认目录和专家都已启动、平台令牌相同，并核对注册卡的 `--public-url` 与端侧允许的源站。 |
| 委托或模型调用失败 | 检查对应终端的日志和模型配置。Codex 可用 `codex login status` 验证登录，dsh 和 AgentScope 要填对模型 ID、根路径和密钥。 |
| 本地报告写入失败 | 路径以 `--workspace` 指定的目录为根，使用相对路径和正斜杠。确认父目录已存在，报告文件名可用。 |

全量依赖安装后，运行测试和性能测量。性能测量需要目录、AgentScope 和模型服务在线，默认另用 8400 和 8401，测量当前平台的端侧进程树。脚本做 30 次进程冷启动，最后一次启动后执行文件统计任务。macOS 记录 RSS，Windows 记录工作集。

```sh
uv run --no-sync pytest
uv run --no-sync --env-file .env python -m edge_agents.benchmark --output benchmark-local.json
```

#### 性能基线

| 平台 | 冷启动次数 | 冷启动 P50 / P95 | 就绪内存 P50 | 标准任务峰值内存 |
| --- | ---: | --- | ---: | ---: |
| macOS 26.6.2，Apple Silicon，10 逻辑核，16 GiB | 30 | 653.94 / 716.62 ms | 132.52 MiB RSS | 139.91 MiB RSS |
| Windows x64 | 待实测 | — | — | — |

macOS 测量使用 Python 3.12.13 和 ZeroClaw 0.8.7，标准任务通过远端 AgentScope 获取计划并在本地生成文件报告。
