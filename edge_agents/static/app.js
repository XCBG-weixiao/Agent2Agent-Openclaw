const byId = (id) => document.getElementById(id);
const mode = byId("mode");
const request = byId("request");
const source = byId("source");
const report = byId("report");
const conversation = byId("conversation");
const transcript = byId("transcript");
const storageKey = "relay-workbench-chats";
const selectionKey = "relay-workbench-selected";
const labels = {
  "general-assistance": "通用协作",
  "code-review": "代码审查",
  "test-design": "测试设计",
  "local-file-plan": "本地文件计划",
};
const toolNames = {
  edge__discover_agents: "发现在线专家",
  edge__delegate_task: "委托专家任务",
};

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function icon(name, className) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "#i-" + name);
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  svg.append(use);
  return svg;
}

function loadChats() {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

const chats = loadChats();
let selected = chats[0] || null;
try {
  const saved = localStorage.getItem(selectionKey);
  if (saved !== null) selected = chats.find((chat) => chat.id === saved) || null;
} catch {
  // The conversation still works when browser storage is disabled.
}
let running = null;
let onlineAgents = [];
let directoryState = "checking";
for (const chat of chats) {
  for (const turn of chat.turns) {
    if (turn.state === "running") finish(turn, "error", "此轮连接已断开。");
  }
}

function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(chats));
    localStorage.setItem(selectionKey, selected?.id || "");
  } catch {
    byId("compose-footnote").textContent = "浏览器存储不可用，当前会话仍可继续。";
  }
}

const historyDrawer = matchMedia("(max-width: 599px)");
const inspectorDrawer = matchMedia("(max-width: 850px)");
let historyOpen = true;
let inspectorOpen = false;

function syncPanels() {
  const showInspectorDrawer = inspectorDrawer.matches && inspectorOpen;
  const panel = showInspectorDrawer ? "inspector" : historyDrawer.matches && historyOpen ? "history" : "";
  document.body.dataset.history = historyOpen ? "open" : "closed";
  document.body.dataset.panel = panel;
  byId("close-panel").hidden = !panel;
  byId("show-history").setAttribute("aria-expanded", historyOpen);
  byId("show-inspector").setAttribute("aria-expanded", showInspectorDrawer);
}

function closeDrawer() {
  if (document.body.dataset.panel === "history") historyOpen = false;
  inspectorOpen = false;
  syncPanels();
}

function focusConversation() {
  if (historyDrawer.matches) historyOpen = false;
  inspectorOpen = false;
  syncPanels();
}

byId("show-history").addEventListener("click", () => {
  inspectorOpen = false;
  historyOpen = !historyOpen;
  syncPanels();
});
byId("show-inspector").addEventListener("click", () => {
  inspectorOpen = !inspectorOpen;
  if (inspectorOpen && historyDrawer.matches) historyOpen = false;
  syncPanels();
});
byId("close-panel").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});
historyDrawer.addEventListener("change", () => {
  if (historyDrawer.matches && inspectorOpen) historyOpen = false;
  syncPanels();
});
inspectorDrawer.addEventListener("change", () => {
  inspectorOpen = false;
  syncPanels();
});
syncPanels();

function currentTurn() {
  return selected?.turns.at(-1);
}

function renderHistory() {
  const history = byId("history");
  history.replaceChildren();
  byId("chat-title").textContent = selected?.title || "新会话";
  if (!chats.length) {
    history.append(node("p", "panel-empty", "还没有会话"));
    return;
  }
  for (const chat of chats) {
    const button = node("button");
    button.type = "button";
    button.title = chat.title;
    if (chat === selected) button.setAttribute("aria-current", "true");
    button.append(icon("chat"), node("span", "", chat.title));
    button.addEventListener("click", () => {
      selected = chat;
      save();
      focusConversation();
      renderChat(true);
    });
    history.append(button);
  }
}

byId("new-chat").addEventListener("click", () => {
  selected = null;
  save();
  request.value = "";
  mode.value = "result";
  focusConversation();
  renderChat(true);
  request.focus();
});

