// 六档几何 + 结论带探针：贴进浏览器控制台 / browser-use 的 evaluate_script 里跑。
// 为什么用 iframe：Qoder 面板视口只有 581px 宽，量不到 1100/1440 的三栏几何；
// iframe 自带视口，同源能读 contentDocument，而且量的是真 CSS 像素。
//
// 判"几行"的口径：把子元素的 top 排序后按 0.6×最高子元素高 聚类，簇数就是行数。
// 前两版都错过：① 拿 top 相等当一行（align-items:center 下 top 本来就不等，一行三格数成三行）；
// ② 拿「容器高 > 最高子元素高 + 2px」当换行（未取整的差就有 2.8px，七档全被误判成换行）。
// 变异臂：最后一跑把 .hd 强设成单列 ⇒ 三个子元素各占一行，尺子必须数出 3；
// 数不出 3 就说明这把尺子恒绿，前面那批「行数 1」全不作数。
//
// 注意：窄屏别用 headless --screenshot 当证据 —— 420 的画布会把 ~480 视口的页面裁掉右边，
// 图看着"截断"而 DOM 量出来横溢 0。窄档只认这里的读数。
async () => {
  var widths = [1440, 1100, 900, 700, 528, 390, 320];
  var out = [];
  function 行数(h) {
    var tops = [], 子高 = 0;
    for (var j = 0; j < h.children.length; j++) {
      var r = h.children[j].getBoundingClientRect();
      tops.push(r.top); if (r.height > 子高) 子高 = r.height;
    }
    tops.sort(function (a, b) { return a - b; });
    var 簇 = 1, 阈 = 子高 * 0.6;
    for (var k = 1; k < tops.length; k++) if (tops[k] - tops[k - 1] > 阈) 簇++;
    return 簇;
  }
  async function 跑一档(w, 注入) {
    var f = document.createElement('iframe');
    f.style.cssText = 'position:fixed;left:-99999px;top:0;width:' + w + 'px;height:900px;border:0';
    document.body.appendChild(f);
    f.src = '/?run=1';
    await new Promise(function (res) { f.onload = res; setTimeout(res, 8000); });
    var d = f.contentDocument, win = f.contentWindow;
    var t0 = Date.now();
    while (Date.now() - t0 < 14000) {
      var b = d.getElementById('budget');
      if (b && b.textContent.indexOf('收了') >= 0) break;
      await new Promise(function (r) { setTimeout(r, 150); });
    }
    if (注入) {
      var st = d.createElement('style'); st.textContent = 注入; d.head.appendChild(st);
      await new Promise(function (r) { setTimeout(r, 260); });
    }
    var rows = [];
    var hds = d.querySelectorAll('li.call .hd');
    for (var i = 0; i < hds.length; i++) {
      var h = hds[i]; var tool = h.querySelector('.tool'); var li = h.closest('li');
      var dur = li ? li.querySelector('.sub .dur') : null;
      var fill = dur && dur.firstElementChild ? dur.firstElementChild.getBoundingClientRect().width : -1;
      rows.push({
        格: h.children.length, 行数: 行数(h), 名宽: tool.clientWidth, 名需: tool.scrollWidth,
        名截: tool.scrollWidth > tool.clientWidth, 条: dur ? Math.round(dur.getBoundingClientRect().width) : -1,
        填充: Math.round(fill), 毫秒: (li.querySelector('.sub .meta') || {}).textContent || '无'
      });
    }
    var 有界 = [];
    ['#msgs', '#calls', '#hist', '#registry', '#findings', '#unknowns'].forEach(function (s) {
      var e = d.querySelector(s);
      if (!e) { 有界.push(s + ':NO-EL'); return; }
      var cs = win.getComputedStyle(e);
      有界.push(s + ':' + cs.maxHeight + '/' + cs.overflowY + (e.getBoundingClientRect().height === 0 ? '/页签藏' : ''));
    });
    var band = d.getElementById('band'); var bcs = win.getComputedStyle(band);
    var txt = d.body.innerText, 脏 = 0;
    ['undefined', 'NaN', '[object Object]', 'null', 'map[', '%!'].forEach(function (k) { 脏 += txt.split(k).length - 1; });
    var r = {
      档: w, 实宽: win.innerWidth, 横滚: d.documentElement.scrollWidth - win.innerWidth,
      表头: rows, 有界: 有界, 脏字: 脏,
      带字数: band.innerText.length, 带行数: Math.round(band.getBoundingClientRect().height / parseFloat(bcs.lineHeight)),
      带全文: band.innerText.replace(/\s+/g, ' '),
      时间线: d.querySelectorAll('li.call').length,
      结论: (d.getElementById('findings') || {}).childElementCount,
      记忆: (d.getElementById('hist') || {}).childElementCount,
      注册: (d.getElementById('registry') || {}).childElementCount
    };
    f.remove();
    return r;
  }
  for (var wi = 0; wi < widths.length; wi++) out.push(await 跑一档(widths[wi], null));
  var 臂 = await 跑一档(1440, 'li.call .hd { grid-template-columns: auto !important }');
  return JSON.stringify({
    判据: '行数=top 聚类（阈 0.6×最高子元素高）；名截=scrollWidth>clientWidth；带行数=高/行高',
    臂_强设单列: 臂.表头.map(function (x) { return x.格 + '格→' + x.行数 + '行'; }),
    读数: out
  }, null, 1);
}
