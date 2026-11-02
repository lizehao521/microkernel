const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
const port = 9670 + Math.floor(Math.random() * 120);
const profile = path.join(process.env.TEMP, 'blueprint-shots', 'edge-' + port);
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitVersion() {
  for (let i = 0; i < 120; i++) {
    try { const r = await fetch('http://127.0.0.1:' + port + '/json/version'); if (r.ok) return r.json(); } catch (_) {}
    await sleep(250);
  }
  throw new Error('NOT_READY');
}
class CDP {
  constructor(url) {
    this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); this.events = new Map();
    this.ready = new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { const { resolve, reject } = this.pending.get(m.id); this.pending.delete(m.id); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); }
      else if (m.method && this.events.has(m.method)) for (const fn of this.events.get(m.method)) fn(m.params);
    };
  }
  async send(method, params = {}) { await this.ready; const id = ++this.id; return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); }); }
  once(method, timeout = 30000) { return new Promise((resolve, reject) => { const t = setTimeout(() => reject(new Error('TIMEOUT')), timeout); const fn = p => { clearTimeout(t); this.events.get(method).delete(fn); resolve(p); }; if (!this.events.has(method)) this.events.set(method, new Set()); this.events.get(method).add(fn); }); }
}
(async () => {
  fs.mkdirSync(outDir, { recursive: true }); fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, ['--headless=new','--disable-gpu','--no-first-run','--disable-extensions','--remote-debugging-port='+port,'--user-data-dir='+profile,'about:blank'], {stdio:'ignore'});
  try {
    await waitVersion();
    const url = 'file:///' + input.replace(/\\/g,'/');
    const tr = await fetch('http://127.0.0.1:'+port+'/json/new?'+encodeURIComponent(url), {method:'PUT'});
    const t = await tr.json();
    const cdp = new CDP(t.webSocketDebuggerUrl);
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
    const loaded = cdp.once('Page.loadEventFired').catch(()=>null);
    await cdp.send('Page.navigate', {url}); await loaded; await sleep(1000);
    await cdp.send('Emulation.setDeviceMetricsOverride', {width:1440, height:900, deviceScaleFactor:1, mobile:false});
    await sleep(500);
    const rects = await cdp.send('Runtime.evaluate', {expression: `(() => [...document.querySelectorAll('section')].map(s => { const r = s.getBoundingClientRect(); return {id:s.id, x:0, y:r.top + window.scrollY, w:document.documentElement.clientWidth, h:r.height}; }))()`, returnByValue:true});
    const out = [];
    for (const r of rects.result.value) {
      const shot = await cdp.send('Page.captureScreenshot', {format:'png', captureBeyondViewport:true, fromSurface:true, clip:{x:r.x, y:r.y, width:r.w, height:Math.ceil(r.h), scale:1}});
      const f = path.join(outDir, '节-' + r.id + '.png');
      fs.writeFileSync(f, Buffer.from(shot.data, 'base64'));
      out.push({id:r.id, bytes:fs.statSync(f).size, h:Math.round(r.h)});
    }
    console.log(JSON.stringify(out, null, 2));
    cdp.ws.close();
  } finally { try { child.kill(); } catch(_){} }
})().catch(e => { console.error('SHOTS_FAIL ' + e.message); process.exit(1); });
