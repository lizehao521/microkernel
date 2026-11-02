const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const URL = process.argv[2] || 'http://127.0.0.1:57195/';
const OUT = path.resolve(process.argv[3] || '读数/截图-v2');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const port = 9800 + Math.floor(Math.random() * 180);
const profile = path.join(process.env.TEMP || 'C:\\Users\\Admin\\AppData\\Local\\Temp', 'weihuetai-shots', 'edge-' + port);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank',
  ], { stdio: 'ignore' });
  const made = [];
  try {
    await waitVersion();
    const targetRes = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent('about:blank'), { method: 'PUT' });
    const target = await targetRes.json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    const loaded = cdp.once('Page.loadEventFired', 30000).catch(() => null);
    await cdp.send('Page.navigate', { url: URL });
    await loaded;
    await sleep(1600);

    async function js(fn, arg) {
      const expr = '(' + fn.toString() + ')(' + JSON.stringify(arg === undefined ? null : arg) + ')';
      const r = await cdp.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error('JS ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
      return r.result.value;
    }
    async function shot(name) {
      await js(async () => {
        document.querySelectorAll('#toasts .toast').forEach((t) => t.remove());
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      });
      const r = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
      const p = path.join(OUT, name);
      fs.writeFileSync(p, Buffer.from(r.data, 'base64'));
      made.push(name + ' ' + fs.statSync(p).size);
      console.log('SHOT ' + name + ' ' + fs.statSync(p).size);
    }
    const ready = await js(async () => {
      for (let i = 0; i < 60; i++) {
        if (document.querySelectorAll('.q-item').length === 3) return true;
        await new Promise((r) => setTimeout(r, 100));
      }
      return false;
    });
    if (!ready) throw new Error('APP_NOT_READY');

    const pillNav = await js(async () => {
      document.querySelector('#modelPill')?.click();
      await new Promise((r) => setTimeout(r, 250));
      const ok = document.querySelector('#view-dialogue')?.classList.contains('is-active');
      document.querySelector('#modeOperate')?.click();
      await new Promise((r) => setTimeout(r, 200));
      return !!ok;
    });
    console.log('MODEL_PILL_NAV ' + pillNav);
    if (!pillNav) throw new Error('MODEL_PILL_NAV_FAIL');

    const decided = await js(async (pairs) => {
      const out = [];
      for (const [id, action, reason] of pairs) {
        document.querySelector('.q-item[data-id="' + id + '"]')?.click();
        await new Promise((r) => setTimeout(r, 250));
        document.querySelector('[data-action="' + action + '"]')?.click();
        await new Promise((r) => setTimeout(r, 250));
        const ta = document.querySelector('#decReason');
        if (ta) ta.value = reason;
        document.querySelector('#decConfirm')?.click();
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 100));
          if (!document.querySelector('#modalDecision')?.classList.contains('is-open')) break;
        }
        out.push(id + ' ' + (document.querySelector('.decision-state')?.innerText || 'NO_STATE').replace(/\s+/g, ' ').slice(0, 30));
      }
      return out;
    }, [
      ['D-1026-01', 'reject', '测试声明没有盘上证据'],
      ['D-1026-03', 'hold', '证据缺席，无法判断'],
      ['D-1026-02', 'accept', '声明与盘上证据全部相符'],
    ]);
    console.log('SEED ' + decided.join(' | '));

    await js(async () => {
      document.querySelector('.q-item[data-id="D-1026-01"]')?.click();
      await new Promise((r) => setTimeout(r, 350));
    });
    await shot('01-operate-D1.png');

    await js(async () => {
      document.querySelector('.q-item[data-id="D-1026-02"]')?.click();
      await new Promise((r) => setTimeout(r, 250));
      document.querySelector('[data-open-drawer="cells"]')?.click();
      await new Promise((r) => setTimeout(r, 450));
    });
    await shot('02-drawer-cells-D2.png');

    await js(async () => {
      document.querySelector('#drawerClose')?.click();
      await new Promise((r) => setTimeout(r, 200));
      document.querySelector('.q-item[data-id="D-1026-01"]')?.click();
      await new Promise((r) => setTimeout(r, 250));
      document.querySelector('[data-open-drawer="steps"]')?.click();
      await new Promise((r) => setTimeout(r, 450));
    });
    await shot('03-drawer-steps-D1.png');

    await js(async () => {
      document.querySelector('#drawerClose')?.click();
      await new Promise((r) => setTimeout(r, 200));
      document.querySelector('.q-item[data-id="D-1026-03"]')?.click();
      await new Promise((r) => setTimeout(r, 250));
      document.querySelector('[data-open-drawer="events"]')?.click();
      await new Promise((r) => setTimeout(r, 450));
    });
    await shot('04-drawer-events-D3.png');

    await js(async () => {
      document.querySelector('#drawerClose')?.click();
      await new Promise((r) => setTimeout(r, 200));
      document.querySelector('#btnMemory')?.click();
      await new Promise((r) => setTimeout(r, 450));
    });
    await shot('05-memory-decisions.png');

    await js(async () => {
      document.querySelector('#modeDialogue')?.click();
      await new Promise((r) => setTimeout(r, 250));
      const form = document.querySelector('#chatForm');
      const input = document.querySelector('#chatInput');
      for (const q of ['这版能收吗？', '测试过了吗？', '事件断线可续吗？']) {
        const before = document.querySelectorAll('.msg.assistant').length;
        input.value = q;
        form.requestSubmit();
        for (let i = 0; i < 50; i++) {
          await new Promise((r) => setTimeout(r, 100));
          if (document.querySelectorAll('.msg.assistant').length > before && !document.querySelector('#chatPending')) break;
        }
      }
      await new Promise((r) => setTimeout(r, 300));
    });
    await shot('06-dialogue-answers.png');

    const modelShot = await js(async () => {
      const cb = document.querySelector('#useModel');
      if (!cb || cb.disabled) return false;
      cb.click();
      await new Promise((r) => setTimeout(r, 120));
      const form = document.querySelector('#chatForm');
      const input = document.querySelector('#chatInput');
      const before = document.querySelectorAll('.msg.assistant').length;
      input.value = '接入验收：哪几条声明与盘上不符？';
      form.requestSubmit();
      for (let i = 0; i < 80; i++) {
        await new Promise((r) => setTimeout(r, 100));
        if (document.querySelectorAll('.msg.assistant').length > before && !document.querySelector('#chatPending')) break;
      }
      await new Promise((r) => setTimeout(r, 300));
      const last = [...document.querySelectorAll('.msg.assistant')].pop();
      return {
        enabled: !document.querySelector('#useModel').disabled,
        tier: last?.querySelector('.tier-badge')?.textContent || '',
        foot: last?.querySelector('.msg-foot')?.textContent || '',
        note: document.querySelector('#modelNote')?.textContent || '',
      };
    });
    if (modelShot) {
      console.log('MODEL_UI ' + JSON.stringify(modelShot));
      if (!modelShot.enabled || modelShot.tier !== '模型转述' || !modelShot.foot.includes('模型转述 · 不是证据')) {
        throw new Error('MODEL_UI_ASSERT_FAIL');
      }
      await shot('06b-dialogue-model.png');
    } else console.log('MODEL_SHOT skipped');

    await js(async () => {
      document.querySelector('#modeOperate')?.click();
      await new Promise((r) => setTimeout(r, 200));
      document.querySelector('#kernelPill')?.click();
      await new Promise((r) => setTimeout(r, 500));
    });
    await shot('07-kernel-modal.png');

    const cleared = await js(async () => {
      document.querySelector('[data-close-modal="modalKernel"]')?.click();
      const r = await fetch('/api/memory/clear', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'CLEAR' }),
      });
      return r.status;
    });
    console.log('CLEAR ' + cleared);
    const reloaded = cdp.once('Page.loadEventFired', 30000).catch(() => null);
    await cdp.send('Page.reload', { ignoreCache: true });
    await reloaded;
    await sleep(1400);

    await js(async () => {
      document.querySelector('.q-item[data-id="D-1026-02"]')?.click();
      await new Promise((r) => setTimeout(r, 300));
    });
    await shot('08-operate-pending.png');

    await js(async () => {
      document.querySelector('[data-action="accept"]')?.click();
      await new Promise((r) => setTimeout(r, 300));
    });
    await shot('09-decision-modal.png');

    await js(async () => {
      document.querySelector('[data-close-modal="modalDecision"]')?.click();
      await new Promise((r) => setTimeout(r, 150));
      document.querySelector('#modeDialogue')?.click();
      await new Promise((r) => setTimeout(r, 400));
    });
    await shot('10-dialogue-empty.png');

    console.log('CDP_OK ' + made.length + ' shots');
    cdp.ws.close();
  } finally {
    try { child.kill(); } catch (_) {}
  }
})().catch((err) => {
  console.error('CDP_FAIL ' + err.message);
  process.exit(1);
});
