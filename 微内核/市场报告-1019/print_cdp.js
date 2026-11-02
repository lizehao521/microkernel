const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const port = 9400 + Math.floor(Math.random() * 400);
const profile = path.join(process.env.TEMP || 'C:\\Users\\Admin\\AppData\\Local\\Temp', 'mktpdf', 'edge-' + port);

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

(async () => {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--disable-extensions',
    '--remote-debugging-port=' + port,
    '--user-data-dir=' + profile,
    'about:blank'
  ], { stdio: 'ignore' });
  try {
    await waitVersion();
    const targetRes = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent('file:///' + input.replace(/\\/g, '/')), { method: 'PUT' });
    const target = await targetRes.json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await sleep(1200);
    const loaded = cdp.once('Page.loadEventFired', 30000).catch(() => null);
    await cdp.send('Page.navigate', { url: 'file:///' + input.replace(/\\/g, '/') });
    await loaded;
    await sleep(2500);

    const footer = '<div style="width:100%; padding:0 15mm; font-family:\'Microsoft YaHei\',sans-serif; font-size:8px; color:#5b6b7f; display:flex; justify-content:space-between; align-items:center;">' +
      '<span>Agentkernel 市场进入研究 · 2026-10-19</span>' +
      '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span>' +
      '</div>';
    const result = await cdp.send('Page.printToPDF', {
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<div></div>',
      footerTemplate: footer,
      paperWidth: 8.27,
      paperHeight: 11.69,
      marginTop: 0.75,
      marginBottom: 0.71,
      marginLeft: 0.59,
      marginRight: 0.59,
      scale: 1,
      preferCSSPageSize: false
    });
    fs.writeFileSync(output, Buffer.from(result.data, 'base64'));
    console.log('CDP_OK ' + fs.statSync(output).size);
    cdp.ws.close();
  } finally {
    try { child.kill(); } catch (_) {}
  }
})().catch((err) => {
  console.error('CDP_FAIL ' + err.message);
  process.exit(1);
});
