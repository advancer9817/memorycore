#!/usr/bin/env node
/**
 * mcore-client — MemoryCore 本地接入边车（Local Sidecar / Transparent Ingress）
 *
 * 设计依据：docs/mcore-client-detailed-design.md（迭代 253/254）
 *
 * 职责边界：
 *   - 向上：在 127.0.0.1:<port> 模拟 mcore 服务端，冻结所有本地 Agent 的端点配置
 *   - 向下：统一代理至 client.yaml 配置的上游服务端，透明注入租户凭据
 *   - 内置：五生态 Hook 引擎（claude/hermes/gemini/opencode/codex）+ WAL 离线队列
 *
 * 零第三方依赖（纯 Node 标准库）。Node >= 18。
 */
'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');

const VERSION = '1.0.0';
const HOME = os.homedir();
const MCORE_DIR = process.env.MCORE_CLIENT_HOME || path.join(HOME, '.mcore');
const CONFIG_PATH = path.join(MCORE_DIR, 'client.yaml');
const PID_PATH = path.join(MCORE_DIR, 'mcore-client.pid');
const LOG_PATH = path.join(MCORE_DIR, 'mcore-client.log');
const CACHE_PATH = path.join(MCORE_DIR, 'cache.json');
const QUEUE_DIR = path.join(MCORE_DIR, 'queue');
const BIN_DIR = path.join(MCORE_DIR, 'bin');
const BACKUP_DIR = path.join(MCORE_DIR, 'backups');

const STATUS_URL = 'http://127.0.0.1:__PORT__/_admin/stats';

// ═══════════════════════════════════════════════════════════════════
// 通用工具
// ═══════════════════════════════════════════════════════════════════

function ensureDir(p, mode) {
  try { fs.mkdirSync(p, { recursive: true, mode: mode || 0o700 }); } catch (_) {}
}

function readJSONFile(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return fallback; }
}

function writeJSONFile(p, obj) {
  const tmp = p + '.tmp-' + process.pid;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2), 'utf8');
  fs.renameSync(tmp, p);
}

function sha256(s) {
  return crypto.createHash('sha256').update(String(s), 'utf8').digest('hex');
}

function redact(key) {
  if (!key) return '';
  const s = String(key);
  if (s.length <= 8) return '[REDACTED]';
  return s.slice(0, 4) + '…' + s.slice(-4) + ' [REDACTED]';
}

function nowIso() { return new Date().toISOString(); }

// ── 日志（单行 JSON，凭据与 prompt 全文永不落盘） ──────────────────
let LOG_FH = null;

function logRotate() {
  try {
    const st = fs.statSync(LOG_PATH);
    if (st.size > 5 * 1024 * 1024) {
      const tail = fs.readFileSync(LOG_PATH, 'utf8').slice(-2 * 1024 * 1024);
      fs.writeFileSync(LOG_PATH, tail, 'utf8');
    }
  } catch (_) {}
}

function log(level, mod, msg, extra) {
  const rec = { ts: nowIso(), level, mod, msg };
  if (extra && typeof extra === 'object') Object.assign(rec, extra);
  const line = JSON.stringify(rec);
  if (level === 'ERROR') process.stderr.write(line + '\n');
  try {
    if (!LOG_FH) { ensureDir(MCORE_DIR); logRotate(); LOG_FH = fs.createWriteStream(LOG_PATH, { flags: 'a' }); }
    LOG_FH.write(line + '\n');
  } catch (_) {}
}

const L = {
  info: (m, x) => log('INFO', m, x && x.msg ? x.msg : '', x),
  warn: (m, x) => log('WARN', m, x && x.msg ? x.msg : '', x),
  error: (m, x) => log('ERROR', m, x && x.msg ? x.msg : '', x),
};

// ═══════════════════════════════════════════════════════════════════
// YAML 受限子集解析 / 序列化（无第三方依赖）
// 支持：注释、两级以上缩进嵌套、标量（字符串/数字/布尔）
// ═══════════════════════════════════════════════════════════════════

function coerceScalar(v) {
  let s = String(v).trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s === 'null' || s === '~') return null;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d*\.\d+$/.test(s)) return parseFloat(s);
  return s;
}

function parseYamlSubset(text) {
  const root = {};
  const stack = [{ indent: -1, obj: root }];
  for (const rawLine of String(text || '').split(/\r?\n/)) {
    if (!rawLine.trim() || rawLine.trim().startsWith('#')) continue;
    const indent = rawLine.match(/^ */)[0].length;
    let line = rawLine.trim();
    if (line.startsWith('- ')) continue; // 数组项不参与本子集
    const hashIdx = line.indexOf(' #');
    if (hashIdx > 0) line = line.slice(0, hashIdx).trim();
    const m = line.match(/^([A-Za-z0-9_.\-]+):\s*(.*)$/);
    if (!m) continue;
    const key = m[1];
    const val = m[2];
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
    const parent = stack[stack.length - 1].obj;
    if (val === '') {
      const child = {};
      parent[key] = child;
      stack.push({ indent, obj: child });
    } else {
      parent[key] = coerceScalar(val);
    }
  }
  return root;
}

function emitScalar(v) {
  if (v === null || v === undefined) return '""';           // 空值必须显式写为 ""，否则回读会变成空对象
  if (typeof v === 'string') return `"${v.replace(/"/g, '\\"')}"`;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return `"${String(v).replace(/"/g, '\\"')}"`;
}

function emitYamlSubset(obj, indent) {
  const pad = ' '.repeat(indent);
  let out = '';
  for (const [k, v] of Object.entries(obj)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      out += `${pad}${k}:\n` + emitYamlSubset(v, indent + 2);
    } else {
      out += `${pad}${k}: ${emitScalar(v)}\n`;
    }
  }
  return out;
}

function getPath(obj, dotted) {
  return String(dotted).split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj, dotted, value) {
  const keys = String(dotted).split('.');
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (cur[keys[i]] == null || typeof cur[keys[i]] !== 'object') cur[keys[i]] = {};
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
}

// ═══════════════════════════════════════════════════════════════════
// 配置子系统
// ═══════════════════════════════════════════════════════════════════

const DEFAULT_CONFIG_TEXT = `# mcore-client 单点配置中心（唯一事实源）
# 本文件是本地所有 Agent 的上游端点真相来源；Agent 侧永远只连 127.0.0.1
version: "1.0"
active_profile: "local"

profiles:
  # 本机 / 局域网直连
  local:
    server_url: "http://127.0.0.1:8318"
    tenant_id: "default"
    api_key: ""
    timeout_ms: 15000
    retry_max: 2

  # 公网云端（示例，按需替换）
  cloud:
    server_url: "https://mcore.099817.xyz"
    tenant_id: "default"
    api_key: ""
    timeout_ms: 20000
    retry_max: 3

local_server:
  host: "127.0.0.1"
  port: 8318
  log_level: "INFO"

resilience:
  enable_cache: true
  cache_ttl_s: 300
  enable_wal_queue: true
  queue_max_items: 1000
  retry_dead_after: 8
`;

function ensureConfig() {
  ensureDir(MCORE_DIR);
  if (!fs.existsSync(CONFIG_PATH)) {
    fs.writeFileSync(CONFIG_PATH, DEFAULT_CONFIG_TEXT, { encoding: 'utf8', mode: 0o600 });
    try { fs.chmodSync(CONFIG_PATH, 0o600); } catch (_) {}
    L.info('config', { msg: '已生成默认配置', path: CONFIG_PATH });
  }
}

function loadConfigRaw() {
  ensureConfig();
  const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
  return parseYamlSubset(raw);
}

