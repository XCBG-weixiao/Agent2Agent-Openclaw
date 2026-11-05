const byId = (id) => document.getElementById(id);
const mode = byId("mode");
mode.addEventListener("change", () => {
  byId("direct").hidden = mode.value === "plan";
  byId("local").hidden = mode.value !== "plan";
});

function item(list, text) {
  const node = document.createElement("li");
  node.textContent = text;
  list.append(node);
}

async function refreshAgents() {
  const list = byId("agents");
  try {
    const response = await fetch("/api/agents");
    if (!response.ok) throw new Error("目录暂不可用。");
    const agents = await response.json();
    list.replaceChildren();
    for (const agent of agents) {
      item(list, agent.name + " · " + agent.skills.map((s) => s.id).join(" / "));
    }
    if (!agents.length) item(list, "当前没有在线专家。");
  } catch (error) {
    list.replaceChildren();
    item(list, error.message);
  }
}

function render(event) {
  const list = byId("events");
  if (event.type === "tool_call") {
    item(list, event.agent_id ? `委托 ${event.agent_id} · ${event.skill_id}` : "查询在线专家");
  } else if (event.type === "tool_result") {
    const data = event.output;
    if (data.error) item(list, data.error);
    else if (data.agents) item(list, "发现 " + (data.agents.map((a) => a.name).join("、") || "0 位专家"));
    else if (data.plan) item(list, `${data.agent_id} 返回计划\n${JSON.stringify(data.plan, null, 2)}`);
    else item(list, `${data.agent_id} 返回结果 · ${data.task_id}\n${data.answer}`);
  } else if (event.type === "plan_validated") {
    item(list, "端侧已校验计划并完成执行。");
  } else if (event.type === "error") {
    item(list, "任务失败：" + event.message);
  } else if (event.type === "done") {
    const output = byId("output");
    output.hidden = false;
    output.textContent = (event.report_path ? `报告路径 ${event.report_path}\n\n` : "") + event.text;
  }
}

byId("task").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("events").replaceChildren();
  byId("output").hidden = true;
  byId("submit").disabled = true;
  const payload = mode.value === "plan"
    ? {mode: "plan", source: byId("source").value, report: byId("report").value}
    : {mode: "result", task: byId("request").value.trim()};
  try {
    const response = await fetch("/api/runs", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const detail = (await response.json()).detail;
      throw new Error(typeof detail === "string" ? detail : "请检查任务输入。");
    }
    let pending = "";
    let finished = false;
    for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
      pending += chunk;
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines) {
        const frame = JSON.parse(line);
        render(frame);
        if (frame.type === "done" || frame.type === "error") finished = true;
      }
    }
    if (!finished) throw new Error("任务连接已断开。");
  } catch (error) {
    render({type: "error", message: error.message});
  } finally {
    byId("submit").disabled = false;
  }
});

refreshAgents();
setInterval(refreshAgents, 5000);
