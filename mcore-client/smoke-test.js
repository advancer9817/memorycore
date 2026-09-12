#!/usr/bin/env node
/**
 * mcore-client 冒烟回归测试（hermetic：内置 stub 上游，无需真实 mcore 服务端）
 *
 * 覆盖：透传 / 凭据注入 / 读路径注入与噪声护栏 / 写路径入队与投递 / 管理面 / 缓存
 * 用法：node smoke-test.js
 * 退出码：0 全部通过，1 存在失败
 */
'use strict';

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const ROOT = __dirname;
const CLIENT = path.join(ROOT, 'mcore-client.js');
const UP_PORT = 18401;
const CL_PORT = 18402;
const TEST_HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'mcore-smoke-'));

const results = [];
function check(name, cond, detail) {
  results.push({ name, ok: !!cond, detail: detail || '' });
  console.log(`  ${cond ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`);
}

// ── stub 上游：记录收到的凭据与调用 ───────────────────────────────
const seen = { headers: [], ingestBatches: [], mcpCalls: 0 };

const upstream = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const body = Buffer.concat(chunks).toString('utf8');
    seen.headers.push({ tenant: req.headers['x-tenant-id'], key: req.headers['x-api-key'], client: req.headers['x-client-info'] });

    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, data: { status: 'ok' } }));
    }
    let payload = {};
    try { payload = JSON.parse(body || '{}'); } catch (_) {}

    if (payload.method === 'tools/list') {
      seen.mcpCalls++;
      res.writeHead(200, { 'Content-Type': 'application/json', 'Mcp-Session-Id': 'upstream-sid-1' });
      return res.end(JSON.stringify({ jsonrpc: '2.0', id: payload.id, result: { tools: [{ name: 'memory_context' }, { name: 'memory_ingest' }] } }));
    }
    if (payload.method === 'tools/call' && payload.params && payload.params.name === 'memory_context') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({
        jsonrpc: '2.0', id: payload.id,
        result: { content: [{ type: 'text', text: JSON.stringify({ context: 'STUB-CONTEXT-OK' }) }] },
      }));
    }
    if (payload.method === 'tools/call' && payload.params && payload.params.name === 'memory_ingest') {
      seen.ingestBatches.push(payload.params.arguments);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ jsonrpc: '2.0', id: payload.id, result: { content: [{ type: 'text', text: '{"added":1}' }] } }));
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ jsonrpc: '2.0', id: payload.id, result: {} }));
  });
});

