// W8 无障碍 / 响应式探针。这是**跑过的那段代码本身**，不是描述：
// 浏览器里执行的就是这个函数体（改这里要重跑，别只改文档）。
//
// 它只量四件事，每件都是能红的：
//   1) 断点几何：iframe 真宽 320/360/390/768/1024/1440 六档下，三栏实际渲染成几栏、有没有横向溢出；
//   2) 键盘焦点：聚焦后 outline 是不是真的看得见（不是 outline:none）；
//   3) 五档徽章的对比度：白字对彩色底，WCAG 相对亮度公式自己算，门槛 4.5:1；
//   4) 可及名：每个 input/select/textarea 有没有 label[for] 或 aria-label（placeholder 不算）。
//
// 探针不猜"应该没问题"：任何一项不达标就写进 failures，让外面拿退出码判。
async function a11yProbe(only) {
  const $ = (id) => document.getElementById(id);
  const out = {failures: [], breakpoints: [], contrast: [], names: [], headings: [], focus: {}, 普查: [], 对照: []};

  // 1) 断点几何（iframe 有自己的视口，媒体查询按它的宽度算）
  //    **必须带 run=1**：不跑一圈的话这里量的是空页面 —— 结论带、九步、13 条卡片全不存在，
  //    溢出自然是 0。那把尺子量的是空气（本项目点过三次名的"探针扫空气"）。
  //    可以只跑其中几档（only=[320,360]）：外面那个浏览器工具单次 15 秒预算装不下六档 × 等跑完，
  //    分段跑同一段代码比"只跑前两档就当六档看过"诚实 —— 件里会把跑了哪几档与全部档都写出来。
  const ALL = [320, 360, 390, 768, 1024, 1440];
  const widths = (Array.isArray(only) && only.length) ? ALL.filter((w) => only.indexOf(w) >= 0) : ALL;
  out.跑的档 = widths;
  out.全部档 = ALL;
  if (!widths.length) out.failures.push(`only 里没有一个认识的档（${JSON.stringify(only)}）⇒ 这一跑是空的，不算跑过`);
  // 先记下**父页面**当前的往轮轨迹负载：iframe 与原页同源同 localStorage，所以它们读的是同一个 session 的历史。
  // 父页面一条都没有 ⇒ 下面那两条"负载必须在场"的判据无从判断，只能如实记 0，不许当成通过。
  const 父历史 = document.querySelectorAll('#hist li').length;
  const 父红字 = document.querySelectorAll('#hist li div.red').length;
  out.父页面负载 = {历史条数: 父历史, 红字行: 父红字};
  if (父历史 === 0) out.failures.push('父页面历史里 0 条 ⇒ 这一跑的六档没量到往轮轨迹那种长串负载（要先进一圈超预算那一发再跑）');
  for (const w of widths) {
    const f = document.createElement('iframe');
    f.style.cssText = `position:absolute;left:-9999px;width:${w}px;height:700px;border:0`;
    f.src = location.pathname + '?probe=' + w + '&run=1';
    document.body.appendChild(f);
    await new Promise((res) => { f.onload = res; setTimeout(res, 6000); });
    const d = f.contentDocument;
    // 等这一发真跑完：九步亮齐 + 结论带有字，才算量到了"有人看的那一份"
    const t0 = Date.now();
    let filled = false;
    while (Date.now() - t0 < 9000) {
      const band = d.querySelector('.band');
      if (d.querySelectorAll('#trace li').length >= 9 && band && band.textContent.length > 40) { filled = true; break; }
      await new Promise((r) => setTimeout(r, 150));
    }
    if (!filled) out.failures.push(`断点 ${w}px：等 9 秒这一发也没跑完 ⇒ 这一档的几何不算数`);
    // 等历史**拉回来**再看红字在不在。`loadHistory()` 是 boot 时的异步 fetch：只等九步亮齐就去数 `#hist li div.red`，
    // 会在 fetch 还没回来那一刻数到 0 ⇒ 10-21 W21 实测到这条假红（同一份历史，多等 2 秒就有 1 行红字）。
    // 口径与 W16 那条一致：不放宽断言，而是给被测系统一个能等的窗口，等不到才算红。
    // 等的是**要断言的那个东西本身**，不是它的邻居：先前只等"#hist li 条数够"，
    // 结果 iframe 里有一行普通历史就算等到了，那行红字却还没渲染出来 ⇒ 守卫误报（10-21 W21 实测两次）。
    const tw = Date.now();
    while (Date.now() - tw < 4000 &&
           (d.querySelectorAll('#hist li').length < 父历史 || d.querySelectorAll('#hist li div.red').length < 父红字)) {
      await new Promise((r) => setTimeout(r, 120));
    }
    out.等待负载ms = Date.now() - tw;
    const de = d.documentElement;
    const main = d.querySelector('main');
    const cols = getComputedStyle(main).gridTemplateColumns.split(' ').filter(Boolean).length;
    const overflow = de.scrollWidth - de.clientWidth;
    const panes = Array.from(d.querySelectorAll('.pane')).map((p) => Math.round(p.getBoundingClientRect().width));
    const expect = w <= 760 ? 1 : (w <= 1100 ? 2 : 3);
    const offenders = overflow > 2 ? Array.from(d.querySelectorAll('body *'))
      .filter((e) => e.getBoundingClientRect().right > w + 1 && e.children.length === 0)
      .slice(0, 3)
      .map((e) => `${e.tagName}${e.id ? '#' + e.id : '.' + String(e.className).split(' ')[0]}` +
        ` 右边界=${Math.round(e.getBoundingClientRect().right)} 字=${(e.textContent || '').trim().slice(0, 22)}`) : [];
    // 5b) 预测"窄屏是靠什么没溢出"。这条口径改了三轮，每一轮都是被实测驳回的：
    //     ① 整段文字不折行的宽度 ⇒ 报 43 处，可摘掉兜底规则后真溢出只有 3 处（中文之间、空格之间本来就能断行）；
    //     ② 按空白切词取最长 ⇒ 仍把汉字之间当成不可断，过报；
    //     ③ 把"非空白且非 CJK"当不可断段 ⇒ select-analyzers 这种**连字符后面 CSS 也给断点**，还是过报（臂件只溢出 208px，它预测 1201px）。
    //     第四轮不再自己猜断点，改成**直接问排版引擎**：克隆一份设成 width:min-content 量最小内容宽度。
    //     判据：这一处真在靠 overflow-wrap: anywhere 兜住 ⇔ 它的最小内容宽度 > 它现在分到的宽度。
    const 不可断词 = w <= 390 ? (() => {
      const sels = ['#hist li', '#decisions li', '#findings .card', '#unknowns li', '#trace li', '#band', '#mix', '#budget'];
      const hits = [];
      for (const sel of sels) {
        for (const e of Array.from(d.querySelectorAll(sel))) {
          if (!e.parentElement) continue;
          const c = e.cloneNode(true);
          c.style.cssText = 'position:absolute;left:-9999px;top:0;width:min-content;max-width:none;' +
            'white-space:normal;overflow-wrap:normal;word-break:normal';
          for (const kid of Array.from(c.querySelectorAll('*'))) {
            kid.style.cssText += ';white-space:normal;overflow-wrap:normal;word-break:normal;max-width:none';
          }
          e.parentElement.appendChild(c);
          const minc = Math.round(c.getBoundingClientRect().width);
          c.remove();
          const visible = e.clientWidth || Math.round(e.getBoundingClientRect().width);
          if (minc > visible + 2) {
            hits.push({sel, 最小内容宽_px: minc, 可见宽_px: visible, 超_px: minc - visible,
              词: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 34)});
          }
        }
      }
      hits.sort((a, b) => b.超_px - a.超_px);
      return hits;
    })() : [];
    // 兜底定位器：文本溢出**不会撑大元素自己的盒子**（字只是视觉上糊出去），所以上面那条"右边界超宽"看不见它。
    // 这种情况改看"哪个元素内部要比自己宽"（scrollWidth > clientWidth），把肇事那句点出来。
    const inner = overflow > 2 ? Array.from(d.querySelectorAll('body *'))
      .filter((e) => e.scrollWidth - e.clientWidth > 2)
      .filter((e) => { const ox = d.defaultView.getComputedStyle(e).overflowX; return ox !== 'auto' && ox !== 'scroll'; }) // 设计成能滚的不算肇事（代码框、预块）
      .sort((a, b) => (b.scrollWidth - b.clientWidth) - (a.scrollWidth - a.clientWidth))
      .slice(0, 3)
      .map((e) => `${e.tagName}${e.id ? '#' + e.id : '.' + String(e.className).split(' ')[0]}` +
        ` 内部超 ${e.scrollWidth - e.clientWidth}px 字=${(e.textContent || '').trim().slice(0, 30)}`) : [];
    // 屏幕上有没有"编程脏字"：JS 字段名写错（比如把 step 的 out 写成 summary）时，Go 侧一切照绿、
    // 接口照样回 13 步，只有真渲染的页面上会印出 undefined。这条就是给那种时刻准备的。
    const screen = ((main.innerText || '') + ' ' + ((d.querySelector('.band') || {}).innerText || ''));
    const dirty = screen.match(/undefined|NaN|\[object Object\]/g) || [];
    const dirtyWhere = dirty.length ? (screen.match(/.{0,40}(undefined|NaN|\[object Object\]).{0,40}/) || [''])[0].replace(/\s+/g, ' ') : '';
    out.breakpoints.push({width: w, cols, overflow_px: overflow, pane_widths: panes, expect_cols: expect,
      dirty_上屏: dirty.length, dirty_出处: dirtyWhere,
      trace_items: d.querySelectorAll('#trace li').length, band_chars: (d.querySelector('.band') || {}).textContent ? d.querySelector('.band').textContent.length : 0,
      历史条数: d.querySelectorAll('#hist li').length,
      历史红字行: d.querySelectorAll('#hist li div.red').length, 等了ms: out.等待负载ms,
      历史最长一句: (() => { const xs = Array.from(d.querySelectorAll('#hist li')).map((n) => (n.innerText || '').length); return xs.length ? Math.max(...xs) : 0; })(),
      offenders, 内部溢出: inner, 不可断词兜住: 不可断词.slice(0, 6), 不可断词计数: 不可断词.length});
    // 预测与实测必须自洽：窄档（≤390）真溢出了，可"靠折行兜住"的清单却是空的 ⇒ 预测与定位两头都没抓住肇事者，
    // 这时候报出来的数不可用（宁可红，也别给一份"溢出但没人知道为什么"的读数）。
    if (w <= 390 && overflow > 2 && 不可断词.length === 0) {
      out.failures.push(`断点 ${w}px：溢出 ${overflow}px 但预测清单为空 ⇒ "靠什么兜住的"这件事现在没人知道，这份读数不可用`);
    }
    if (cols !== expect) out.failures.push(`断点 ${w}px：媒体查询说应该 ${expect} 栏，实测 ${cols} 栏`);
    if (overflow > 2) out.failures.push(`断点 ${w}px：横向溢出 ${overflow}px（小屏不许要横滚）｜撑出边界的叶子：${offenders.join(' ; ') || '没定位到'}｜内部比自己能见的宽：${inner.join(' ; ') || '没定位到'}`);
    if (panes.some((p) => p <= 0)) out.failures.push(`断点 ${w}px：有栏宽度为 0（被挤掉了）`);
    if (dirty.length) out.failures.push(`断点 ${w}px：屏幕上有 ${dirty.length} 处 undefined/NaN/[object Object] ⇒ 出处：${dirtyWhere}`);
    // 这一档量到的必须是**带着往轮轨迹的那一份**：W18 起历史里会出现「要进账 N 字节 > 本机生效额度 M 字节」这种
    // 不可断长串 —— 那正是 W9 撑破 320/360/390 的同一种东西。iframe 若一条历史都没渲染，这几档量的又是空气。
    if (父历史 > 0 && d.querySelectorAll('#hist li').length === 0) {
      out.failures.push(`断点 ${w}px：父页面有 ${父历史} 条往轮轨迹，这一档的 iframe 里却是 0 条 ⇒ 这一档的几何不是有人看的那一份`);
    }
    if (父红字 > 0 && d.querySelectorAll('#hist li div.red').length === 0) {
      out.failures.push(`断点 ${w}px：父页面历史里有 ${父红字} 行红字（没落账那句），这一档的 iframe 里没渲染出来 ⇒ 长串负载没被量到`);
    }
    f.remove();
  }

  // 脏字检测自己的正对照：这栏如果量不出一个**明知有**的 undefined，那上面六档的 dirty_上屏=0 就只是装饰。
  out.dirty_正对照 = /undefined|NaN|\[object Object\]/.test('读回这一步的原话：' + String(undefined));
  if (!out.dirty_正对照) out.failures.push('探针自己的脏字检测没检出明知有的 undefined ⇒ 上面各档的 dirty_上屏 这栏不可信');

  // 2) 焦点看得见。这台宿主里标签页拿不到系统焦点（视口 0×0 那一族），
  //    此时 btn.focus() 会设 activeElement 但**不匹配 :focus** ⇒ 直接读 computed outline 会假红。
  //    所以分三层量：① 浏览器有没有把 :focus 规则解析进来（可证）；
  //                  ② 这个元素能不能画出 outline（内联一份，可证）；
  //                  ③ 真键盘焦点下轮廓长什么样（要 document.hasFocus()=true 才能算量到，否则如实 NOT_VERIFIED）。
  const btn = $('go');
  btn.focus();
  const focusRules = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue }
    for (const r of rules) {
      if (r.selectorText && r.selectorText.indexOf(':focus') >= 0 && /outline/.test(r.style.cssText)) {
        focusRules.push(r.selectorText);
      }
    }
  }
  btn.style.outline = '3px solid rgb(31, 95, 139)';
  const inlineRing = getComputedStyle(btn).outlineStyle;
  btn.style.outline = '';
  const cs = getComputedStyle(btn);
  out.focus = {
    document_has_focus: document.hasFocus(),
    document_active: document.activeElement === btn,
    css_focus_rules_parsed: focusRules.length,
    selectors: focusRules,
    inline_outline_style: inlineRing,
    computed_outline_after_programmatic_focus: cs.outlineStyle,
    visible_ring_verdict: 'NOT_VERIFIED（标签页拿不到系统焦点 ⇒ :focus 不参与匹配，这一层量不到）',
  };
  if (focusRules.length === 0) out.failures.push('浏览器没解析进任何 :focus 轮廓规则（键盘焦点没人守）');
  if (inlineRing !== 'solid') out.failures.push(`这个元素连内联 outline 都画不出来（style=${inlineRing}）`);
  if (!out.focus.document_active) out.failures.push('点 go 按钮拿不到 activeElement（键盘走不到 = 不可用）');
  if (document.hasFocus() && cs.outlineStyle === 'none') {
    out.failures.push(`文档有焦点却仍量到 outline:none —— :focus 规则没生效`);
  }

  // 3) 对比度（WCAG 2.1 相对亮度）
  const lum = (c) => {
    const m = c.match(/\d+(\.\d+)?/g);
    if (!m) return null;
    const f = m.slice(0, 3).map((v) => {
      const s = Number(v) / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  };
  const opaqueBg = (n) => { // 底色要往上找到**真的涂了颜色**那一层：拿 rgba(0,0,0,0) 直接算会得出假对比度
    for (let e = n; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor;
      if (c && c.indexOf('rgba(0, 0, 0, 0)') !== 0 && c !== 'transparent') {
        return {c, from: e.tagName + (e.id ? '#' + e.id : '.' + String(e.className).split(' ')[0])};
      }
    }
    return {c: 'rgb(255, 255, 255)', from: '兜底白'};
  };
  const ratio = (a, b) => {
    const la = lum(a), lb = lum(b);
    if (la === null || lb === null) return null;
    const hi = Math.max(la, lb), lo = Math.min(la, lb);
    return (hi + 0.05) / (lo + 0.05);
  };
  for (const sel of ['.b.m', '.b.e', '.b.s', '.b.r', '.b.a']) {
    const n = document.querySelector('footer ' + sel);
    if (!n) { out.failures.push(`页面上找不到徽章 ${sel}`); continue; }
    const st = getComputedStyle(n);
    const bg = opaqueBg(n);
    const r = ratio(st.color, bg.c);
    out.contrast.push({sel, color: st.color, bg: st.backgroundColor, ratio: r === null ? '算不出' : Number(r.toFixed(2)), size_px: st.fontSize});
    if (r === null || r < 4.5) out.failures.push(`徽章 ${sel} 对比度 ${r === null ? 'N/A' : r.toFixed(2)} < 4.5:1`);
  }
  // 正文那两档灰字也一起量（.dim 是页面上最小的字）
  // 正文与状态色也一起量。找不到就**写进件里**（`#band .red` 只在"没落账/被打断"那一形才存在，
  // 悄悄 continue 会让覆盖面看起来比实际大 —— 这是本项目点过名的"扫空气"另一形）。
  const bodySels = ['.dim', '.note', '#budget', '#band .red', 'h1'];
  for (const sel of bodySels) {
    const n = document.querySelector(sel);
    if (!n) { out.contrast.push({sel, 没找到: true, 为什么: '这一形页面上没有这个元素（比如 .red 只在没落账那一发才亮）'}); continue; }
    const st = getComputedStyle(n);
    const parentBg = opaqueBg(n.parentElement || document.body).c;
    const r = ratio(st.color, parentBg);
    out.contrast.push({sel, color: st.color, bg: parentBg, ratio: r === null ? '算不出' : Number(r.toFixed(2)), size_px: st.fontSize});
    if (r !== null && r < 4.5) out.failures.push(`${sel} 文字对比度 ${r.toFixed(2)} < 4.5:1`);
  }

  // 4) 可及名
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (!el.id) { out.failures.push(`有个 ${el.tagName} 没有 id，也没法挂 label`); continue; }
    const lab = document.querySelector(`label[for="${el.id}"]`);
    const name = (lab ? lab.textContent : (el.getAttribute('aria-label') || '')).trim();
    out.names.push({id: el.id, tag: el.tagName, name: name.slice(0, 24)});
    if (!name) out.failures.push(`${el.tagName}#${el.id} 没有可及名（placeholder 不算名字）`);
  }

  // 标题层级：不许跳级（h1 → h3 那种）
  let last = 0;
  for (const h of document.querySelectorAll('h1,h2,h3,h4')) {
    const lv = Number(h.tagName[1]);
    out.headings.push(h.tagName + ':' + h.textContent.trim().slice(0, 12));
    if (last !== 0 && lv > last + 1) out.failures.push(`标题跳级：h${last} → h${lv}（屏幕阅读器的结构导航会断）`);
    last = lv;
  }
  // 5) 容器普查：每个计数都要能区分「容器不存在」「容器在场但空的」「容器在场、内容不是我数的那种标签」。
  //    10-21 我自己踩出来的：在会话外手打 `#history li` 数到 0，读成「往轮轨迹没渲染」，实际容器叫 `#hist`。
  //    拿不存在的容器数出来的 0，和「真的一条没渲染」在数字上一模一样；任何「等于 0 就通过」的断言
  //    在前一种情形下是**恒过**的 —— W9 那条「探针扫空气」换了个地方长回来。
  out.普查 = [];
  const census = (name, sel, kid) => {
    const host = document.querySelector(sel);
    const row = {名: name, 容器: sel, 在场: !!host,
                 子元素总数: host ? host.childElementCount : '容器不存在，没数',
                 标签口径: kid || '（不数标签）',
                 该标签条数: (host && kid) ? host.querySelectorAll(kid).length : (host ? '（不数）' : '容器不存在，没数')};
    if (!host) {
      out.failures.push(`普查「${name}」：页面上没有容器 ${sel} ⇒ 这一格不可用（别把「没数」读成 0）`);
    } else if (kid && host.childElementCount > 0 && host.querySelectorAll(kid).length === 0) {
      out.failures.push(`普查「${name}」：容器 ${sel} 里有 ${host.childElementCount} 个子元素，但没有一个 ${kid} ⇒ 是计数口径错了，不是页面没渲染`);
    }
    out.普查.push(row);
    return row;
  };
  // 对照那一格**不许进 failures**：它红是设计如此，混进去就等于「不达标」永远 ≥1，
  // 那这一栏就再也不能被当成判据用了（判据要么恒红、要么恒绿，两种都一样没牙）。
  const control = (name, sel) => {
    const host = document.querySelector(sel);
    const row = {名: name, 容器: sel, 在场: !!host};
    if (host) out.failures.push(`对照失效：明知不存在的容器 ${sel} 被判「在场」⇒ 普查整栏不可信`);
    else out.对照 = (out.对照 || []).concat([`对照「${name}」如预期报不在场（这条不进不达标）`]);
    out.普查.push(row);
    return row;
  };
  census('往轮轨迹', '#hist', 'li');
  census('往轮那行计数', '#hist-note', null);
  census('本发步骤流', '#trace', 'li');
  // findings 里装的是 article.card，不是 li —— 这条是普查当场替我抓出来的（我第一版就写成了 li）。
  // 「容器在场、有 13 个子元素、li 数出 0」与「真的一条没渲染」必须是两个形状，不然计数会说假话。
  census('结构化结果', '#findings', 'article');
  census('未决区', '#unknowns', 'li');
  census('账本改写', '#decisions', 'li');
  census('结论带', '#band', 'span');
  census('额度预告', '#budget', null);
  census('五档加总', '#mix', null);
  census('KPI 那句为什么', '#kpi-why', null);
  census('网关那一行', '#gwline', null);
  census('栈那一栏', '#debug', null);
  census('行号槽', '#gutter', null);
  census('状态灯', '#state', null);
  census('代码编辑区', '#code', null);
  census('自动触发声明', '#autorun', null);
  // 负对照：明知不存在的容器必须报「不在场」。它要是报了在场，上面整栏普查都是白数的。
  if (control('对照_假容器', '#no-such-container-pgagent').在场 !== false) {
    out.failures.push('负对照没起作用：不存在的容器被判「在场」');
  }
  // 上面那些真容器若全部「不在场」，说明这一跑的根本不是这台应用的页面（URL 打错、页面没加载、build 不对）。
  if (out.普查.filter((r) => r.名 !== '对照_假容器' && r.在场).length === 0) {
    out.failures.push('普查里没有一个真容器在场 ⇒ 这一跑量的不是这台应用的页面，整份读数作废');
  }

  // 6) 往轮轨迹那一栏：有界、内部能滚、键盘走得到（10-21 W22 实测到过 20 发时无界撑到 1945px 且不内部滚动）
  {
    const h = document.getElementById('hist');
    if (!h) {
      out.failures.push('页面上找不到历史面板 #hist ⇒ 这一栏没量到');
    } else {
      const rows = h.querySelectorAll('li').length;
      const st = getComputedStyle(h);
      h.focus();
      out.历史栏 = {行数: rows, 内容高: h.scrollHeight, 可见高: h.clientHeight,
        内部可滚: h.scrollHeight > h.clientHeight, overflowY: st.overflowY, maxHeight: st.maxHeight,
        可聚焦: document.activeElement === h};
      if (rows > 6 && !(h.scrollHeight > h.clientHeight)) {
        out.failures.push(`历史栏 ${rows} 行却没有内部滚动（内容 ${h.scrollHeight}px vs 可见 ${h.clientHeight}px）⇒ 又在无界撑整栏`);
      }
      if (rows > 6 && st.overflowY !== 'auto' && st.overflowY !== 'scroll') {
        out.failures.push(`历史栏 overflow-y=${st.overflowY} ⇒ 限了高也滚不动`);
      }
      if (!out.历史栏.可聚焦) out.failures.push('历史面板 focus() 后不是 activeElement ⇒ 键盘用户滚不动它（WCAG 2.1.1）');
      if (rows <= 6) out.failures.push(`历史栏只有 ${rows} 行 ⇒ 这一跑**没量到多发累积**，有界与否不作数（要连发 >6 发再跑）`);
    }
  }

  out.summary = `这一跑覆盖 ${out.跑的档.join('/')}（全部档 ${out.全部档.join('/')}）· 断点 ${out.breakpoints.length} 个 · ` +
    `负载：父页历史 ${out.父页面负载.历史条数} 条 / 红字 ${out.父页面负载.红字行} 行，` +
    `各档 iframe 历史 ${out.breakpoints.map((b) => b.历史条数).join('/')} 条 · ` +
    `对比度 ${out.contrast.filter(x => !x.没找到).length}/${bodySels.length + 5} 项实量（其余见件）· 可及名 ${out.names.length} 项 · ` +
    `标题 ${out.headings.length} 个 · :focus 规则 ${out.focus.css_focus_rules_parsed} 条已解析 · ` +
    `容器普查 ${out.普查.length} 格（真容器在场 ${out.普查.filter(r => r.名 !== '对照_假容器' && r.在场).length}/${out.普查.filter(r => r.名 !== '对照_假容器').length}，` +
    `负对照 ${out.对照.length} 条按预期红、不计入不达标）· ` +
    `窄档最小内容宽超可见宽的：${out.breakpoints.filter(b => b.不可断词计数).map((b) => b.width + 'px→' + b.不可断词计数 + '处').join('、') || '没有一处需要兜（都是天然放得下）'} · ` +
    `真键盘焦点=${out.focus.document_has_focus ? '有焦点，已量' : '量不到（NOT_VERIFIED）'} · 不达标 ${out.failures.length} 条`;
  return out;
}