function loadConfig() {
  const cfg = loadConfigRaw();
  const active = cfg.active_profile || 'local';
  const profiles = cfg.profiles || {};
  const p = profiles[active] || {};
  const ls = cfg.local_server || {};
  const rz = cfg.resilience || {};

  // 安全硬约束：拒绝非回环监听
  const host = String(ls.host || '127.0.0.1');
  if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
    throw new Error(`local_server.host 必须是回环地址（当前 "${host}"），拒绝启动`);
  }

  return {
    version: cfg.version || '1.0',
    activeProfile: active,
    profiles,
    serverUrl: String(p.server_url || '').replace(/\/+$/, ''),
    tenantId: String(p.tenant_id || 'default'),
    apiKey: String(p.api_key || ''),
    timeoutMs: Number(p.timeout_ms || 15000),
    retryMax: Number(p.retry_max == null ? 2 : p.retry_max),
    localHost: host,
    localPort: Number(ls.port || 8318),
    logLevel: String(ls.log_level || 'INFO'),
    enableCache: rz.enable_cache !== false,
    cacheTtlS: Number(rz.cache_ttl_s || 300),
    enableQueue: rz.enable_wal_queue !== false,
    queueMaxItems: Number(rz.queue_max_items || 1000),
    retryDeadAfter: Number(rz.retry_dead_after || 8),
  };
}

function tightenConfigPerms() {
  try {
    const st = fs.statSync(CONFIG_PATH);
    if (st.mode & 0o077) {
      fs.chmodSync(CONFIG_PATH, 0o600);
      L.warn('config', { msg: '配置文件权限过宽，已自动收紧为 600' });
    }
  } catch (_) {}
}

// ═══════════════════════════════════════════════════════════════════
// egress —— 上游出站统一入口（连接复用 + 凭据注入 + 瞬时重试）
// ═══════════════════════════════════════════════════════════════════

const AGENT_HTTP = new http.Agent({ keepAlive: true, maxSockets: 8, keepAliveMsecs: 30000 });
const AGENT_HTTPS = new https.Agent({ keepAlive: true, maxSockets: 8, keepAliveMsecs: 30000 });

let CFG = null;

function upstreamRequest(spec) {
  const { method, path: reqPath, headers, body, timeoutMs, retryMax } = spec;
  const base = String(CFG.serverUrl || '');
  if (!base) return Promise.reject(new Error('未配置 server_url'));

  const url = new URL(base + (reqPath || '/'));
  const isHttps = url.protocol === 'https:';
  const mod = isHttps ? https : http;
  const agent = isHttps ? AGENT_HTTPS : AGENT_HTTP;

  const outHeaders = Object.assign({}, headers || {});
  outHeaders['X-Tenant-Id'] = CFG.tenantId;
  if (CFG.apiKey) outHeaders['X-API-Key'] = CFG.apiKey;
  outHeaders['X-Client-Info'] = `mcore-client/${VERSION}`;
  outHeaders['Host'] = url.host;

  const attempts = Math.max(1, Number(retryMax == null ? CFG.retryMax : retryMax));
  let lastErr = null;

  const once = () => new Promise((resolve, reject) => {
    const req = mod.request({
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: method || 'POST',
      headers: outHeaders,
      agent,
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    req.setTimeout(Number(timeoutMs || CFG.timeoutMs), () => {
      req.destroy(new Error('upstream timeout'));
    });
    req.on('error', reject);
    if (body != null) req.write(typeof body === 'string' ? body : JSON.stringify(body));
    req.end();
  });

  const run = async (n) => {
    try {
      const res = await once();
      // 仅对典型瞬时故障重试
      if ([502, 503, 504].includes(res.status) && n < attempts) {
        await new Promise((r) => setTimeout(r, 500));
        return run(n + 1);
      }
      return res;
    } catch (e) {
      lastErr = e;
      if (n < attempts) {
        await new Promise((r) => setTimeout(r, 500));
        return run(n + 1);
      }
      throw lastErr;
    }
  };

  return run(1);
}

// ═══════════════════════════════════════════════════════════════════
// ContextCache —— 上下文 LRU（读路径离线兜底）
// ═══════════════════════════════════════════════════════════════════

const CACHE = new Map();
const CACHE_MAX = 64;

function cacheKey(agent, prompt) {
  return sha256(`${CFG.activeProfile}|${agent}|${prompt}`);
}

function cacheGet(k) {
  const e = CACHE.get(k);
  if (!e) return null;
  if (Date.now() > e.exp) { CACHE.delete(k); return null; }
  CACHE.delete(k); CACHE.set(k, e); // LRU 提升
  return e.v;
}

function cacheSet(k, v) {
  if (!CFG.enableCache) return;
  if (CACHE.size >= CACHE_MAX) CACHE.delete(CACHE.keys().next().value);
  CACHE.set(k, { v, exp: Date.now() + CFG.cacheTtlS * 1000 });
}

function cacheClear() { CACHE.clear(); }

function cacheLoad() {
  const d = readJSONFile(CACHE_PATH, null);
  if (!d || !Array.isArray(d.items)) return;
  const now = Date.now();
  for (const it of d.items.slice(-CACHE_MAX)) {
    if (it && it.k && it.exp > now) CACHE.set(it.k, { v: it.v, exp: it.exp });
  }
}

function cacheSave() {
  try {
    const items = [];
    for (const [k, e] of CACHE.entries()) items.push({ k, v: e.v, exp: e.exp });
    writeJSONFile(CACHE_PATH, { saved_at: nowIso(), items });
  } catch (_) {}
}

// ═══════════════════════════════════════════════════════════════════
// WALQueue —— 会话回写持久化队列（至少一次投递）
// 状态由文件后缀表达：pending → inflight → done / dead
// ═══════════════════════════════════════════════════════════════════

let QUEUE_SEQ = 0;

function queueInit() {
  if (!CFG.enableQueue) return;
  ensureDir(QUEUE_DIR, 0o700);
  const cur = path.join(QUEUE_DIR, '.cursor');
  QUEUE_SEQ = fs.existsSync(cur) ? (parseInt(fs.readFileSync(cur, 'utf8'), 10) || 0) : 0;
  // 崩溃恢复：inflight 回退 pending
  for (const f of fs.readdirSync(QUEUE_DIR)) {
    if (f.endsWith('.inflight')) {
      try {
        fs.renameSync(path.join(QUEUE_DIR, f), path.join(QUEUE_DIR, f.replace(/\.inflight$/, '.pending')));
        L.warn('queue', { msg: '崩溃恢复：inflight 回退 pending', file: f });
      } catch (_) {}
    }
  }
  if (QUEUE_SEQ === 0) {
    // 从现有文件推断最大序号
    for (const f of fs.readdirSync(QUEUE_DIR)) {
      const m = f.match(/^(\d+)\./);
      if (m) QUEUE_SEQ = Math.max(QUEUE_SEQ, parseInt(m[1], 10));
    }
  }
}

function queueNextId() {
  QUEUE_SEQ += 1;
  try { fs.writeFileSync(path.join(QUEUE_DIR, '.cursor'), String(QUEUE_SEQ)); } catch (_) {}
  return String(QUEUE_SEQ).padStart(6, '0');
}

function queueDepth() {
  if (!fs.existsSync(QUEUE_DIR)) return { pending: 0, inflight: 0, done: 0, dead: 0 };
  const d = { pending: 0, inflight: 0, done: 0, dead: 0 };
  for (const f of fs.readdirSync(QUEUE_DIR)) {
    const m = f.match(/\.(pending|inflight|done|dead)$/);
    if (m) d[m[1]] += 1;
  }
  return d;
}

function queueList() {
  const out = [];
  if (!fs.existsSync(QUEUE_DIR)) return out;
  for (const f of fs.readdirSync(QUEUE_DIR).sort()) {
    const m = f.match(/^(\d+)\.(pending|inflight|done|dead)$/);
    if (!m) continue;
    let meta = {};
    try { meta = JSON.parse(fs.readFileSync(path.join(QUEUE_DIR, f), 'utf8')); } catch (_) {}
    out.push({
      id: m[1], state: m[2], agent: meta.agent || '-',
      attempts: meta.attempts || 0, messages: (meta.messages || []).length,
      bytes: fs.statSync(path.join(QUEUE_DIR, f)).size,
      created_at: meta.created_at || '-',
    });
  }
  return out;
}

function queueEnqueue(rec) {
  const id = queueNextId();
  const file = path.join(QUEUE_DIR, `${id}.pending`);
  const payload = Object.assign({ id, created_at: nowIso(), attempts: 0, next_retry_at: 0 }, rec);
  fs.writeFileSync(file, JSON.stringify(payload), { encoding: 'utf8', mode: 0o600 });
  L.info('queue', { msg: '会话转录已入队', id, agent: rec.agent, messages: (rec.messages || []).length });
  return id;
}

const BACKOFF_S = [5, 10, 20, 40, 60, 120, 300, 600];

function backoffMs(attempts) {
  const base = BACKOFF_S[Math.min(attempts, BACKOFF_S.length - 1)] * 1000;
  const jitter = base * 0.2 * (Math.random() * 2 - 1);
  return Math.round(base + jitter);
}

// 容量保护：超限淘汰最旧 pending
function queueEvictIfNeeded() {
  const d = queueDepth();
  if (d.pending + d.inflight <= CFG.queueMaxItems) return;
  const pend = fs.readdirSync(QUEUE_DIR).filter((f) => f.endsWith('.pending')).sort();
  const excess = d.pending + d.inflight - CFG.queueMaxItems;
  for (let i = 0; i < excess && i < pend.length; i++) {
    try {
      fs.unlinkSync(path.join(QUEUE_DIR, pend[i]));
      L.warn('queue', { msg: '容量超限，淘汰最旧 pending', file: pend[i] });
    } catch (_) {}
  }
}

let flushing = false;

async function queueFlush() {
  if (!CFG.enableQueue || flushing) return;
  flushing = true;
  try {
    const files = fs.readdirSync(QUEUE_DIR).filter((f) => f.endsWith('.pending')).sort();
    for (const f of files) {
      const full = path.join(QUEUE_DIR, f);
      let rec;
      try { rec = JSON.parse(fs.readFileSync(full, 'utf8')); } catch (_) { continue; }
      if (rec.next_retry_at && Date.now() < rec.next_retry_at) continue;

      const inflight = full.replace(/\.pending$/, '.inflight');
      try { fs.renameSync(full, inflight); } catch (_) { continue; }

      try {
        const res = await upstreamRequest({
          method: 'POST',
          path: '/mcp',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' },
          body: JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'tools/call',
            params: { name: 'memory_ingest', arguments: { messages: rec.messages, agent_id: rec.agent, project_path: rec.project_path || '' } },
          }),
          timeoutMs: 60000,
          retryMax: 1,
        });
        if (res.status >= 200 && res.status < 300) {
          fs.renameSync(inflight, inflight.replace(/\.inflight$/, '.done'));
          L.info('queue', { msg: '回写成功', id: rec.id, agent: rec.agent });
        } else {
          throw new Error(`HTTP ${res.status}`);
        }
      } catch (e) {
        rec.attempts = (rec.attempts || 0) + 1;
        rec.last_error = String(e.message).slice(0, 200);
        try { fs.writeFileSync(inflight, JSON.stringify(rec), 'utf8'); } catch (_) {}
        if (rec.attempts >= CFG.retryDeadAfter) {
          try { fs.renameSync(inflight, inflight.replace(/\.inflight$/, '.dead')); } catch (_) {}
          L.error('queue', { msg: '重试超限转入死信', id: rec.id, attempts: rec.attempts, err: rec.last_error.slice(0, 120) });
        } else {
          rec.next_retry_at = Date.now() + backoffMs(rec.attempts);
          try {
            fs.writeFileSync(inflight, JSON.stringify(rec), 'utf8');
            fs.renameSync(inflight, inflight.replace(/\.inflight$/, '.pending'));
          } catch (_) {}
          L.warn('queue', { msg: '回写失败，安排退避重试', id: rec.id, attempts: rec.attempts, err: rec.last_error.slice(0, 120) });
        }
      }
    }
    // .done 文件 60s 后物理删除
    const cutoff = Date.now() - 60000;
    for (const f of fs.readdirSync(QUEUE_DIR)) {
      if (!f.endsWith('.done')) continue;
      const full = path.join(QUEUE_DIR, f);
      try { if (fs.statSync(full).mtimeMs < cutoff) fs.unlinkSync(full); } catch (_) {}
    }
  } finally {
    flushing = false;
  }
}

