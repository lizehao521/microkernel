const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const selector = process.argv[4] || '.sheet';
const scale = Number(process.argv[5] || 2);
const port = 9600 + Math.floor(Math.random() * 200);
const profile = path.join(process.env.TEMP || 'C:\\Users\\Admin\\AppData\\Local\\Temp', 'card-shot-' + port);

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
}

(async () => {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, '--window-size=900,1400',
    'about:blank'
  ], { stdio: 'ignore' });
  try {
    await waitVersion();
    const targetRes = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent('about:blank'), { method: 'PUT' });
    const target = await targetRes.json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setEmulatedMedia', { media: 'print' });
    await cdp.send('Page.navigate', { url: 'file:///' + input.replace(/\\/g, '/') });
    await sleep(2200);
    const r = await cdp.send('Runtime.evaluate', {
      expression: `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        const b = el.getBoundingClientRect();
        return { x: b.left + window.scrollX, y: b.top + window.scrollY, width: b.width, height: b.height };
      })()`,
      returnByValue: true
    });
    const box = r.result.value;
    const shot = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
      clip: { x: box.x, y: box.y, width: box.width, height: box.height, scale }
    });
    fs.writeFileSync(output, Buffer.from(shot.data, 'base64'));
    console.log('SHOT_OK ' + JSON.stringify(box) + ' ' + fs.statSync(output).size);
    cdp.ws.close();
  } finally {
    try { child.kill(); } catch (_) {}
  }
})().catch(err => { console.error('SHOT_FAIL ' + err.message); process.exit(1); });
