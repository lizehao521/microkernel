const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const port = 9800 + Math.floor(Math.random() * 200);
const profile = path.join(process.env.TEMP || 'C:\\Users\\Admin\\AppData\\Local\\Temp', 'card-measure-' + port);

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
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank'
  ], { stdio: 'ignore' });
  try {
    await waitVersion();
    const targetRes = await fetch('http://127.0.0.1:' + port + '/json/new?' + encodeURIComponent('file:///' + input.replace(/\\/g, '/')), { method: 'PUT' });
    const target = await targetRes.json();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await sleep(800);
    await cdp.send('Page.navigate', { url: 'file:///' + input.replace(/\\/g, '/') });
    await sleep(2200);
    const r = await cdp.send('Runtime.evaluate', {
      expression: `(() => {
        const q = s => document.querySelector(s);
        const rect = s => { const el=q(s); if(!el) return null; const b=el.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,height:b.height}; };
        const body=q('.body');
        const secs=[...document.querySelectorAll('.sec')].map((el,i)=>({i:i+1,top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom,height:el.getBoundingClientRect().height}));
        return {
          sheet: rect('.sheet'), body: rect('.body'), foot: rect('.body > .foot'),
          decide: rect('.decide'),
          bodyScroll: body?body.scrollHeight:null, bodyClient: body?body.clientHeight:null,
          docScroll: document.documentElement.scrollHeight,
          secs,
          font: getComputedStyle(document.body).fontFamily
        };
      })()`,
      returnByValue: true
    });
    console.log(JSON.stringify(r.result.value, null, 1));
    cdp.ws.close();
  } finally {
    try { child.kill(); } catch (_) {}
  }
})().catch(err => { console.error('MEASURE_FAIL ' + err.message); process.exit(1); });