function queueReplay(id) {
  const dir = QUEUE_DIR;
  for (const ext of ['dead', 'pending', 'inflight']) {
    const src = path.join(dir, `${id}.${ext}`);
    if (fs.existsSync(src)) {
      const dst = path.join(dir, `${id}.pending`);
      try {
        let rec = JSON.parse(fs.readFileSync(src, 'utf8'));
        rec.attempts = 0; rec.next_retry_at = 0;
        fs.writeFileSync(src, JSON.stringify(rec), 'utf8');
        if (src !== dst) fs.renameSync(src, dst);
        L.info('queue', { msg: '死信已重放', id });
        return true;
      } catch (_) { return false; }
    }
  }
  return false;
}

// ═══════════════════════════════════════════════════════════════════
// transcriptExtractors —— 五源转录提取（口径对齐 mcore-ingest.py）
// ═══════════════════════════════════════════════════════════════════

const TRUNC_PER_MSG = 2000;
const MAX_MSGS = 500;
const TAIL_LINES = 5000;

function readTailLines(p, n) {
  const text = fs.readFileSync(p, 'utf8');
  const lines = text.split(/\r?\n/).filter(Boolean);
  return lines.slice(-n);
}

function textFromBlocks(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content
    .filter((b) => b && typeof b === 'object' && (b.type == null || b.type === 'text') && b.text)
    .map((b) => b.text)
    .join(' ');
}

function finalize(messages) {
  const out = messages
    .filter((m) => m && m.content && String(m.content).trim())
    .map((m) => ({ role: m.role, content: String(m.content).trim().slice(0, TRUNC_PER_MSG) }));
  return out.slice(-MAX_MSGS);
}

function extractClaude(p) {
  const messages = [];
  for (const line of readTailLines(p, TAIL_LINES)) {
    let item; try { item = JSON.parse(line); } catch (_) { continue; }
    const msg = item.message && typeof item.message === 'object' ? item.message : item;
    if (!msg || typeof msg !== 'object') continue;
    const role = msg.role;
    if (role !== 'user' && role !== 'assistant') continue;
    const text = String(textFromBlocks(msg.content) || '').trim();
    if (text) messages.push({ role, content: text });
  }
  return finalize(messages);
}

function extractCodex(p) {
  const primary = [];
  const fallback = [];
  for (const line of readTailLines(p, TAIL_LINES)) {
    let item; try { item = JSON.parse(line); } catch (_) { continue; }
    const payload = item.payload && typeof item.payload === 'object' ? item.payload : {};
    let role = '', text = '';
    if (item.type === 'event_msg') {
      if (payload.type === 'user_message') { role = 'user'; text = String(payload.message || ''); }
      else if (payload.type === 'agent_message') { role = 'assistant'; text = String(payload.message || ''); }
    } else if (item.type === 'response_item' && payload.type === 'message') {
      role = String(payload.role || '');
      if (role !== 'user' && role !== 'assistant') continue;
      if (Array.isArray(payload.content)) {
        text = payload.content
          .filter((x) => x && typeof x === 'object')
          .map((x) => x.text || x.input_text || x.output_text || '')
          .join(' ');
      }
    }
    text = String(text || '').trim();
    if (!(role && text)) continue;
    if (item.type === 'event_msg') primary.push({ role, content: text });
    else fallback.push({ role, content: text });
  }
  return finalize(primary.length ? primary : fallback);
}

function extractGemini(p) {
  const messages = [];
  for (const line of readTailLines(p, TAIL_LINES)) {
    let item; try { item = JSON.parse(line); } catch (_) { continue; }
    const role = item.role || item.author || item.speaker || item.type || '';
    if (!['user', 'assistant', 'model', 'gemini'].includes(role)) continue;
    const norm = role === 'model' || role === 'gemini' ? 'assistant' : role;
    const text = String(textFromBlocks(item.content) || item.text || item.message || '').trim();
    if (text) messages.push({ role: norm, content: text });
  }
  return finalize(messages);
}