function updateComposer() {
  const isPlan = mode.value === "plan";
  byId("local").hidden = !isPlan;
  request.hidden = isPlan;
  source.disabled = report.disabled = !isPlan;
  byId("shortcut").textContent = isPlan ? "工作区内的相对路径" : "Enter 发送 · Shift + Enter 换行";
  byId("compose-footnote").textContent = isPlan
    ? "文件由端侧读取和处理。远端只提供计划。"
    : "ZeroClaw 会按需调用已注册的专家。";
  byId("submit").disabled = Boolean(running) || !(isPlan
    ? source.value.trim() && report.value.trim()
    : request.value.trim());
  request.style.height = "auto";
  if (!isPlan) request.style.height = Math.min(request.scrollHeight, 180) + "px";
}

for (const input of [request, source, report]) input.addEventListener("input", updateComposer);
mode.addEventListener("change", updateComposer);
request.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!byId("submit").disabled) byId("task").requestSubmit();
  }
});

document.querySelectorAll("[data-suggestion]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.suggestion === "plan") {
      mode.value = "plan";
      updateComposer();
      source.focus();
    } else {
      mode.value = "result";
      request.value = "请为这个任务查找合适的在线 Agent，并汇总结果：\n\n";
      updateComposer();
      request.focus();
      request.setSelectionRange(request.value.length, request.value.length);
    }
  });
});

function inline(parent, text) {
  const tick = String.fromCharCode(96);
  const marks = new RegExp(tick + "([^" + tick + "\\n]+)" + tick + "|\\*\\*([^*\\n]+)\\*\\*", "g");
  let previous = 0;
  for (const match of text.matchAll(marks)) {
    parent.append(document.createTextNode(text.slice(previous, match.index)));
    parent.append(node(match[1] === undefined ? "strong" : "code", "", match[1] ?? match[2]));
    previous = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(previous)));
}

const fence = String.fromCharCode(96).repeat(3);
const listItem = /^(\s*)([-*]|\d+[.)])\s+(.*)$/;
const heading = /^(#{1,6})\s+(.*)$/;
const tableRule = /^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/;

function markdown(parent, text) {
  const lines = text.split("\n");
  for (let i = 0; i < lines.length;) {
    const line = lines[i++];
    if (!line.trim()) continue;
    if (line.startsWith(fence)) {
      const code = [];
      while (i < lines.length && !lines[i].startsWith(fence)) code.push(lines[i++]);
      if (i < lines.length) i++;
      const pre = node("pre");
      pre.append(node("code", "", code.join("\n")));
      parent.append(pre);
      continue;
    }
    const title = line.match(heading);
    if (title) {
      const block = node(title[1].length < 3 ? "h3" : "h4");
      inline(block, title[2]);
      parent.append(block);
      continue;
    }
    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      parent.append(node("hr"));
      continue;
    }
    if (line.includes("|") && tableRule.test(lines[i] || "")) {
      const table = node("table");
      const appendRow = (value, cellTag) => {
        const row = node("tr");
        for (const cell of value.trim().replace(/^\||\|$/g, "").split("|")) {
          const element = node(cellTag);
          inline(element, cell.trim().replaceAll("&#124;", "|"));
          row.append(element);
        }
        table.append(row);
      };
      appendRow(line, "th");
      i++;
      while (i < lines.length && lines[i].trimStart().startsWith("|")) appendRow(lines[i++], "td");
      parent.append(table);
      continue;
    }
    const item = line.match(listItem);
    if (item) {
      const ordered = /^\d/.test(item[2]);
      const list = node(ordered ? "ol" : "ul");
      let entry = item;
      while (entry) {
        const element = node("li");
        inline(element, entry[3]);
        list.append(element);
        entry = (lines[i] || "").match(listItem);
        if (!entry || /^\d/.test(entry[2]) !== ordered) break;
        i++;
      }
      parent.append(list);
      continue;
    }
    const paragraph = [line];
    while (i < lines.length && lines[i].trim() && !lines[i].startsWith(fence)
      && !heading.test(lines[i]) && !listItem.test(lines[i])
      && !tableRule.test(lines[i + 1] || "")) {
      paragraph.push(lines[i++]);
    }
    const block = node("p");
    inline(block, paragraph.join("\n"));
    parent.append(block);
  }
}

function nearBottom() {
  return conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 95;
}

