// 真浏览器里量「叫停 → 界面交出被打断」：MutationObserver，不用 setTimeout 轮询。
// 后台 Tab 把计时器钳到 ~1s，轮询量出来的是钳位不是延迟（上一版 999ms 就是这个假数）。
// 同时把 served app.js/index.html 的字节与盘上源码对哈希：证明跑的是这一版 build。
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const ROOT = path.resolve(__dirname, '..');
const SRCWEB = path.join(ROOT, 'src', 'hubd', 'web');
const EXE = path.join(ROOT, '构建-hubd', 'hubd-停止-1023.exe');
const HUB = process.argv[2] || 'http://127.0.0.1:55378/';
const FAULT = process.argv[3] || 'http://127.0.0.1:55377/slow';
const OUT = path.resolve(process.argv[4] || path.join(ROOT, '读数', '浏览器-停止-1023.json'));
const PNG = path.resolve(process.argv[5] || path.join(ROOT, '读数', '截图', 'hubd-停止-1023.png'));
const port = 9600 + Math.floor(Math.random() * 300);
const profile = path.join(process.env.TEMP || '.', 'hubd-probe', 'edge-' + port);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

async function waitVersion() {
  for (let i = 0; i < 120; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + port + '/json/version');
      if (r.ok) return await r.json();
    } catch (_) {}
    await sleep(250);
  }
  throw new Error('EDGE_DEBUG_NOT_READY');
}

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.pending = new Map();
    this.events = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      } else if (msg.method && this.events.has(msg.method)) {
        for (const fn of this.events.get(msg.method)) fn(msg.params);
      }
    };
  }
  async send(method, params = {}) {
    await this.ready;
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  once(method, timeout = 30000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('TIMEOUT ' + method)), timeout);
      const fn = (params) => {
        clearTimeout(timer);
        this.events.get(method).delete(fn);
        resolve(params);
      };
      if (!this.events.has(method)) this.events.set(method, new Set());
      this.events.get(method).add(fn);
    });
  }
}

function 页内探针(how, fault) {
  return `(async () => {
  const $ = (id) => document.getElementById(id);
  const band = $('band'), calls = $('calls'), input = $('input'), form = $('say'), msgs = $('msgs');
  const waitText = (el, needle, ms) => new Promise((res) => {
    const hit = () => (el.innerText || '').includes(needle);
    if (hit()) return res(true);
    const mo = new MutationObserver(() => { if (hit()) { mo.disconnect(); res(true); } });
    mo.observe(el, { childList: true, subtree: true, characterData: true });
    setTimeout(() => { mo.disconnect(); res(false); }, ms);
  });
  input.value = '取一下 ' + ${JSON.stringify(fault)};
  form.requestSubmit();
  const sawTool = await waitText(calls, 'http.get', 8000);
  // 前提：工具那一行已经亮出来（真的在跑慢端点上），这时才按叫停。
  const t0 = performance.now();
  if (${JSON.stringify(how)} === 'esc') {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  } else {
    $('stop').click();
  }
  const seen = await waitText(band, '结束=被打断', 8000);
  const ms = performance.now() - t0;
  await new Promise((r) => setTimeout(r, 500));
  const 行 = [...calls.querySelectorAll('li.call')];
  const bodyText = document.body.innerText || '';
  return {
    how: ${JSON.stringify(how)},
    sawTool: sawTool, seen: seen, ms: Math.round(ms),
    budget: $('budget').textContent,
    stopLine: ((band.innerText || '').split('\\n').filter((x) => x.includes('结束=')).slice(-1)[0] || '').slice(0, 200),
    steps: 行.length,
    callText: 行.map((li) => (li.innerText || '').replace(/\\s+/g, ' ').slice(0, 220)),
    saneText: (band.innerText || '').includes('自洽=过'),
    dirty: ['undefined', 'NaN', '[object Object]'].filter((k) => bodyText.includes(k))
  };
})()`;
}