// SQLite 读取：优先 node:sqlite，回落 sqlite3 CLI
function sqliteQueryJson(dbPath, sql) {
  try {
    const { DatabaseSync } = require('node:sqlite');
    const db = new DatabaseSync(dbPath, { readOnly: true });
    try {
      const rows = db.prepare(sql).all();
      return rows || [];
    } finally { try { db.close(); } catch (_) {} }
  } catch (_) {
    const r = spawnSync('sqlite3', ['-json', '-readonly', dbPath, sql], { encoding: 'utf8', timeout: 15000 });
    if (r.status !== 0 || !r.stdout) return [];
    try { return JSON.parse(r.stdout); } catch (_) { return []; }
  }
}

function extractHermes(sessionId) {
  const dbPath = process.env.HERMES_STATE_DB || path.join(HOME, '.hermes', 'state.db');
  if (!fs.existsSync(dbPath)) { L.warn('extract', { msg: 'hermes state.db 不存在', path: dbPath }); return []; }
  let sid = sessionId;
  if (!sid) {
    const r = sqliteQueryJson(dbPath, 'SELECT id FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1');
    sid = r && r[0] ? String(r[0].id) : '';
  }
  if (!sid) return [];
  const rows = sqliteQueryJson(dbPath, `SELECT role, content FROM messages WHERE session_id = '${String(sid).replace(/'/g, "''")}' AND role IN ('user','assistant') AND content IS NOT NULL AND trim(content) != '' ORDER BY id DESC LIMIT 800`);
  const messages = [];
  for (const row of (rows || []).reverse()) {
    const text = String(row.content || '').trim();
    if (text) messages.push({ role: String(row.role), content: text });
  }
  return finalize(messages);
}

function extractOpencode(sessionId) {
  const dbPath = path.join(HOME, '.local', 'share', 'opencode', 'opencode.db');
  const alt = path.join(HOME, '.opencode', 'opencode.db');
  const db = fs.existsSync(dbPath) ? dbPath : (fs.existsSync(alt) ? alt : '');
  if (!db) { L.warn('extract', { msg: 'opencode 数据库未找到' }); return []; }
  let sid = sessionId;
  if (!sid) {
    const r = sqliteQueryJson(db, 'SELECT id FROM session ORDER BY time_updated DESC LIMIT 1');
    sid = r && r[0] ? String(r[0].id) : '';
  }
  if (!sid) return [];
  const rows = sqliteQueryJson(db, `SELECT m.data AS message_data, p.data AS part_data FROM message m LEFT JOIN part p ON p.message_id = m.id WHERE m.session_id = '${String(sid).replace(/'/g, "''")}' ORDER BY m.time_created ASC, p.time_created ASC`);
  const grouped = new Map();
  const order = [];
  for (const row of rows || []) {
    let minfo = {}; try { minfo = JSON.parse(row.message_data || '{}'); } catch (_) {}
    let pinfo = {}; try { pinfo = JSON.parse(row.part_data || '{}'); } catch (_) {}
    const mid = minfo.id || String(order.length);
    if (!grouped.has(mid)) { grouped.set(mid, { role: String(minfo.role || ''), parts: [] }); order.push(mid); }
    const ptext = String(pinfo.text || pinfo.content || '').trim();
    if (ptext) grouped.get(mid).parts.push(ptext);
  }
  const messages = [];
  for (const mid of order) {
    const g = grouped.get(mid);
    if (g.role !== 'user' && g.role !== 'assistant') continue;
    const text = g.parts.join(' ').trim();
    if (text) messages.push({ role: g.role, content: text });
  }
  return finalize(messages);
}

function findLatestFile(root, pattern) {
  if (!fs.existsSync(root)) return null;
  const hits = [];
  const walk = (dir, depth) => {
    if (depth > 4) return;
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) { return; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (pattern.test(e.name)) {
        try { hits.push({ full, mtime: fs.statSync(full).mtimeMs }); } catch (_) {}
      }
    }
  };
  walk(root, 0);
  if (!hits.length) return null;
  hits.sort((a, b) => b.mtime - a.mtime);
  return hits[0].full;
}

// ═══════════════════════════════════════════════════════════════════
// payloadAdapter —— 五生态 Hook Payload 解析
// ═══════════════════════════════════════════════════════════════════

const AGENT_ALIAS = {
  claude: 'claude', 'claude-code': 'claude', 'claude code': 'claude',
  hermes: 'hermes', 'hermes-agent': 'hermes',
  codex: 'codex', 'codex-cli': 'codex',
  gemini: 'gemini', 'gemini-cli': 'gemini',
  opencode: 'opencode', 'open-code': 'opencode',
};

function normalizeAgent(raw) {
  if (!raw) return '';
  const k = String(raw).trim().toLowerCase();
  return AGENT_ALIAS[k] || k;
}

function pickStr(obj, keys) {
  for (const k of keys) {
    const v = k.split('.').reduce((o, kk) => (o == null ? undefined : o[kk]), obj);
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return '';
}

function adaptHookPayload(body, headers, query) {
  const b = body && typeof body === 'object' ? body : {};
  const extra = b.extra && typeof b.extra === 'object' ? b.extra : {};

  let agent = normalizeAgent(headers['x-agent-id'] || query.get('agent') || b.agent || b.agent_id || '');
  if (!agent && b.hook_event_name === 'UserPromptSubmit') agent = 'claude';

  const prompt = pickStr(
    { ...b, tool_input: b.tool_input, extra },
    ['tool_input.prompt', 'prompt', 'user_prompt', 'user_message', 'message', 'input', 'extra.user_message']
  );

  const projectPath = pickStr(
    { ...b, extra },
    ['cwd', 'project_path', 'working_directory', 'workspace', 'extra.cwd', 'extra.project_path']
  );

  const sessionId = pickStr(
    { ...b, session: b.session },
    ['session_id', 'sessionId', 'sessionID', 'id', 'session.id']
  );

  const transcriptPath = pickStr(
    { ...b, session: b.session },
    ['transcript_path', 'transcriptPath', 'transcript', 'session.transcript_path']
  );

  const hookEvent = pickStr(b, ['hook_event_name', 'hookEventName']);

  return { agent: agent || 'generic', prompt, projectPath, sessionId, transcriptPath, hookEvent, raw: b };
}

// 噪声护栏：泛化短查询直接跳过召回（历史"不相关注入"教训）
const GENERIC_PROMPT_RE = /^(现在)?(todo|待办|有什么|还有啥|剩下什么|help|帮助|你好|hi|hello)\b/i;

function shouldSkipRecall(agent, prompt) {
  const p = String(prompt || '').trim();
  if (p.length < 4) return true;
  if (agent === 'codex' && p.length < 20 && GENERIC_PROMPT_RE.test(p)) return true;
  return false;
}

// ═══════════════════════════════════════════════════════════════════
// Hook 处理器
// ═══════════════════════════════════════════════════════════════════

function hookResponseEnvelope(agent, hookEvent, contextText) {
  const ev = hookEvent || (agent === 'gemini' ? 'BeforeAgent' : (agent === 'hermes' ? 'pre_llm_call' : 'UserPromptSubmit'));
  if (agent === 'hermes') return { context: contextText };
  return { hookSpecificOutput: { hookEventName: ev, additionalContext: contextText } };
}

async function callMemoryContext(agent, prompt, projectPath) {
  const res = await upstreamRequest({
    method: 'POST',
    path: '/mcp',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1, method: 'tools/call',
      params: { name: 'memory_context', arguments: { task: prompt, agent, project_path: projectPath || '', token_budget: 2000 } },
    }),
    timeoutMs: 5000,
    retryMax: 1,
  });
  if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
  const raw = parseMcpBody(res.body);
  const content = raw && raw.result && Array.isArray(raw.result.content) ? raw.result.content : [];
  const text = content.length && content[0].text ? content[0].text : '';
  if (!text) return '';
  try {
    const inner = JSON.parse(text);
    if (inner && typeof inner === 'object') return String(inner.context || inner.text || '');
    return String(text);
  } catch (_) { return String(text); }
}

function parseMcpBody(body) {
  const s = String(body || '').trim();
  for (const line of s.split(/\r?\n/)) {
    if (line.startsWith('data:')) {
      try { return JSON.parse(line.slice(5).trim()); } catch (_) {}
    }
  }
  try { return JSON.parse(s); } catch (_) { return null; }
}