function showAnswer(answer, turn) {
  answer.replaceChildren();
  if (turn.reportPath) {
    const path = node("div", "report-path");
    path.append(icon("file"), node("span", "", turn.reportPath));
    answer.append(path);
  }
  if (turn.text && turn.state === "running") answer.append(node("p", "", turn.text));
  else if (turn.text) markdown(answer, turn.text);
  if (turn.state === "error") answer.append(node("p", "failed", turn.error));
  else if (turn.state === "running" && !turn.text) {
    answer.append(node("p", "waiting", turn.localExecution ? "正在本地执行…" : "正在处理…"));
  }
}

function renderTranscript(jump = false) {
  const shouldScroll = jump || nearBottom();
  transcript.replaceChildren();
  const turns = selected?.turns || [];
  byId("empty-chat").hidden = turns.length > 0;
  transcript.hidden = turns.length === 0;
  for (const turn of turns) {
    const block = node("article", "turn");
    block.append(node("div", "user-message", turn.objective));
    const assistant = node("div", "assistant");
    const avatar = node("div", "assistant-avatar");
    avatar.append(icon("relay"));
    const content = node("div");
    const title = node("div", "assistant-title", "ZeroClaw");
    if (turn.mode === "plan") title.append(node("small", "", "本地执行"));
    const answer = node("div", "answer");
    showAnswer(answer, turn);
    content.append(title, answer);
    assistant.append(avatar, content);
    block.append(assistant);
    transcript.append(block);
  }
  if (shouldScroll) conversation.scrollTop = conversation.scrollHeight;
}

function updateAnswer(turn) {
  if (currentTurn() !== turn) return;
  const answer = transcript.lastElementChild?.querySelector(".answer");
  if (!answer) return;
  const shouldScroll = nearBottom();
  showAnswer(answer, turn);
  if (shouldScroll) conversation.scrollTop = conversation.scrollHeight;
}

function setBadge(element, text, tone) {
  element.textContent = text;
  element.dataset.tone = tone;
}

function badge(text, tone = "idle") {
  const element = node("span", "badge");
  setBadge(element, text, tone);
  return element;
}

function duration(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return seconds < 60 ? seconds + "s" : Math.floor(seconds / 60) + "m " + seconds % 60 + "s";
}

function updateElapsed() {
  const turn = currentTurn();
  byId("elapsed").textContent = turn ? duration((turn.ended || Date.now()) - turn.started) : "—";
}

function renderOverview(turn, delegates) {
  const failed = turn?.tools.some((tool) => tool.state === "error");
  const state = turn?.state || "idle";
  const titles = { idle: "待开始", running: "进行中", done: failed ? "完成 · 有失败" : "已完成", error: "失败" };
  setBadge(byId("run-state"), titles[state], state === "done" && failed ? "error" : state);
  byId("objective").textContent = turn?.objective || "发送消息后，这里会显示本轮任务。";
  byId("task-count").textContent = delegates.length
    ? delegates.filter((tool) => tool.state === "done").length + " / " + delegates.length + " 次委托完成"
    : "0 次委托";
  updateElapsed();

  const hasCalls = Boolean(turn?.tools.length);
  const pendingTools = turn?.tools.some((tool) => tool.state === "running");
  let toolsState = "idle";
  if (hasCalls) toolsState = pendingTools ? "running" : failed ? "error" : "done";
  const finishing = Boolean(turn?.localExecution || (turn?.mode === "result" && !pendingTools));
  const phases = [
    ["接收任务", turn ? "done" : "idle"],
    [state === "done" && !hasCalls ? "本轮无需委托" : "发现与委托", toolsState],
    [turn?.mode === "plan" ? "校验与本地执行" : "生成回复",
      state === "done" || state === "error" ? state : state === "running" && finishing ? "running" : "idle"],
  ];
  byId("phases").replaceChildren(...phases.map(([name, status]) => {
    const row = node("li");
    row.dataset.phase = status;
    row.append(node("span", "phase-dot"), node("span", "", name));
    return row;
  }));
}

function toolState(tool) {
  if (tool.state === "running") return ["运行中", "running"];
  if (tool.state === "error") return ["失败", "error"];
  return ["已返回", "done"];
}

