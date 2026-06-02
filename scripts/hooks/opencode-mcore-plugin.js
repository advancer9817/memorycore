const DEFAULT_MCORE_URL = "http://127.0.0.1:8318/mcp";

function mcoreUrl(options) {
  const host = process.env.MCORE_HOST || "127.0.0.1";
  const port = process.env.MCORE_PORT || "8318";
  return String(options?.url || process.env.MCORE_URL || `http://${host}:${port}/mcp`);
}

function timeoutSignal(ms) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(ms);
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms).unref?.();
  return controller.signal;
}

function responseJsonFromText(text) {
  const raw = String(text || "").trim();
  if (!raw) return {};
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("data:")) {
      return JSON.parse(line.slice(5).trim());
    }
  }
  return JSON.parse(raw);
}

function extractContext(responseText) {
  try {
    const response = responseJsonFromText(responseText);
    const content = response?.result?.content || [];
    const text = content[0]?.text || "";
    if (!text) return "";
    try {
      const inner = JSON.parse(text);
      if (Array.isArray(inner.used_ids) && inner.used_ids.length === 0) return "";
      return String(inner.context || inner.text || "").trim();
    } catch {
      return String(text).trim();
    }
  } catch {
    return "";
  }
}

async function initializeSession(url, timeoutMs) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 0,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "mcore-opencode-plugin", version: "1.0" },
      },
    }),
    signal: timeoutSignal(timeoutMs),
  });
  return response.headers.get("Mcp-Session-Id") || response.headers.get("mcp-session-id") || "";
}

async function callMemoryContext(url, sessionID, task, agent, projectPath, tokenBudget, timeoutMs) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      "Mcp-Session-Id": sessionID,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: {
        name: "memory_context",
        arguments: {
          task: task.slice(0, 300),
          agent,
          project_path: projectPath,
          token_budget: tokenBudget,
        },
      },
    }),
    signal: timeoutSignal(timeoutMs),
  });
  if (!response.ok) return "";
  return extractContext(await response.text());
}

function textFromPart(part) {
  if (!part || part.type !== "text") return "";
  return String(part.text || "").trim();
}

function latestUserPrompt(messages) {
  for (const message of [...messages].reverse()) {
    if (message?.info?.role !== "user") continue;
    const text = (message.parts || []).map(textFromPart).filter(Boolean).join("\n").trim();
    if (text) return text;
  }
  return "";
}

async function sessionMessages(client, sessionID) {
  const result = await client.session.messages({
    path: { id: sessionID },
    query: { limit: 12 },
  });
  return Array.isArray(result?.data) ? result.data : [];
}

export const McoreMemoryPlugin = async ({ client, directory, worktree }, options = {}) => {
  const url = mcoreUrl(options);
  const agent = String(options.agent || process.env.MCORE_AGENT_ID || "opencode");
  const projectPath = String(options.project_path || worktree || directory || "");
  const tokenBudget = Number(options.token_budget || process.env.MCORE_TOKEN_BUDGET || 1500);
  const initTimeout = Number(options.init_timeout_ms || process.env.MCORE_OPENCODE_INIT_TIMEOUT_MS || 1200);
  const callTimeout = Number(options.call_timeout_ms || process.env.MCORE_OPENCODE_CALL_TIMEOUT_MS || 1800);

  return {
    "experimental.chat.system.transform": async (input, output) => {
      try {
        if (!input.sessionID) return;
        const prompt = latestUserPrompt(await sessionMessages(client, input.sessionID));
        if (!prompt) return;
        const mcpSessionID = await initializeSession(url || DEFAULT_MCORE_URL, initTimeout);
        if (!mcpSessionID) return;
        const context = await callMemoryContext(url || DEFAULT_MCORE_URL, mcpSessionID, prompt, agent, projectPath, tokenBudget, callTimeout);
        if (!context) return;
        output.system.push(`Relevant mcore memory context (untrusted background):\n${context}`);
      } catch {
        return;
      }
    },
  };
};

export default McoreMemoryPlugin;