async function handleHookContext(req, res, url) {
  const body = await readBody(req);
  let parsed = {};
  try { parsed = JSON.parse(body || '{}'); } catch (_) {}
  const h = adaptHookPayload(parsed, req.headers, url.searchParams);

  if (shouldSkipRecall(h.agent, h.prompt)) {
    L.info('hooks', { msg: '跳过召回', agent: h.agent, reason: 'short_or_generic' });
    return sendJson(res, 200, hookResponseEnvelope(h.agent, h.hookEvent, ''));
  }

  const key = cacheKey(h.agent, h.prompt);
  const cached = cacheGet(key);
  if (cached != null) {
    STATS.hook_context_cache_hits += 1;
    L.info('hooks', { msg: '上下文缓存命中', agent: h.agent });
    return sendJson(res, 200, hookResponseEnvelope(h.agent, h.hookEvent, cached));
  }

  try {
    const ctx = await callMemoryContext(h.agent, h.prompt, h.projectPath);
    if (ctx) cacheSet(key, ctx);
    L.info('hooks', { msg: '上下文注入成功', agent: h.agent, len: ctx.length });
    return sendJson(res, 200, hookResponseEnvelope(h.agent, h.hookEvent, ctx));
  } catch (e) {
    L.warn('hooks', { msg: '上游召回失败，空注入兜底', agent: h.agent, err: String(e.message).slice(0, 120) });
    return sendJson(res, 200, hookResponseEnvelope(h.agent, h.hookEvent, ''));
  }
}

async function handleHookIngest(req, res, url) {
  const body = await readBody(req);
  let parsed = {};
  try { parsed = JSON.parse(body || '{}'); } catch (_) {}
  const h = adaptHookPayload(parsed, req.headers, url.searchParams);

  // 立即应答，绝不阻塞 Agent 的 Stop 钩子
  sendJson(res, 200, { ok: true, queued: true, agent: h.agent });

  setImmediate(() => {
    try {
      const msgs = extractMessages(h);
      if (!msgs.length) {
        L.info('hooks', { msg: '转录为空，跳过回写', agent: h.agent });
        return;
      }
      ensureDir(QUEUE_DIR, 0o700);
      const id = queueEnqueue({ agent: h.agent, project_path: h.projectPath, source: 'hook', messages: msgs });
      queueEvictIfNeeded();
      L.info('hooks', { msg: '入队完成', agent: h.agent, batch: id, messages: msgs.length });
      setTimeout(() => { queueFlush().catch(() => {}); }, 50);
    } catch (e) {
      L.error('hooks', { msg: '转录提取失败', agent: h.agent, err: String(e.message).slice(0, 200) });
    }
  });
}

function extractMessages(h) {
  switch (h.agent) {
    case 'claude': {
      let p = h.transcriptPath;
      if (!p || !fs.existsSync(p)) {
        const root = path.join(HOME, '.claude', 'projects');
        p = findLatestFile(root, /\.jsonl$/);
      }
      if (!p || !fs.existsSync(p)) { L.warn('extract', { msg: 'claude 转录未找到' }); return []; }
      return extractClaude(p);
    }
    case 'codex': {
      const env = process.env.CODEX_SESSION_FILE;
      let p = env && fs.existsSync(env) ? env : h.transcriptPath;
      if (!p || !fs.existsSync(p)) p = findLatestFile(path.join(HOME, '.codex', 'sessions'), /\.jsonl$/);
      if (!p || !fs.existsSync(p)) { L.warn('extract', { msg: 'codex 转录未找到' }); return []; }
      return extractCodex(p);
    }
    case 'gemini': {
      let p = h.transcriptPath;
      if (!p || !fs.existsSync(p)) p = findLatestFile(path.join(HOME, '.gemini', 'tmp'), /\.jsonl$/);
      if (!p || !fs.existsSync(p)) { L.warn('extract', { msg: 'gemini 转录未找到' }); return []; }
      return extractGemini(p);
    }
    case 'hermes':
      return extractHermes(h.sessionId);
    case 'opencode':
      return extractOpencode(h.sessionId);
    default:
      L.warn('extract', { msg: '未知 agent，跳过', agent: h.agent });
      return [];
  }
}

// ═══════════════════════════════════════════════════════════════════
// HTTP 工具
// ═══════════════════════════════════════════════════════════════════

const MAX_BODY = 8 * 1024 * 1024;

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) { req.destroy(); reject(new Error('payload too large')); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function sendJson(res, status, obj) {
  const s = JSON.stringify(obj);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(s) });
  res.end(s);
}

// ═══════════════════════════════════════════════════════════════════
// ingress —— 本地接入面
// ═══════════════════════════════════════════════════════════════════

const STATS = {
  started_at: nowIso(),
  requests_total: 0,
  mcp_calls: 0,
  hook_context_total: 0,
  hook_context_cache_hits: 0,
  hook_ingest_total: 0,
  upstream_errors: 0,
  upstream_latency: [],
};

function recordLatency(ms) {
  STATS.upstream_latency.push(ms);
  if (STATS.upstream_latency.length > 200) STATS.upstream_latency.shift();
}

function latencySummary() {
  const a = STATS.upstream_latency.slice().sort((x, y) => x - y);
  if (!a.length) return { p50: 0, p95: 0, samples: 0 };
  const at = (q) => a[Math.min(a.length - 1, Math.floor(a.length * q))];
  return { p50: at(0.5), p95: at(0.95), samples: a.length };
}

async function handleMcp(req, res) {
  STATS.mcp_calls += 1;
  const body = await readBody(req);
  const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' };
  const sid = req.headers['mcp-session-id'];
  if (sid) headers['Mcp-Session-Id'] = sid;

  const t0 = Date.now();
  try {
    const r = await upstreamRequest({ method: 'POST', path: '/mcp', headers, body, timeoutMs: Math.max(CFG.timeoutMs, 60000), retryMax: CFG.retryMax });
    recordLatency(Date.now() - t0);
    const outHeaders = { 'Content-Type': r.headers['content-type'] || 'application/json' };
    if (r.headers['mcp-session-id']) outHeaders['Mcp-Session-Id'] = r.headers['mcp-session-id'];
    res.writeHead(r.status, outHeaders);
    res.end(r.body);
  } catch (e) {
    STATS.upstream_errors += 1;
    L.error('mcp', { msg: '上游不可达', err: String(e.message).slice(0, 160) });
    sendJson(res, 200, { jsonrpc: '2.0', id: null, error: { code: -32001, message: 'upstream unreachable: ' + String(e.message).slice(0, 120) } });
  }
}

async function handlePassthrough(req, res, url) {
  const body = req.method === 'GET' || req.method === 'HEAD' ? null : await readBody(req);
  const headers = {};
  for (const k of ['content-type', 'accept', 'user-agent']) if (req.headers[k]) headers[k] = req.headers[k];
  try {
    const r = await upstreamRequest({ method: req.method, path: url.pathname + url.search, headers, body, timeoutMs: CFG.timeoutMs });
    recordLatency(0);
    res.writeHead(r.status, { 'Content-Type': r.headers['content-type'] || 'application/json' });
    res.end(r.body);
  } catch (e) {
    STATS.upstream_errors += 1;
    sendJson(res, 502, { ok: false, error: 'upstream unreachable', detail: String(e.message).slice(0, 120) });
  }
}

async function handleHealth(req, res) {
  const t0 = Date.now();
  let upstream = { url: CFG.serverUrl, status: 'unknown', latency_ms: null };
  try {
    const r = await upstreamRequest({ method: 'GET', path: '/health', headers: { Accept: 'application/json' }, timeoutMs: 2000, retryMax: 1 });
    upstream.status = r.status === 200 ? 'connected' : 'degraded';
    upstream.latency_ms = Date.now() - t0;
    recordLatency(upstream.latency_ms);
  } catch (_) {
    upstream.status = 'disconnected';
  }
  const d = queueDepth();
  sendJson(res, 200, {
    ok: true,
    client: {
      status: 'running', version: VERSION, pid: process.pid,
      active_profile: CFG.activeProfile, listening: `${CFG.localHost}:${CFG.localPort}`,
      offline_queue_size: d.pending + d.inflight,
    },
    upstream,
    queue: d,
  });
}