(async () => {
  const exeBuf = fs.readFileSync(EXE);
  const servedApp = Buffer.from(await (await fetch(HUB + 'app.js')).arrayBuffer());
  const servedIdx = Buffer.from(await (await fetch(HUB + 'index.html')).arrayBuffer());
  const diskApp = fs.readFileSync(path.join(SRCWEB, 'app.js'));
  const diskIdx = fs.readFileSync(path.join(SRCWEB, 'index.html'));

  fs.mkdirSync(profile, { recursive: true });
  fs.mkdirSync(path.dirname(PNG), { recursive: true });
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--window-size=1440,900',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank'
  ], { stdio: 'ignore' });
  let 读 = { 时刻: new Date().toISOString(), hub: HUB, fault: FAULT,
    exe: EXE, exe_bytes: exeBuf.length, exe_sha256: sha(exeBuf),
    served_app_js_sha256: sha(servedApp), disk_app_js_sha256: sha(diskApp),
    served_app_js_equals_disk: sha(servedApp) === sha(diskApp),
    served_index_sha256: sha(servedIdx), disk_index_sha256: sha(diskIdx),
    served_index_equals_disk: sha(servedIdx) === sha(diskIdx),
    手法: 'MutationObserver 等 #band 出现「结束=被打断」；不用 setTimeout 轮询（后台 Tab 计时器会被钳到 ~1s，轮询量的是钳位不是延迟）',
    探针: [] };
  try {
    await waitVersion();
    const target = await (await fetch('http://127.0.0.1:' + port + '/json/new?about:blank', { method: 'PUT' })).json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    const loaded = cdp.once('Page.loadEventFired', 30000).catch(() => null);
    await cdp.send('Page.navigate', { url: HUB });
    await loaded;
    await sleep(800);

    for (const how of ['stop-button', 'esc']) {
      const r = await cdp.send('Runtime.evaluate', { expression: 页内探针(how, FAULT), awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error('页内探针抛错：' + JSON.stringify(r.exceptionDetails).slice(0, 400));
      读.探针.push(r.result.value);
    }

    const idle = await cdp.send('Runtime.evaluate', {
      expression: "fetch('/api/stop',{method:'POST'}).then(r=>r.json())", awaitPromise: true, returnByValue: true
    });
    读.空闲叫停 = idle.result.value;

    const 量 = await cdp.send('Page.getLayoutMetrics');
    const h = Math.ceil(量.cssContentSize.height);
    const 图 = await cdp.send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: Math.ceil(量.cssContentSize.width), height: h, scale: 1 }
    });
    fs.writeFileSync(PNG, Buffer.from(图.data, 'base64'));

    const 过 = 读.探针.every((p) => p.sawTool && p.seen && p.ms < 1000 && p.saneText && p.dirty.length === 0);
    读.判据 = {
      '两次都在 1 秒内交出被打断': 过,
      '前提工具行都亮过': 读.探针.every((p) => p.sawTool),
      '每次恰好 1 步': 读.探针.every((p) => p.steps === 1),
      '引用不到脏字': 读.探针.every((p) => p.dirty.length === 0),
      '跑的 build 前端字节等于盘上源码': 读.served_app_js_equals_disk && 读.served_index_equals_disk,
      '截图': PNG, '截图像素': 量.cssContentSize.width + 'x' + h
    };
    读.过 = 过 && 读.判据['跑的 build 前端字节等于盘上源码'];
    fs.writeFileSync(OUT, JSON.stringify(读, null, 2), 'utf8');
    console.log('PROBE_OK ' + 读.探针.map((p) => p.how + '=' + p.ms + 'ms').join(' ') +
      ' built=' + (读.判据['跑的 build 前端字节等于盘上源码']) + ' pass=' + 读.过);
    cdp.ws.close();
  } catch (e) {
    fs.writeFileSync(OUT, JSON.stringify(Object.assign(读, { 错: String(e.message || e) }), null, 2), 'utf8');
    console.error('PROBE_FAIL ' + (e.message || e));
    process.exitCode = 1;
  } finally {
    try { child.kill(); } catch (_) {}
    await sleep(600);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  }
})();