function httpJson(method, url, body, headers) {
  return new Promise((resolve) => {
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname + u.search, method, headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}) }, (res) => {
      const c = [];
      res.on('data', (x) => c.push(x));
      res.on('end', () => {
        const t = Buffer.concat(c).toString('utf8');
        let j = null; try { j = JSON.parse(t); } catch (_) {}
        resolve({ status: res.statusCode, body: t, json: j });
      });
    });
    req.on('error', (e) => resolve({ status: 0, body: String(e.message), json: null }));
    if (body != null) req.write(typeof body === 'string' ? body : JSON.stringify(body));
    req.end();
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  console.log('mcore-client 冒烟测试');
  console.log(`  隔离 HOME: ${TEST_HOME}\n`);

  // 准备隔离配置
  fs.mkdirSync(path.join(TEST_HOME, '.mcore'), { recursive: true });
  fs.writeFileSync(path.join(TEST_HOME, '.mcore', 'client.yaml'), `version: "1.0"
active_profile: "test"
profiles:
  test:
    server_url: "http://127.0.0.1:${UP_PORT}"
    tenant_id: "smoke-tenant"
    api_key: "smoke-key-secret"
    retry_max: 1
local_server:
  host: "127.0.0.1"
  port: ${CL_PORT}
resilience:
  enable_cache: true
  cache_ttl_s: 60
  enable_wal_queue: true
  queue_max_items: 100
  retry_dead_after: 3
`, { mode: 0o600 });

  // 构造 Claude 转录
  const transcript = path.join(TEST_HOME, 'claude.jsonl');
  fs.writeFileSync(transcript, [
    JSON.stringify({ type: 'user', message: { role: 'user', content: '冒烟测试：验证客户端写路径是否可用' } }),
    JSON.stringify({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: '客户端应把转录入队并异步投递上游 memory_ingest。' }] } }),
  ].join('\n') + '\n');

  await new Promise((r) => upstream.listen(UP_PORT, '127.0.0.1', r));
  console.log('  · stub 上游已启动\n');

  const child = spawn(process.execPath, [CLIENT, 'start'], {
    env: Object.assign({}, process.env, { HOME: TEST_HOME, MCORE_CLIENT_HOME: path.join(TEST_HOME, '.mcore') }),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let clientOut = '';
  child.stdout.on('data', (d) => { clientOut += d.toString(); });
  child.stderr.on('data', (d) => { clientOut += d.toString(); });

  const base = `http://127.0.0.1:${CL_PORT}`;
  await sleep(1500);

  try {
    // 1. 复合健康
    const h = await httpJson('GET', `${base}/health`);
    check('健康检查返回 client running', h.json && h.json.client && h.json.client.status === 'running');
    check('健康检查探测到上游 connected', h.json && h.json.upstream && h.json.upstream.status === 'connected');

    // 2. MCP 透传
    const m = await httpJson('POST', `${base}/mcp`, { jsonrpc: '2.0', id: 1, method: 'tools/list' });
    check('MCP 透传返回 2 个工具', m.json && m.json.result && m.json.result.tools && m.json.result.tools.length === 2);

    // 3. 凭据注入
    const inj = seen.headers.find((x) => x.tenant === 'smoke-tenant');
    check('出站自动注入 X-Tenant-Id', !!inj);
    check('出站自动注入 X-API-Key', !!(inj && inj.key === 'smoke-key-secret'));
    check('出站附带 X-Client-Info', !!(inj && /mcore-client\//.test(inj.client || '')));

    // 4. 读路径注入
    const c1 = await httpJson('POST', `${base}/api/v1/hooks/context`, { hook_event_name: 'UserPromptSubmit', tool_input: { prompt: '冒烟测试上下文注入' } }, { 'X-Agent-Id': 'claude' });
    check('读路径返回 hookSpecificOutput.additionalContext', !!(c1.json && c1.json.hookSpecificOutput && c1.json.hookSpecificOutput.additionalContext === 'STUB-CONTEXT-OK'));

    // 5. 缓存命中
    const t0 = Date.now();
    await httpJson('POST', `${base}/api/v1/hooks/context`, { hook_event_name: 'UserPromptSubmit', tool_input: { prompt: '冒烟测试上下文注入' } }, { 'X-Agent-Id': 'claude' });
    const dt = Date.now() - t0;
    const st = await httpJson('GET', `${base}/_admin/stats`);
    check('第二次相同 prompt 命中缓存', st.json && st.json.counters.hook_context_cache_hits >= 1, `${dt}ms`);

    // 6. 噪声护栏
    const c2 = await httpJson('POST', `${base}/api/v1/hooks/context`, { prompt: '现在TODO还有啥' }, { 'X-Agent-Id': 'codex' });
    check('Codex 泛化短查询返回空注入', !!(c2.json && c2.json.hookSpecificOutput && c2.json.hookSpecificOutput.additionalContext === ''));

    // 7. 写路径
    const ing = await httpJson('POST', `${base}/api/v1/hooks/ingest`, { hook_event_name: 'Stop', transcript_path: transcript }, { 'X-Agent-Id': 'claude' });
    check('ingest 立即应答 200', ing.status === 200 && ing.json && ing.json.queued === true);

    await sleep(3000);
    check('转录已投递上游 memory_ingest', seen.ingestBatches.length >= 1, `批次=${seen.ingestBatches.length}`);
    const batch = seen.ingestBatches[0];
    check('投递载荷含 2 条消息', !!(batch && batch.messages && batch.messages.length === 2));
    check('投递载荷 agent_id 正确', !!(batch && batch.agent_id === 'claude'));
    check('投递载荷 project_path 字段存在', !!(batch && 'project_path' in batch));

    const q = await httpJson('GET', `${base}/_admin/queue`);
    const done = (q.json && q.json.items || []).filter((i) => i.state === 'done').length;
    check('队列排空（done ≥ 1）', done >= 1, `done=${done}`);

    // 8. 管理面回环限制（用非回环地址不可测，此处验证端点存在）
    const admin = await httpJson('GET', `${base}/_admin/stats`);
    check('管理面 stats 可访问', !!(admin.json && admin.json.ok === true));
  } catch (e) {
    check('冒烟流程未抛异常', false, String(e.message));
  } finally {
    try { child.kill('SIGTERM'); } catch (_) {}
    await sleep(400);
    try { child.kill('SIGKILL'); } catch (_) {}
    upstream.close();
    try { fs.rmSync(TEST_HOME, { recursive: true, force: true }); } catch (_) {}
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果: ${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) {
    console.log('失败项:');
    for (const f of failed) console.log(`  - ${f.name} ${f.detail}`);
  }
  process.exit(failed.length ? 1 : 0);
})();