function isLoopback(req) {
  const a = req.socket.remoteAddress || '';
  return a === '127.0.0.1' || a === '::1' || a === '::ffff:127.0.0.1';
}

async function handleAdmin(req, res, pathname) {
  if (!isLoopback(req)) return sendJson(res, 403, { ok: false, error: 'admin endpoints are loopback-only' });

  if (pathname === '/_admin/stats') {
    return sendJson(res, 200, {
      ok: true, version: VERSION, pid: process.pid, started_at: STATS.started_at,
      active_profile: CFG.activeProfile, upstream: CFG.serverUrl,
      counters: {
        requests_total: STATS.requests_total,
        mcp_calls: STATS.mcp_calls,
        hook_context_total: STATS.hook_context_total,
        hook_context_cache_hits: STATS.hook_context_cache_hits,
        hook_ingest_total: STATS.hook_ingest_total,
        upstream_errors: STATS.upstream_errors,
      },
      latency: latencySummary(),
      cache_size: CACHE.size,
      queue: queueDepth(),
    });
  }
  if (pathname === '/_admin/queue') return sendJson(res, 200, { ok: true, items: queueList() });
  if (pathname === '/_admin/cache/clear' && req.method === 'POST') { cacheClear(); return sendJson(res, 200, { ok: true }); }
  if (pathname === '/_admin/reload' && req.method === 'POST') {
    try { CFG = loadConfig(); tightenConfigPerms(); cacheClear(); return sendJson(res, 200, { ok: true, active_profile: CFG.activeProfile }); }
    catch (e) { return sendJson(res, 500, { ok: false, error: String(e.message) }); }
  }
  if (pathname === '/_admin/shutdown' && req.method === 'POST') {
    sendJson(res, 200, { ok: true, msg: 'shutting down' });
    setTimeout(() => gracefulExit(0), 100);
    return;
  }
  const m = pathname.match(/^\/_admin\/queue\/(\d+)\/replay$/);
  if (m && req.method === 'POST') return sendJson(res, 200, { ok: queueReplay(m[1]) });

  return sendJson(res, 404, { ok: false, error: 'unknown admin endpoint' });
}

function createServer() {
  return http.createServer(async (req, res) => {
    STATS.requests_total += 1;
    const url = new URL(req.url, `http://${CFG.localHost}:${CFG.localPort}`);
    const p = url.pathname;
    try {
      if (p === '/health' && req.method === 'GET') return await handleHealth(req, res);
      if (p === '/mcp') return await handleMcp(req, res);
      if (p.startsWith('/api/v1/hooks/')) {
        if (p.endsWith('/context') || p.endsWith('/context/')) { STATS.hook_context_total += 1; return await handleHookContext(req, res, url); }
        if (p.endsWith('/ingest') || p.endsWith('/stop') || p.endsWith('/session-end')) { STATS.hook_ingest_total += 1; return await handleHookIngest(req, res, url); }
        return sendJson(res, 200, { ok: true });
      }
      if (p.startsWith('/_admin/')) return await handleAdmin(req, res, p);
      return await handlePassthrough(req, res, url);
    } catch (e) {
      L.error('ingress', { msg: '未捕获异常', path: p, err: String(e.message).slice(0, 200) });
      try { sendJson(res, 500, { ok: false, error: String(e.message).slice(0, 200) }); } catch (_) {}
    }
  });
}

// ═══════════════════════════════════════════════════════════════════
// 生命周期
// ═══════════════════════════════════════════════════════════════════

let SERVER = null;
let TIMERS = [];
let shuttingDown = false;

function gracefulExit(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  try { cacheSave(); } catch (_) {}
  for (const t of TIMERS) { try { clearInterval(t); } catch (_) {} }
  const done = () => { try { if (fs.existsSync(PID_PATH)) fs.unlinkSync(PID_PATH); } catch (_) {} process.exit(code); };
  if (SERVER) {
    SERVER.close(done);
    setTimeout(done, 3000);
  } else done();
}

function portProbe(host, port) {
  return new Promise((resolve) => {
    const s = http.request({ host, port, path: '/health', method: 'GET', timeout: 1200 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8');
        let looksLikeMcore = false;
        try { const j = JSON.parse(body); looksLikeMcore = !!(j && (j.ok !== undefined || j.data || j.name === 'mcore')); } catch (_) {}
        resolve({ occupied: true, looksLikeMcore });
      });
    });
    s.on('error', () => resolve({ occupied: false, looksLikeMcore: false }));
    s.on('timeout', () => { s.destroy(); resolve({ occupied: true, looksLikeMcore: false }); });
    s.end();
  });
}

async function runServerForeground() {
  CFG = loadConfig();
  tightenConfigPerms();
  cacheLoad();
  queueInit();
  QUEUE_SEQ = QUEUE_SEQ || 0;

  SERVER = createServer();
  await new Promise((resolve, reject) => {
    SERVER.once('error', reject);
    SERVER.listen(CFG.localPort, CFG.localHost, resolve);
  });

  fs.writeFileSync(PID_PATH, String(process.pid), 'utf8');

  TIMERS.push(setInterval(() => { queueFlush().catch(() => {}); }, 5000));
  TIMERS.push(setInterval(() => cacheSave(), 60000));

  process.on('SIGHUP', () => {
    try { CFG = loadConfig(); tightenConfigPerms(); cacheClear(); L.info('lifecycle', { msg: 'SIGHUP 热重载完成', profile: CFG.activeProfile }); }
    catch (e) { L.error('lifecycle', { msg: '热重载失败，保留原配置', err: String(e.message) }); }
  });
  process.on('SIGTERM', () => gracefulExit(0));
  process.on('SIGINT', () => gracefulExit(0));

  L.info('lifecycle', { msg: '客户端已启动', listen: `${CFG.localHost}:${CFG.localPort}`, upstream: CFG.serverUrl, profile: CFG.activeProfile });
  queueFlush().catch(() => {});
}

// ═══════════════════════════════════════════════════════════════════
// CLI
// ═══════════════════════════════════════════════════════════════════

function readPid() {
  try { return parseInt(fs.readFileSync(PID_PATH, 'utf8').trim(), 10) || 0; } catch (_) { return 0; }
}

function isAlive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (_) { return false; }
}

function cliStatus() {
  const pid = readPid();
  const alive = isAlive(pid);
  let cfg = {};
  try { cfg = loadConfig(); } catch (e) { console.log('配置错误:', e.message); return 1; }
  console.log(`mcore-client v${VERSION}`);
  console.log(`  进程      : ${alive ? `运行中 (pid ${pid})` : '未运行'}`);
  console.log(`  激活 Profile: ${cfg.activeProfile}`);
  console.log(`  监听      : ${cfg.localHost}:${cfg.localPort}`);
  console.log(`  上游      : ${cfg.serverUrl || '(未配置)'}`);
  console.log(`  租户      : ${cfg.tenantId}  凭据: ${cfg.apiKey ? redact(cfg.apiKey) : '(无)'}`);
  if (!alive) return 3;

  return new Promise((resolve) => {
    const req = http.request({ host: cfg.localHost, port: cfg.localPort, path: '/_admin/stats', method: 'GET', timeout: 3000 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        try {
          const j = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          console.log(`  队列      : pending=${j.queue.pending} inflight=${j.queue.inflight} dead=${j.queue.dead}`);
          console.log(`  缓存      : ${j.cache_size} 条`);
          console.log(`  计数器    : mcp=${j.counters.mcp_calls} ctx=${j.counters.hook_context_total} ingest=${j.counters.hook_ingest_total} errors=${j.counters.upstream_errors}`);
          console.log(`  上游延迟  : p50=${j.latency.p50}ms p95=${j.latency.p95}ms (${j.latency.samples} 样本)`);
          resolve(0);
        } catch (_) { resolve(0); }
      });
    });
    req.on('error', () => resolve(1));
    req.end();
  });
}

