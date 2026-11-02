const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const input = path.resolve(process.argv[2]);
const port = 9820 + Math.floor(Math.random() * 150);
const profile = path.join(process.env.TEMP, 'blueprint-probe', 'edge-' + port);
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
const expr = `(() => {
  const de = document.documentElement, vw = de.clientWidth;
  const insideScroller = el => { let p = el.parentElement; while (p) { const s = getComputedStyle(p); if (/(auto|scroll|hidden)/.test(s.overflowX)) return true; p = p.parentElement; } return false; };
  const rows = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.right > vw + 1) rows.push({tag: el.tagName.toLowerCase(), cls: (el.className||'').toString().slice(0,50), id: el.id||'', left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width), sw: el.scrollWidth, cw: el.clientWidth, scroller: insideScroller(el), pos: getComputedStyle(el).position});
  }
  const roots = [];
  for (const el of document.body.children) { const r = el.getBoundingClientRect(); roots.push({tag: el.tagName.toLowerCase(), cls: (el.className||'').toString().slice(0,40), id: el.id||'', w: Math.round(r.width), right: Math.round(r.right), sw: el.scrollWidth, cw: el.clientWidth, ovx: getComputedStyle(el).overflowX}); }
  return {vw, docSW: de.scrollWidth, bodySW: document.body.scrollWidth, bodyCW: document.body.clientWidth, roots, rows: rows.slice(0, 30)};
})()`;
(async () => {
  fs.mkdirSync(profile, { recursive: true });
  const child = spawn(EDGE, ['--headless=new','--disable-gpu','--no-first-run','--disable-extensions','--remote-debugging-port='+port,'--user-data-dir='+profile,'about:blank'], {stdio:'ignore'});
  try {
    await waitVersion();
    const url = 'file:///' + input.replace(/\\/g,'/');
    const tr = await fetch('http://127.0.0.1:'+port+'/json/new?'+encodeURIComponent(url), {method:'PUT'});
    const t = await tr.json();
    const cdp = new CDP(t.webSocketDebuggerUrl);
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
    const loaded = cdp.once('Page.loadEventFired').catch(()=>null);
    await cdp.send('Page.navigate', {url}); await loaded; await sleep(1200);
    await cdp.send('Emulation.setDeviceMetricsOverride', {width:375, height:844, deviceScaleFactor:1, mobile:true});
    await sleep(600);
    const res = await cdp.send('Runtime.evaluate', {expression: expr, returnByValue:true});
    console.log(JSON.stringify(res.result.value, null, 2));
    cdp.ws.close();
  } finally { try { child.kill(); } catch(_){} }
})().catch(e => { console.error('PROBE_FAIL ' + e.message); process.exit(1); });