// pgagentInterleaveProbe() —— 跟 a11yProbe 分开的一个行为探针：连点两次「发」，看两发的步骤会不会混进同一列。
// 需要服务端带 -step-delay 跑（一圈慢到能被点第二次）；不加延迟时一发 45ms 就完，点不出重叠，那这探针只能报"没造出现场"。
// 10-21 W24 实测（未修的 build）：步号列变成 `1,8,2,9,10,11,12,13,3,4,5,6,7,8,9,…` —— 两发写在同一列里。
// 数据侧没事（两发各自落盘），坏的是这块"看得见循环"的面板本身。
async function pgagentInterleaveProbe(gapMs) {
  const $ = (id) => document.getElementById(id);
  const nums = () => Array.from(document.querySelectorAll('#trace li .no')).map((x) => x.textContent.trim());
  const out = {间隔ms: gapMs, 不达标: []};
  const go = $('go');
  if (!go) { out.不达标.push('页面上找不到 #go 按钮 ⇒ 这一跑没东西可点'); return out; }
  $('code').value = 'def probe(x):\n    if x:\n        return None\n';
  $('q').value = '重叠探针 第一发';
  go.click();
  await new Promise((r) => setTimeout(r, gapMs));
  const 中途 = nums();
  if (中途.length === 0 || 中途.length >= 13) {
    out.没造出现场 = `点第二发时第一发已有 ${中途.length} 步（要 1–12 之间才算重叠）⇒ 服务端没开 -step-delay，这一跑不算量过`;
    return out;
  }
  $('q').value = '重叠探针 第二发';
  go.click();
  await new Promise((r) => setTimeout(r, 6000));
  const 最后 = nums();
  out.第一发中途步号 = 中途.join(',');
  out.两发结束后步号 = 最后.join(',');
  out.列里步数 = 最后.length;
  // 判据：这一列必须是**一发**的 1..13 递增，不许出现第二个 1，也不许步数超过 13
  const 有第二个一 = 最后.slice(1).indexOf('1') >= 0;
  if (有第二个一 || 最后.length > 13) {
    out.不达标.push(`#trace 里混进了两发的步骤（${最后.length} 格、出现第二个 1：${有第二个一}）⇒ 面板没有"只画当前这一发"的保护`);
  }
  const 递增 = 最后.every((v, i) => i === 0 || Number(v) > Number(最后[i - 1]));
  if (!递增 && !out.不达标.length) out.不达标.push(`步号不是递增序列：${最后.join(',')} ⇒ 顺序被打乱`);
  out.结论 = out.不达标.length ? '混列' : '一列只有一发';
  return out;
}