function cliStart(args) {
  const daemon = args.includes('--daemon') || args.includes('-d');
  const pid = readPid();
  if (isAlive(pid)) { console.log(`已运行中 (pid ${pid})`); return 0; }
  ensureConfig();

  if (!daemon) {
    // 前台/服务模式：启动后常驻，交由信号处理器退出（systemd 与手动前台均走此路径）
    return runServerForeground().then(() => new Promise(() => {})).catch((e) => { console.error('启动失败:', e.message); return 1; });
  }

  ensureDir(MCORE_DIR);
  const out = fs.openSync(LOG_PATH, 'a');
  const child = spawn(process.execPath, [__filename, '__serve'], {
    detached: true, stdio: ['ignore', out, out], cwd: process.cwd(),
  });
  child.unref();
  console.log(`已后台启动 (pid ${child.pid})，日志: ${LOG_PATH}`);
  return 0;
}

function cliStop() {
  const pid = readPid();
  if (!isAlive(pid)) { console.log('未运行'); return 0; }
  try { process.kill(pid, 'SIGTERM'); } catch (_) {}
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    if (!isAlive(pid)) { console.log('已停止'); return 0; }
    try { spawnSync(process.execPath, ['-e', 'setTimeout(()=>{},200)'], { timeout: 300 }); } catch (_) {}
  }
  try { process.kill(pid, 'SIGKILL'); } catch (_) {}
  console.log('已强制停止');
  return 0;
}

function cliSwitch(name) {
  if (!name) { console.error('用法: mcore-client switch <profile>'); return 1; }
  const raw = loadConfigRaw();
  if (!raw.profiles || !raw.profiles[name]) {
    console.error(`profile "${name}" 不存在。可用: ${Object.keys(raw.profiles || {}).join(', ')}`);
    return 1;
  }
  const before = raw.active_profile;
  raw.active_profile = name;
  fs.writeFileSync(CONFIG_PATH, emitYamlSubset(raw, 0), { encoding: 'utf8', mode: 0o600 });
  console.log(`已切换: ${before} → ${name}`);
  console.log(`  上游: ${getPath(raw, `profiles.${name}.server_url`) || '-'}`);

  const pid = readPid();
  if (isAlive(pid)) {
    try {
      process.kill(pid, 'SIGHUP');
      console.log('  已向运行中进程发送 SIGHUP，热重载生效（监听不中断）');
    } catch (e) { console.log('  热重载信号发送失败:', e.message); }
  } else {
    console.log('  （客户端未运行，下次启动生效）');
  }
  return 0;
}

function cliConfig(sub, key, value) {
  const raw = loadConfigRaw();
  if (sub === 'get') {
    if (!key) {
      const view = JSON.parse(JSON.stringify(raw));
      for (const p of Object.values(view.profiles || {})) if (p.api_key) p.api_key = redact(p.api_key);
      console.log(emitYamlSubset(view, 0));
      return 0;
    }
    let v = getPath(raw, key);
    if (typeof v === 'string' && /api_key/i.test(key)) v = redact(v);
    console.log(v === undefined ? '(未设置)' : String(v));
    return 0;
  }
  if (sub === 'set') {
    if (!key || value === undefined) { console.error('用法: mcore-client config set <path> <value>'); return 1; }
    setPath(raw, key, coerceScalar(value));
    fs.writeFileSync(CONFIG_PATH, emitYamlSubset(raw, 0), { encoding: 'utf8', mode: 0o600 });
    console.log(`已设置 ${key} = ${/api_key/i.test(key) ? redact(value) : value}`);
    return 0;
  }
  console.error('用法: mcore-client config get|set ...');
  return 1;
}

function cliQueue(sub, id) {
  CFG = loadConfig();
  queueInit();
  if (sub === 'list' || !sub) {
    const items = queueList();
    if (!items.length) { console.log('队列为空'); return 0; }
    for (const it of items) console.log(`${it.id}  ${it.state.padEnd(8)} agent=${it.agent.padEnd(9)} msgs=${String(it.messages).padStart(3)} attempts=${it.attempts}`);
    return 0;
  }
  if (sub === 'replay') {
    if (!id) { console.error('用法: mcore-client queue replay <id>'); return 1; }
    const ok = queueReplay(id);
    console.log(ok ? `已重放 ${id}` : `未找到 ${id}`);
    return ok ? 0 : 1;
  }
  console.error('用法: mcore-client queue [list|replay <id>]');
  return 1;
}

function cliDoctor() {
  let ok = true;
  const tick = (cond, label, detail) => {
    console.log(`  ${cond ? '✓' : '✗'} ${label}${detail ? ' — ' + detail : ''}`);
    if (!cond) ok = false;
  };
  console.log('mcore-client doctor');
  const major = parseInt(process.versions.node.split('.')[0], 10);
  tick(major >= 18, `Node 版本 ${process.version}`, major >= 18 ? '' : '需要 >= 18');

  ensureConfig();
  let cfg = null;
  try { cfg = loadConfig(); CFG = cfg; tick(true, '配置文件可解析', CONFIG_PATH); }
  catch (e) { tick(false, '配置文件解析', e.message); }

  if (cfg) {
    let mode = 0;
    try { mode = fs.statSync(CONFIG_PATH).mode & 0o777; } catch (_) {}
    tick((mode & 0o077) === 0, '配置文件权限 600', 'mode=' + mode.toString(8));

    const pid = readPid();
    tick(isAlive(pid), '客户端进程', isAlive(pid) ? `pid ${pid}` : '未运行');

    const d = queueDepth();
    tick(d.dead < 100, '队列健康', `pending=${d.pending} inflight=${d.inflight} dead=${d.dead}`);
  }
  console.log(ok ? '\n全部检查通过' : '\n存在未通过项');
  return ok ? 0 : 1;
}

// ── 超薄传输脚本（供 Codex/Gemini/OpenCode 等仅支持 command 型钩子的 Agent 使用） ──

function thinScripts(port) {
  return {
    'mcore-hook-context.sh': `#!/bin/sh
# mcore-client 超薄传输层：把 Hook payload 转投本地客户端（无任何业务逻辑）
exec curl -sS --max-time 4 -X POST "http://127.0.0.1:${port}/api/v1/hooks/context" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Id: \${MCORE_AGENT_ID:-generic}" \\
  --data-binary @-
`,
    'mcore-hook-ingest.sh': `#!/bin/sh
# mcore-client 超薄传输层：把会话结束事件转投本地客户端（无任何业务逻辑）
exec curl -sS --max-time 6 -X POST "http://127.0.0.1:${port}/api/v1/hooks/ingest" \\
  -H "Content-Type: application/json" \\
  -H "X-Agent-Id: \${MCORE_AGENT_ID:-generic}" \\
  --data-binary @-
`,
  };
}

function deployThinScripts(port) {
  ensureDir(BIN_DIR, 0o700);
  const files = thinScripts(port);
  const written = [];
  for (const [name, content] of Object.entries(files)) {
    const p = path.join(BIN_DIR, name);
    let prev = '';
    try { prev = fs.readFileSync(p, 'utf8'); } catch (_) {}
    if (prev === content) continue;            // 幂等：内容一致则跳过
    fs.writeFileSync(p, content, { encoding: 'utf8', mode: 0o755 });
    try { fs.chmodSync(p, 0o755); } catch (_) {}
    written.push(p);
  }
  return written;
}

function backupFile(p, stamp) {
  if (!fs.existsSync(p)) return;
  const dest = path.join(BACKUP_DIR, stamp, String(p).replace(/^[A-Za-z]:/, '').replace(/[\\/]/g, '__'));
  ensureDir(path.dirname(dest), 0o700);
  try { fs.copyFileSync(p, dest); } catch (_) {}
}

