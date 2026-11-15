// 课程资料获取助手 · 前端（零依赖）
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const el = {
    q: $('q'), go: $('go'), crawl: $('crawl'), limit: $('limit'), download: $('download'),
    scope: $('scope'), advToggle: $('advToggle'), adv: $('adv'), srcList: $('srcList'),
    minscore: $('minscore'), budget: $('budget'),
    status: $('status'), phase: $('phase'), elapsed: $('elapsed'), srcbar: $('srcbar'),
    results: $('results'), portals: $('portals'), failures: $('failures'),
  };

  let SOURCES = [];
  let job = null;
  let timer = null;
  let data = null;
  let previewed = false;
  let activeKind = 'all';
  const chosen = new Set();

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const STATUS = {
    'ok': ['已抓正文', 'ok'], 'pdf': ['PDF 直链', 'pdf'],
    'blocked': ['被反爬', 'warn'], 'not-found': ['页面不存在', 'warn'],
    'timeout': ['抓取超时', 'warn'], 'not-html': ['非网页内容', 'warn'],
    'empty': ['页面为空', 'warn'], 'error': ['抓取失败', 'bad'],
    '': ['未抓取', ''],
  };
  const PHASES = {
    sources: '检索数据源中', ranking: '排序中', crawl: '抓取正文中',
    finishing: '整理结果中', done: '完成',
  };

  async function api(path) {
    const r = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  // -------------------------------------------------------------- bootstrap
  async function boot() {
    try {
      const b = await api('/api/bootstrap');
      SOURCES = b.sources || [];
      el.srcList.innerHTML = SOURCES.map((s) =>
        `<button class="chip" data-src="${esc(s.id)}" aria-pressed="false" title="${esc(s.note || '')}">${esc(s.label)}</button>`
      ).join('');
    } catch (e) {
      el.results.innerHTML = `<div class="err">无法连接本地服务：${esc(e.message)}</div>`;
    }
  }

  // ------------------------------------------------------------------- form
  el.advToggle.addEventListener('click', () => {
    const open = el.adv.hidden;
    el.adv.hidden = !open;
    el.advToggle.setAttribute('aria-expanded', String(open));
  });

  el.scope.addEventListener('change', () => {
    if (el.scope.value === 'custom' && el.adv.hidden) el.advToggle.click();
  });

  el.srcList.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-src]');
    if (!btn) return;
    const id = btn.dataset.src;
    const on = btn.getAttribute('aria-pressed') !== 'true';
    btn.setAttribute('aria-pressed', String(on));
    on ? chosen.add(id) : chosen.delete(id);
    el.scope.value = 'custom';
  });

  el.q.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); run(); }
    if (e.key === 'Escape') { el.q.value = ''; }
  });
  el.go.addEventListener('click', (e) => { e.preventDefault(); run(); });

  function sourceList() {
    const scope = el.scope.value;
    const active = SOURCES.filter((s) => s.enabled);
    if (scope === 'custom') return [...chosen];
    if (scope === 'zh') return active.filter((s) => s.lang !== 'en').map((s) => s.id);
    if (scope === 'en') return active.filter((s) => s.lang === 'en').map((s) => s.id);
    return null;
  }

  // --------------------------------------------------------------------- run
  async function run() {
    const q = el.q.value.trim();
    if (!q) { el.q.focus(); return; }
    stopPoll();
    data = null; previewed = false; activeKind = 'all';
    job = null;
    el.results.innerHTML = '';
    el.portals.innerHTML = '';
    el.failures.textContent = '';
    el.go.disabled = true;
    el.go.textContent = '检索中';
    el.status.hidden = false;
    el.status.classList.remove('done');
    el.phase.textContent = '准备中';
    el.elapsed.textContent = '';
    el.srcbar.innerHTML = '';

    const params = new URLSearchParams({
      q,
      limit: el.limit.value,
      crawl: el.crawl.checked ? '1' : '0',
      download: el.download.checked ? '1' : '0',
      minscore: el.minscore.value || '10',
      budget: el.budget.value || '100',
    });
    const src = sourceList();
    if (src) params.set('sources', src.join(','));
    history.replaceState(null, '', '?q=' + encodeURIComponent(q));

    try {
      const res = await api('/api/start?' + params.toString());
      job = res.job;
      paintRunning();
      timer = setInterval(poll, 400);
      poll();
    } catch (e) {
      fail(e.message);
    }
  }

  function stopPoll() { if (timer) { clearInterval(timer); timer = null; } }

  function paintRunning() {
    const scopeIds = sourceList();
    el.srcbar.innerHTML = SOURCES.filter((s) => s.enabled && (!scopeIds || scopeIds.includes(s.id)))
      .map((s) => `<span class="src run" data-id="${esc(s.id)}" title="${esc(s.label)}"><i></i>${esc(s.label)}</span>`)
      .join('');
  }

  function phaseText(p) {
    const base = PHASES[p.phase] || '处理中';
    if (p.phase === 'sources') return `${base} ${p.done}/${p.total}`;
    if (p.phase === 'crawl') return `${base}（结果已出，正文陆续补全）`;
    return base;
  }

  async function poll() {
    if (!job) return;
    let p;
    try { p = await api('/api/progress?job=' + encodeURIComponent(job)); }
    catch (e) { fail(e.message); return; }

    el.phase.textContent = phaseText(p);
    el.elapsed.textContent = p.elapsed != null ? p.elapsed.toFixed(1) + 's' : '';

    const done = new Map((p.sources || []).map((s) => [s.id, s]));
    el.srcbar.querySelectorAll('.src').forEach((node) => {
      const s = done.get(node.dataset.id);
      if (!s) return;
      node.classList.remove('run');
      node.classList.add(s.ok ? 'ok' : (/超时/.test(s.error || '') ? 'blocked' : 'fail'));
      node.title = `${s.label} · ${s.ok ? s.count + ' 条' : (s.error || '失败')} · ${(s.elapsed || 0).toFixed(1)}s`;
    });

    if (p.state === 'error') { fail(p.error || '检索失败'); return; }

    if (p.state === 'done') {
      stopPoll();
      try {
        data = await api('/api/result?job=' + encodeURIComponent(job));
        render(false);
      } catch (e) { fail(e.message); }
      el.go.disabled = false;
      el.go.textContent = '检索';
      const ok = (p.sources || []).filter((s) => s.ok).length;
      el.status.classList.add('done');
      el.phase.textContent = '完成';
      el.elapsed.textContent = `${ok}/${p.total} 个源 · ${p.elapsed.toFixed(1)}s`;
      return;
    }

    // 排序已出（哪怕还有慢源在跑）：先把结果给出来，别让人盯着空屏
    if (!previewed) {
      try {
        const part = await api('/api/partial?job=' + encodeURIComponent(job));
        if (part.ready && (part.resources || []).length) {
          previewed = true;
          data = { resources: part.resources, portals: [], stats: {}, elapsed: part.elapsed, sources: p.sources };
          render(true);
        }
      } catch (e) { /* 预览失败不影响主流程 */ }
    }
  }

  function fail(msg) {
    stopPoll();
    el.go.disabled = false;
    el.go.textContent = '检索';
    el.status.classList.remove('done');
    el.phase.textContent = '出错了';
    el.results.innerHTML = `<div class="err">${esc(msg)}</div>`;
  }

  // 与 cmf/models.py 的 KIND_ORDER 一致：全部 → 学习向 → 教材/官方 → 其他。
  const KIND_ORDER = [
    'exercise', 'exam', 'solution', 'review', 'explanation', 'note', 'slides', 'video', 'qa',
    'textbook', 'official', 'course',
    'paper', 'reference', 'repo', 'dataset', 'web', 'link',
  ];
  const FAMILY_OF = {
    exercise: 'study', exam: 'study', solution: 'study', review: 'study', explanation: 'study',
    note: 'study', slides: 'study', video: 'study', qa: 'study',
    textbook: 'canonical', official: 'canonical', course: 'canonical',
  };
  const FAMILY_LABEL = { study: '学习向', canonical: '教材/官方', other: '其他' };

  function familyOf(r) {
    return r.kind_family || FAMILY_OF[r.kind] || 'other';
  }

  function orderedKinds(rs) {
    const present = new Map();
    rs.forEach((r) => { if (!present.has(r.kind)) present.set(r.kind, r.kind_label || r.kind); });
    const out = [];
    KIND_ORDER.forEach((k) => { if (present.has(k)) out.push([k, present.get(k)]); });
    present.forEach((label, k) => { if (!KIND_ORDER.includes(k)) out.push([k, label]); });
    return out;
  }

  function familyCountLine(rs) {
    const n = { study: 0, canonical: 0, other: 0 };
    rs.forEach((r) => {
      if (r.kind === 'link') return;
      const fam = familyOf(r);
      n[fam] = (n[fam] || 0) + 1;
    });
    return `${FAMILY_LABEL.study} ${n.study} · ${FAMILY_LABEL.canonical} ${n.canonical} · ${FAMILY_LABEL.other} ${n.other}`;
  }

  // ------------------------------------------------------------------ render
  function render(preview) {
    if (!data) return;
    const rs = data.resources || [];
    const counts = {};
    rs.forEach((r) => { counts[r.kind] = (counts[r.kind] || 0) + 1; });
    const tabs = [['all', `全部 ${rs.length}`]]
      .concat(orderedKinds(rs).map(([k, label]) => [k, `${label} ${counts[k]}`]));

    const exp = `/api/export?job=${encodeURIComponent(job)}`;
    const exportHtml = preview ? '' : `<div class="rexport">
        <a href="${exp}&fmt=md" download>Markdown</a>
        <a href="${exp}&fmt=html" download>HTML</a>
        <a href="${exp}&fmt=json" download>JSON</a>
        <a href="${exp}&fmt=csv" download>CSV</a>
      </div>`;

    el.results.innerHTML = `
      ${preview ? '<div class="previewbar">结果已出来，正在抓正文与开放全文，完成后自动刷新</div>' : ''}
      <div class="rtools">
        <div class="rtabs">${tabs.map(([k, label], i) =>
          `<button class="rtab${i === 0 ? ' on' : ''}" data-kind="${esc(k)}">${esc(label)}</button>`).join('')}</div>
        ${exportHtml}
      </div>
      <div class="rsum" id="rsum"></div>
      <div id="cards"></div>`;

    el.results.querySelectorAll('.rtab').forEach((b) => {
      b.addEventListener('click', () => {
        el.results.querySelectorAll('.rtab').forEach((x) => x.classList.remove('on'));
        b.classList.add('on');
        activeKind = b.dataset.kind;
        paintCards(preview);
      });
    });
    paintCards(preview);

    renderPortals();
    if (!preview) {
      const failed = (data.sources || []).filter((s) => !s.ok);
      el.failures.innerHTML = failed.length
        ? '失败/跳过：' + failed.map((s) => `${esc(s.label)}（${esc((s.error || '').slice(0, 28))}）`).join(' · ')
        : '';
    }
  }

  function paintCards(preview) {
    const rs = (data.resources || []).filter((r) => activeKind === 'all' || r.kind === activeKind);
    const st = data.stats || {};
    const all = data.resources || [];
    const detail =
      `当前 ${rs.length} 条 · ${preview ? '正文抓取中' : `用时 ${data.elapsed}s`}` +
      (!preview ? ` · 正文 ${st.crawled || 0} 条` : '') +
      (!preview && st.downloaded ? ` · 已下载 ${st.downloaded}` : '') +
      (!preview && st.timed_out ? ` · ${st.timed_out} 个源超时` : '');
    $('rsum').innerHTML = `<div class="counts">${esc(familyCountLine(all))}</div><div>${esc(detail)}</div>`;
    $('cards').innerHTML = rs.length
      ? rs.map(card).join('')
      : `<div class="empty">这一类没有结果。换个关键词，或把「最低相关度」调低一点。</div>`;
  }

  function card(r) {
    const [label, cls] = STATUS[r.crawl_status || ''] || ['未抓取', ''];
    const meta = [r.source_label, r.lang_label, r.year, r.org]
      .filter(Boolean).map((x) => `<em>${esc(x)}</em>`).join(' · ');
    const fam = familyOf(r);
    let summary = r.excerpt || r.description || '';
    if (r.kind === 'video' && summary.length < 20) summary = ''; // 视频的「自用」这类占位简介没信息量
    const pdf = r.pdf_url
      ? `<a class="badge pdf" href="${esc(r.pdf_url)}" target="_blank" rel="noreferrer">PDF</a>` : '';
    const local = r.downloaded ? `<span class="badge">已存本地</span>` : '';
    const play = r.extra && r.extra.play ? `<span class="badge">▶ ${esc(shortNum(r.extra.play))}</span>` : '';
    const dur = r.extra && r.extra.duration ? `<span class="badge">${esc(fmtDur(r.extra.duration))}</span>` : '';
    return `<article class="card">
      <div class="kbadge ${esc(fam)}">${esc(r.kind_label || r.kind)}</div>
      <h3><a href="${esc(r.url)}" target="_blank" rel="noreferrer">${esc(r.title)}</a></h3>
      <div class="meta">${meta}</div>
      ${summary ? `<p class="para">${esc(summary.slice(0, 260))}</p>` : ''}
      <div class="badges">
        <span class="badge ${cls}">${esc(label)}</span>${play}${dur}${pdf}${local}
        <span class="score">${Math.round(r.score)}</span>
      </div>
    </article>`;
  }

  function shortNum(n) {
    const v = Number(n);
    if (!isFinite(v)) return String(n);
    if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿';
    if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
    return String(v);
  }

  function fmtDur(d) {
    const s = String(d);
    if (!/^\d+$/.test(s)) return s; // 已经是 12:34 这种格式
    const total = Number(s);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const sec = total % 60;
    const pad = (x) => String(x).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }

  function renderPortals() {
    const ps = data.portals || [];
    if (!ps.length) { el.portals.innerHTML = ''; return; }
    el.portals.innerHTML = `
      <details>
        <summary>还有 ${ps.length} 个平台只能给链接（反爬 / 登录墙 / 付费墙，本工具不绕过）</summary>
        <div class="plist">${ps.map((p) =>
          `<div><a href="${esc(p.url)}" target="_blank" rel="noreferrer">${esc(p.org || p.title)}</a>
           <span>${esc((p.description || '').replace('（本工具不抓取其内容，仅提供检索入口）', ''))}</span></div>`).join('')}</div>
      </details>`;
  }

  // ------------------------------------------------------------------- start
  boot().then(() => {
    const initial = new URLSearchParams(location.search).get('q');
    if (initial) { el.q.value = initial; run(); }
  });
  el.q.focus();
})();
