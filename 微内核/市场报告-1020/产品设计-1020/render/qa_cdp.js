const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
const port = 9500 + Math.floor(Math.random() * 300);
const profile = path.join(process.env.TEMP || 'C:\\Users\\Admin\\AppData\\Local\\Temp', 'blueprint-qa', 'edge-' + port);

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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

const probe = `(() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.right > vw + 1 || r.left < -1) {
      const s = getComputedStyle(el);
      if (s.position === 'fixed') continue;
      offenders.push({tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 40), left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width)});
      if (offenders.length >= 8) break;
    }
  }
  const ext = [...document.querySelectorAll('script[src],link[href],img[src],iframe[src]')].map(e => e.src || e.href).filter(u => u && !u.startsWith('file:') && !u.startsWith('data:'));
  return {
    viewport: vw + 'x' + window.innerHeight,
    docScrollWidth: de.scrollWidth,
    docClientWidth: vw,
    overflow: de.scrollWidth > vw,
    offenders,
    sections: [...document.querySelectorAll('section')].map(s => s.id),
    h2s: [...document.querySelectorAll('h2')].map(h => h.innerText.trim()),
    tables: document.querySelectorAll('table').length,
    externalResources: ext,
    bodyTextLen: document.body.innerText.length
  };
})()`;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank'
  ], { stdio: 'ignore' });
  try {
    await waitVersion();
    const url = 'file:///' + input.replace(/\\/g, '/');
    const targetRes = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent(url), { method: 'PUT' });
    const target = await targetRes.json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    const consoleEntries = [];
    cdp.events.set('Log.entryAdded', new Set([(p) => consoleEntries.push({ level: p.entry.level, text: p.entry.text })]));
    cdp.events.set('Runtime.exceptionThrown', new Set([(p) => consoleEntries.push({ level: 'exception', text: p.exceptionDetails.text })]));
    await cdp.send('Log.enable');
    const loaded = cdp.once('Page.loadEventFired', 30000).catch(() => null);
    await cdp.send('Page.navigate', { url });
    await loaded;
    await sleep(1200);

    const results = [];
    for (const [w, h] of [[1440, 900], [1024, 900], [390, 844]]) {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await sleep(500);
      const evalRes = await cdp.send('Runtime.evaluate', { expression: probe, returnByValue: true });
      results.push(evalRes.result.value);
    }

    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(600);
    const lm = await cdp.send('Page.getLayoutMetrics');
    const cs = lm.cssContentSize;
    const shot = await cdp.send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true, fromSurface: true,
      clip: { x: 0, y: 0, width: cs.width, height: cs.height, scale: 1 }
    });
    fs.writeFileSync(path.join(outDir, '蓝图-桌面1440-全页.png'), Buffer.from(shot.data, 'base64'));

    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const top = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
    fs.writeFileSync(path.join(outDir, '蓝图-桌面1440-首屏.png'), Buffer.from(top.data, 'base64'));

    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const mob = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
    fs.writeFileSync(path.join(outDir, '蓝图-窄屏390-首屏.png'), Buffer.from(mob.data, 'base64'));

    const a11y = await cdp.send('Accessibility.getFullAXTree');
    const headingCount = a11y.nodes.filter(n => n.role && n.role.value === 'heading').length;

    console.log(JSON.stringify({ results, contentSize: { w: Math.round(cs.width), h: Math.round(cs.height) }, axHeadings: headingCount, consoleEntries }, null, 2));
    cdp.ws.close();
  } finally {
    try { child.kill(); } catch (_) {}
  }
})().catch((err) => {
  console.error('QA_FAIL ' + err.message);
  process.exit(1);
});