function renderAgents(delegates) {
  const section = byId("agents");
  const byAgent = new Map(onlineAgents.map((agent) => [agent.id, agent]));
  const names = new Map(onlineAgents.map((agent) => [agent.id, agent.name]));
  for (const tool of delegates) {
    if (!names.has(tool.agentId)) names.set(tool.agentId, tool.agentName || tool.agentId);
  }
  byId("agent-count").textContent = directoryState === "online"
    ? onlineAgents.length + " 在线"
    : directoryState === "checking" ? "连接目录中" : "目录暂不可用";
  section.replaceChildren();
  if (!names.size) {
    section.append(node("p", "panel-empty", directoryState === "online" ? "暂无在线专家" : "等待目录连接"));
  }
  for (const [id, name] of names) {
    const agent = byAgent.get(id);
    const tasks = delegates.filter((tool) => tool.agentId === id);
    const active = tasks.some((tool) => tool.state === "running");
    const failure = tasks.some((tool) => tool.state === "error");
    const status = active ? ["进行中", "running"] : failure ? ["有失败", "error"] : tasks.length
      ? ["已完成", "done"] : [agent ? "空闲" : "离线", "idle"];
    const card = node("div", "agent");
    const header = node("div", "agent-header");
    const dot = node("span", "agent-dot");
    dot.dataset.online = Boolean(agent);
    dot.title = agent ? "在线" : "离线";
    header.append(dot, node("span", "agent-name", name), badge(...status));
    card.append(header);
    if (agent) {
      card.append(node("small", "agent-description", agent.skills.map((skill) => labels[skill.id] || skill.id).join(" · ")));
    }
    for (const tool of tasks) {
      const row = node("div", "agent-task");
      row.append(node("span", "task-label", labels[tool.skillId] || tool.skillId || "委托任务"));
      if (tool.objective) row.append(node("small", "", tool.objective));
      const detail = node("small", "", tool.output?.error || tool.error
        || tool.output?.task_id || tool.output?.message_id || "等待远端返回");
      detail.dataset.tone = tool.state;
      row.append(detail);
      card.append(row);
    }
    section.append(card);
  }
}

function renderTools(turn) {
  const section = byId("tools");
  const open = new Set(Array.from(section.querySelectorAll("[open]"), (entry) => entry.dataset.key));
  const tools = turn?.tools || [];
  byId("tool-count").textContent = tools.length + " 次";
  section.replaceChildren();
  if (!tools.length) section.append(node("p", "panel-empty", "本轮调用的工具会显示在这里。"));
  for (const tool of tools) {
    const entry = node("details", "tool-entry");
    entry.dataset.key = tool.key;
    entry.open = open.has(tool.key);
    const header = node("summary");
    const title = toolNames[tool.name] || tool.name;
    header.append(icon("chevron", "chevron"), icon("tool"), node("span", "tool-title",
      tool.agentId ? title + " · " + (tool.agentName || tool.agentId) : title), badge(...toolState(tool)));
    const meta = [tool.name];
    if (tool.output?.transport) meta.push(tool.output.transport);
    if (tool.started) meta.push(new Date(tool.started).toLocaleTimeString("zh-CN", { hour12: false }));
    if (tool.started && tool.ended) meta.push(duration(tool.ended - tool.started));
    const detail = tool.output?.answer || tool.output?.error || tool.error
      || (tool.output ? JSON.stringify(tool.output.plan || tool.output, null, 2) : tool.objective)
      || "等待工具返回…";
    entry.append(header, node("p", "tool-meta", meta.join(" · ")), node("pre", "tool-detail", detail));
    section.append(entry);
  }
}

function renderInspector() {
  const turn = currentTurn();
  const delegates = (turn?.tools || []).filter((tool) => tool.name === "edge__delegate_task" && tool.agentId);
  renderOverview(turn, delegates);
  renderAgents(delegates);
  renderTools(turn);
}

function renderChat(jump = false) {
  renderHistory();
  renderTranscript(jump);
  renderInspector();
  updateComposer();
}