function cliBind(args) {
  const dryRun = args.includes('--dry-run');
  const cfg = loadConfig();
  const port = cfg.localPort;
  const endpoint = `http://127.0.0.1:${port}`;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const changed = [];

  const writeJson = (p, obj) => {
    const next = JSON.stringify(obj, null, 2) + '\n';
    let prev = '';
    try { prev = fs.readFileSync(p, 'utf8'); } catch (_) {}
    if (prev === next) return false;           // 幂等：内容一致则不动
    if (dryRun) return true;
    backupFile(p, stamp);
    ensureDir(path.dirname(p), 0o700);
    fs.writeFileSync(p, next, 'utf8');
    return true;
  };
  const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return {}; } };
  const log = (s) => console.log('  ' + s);

  console.log(`mcore-client bind${dryRun ? ' (dry-run)' : ''} → ${endpoint}`);

  // 1. 超薄脚本
  if (!dryRun) {
    const files = deployThinScripts(port);
    for (const f of files) { changed.push(f); log(`已部署超薄脚本 ${f}`); }
  } else {
    log(`[dry-run] 将部署超薄脚本至 ${BIN_DIR}`);
  }

  // 2. Claude Code
  const claudeJson = path.join(HOME, '.claude.json');
  const claudeSettings = path.join(HOME, '.claude', 'settings.json');
  if (fs.existsSync(claudeJson)) {
    const j = readJson(claudeJson);
    j.mcpServers = j.mcpServers || {};
    j.mcpServers.memorycore = { type: 'http', url: `${endpoint}/mcp`, headers: { 'X-Agent-Id': 'claude' } };
    if (writeJson(claudeJson, j)) { changed.push(claudeJson); log(`Claude MCP → ${endpoint}/mcp`); }
  }
  if (fs.existsSync(path.dirname(claudeSettings))) {
    const s = readJson(claudeSettings);
    s.hooks = s.hooks || {};
    s.hooks.UserPromptSubmit = [{ hooks: [{ type: 'http', url: `${endpoint}/api/v1/hooks/context`, timeout: 5 }] }];
    s.hooks.Stop = [{ hooks: [{ type: 'http', url: `${endpoint}/api/v1/hooks/ingest`, timeout: 10 }] }];
    s.hooks.SessionStart = [{ hooks: [{ type: 'http', url: `${endpoint}/api/v1/hooks/session-start`, timeout: 5 }] }];
    if (writeJson(claudeSettings, s)) { changed.push(claudeSettings); log('Claude Hooks → HTTP 原生形态（零脚本）'); }
  }

  // 3. Hermes
  const hermesCfg = path.join(HOME, '.hermes', 'config.yaml');
  if (fs.existsSync(hermesCfg)) {
    let text = fs.readFileSync(hermesCfg, 'utf8');
    const original = text;
    const re = /(mcp_servers:[\s\S]*?memorycore:[\s\S]*?url:\s*)(\S+)/;
    if (re.test(text)) {
      text = text.replace(re, `$1${endpoint}/mcp`);
      if (text !== original) {
        if (!dryRun) { backupFile(hermesCfg, stamp); fs.writeFileSync(hermesCfg, text, 'utf8'); }
        changed.push(hermesCfg); log(`Hermes MCP → ${endpoint}/mcp`);
      }
    } else {
      log('Hermes 配置中未找到 memorycore 服务器条目，跳过');
    }
  }

  // 4. Codex（MCP + hooks.json）
  const codexHooks = path.join(HOME, '.codex', 'hooks.json');
  if (fs.existsSync(path.join(HOME, '.codex'))) {
    const h = readJson(codexHooks);
    h.hooks = h.hooks || {};
    h.hooks.SessionStart = [{ hooks: [{ type: 'command', command: `MCORE_AGENT_ID=codex sh ${BIN_DIR}/mcore-hook-context.sh`, timeout: 5 }] }];
    h.hooks.UserPromptSubmit = [{ hooks: [{ type: 'command', command: `MCORE_AGENT_ID=codex sh ${BIN_DIR}/mcore-hook-context.sh`, timeout: 5 }] }];
    h.hooks.Stop = [{ hooks: [{ type: 'command', command: `MCORE_AGENT_ID=codex sh ${BIN_DIR}/mcore-hook-ingest.sh`, timeout: 30 }] }];
    if (writeJson(codexHooks, h)) { changed.push(codexHooks); log('Codex Hooks → UserPromptSubmit 读前注入已启用 + Stop 回写'); }
  }

  // 5. Gemini CLI
  const geminiSettings = path.join(HOME, '.gemini', 'settings.json');
  if (fs.existsSync(path.dirname(geminiSettings))) {
    const g = readJson(geminiSettings);
    g.hooks = g.hooks || {};
    g.hooks.BeforeAgent = [{ hooks: [{ type: 'command', command: `MCORE_AGENT_ID=gemini sh ${BIN_DIR}/mcore-hook-context.sh`, timeout: 5000 }] }];
    g.hooks.AfterAgent = [{ hooks: [{ type: 'command', command: `MCORE_AGENT_ID=gemini sh ${BIN_DIR}/mcore-hook-ingest.sh`, timeout: 30000 }] }];
    if (writeJson(geminiSettings, g)) { changed.push(geminiSettings); log('Gemini Hooks → BeforeAgent 注入 + AfterAgent 回写'); }
  }

  // 6. OpenCode
  const ocConfig = path.join(HOME, '.config', 'opencode', 'opencode.json');
  if (fs.existsSync(path.dirname(ocConfig))) {
    const o = readJson(ocConfig);
    o.mcp = o.mcp || {};
    o.mcp.memorycore = { type: 'remote', url: `${endpoint}/mcp` };
    o.hooks = o.hooks || {};
    o.hooks.session_start = `MCORE_AGENT_ID=opencode sh ${BIN_DIR}/mcore-hook-context.sh`;
    o.hooks.session_end = `MCORE_AGENT_ID=opencode sh ${BIN_DIR}/mcore-hook-ingest.sh`;
    if (writeJson(ocConfig, o)) { changed.push(ocConfig); log('OpenCode MCP + Hooks 已指向本地客户端'); }
  }

  console.log(`\n完成，共触及 ${changed.length} 处配置。${dryRun ? '（dry-run 未写入）' : `备份: ${path.join(BACKUP_DIR, stamp)}`}`);
  console.log(`提示：确保 ${BIN_DIR} 在 PATH 中（供 Codex/Gemini/OpenCode 的钩子脚本调用）`);
  return 0;
}

function cliHelp() {
  console.log(`mcore-client v${VERSION} — MemoryCore 本地接入边车

用法: mcore-client <命令> [参数]

命令:
  start [--daemon]      启动客户端（-d 后台守护）
  stop                  停止客户端
  restart               重启客户端
  status                查看客户端与上游连通状态
  switch <profile>      切换上游 Profile（热重载，监听不中断）
  config get [path]     查看配置（api_key 自动脱敏）
  config set <p> <val>  修改配置（点路径，如 profiles.cloud.api_key）
  bind [--dry-run]      一键接管本机 Agent（MCP + Hooks 全部指向本地客户端）
  queue [list|replay <id>]  查看/重放离线回写队列
  doctor                环境体检
  version               版本号
`);
  return 0;
}

// ═══════════════════════════════════════════════════════════════════
// 入口分派
// ═══════════════════════════════════════════════════════════════════

async function main(argv) {
  const [cmd, ...rest] = argv;

  if (cmd === '__serve') {
    try {
      await runServerForeground();
      // 服务模式：常驻不返回，交由信号处理器退出
      await new Promise(() => {});
      return 0;
    } catch (e) { console.error('服务启动失败:', e.message); return 1; }
  }

  switch (cmd) {
    case undefined:
    case 'help':
    case '--help':
    case '-h': return cliHelp();
    case 'version':
    case '--version':
    case '-v': console.log(`mcore-client ${VERSION} (node ${process.version})`); return 0;
    case 'start': return await cliStart(rest);
    case 'stop': return cliStop();
    case 'restart': cliStop(); return await cliStart(rest);
    case 'status': return await cliStatus();
    case 'switch': return cliSwitch(rest[0]);
    case 'config': return cliConfig(rest[0], rest[1], rest[2]);
    case 'queue': return cliQueue(rest[0], rest[1]);
    case 'bind': return cliBind(rest);
    case 'doctor': return cliDoctor();
    default:
      console.error(`未知命令: ${cmd}\n`);
      return cliHelp() || 1;
  }
}

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => {
    // 显式退出，规避实验性 node:sqlite 的退出期 abort
    process.exit(typeof code === 'number' ? code : 0);
  }).catch((e) => {
    console.error('致命错误:', e && e.message ? e.message : String(e));
    process.exit(1);
  });
}

module.exports = { parseYamlSubset, emitYamlSubset, adaptHookPayload, extractCodex, extractGemini, extractClaude, normalizeAgent };