async function refreshAgents() {
  try {
    const response = await fetch("/api/agents");
    if (!response.ok) throw new Error();
    onlineAgents = await response.json();
    directoryState = "online";
  } catch {
    onlineAgents = [];
    directoryState = "offline";
  }
  renderInspector();
}

async function refreshConnection() {
  let ready = false;
  try {
    ready = (await fetch("/api/connection", { signal: AbortSignal.timeout(4500) })).ok;
  } catch {
    // The next poll reflects a restart or reconnect.
  }
  byId("connection").dataset.state = ready ? "online" : "offline";
  byId("connection-text").textContent = ready ? "ZeroClaw 已连接" : "ZeroClaw 未连接";
}

function finish(turn, state, message) {
  turn.state = state;
  turn.ended = Date.now();
  if (message) turn.error = message;
  for (const tool of turn.tools) {
    if (tool.state === "running") {
      tool.state = "error";
      tool.ended = turn.ended;
      tool.error = "本轮结束前未收到工具结果。";
    }
  }
}

function accept(turn, event) {
  if (event.type === "delta") {
    turn.text += event.text;
    updateAnswer(turn);
    return;
  }
  if (event.type === "tool_call" || event.type === "tool_result") {
    const found = event.id ? turn.tools.find((tool) => tool.id === event.id)
      : turn.tools.findLast((tool) => tool.name === event.name && tool.state === "running");
    const output = event.output;
    const id = event.agent_id || output?.agent_id;
    const tool = found || {
      key: event.id || event.name + "-" + turn.tools.length,
      id: event.id, name: event.name, agentId: id,
      agentName: onlineAgents.find((agent) => agent.id === id)?.name,
      skillId: event.skill_id || output?.skill_id, objective: event.objective,
      started: event.type === "tool_call" ? Date.now() : null, state: "running",
    };
    if (!found) turn.tools.push(tool);
    if (event.type === "tool_result") {
      tool.output = output;
      tool.ended = Date.now();
      tool.state = output?.error ? "error" : "done";
    }
  } else if (event.type === "plan_validated") {
    turn.localExecution = true;
    updateAnswer(turn);
  } else if (event.type === "done") {
    turn.text = event.text;
    turn.reportPath = event.report_path;
    finish(turn, "done");
    updateAnswer(turn);
  } else if (event.type === "error") {
    finish(turn, "error", event.message);
    updateAnswer(turn);
  }
  save();
  if (currentTurn() === turn) renderInspector();
}

async function receive(response, turn) {
  if (!response.ok) {
    const detail = (await response.json()).detail;
    throw new Error(typeof detail === "string" ? detail : "请检查任务输入。");
  }
  let pending = "";
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    pending += chunk;
    const lines = pending.split("\n");
    pending = lines.pop();
    for (const line of lines) if (line) accept(turn, JSON.parse(line));
  }
  if (turn.state === "running") throw new Error("任务连接已断开。");
}

byId("task").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (running) return;
  const isPlan = mode.value === "plan";
  const payload = isPlan
    ? { mode: "plan", source: source.value.trim(), report: report.value.trim() }
    : { mode: "result", task: request.value.trim() };
  if (isPlan ? !payload.source || !payload.report : !payload.task) return;
  if (!selected) {
    selected = {
      id: crypto.randomUUID(),
      title: isPlan ? "生成本地文件报告" : payload.task.replace(/\s+/g, " ").slice(0, 34),
      turns: [],
    };
    chats.unshift(selected);
    if (chats.length > 25) chats.pop();
  }
  const turn = {
    mode: payload.mode, text: "", tools: [], state: "running", started: Date.now(),
    objective: isPlan ? "统计「" + payload.source + "」中的文件，生成「" + payload.report + "」。" : payload.task,
  };
  payload.session_id = selected.id;
  selected.turns.push(turn);
  running = turn;
  if (!isPlan) request.value = "";
  save();
  renderChat(true);
  try {
    const response = await fetch("/api/runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    await receive(response, turn);
  } catch (error) {
    accept(turn, { type: "error", message: error.message });
  } finally {
    running = null;
    updateComposer();
  }
});

renderChat(true);
refreshConnection();
refreshAgents();
setInterval(refreshConnection, 5000);
setInterval(refreshAgents, 5000);
setInterval(updateElapsed, 1000);
