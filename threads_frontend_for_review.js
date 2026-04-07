// ═══════════════════════════ THREADS (쓰레드) ═══════════════════════════

let THREADS = { accounts: [], results: [], refPosts: [], isRunning: false, abortCtrl: null, activeTab: 'accounts' };

function renderThreads(mc) {
  mc.innerHTML = `
  <div class="ka-wrap" style="max-width:900px;">
    <div class="ka-title">🧵 쓰레드 자동화</div>

    <!-- 탭 -->
    <div style="display:flex;gap:4px;margin-bottom:16px;">
      <button class="ka-btn ${THREADS.activeTab==='accounts'?'ka-btn-primary':''}" onclick="threadsTab('accounts')" style="flex:1">계정 관리</button>
      <button class="ka-btn ${THREADS.activeTab==='daily'?'ka-btn-primary':''}" onclick="threadsTab('daily')" style="flex:1">일상글</button>
      <button class="ka-btn ${THREADS.activeTab==='traffic'?'ka-btn-primary':''}" onclick="threadsTab('traffic')" style="flex:1">물길글</button>
      <button class="ka-btn ${THREADS.activeTab==='comment'?'ka-btn-primary':''}" onclick="threadsTab('comment')" style="flex:1">댓글</button>
      <button class="ka-btn ${THREADS.activeTab==='queue'?'ka-btn-primary':''}" onclick="threadsTab('queue')" style="flex:1">스케줄</button>
    </div>

    <div id="threadsContent"></div>
  </div>`;
  threadsRenderTab();
}

function threadsTab(tab) {
  THREADS.activeTab = tab;
  document.querySelectorAll('.ka-wrap button').forEach(b => b.classList.remove('ka-btn-primary'));
  event.target.classList.add('ka-btn-primary');
  threadsRenderTab();
}

function threadsRenderTab() {
  const el = document.getElementById('threadsContent');
  if (!el) return;
  if (THREADS.activeTab === 'accounts') threadsRenderAccounts(el);
  else if (THREADS.activeTab === 'daily') threadsRenderDaily(el);
  else if (THREADS.activeTab === 'traffic') threadsRenderTraffic(el);
  else if (THREADS.activeTab === 'comment') threadsRenderComment(el);
  else if (THREADS.activeTab === 'queue') threadsRenderQueue(el);
}

// ── 계정 관리 탭 ──

async function threadsLoadAccounts() {
  try {
    const r = await fetch('/api/threads/accounts');
    const d = await r.json();
    THREADS.accounts = d.accounts || [];
  } catch(e) { THREADS.accounts = []; }
}

function threadsRenderAccounts(el) {
  threadsLoadAccounts().then(() => {
    let html = '<div class="ka-section"><div class="ka-section-title">계정 목록</div>';
    if (THREADS.accounts.length === 0) {
      html += '<p style="color:var(--text-secondary);padding:12px 0;">등록된 계정이 없습니다.</p>';
    }
    THREADS.accounts.forEach(acc => {
      const status = acc.connected ? '<span style="color:#22c55e;">● 연결됨</span>' : '<span style="color:#ef4444;">● 미연결</span>';
      const role = acc.role === 'main' ? '<span style="background:#5b7cfa;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;">메인</span>' : '<span style="background:#6b7280;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;">동조</span>';
      const persona = acc.persona || {};
      const warn = acc.token_expires && (() => { try { const d = Math.floor((new Date(acc.token_expires) - new Date()) / 86400000); return d <= 7 ? `<span style="color:#f59e0b;font-size:11px;"> (${d}일 남음)</span>` : ''; } catch(e) { return ''; } })();
      html += `<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div>${role} <strong>${acc.username || persona.name || acc.id}</strong> ${status}${warn || ''}</div>
          <div style="display:flex;gap:6px;">
            ${!acc.connected ? `<button class="ka-btn" onclick="threadsConnect('${acc.id}')" style="font-size:11px;padding:4px 10px;">OAuth 연결</button>` : ''}
            <button class="ka-btn" onclick="threadsEditAccount('${acc.id}')" style="font-size:11px;padding:4px 10px;">편집</button>
            <button class="ka-btn" onclick="threadsDeleteAccount('${acc.id}')" style="font-size:11px;padding:4px 10px;color:#ef4444;">삭제</button>
          </div>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);">
          페르소나: ${persona.name || '-'} / ${persona.age || '-'}세 / ${persona.job || '-'} / 말투: ${persona.tone || '-'}<br>
          관심사: ${(persona.interests || []).join(', ') || '-'} | 참조계정: ${(acc.reference_accounts || []).join(', ') || '-'}<br>
          스케줄: 하루 ${acc.schedule?.daily_posts || '-'}개 / ${acc.schedule?.active_hours?.[0] || 9}시~${acc.schedule?.active_hours?.[1] || 22}시 / 간격 ${acc.schedule?.min_interval_hours || 3}시간 | 오늘 게시: ${acc.daily_count || 0}개
        </div>
      </div>`;
    });
    html += `<button class="ka-btn ka-btn-primary" onclick="threadsAddAccount()" style="width:100%;margin-top:8px;">+ 계정 추가</button>`;
    html += '</div>';
    el.innerHTML = html;
  });
}

async function threadsConnect(accId) {
  try {
    const r = await fetch('/api/threads/auth-url?account_id=' + accId);
    const d = await r.json();
    if (d.url) window.open(d.url, '_blank');
    else showToast(d.error || 'OAuth URL 생성 실패');
  } catch(e) { showToast('연결 오류: ' + e.message); }
}

async function threadsAddAccount() {
  const name = prompt('페르소나 이름:');
  if (!name) return;
  const age = prompt('나이:') || '';
  const job = prompt('직업:') || '';
  const tone = prompt('말투 (친근/전문/유머/감성):', '친근') || '친근';
  const interests = (prompt('관심사 (쉼표 구분):') || '').split(',').map(s => s.trim()).filter(Boolean);
  const refs = (prompt('참조계정 (@username, 쉼표 구분):') || '').split(',').map(s => s.trim()).filter(Boolean);
  const role = confirm('메인 계정인가요? (확인=메인, 취소=동조)') ? 'main' : 'support';
  const dailyPosts = parseInt(prompt('하루 게시 수:', role === 'main' ? '3' : '2')) || 2;
  try {
    await fetch('/api/threads/accounts', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        role, persona: { name, age, job, tone, interests },
        reference_accounts: refs,
        schedule: { daily_posts: dailyPosts, active_hours: [9, 22], min_interval_hours: role === 'main' ? 3 : 5 }
      })
    });
    showToast('계정 추가 완료');
    threadsRenderTab();
  } catch(e) { showToast('추가 실패: ' + e.message); }
}

async function threadsEditAccount(accId) {
  const acc = THREADS.accounts.find(a => a.id === accId);
  if (!acc) return;
  const p = acc.persona || {};
  const name = prompt('이름:', p.name) || p.name;
  const age = prompt('나이:', p.age) || p.age;
  const job = prompt('직업:', p.job) || p.job;
  const tone = prompt('말투:', p.tone) || p.tone;
  const interests = (prompt('관심사:', (p.interests||[]).join(',')) || '').split(',').map(s=>s.trim()).filter(Boolean);
  const refs = (prompt('참조계정:', (acc.reference_accounts||[]).join(',')) || '').split(',').map(s=>s.trim()).filter(Boolean);
  const role = confirm('메인 계정? (확인=메인, 취소=동조)') ? 'main' : 'support';
  const dp = parseInt(prompt('하루 게시 수:', acc.schedule?.daily_posts)) || 2;
  try {
    await fetch('/api/threads/accounts/' + accId, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        role, persona: { name, age, job, tone, interests },
        reference_accounts: refs,
        schedule: { daily_posts: dp, active_hours: acc.schedule?.active_hours || [9,22], min_interval_hours: acc.schedule?.min_interval_hours || 3 }
      })
    });
    showToast('수정 완료');
    threadsRenderTab();
  } catch(e) { showToast('수정 실패: ' + e.message); }
}

async function threadsDeleteAccount(accId) {
  if (!confirm('정말 삭제하시겠습니까?')) return;
  try {
    await fetch('/api/threads/accounts/' + accId, { method: 'DELETE' });
    showToast('삭제 완료');
    threadsRenderTab();
  } catch(e) { showToast('삭제 실패: ' + e.message); }
}

// ── 일상글 탭 ──

function threadsRenderDaily(el) {
  const accOptions = THREADS.accounts.map(a => `<option value="${a.id}">${a.persona?.name || a.username || a.id} (${a.role === 'main' ? '메인' : '동조'})</option>`).join('');
  el.innerHTML = `
  <div class="ka-section">
    <div class="ka-section-title">일상글 생성 — 참조계정 스타일 카피</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
      <div>
        <label style="font-size:12px;color:var(--text-secondary);">계정 선택</label>
        <select id="thrDailyAcc" class="ka-input" style="width:100%;">${accOptions}</select>
      </div>
      <div>
        <label style="font-size:12px;color:var(--text-secondary);">생성 개수</label>
        <input type="number" id="thrDailyCount" class="ka-input" value="3" min="1" max="10" style="width:100%;">
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px;">
      <button class="ka-btn" onclick="threadsCrawlRef()" id="thrCrawlBtn">참조계정 크롤링</button>
      <span id="thrCrawlStatus" style="color:var(--text-secondary);font-size:12px;line-height:32px;"></span>
    </div>
    <div style="display:flex;gap:8px;">
      <button class="ka-btn ka-btn-primary" onclick="threadsDailyGenerate()" id="thrDailyGenBtn">일상글 생성</button>
      <button class="ka-btn" onclick="threadsStopGen()" style="display:none;" id="thrDailyStopBtn">중지</button>
    </div>
    <div id="thrDailyProgress" style="margin-top:10px;"></div>
  </div>
  <div id="thrDailyResults"></div>`;
  threadsLoadAccounts();
}

async function threadsCrawlRef() {
  const accId = document.getElementById('thrDailyAcc')?.value;
  if (!accId) { showToast('계정을 선택하세요'); return; }
  const btn = document.getElementById('thrCrawlBtn');
  const status = document.getElementById('thrCrawlStatus');
  btn.disabled = true; status.textContent = '크롤링 중...';
  try {
    const r = await fetch('/api/threads/crawl-reference', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accId })
    });
    const d = await r.json();
    if (d.error) { showToast(d.error); status.textContent = '실패'; }
    else { THREADS.refPosts = d.posts || []; status.textContent = `${d.count}개 글 수집 완료`; showToast(`참조 글 ${d.count}개 수집`); }
  } catch(e) { showToast('크롤링 오류: ' + e.message); status.textContent = '오류'; }
  btn.disabled = false;
}

async function threadsDailyGenerate() {
  const accId = document.getElementById('thrDailyAcc')?.value;
  const count = parseInt(document.getElementById('thrDailyCount')?.value) || 3;
  if (!accId) { showToast('계정을 선택하세요'); return; }
  THREADS.results = [];
  THREADS.isRunning = true;
  document.getElementById('thrDailyGenBtn').style.display = 'none';
  document.getElementById('thrDailyStopBtn').style.display = '';
  THREADS.abortCtrl = new AbortController();
  try {
    const r = await fetch('/api/threads/generate', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ type: 'daily', account_id: accId, count, ref_posts: THREADS.refPosts }),
      signal: THREADS.abortCtrl.signal
    });
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const ev = JSON.parse(line.slice(6));
          if (ev.type === 'progress') document.getElementById('thrDailyProgress').innerHTML = `<div style="color:var(--text-secondary);font-size:13px;">${ev.msg}</div><div style="background:var(--border);border-radius:4px;height:6px;margin-top:4px;"><div style="background:var(--accent);height:100%;border-radius:4px;width:${Math.round(ev.cur/ev.total*100)}%;transition:width .3s;"></div></div>`;
          if (ev.type === 'result') { THREADS.results.push(ev.data); threadsRenderResults('thrDailyResults', 'daily'); }
          if (ev.type === 'error') showToast(ev.message);
          if (ev.type === 'complete') document.getElementById('thrDailyProgress').innerHTML = `<div style="color:#22c55e;font-size:13px;">✓ ${ev.total}개 생성 완료</div>`;
        } catch(e) {}
      }
    }
  } catch(e) { if (e.name !== 'AbortError') showToast('생성 오류: ' + e.message); }
  THREADS.isRunning = false;
  document.getElementById('thrDailyGenBtn').style.display = '';
  document.getElementById('thrDailyStopBtn').style.display = 'none';
}

function threadsStopGen() {
  if (THREADS.abortCtrl) THREADS.abortCtrl.abort();
  THREADS.isRunning = false;
}

// ── 물길글 탭 ──

function threadsRenderTraffic(el) {
  const accOptions = THREADS.accounts.map(a => `<option value="${a.id}">${a.persona?.name || a.username || a.id} (${a.role === 'main' ? '메인' : '동조'})</option>`).join('');
  const prod = JSON.parse(localStorage.getItem('blogProduct') || '{}');
  el.innerHTML = `
  <div class="ka-section">
    <div class="ka-section-title">물길글 생성</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;">
      <div>
        <label style="font-size:12px;color:var(--text-secondary);">계정 선택</label>
        <select id="thrTrafficAcc" class="ka-input" style="width:100%;">${accOptions}</select>
      </div>
      <div>
        <label style="font-size:12px;color:var(--text-secondary);">셀링 로직 (SL)</label>
        <select id="thrSellingLogic" class="ka-input" style="width:100%;">
          <option value="shuffle">정보 셔플식</option>
          <option value="sympathy">연민 판매자식</option>
          <option value="review">후기 신뢰식</option>
        </select>
      </div>
      <div>
        <label style="font-size:12px;color:var(--text-secondary);">키워드당 생성 수</label>
        <input type="number" id="thrTrafficCount" class="ka-input" value="1" min="1" max="5" style="width:100%;">
      </div>
    </div>

    <!-- 키워드 입력 -->
    <div style="display:flex;gap:4px;margin-bottom:8px;">
      <button class="ka-btn ka-btn-primary" id="thrKwTabDirect" onclick="thrKwTab('direct')" style="font-size:11px;">직접입력</button>
      <button class="ka-btn" id="thrKwTabNotion" onclick="thrKwTab('notion')" style="font-size:11px;">Notion</button>
    </div>
    <div id="thrKwDirect">
      <textarea id="thrKeywords" class="ka-input" rows="3" placeholder="키워드를 줄바꿈으로 입력" style="width:100%;"></textarea>
    </div>
    <div id="thrKwNotion" style="display:none;">
      <button class="ka-btn" onclick="thrFetchNotion()">Notion에서 불러오기</button>
      <div id="thrNotionList" style="margin-top:8px;"></div>
    </div>

    <!-- 제품 정보 -->
    <div class="ka-section-title" style="margin-top:16px;">제품 정보</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px;">
      <input class="ka-input" id="thrProdName" placeholder="제품명" value="${prod.name||''}" style="width:100%;">
      <input class="ka-input" id="thrProdBrand" placeholder="나만의 키워드" value="${prod.brand_keyword||''}" style="width:100%;">
      <input class="ka-input" id="thrProdUsp" placeholder="핵심 특징(USP)" value="${prod.usp||''}" style="width:100%;">
      <input class="ka-input" id="thrProdTarget" placeholder="타겟층" value="${prod.target||''}" style="width:100%;">
      <input class="ka-input" id="thrProdIngr" placeholder="주요 성분" value="${prod.ingredients||''}" style="width:100%;">
      <input class="ka-input" id="thrForbidden" placeholder="금지 키워드" style="width:100%;">
    </div>

    <div style="display:flex;gap:8px;">
      <button class="ka-btn ka-btn-primary" onclick="threadsTrafficGenerate()" id="thrTrafficGenBtn">물길글 생성</button>
      <button class="ka-btn" onclick="threadsStopGen()" style="display:none;" id="thrTrafficStopBtn">중지</button>
    </div>
    <div id="thrTrafficProgress" style="margin-top:10px;"></div>
  </div>
  <div id="thrTrafficResults"></div>`;
  threadsLoadAccounts();
}

function thrKwTab(tab) {
  document.getElementById('thrKwDirect').style.display = tab === 'direct' ? '' : 'none';
  document.getElementById('thrKwNotion').style.display = tab === 'notion' ? '' : 'none';
  document.getElementById('thrKwTabDirect').classList.toggle('ka-btn-primary', tab === 'direct');
  document.getElementById('thrKwTabNotion').classList.toggle('ka-btn-primary', tab === 'notion');
}

let _thrNotionKws = [];
async function thrFetchNotion() {
  try {
    const r = await fetch('/api/threads/notion-keywords');
    const d = await r.json();
    _thrNotionKws = d.keywords || [];
    const el = document.getElementById('thrNotionList');
    if (_thrNotionKws.length === 0) { el.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">배정된 키워드 없음</span>'; return; }
    el.innerHTML = _thrNotionKws.map(k => `<span style="display:inline-block;background:var(--card);border:1px solid var(--border);border-radius:4px;padding:4px 10px;margin:2px;font-size:12px;">${k.keyword}</span>`).join('');
  } catch(e) { showToast('Notion 조회 실패'); }
}

async function threadsTrafficGenerate() {
  const accId = document.getElementById('thrTrafficAcc')?.value;
  const count = parseInt(document.getElementById('thrTrafficCount')?.value) || 1;
  if (!accId) { showToast('계정을 선택하세요'); return; }

  // 키워드 수집
  let keywords = [];
  if (document.getElementById('thrKwDirect').style.display !== 'none') {
    keywords = (document.getElementById('thrKeywords')?.value || '').split('\n').map(s => s.trim()).filter(Boolean).map(k => ({ keyword: k, page_id: '' }));
  } else {
    keywords = _thrNotionKws;
  }
  if (keywords.length === 0) { showToast('키워드를 입력하세요'); return; }

  const product = {
    name: document.getElementById('thrProdName')?.value || '',
    brand_keyword: document.getElementById('thrProdBrand')?.value || '',
    usp: document.getElementById('thrProdUsp')?.value || '',
    target: document.getElementById('thrProdTarget')?.value || '',
    ingredients: document.getElementById('thrProdIngr')?.value || '',
  };
  const forbidden = document.getElementById('thrForbidden')?.value || '';

  THREADS.results = [];
  THREADS.isRunning = true;
  document.getElementById('thrTrafficGenBtn').style.display = 'none';
  document.getElementById('thrTrafficStopBtn').style.display = '';
  THREADS.abortCtrl = new AbortController();

  try {
    const r = await fetch('/api/threads/generate', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ type: 'traffic', account_id: accId, keywords, product, forbidden, count, selling_logic: document.getElementById('thrSellingLogic')?.value || 'shuffle' }),
      signal: THREADS.abortCtrl.signal
    });
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const ev = JSON.parse(line.slice(6));
          if (ev.type === 'progress') document.getElementById('thrTrafficProgress').innerHTML = `<div style="color:var(--text-secondary);font-size:13px;">${ev.msg}</div><div style="background:var(--border);border-radius:4px;height:6px;margin-top:4px;"><div style="background:var(--accent);height:100%;border-radius:4px;width:${Math.round(ev.cur/ev.total*100)}%;transition:width .3s;"></div></div>`;
          if (ev.type === 'result') { THREADS.results.push(ev.data); threadsRenderResults('thrTrafficResults', 'traffic'); }
          if (ev.type === 'error') showToast(ev.message);
          if (ev.type === 'complete') document.getElementById('thrTrafficProgress').innerHTML = `<div style="color:#22c55e;font-size:13px;">✓ ${ev.total}개 생성 완료</div>`;
        } catch(e) {}
      }
    }
  } catch(e) { if (e.name !== 'AbortError') showToast('생성 오류: ' + e.message); }
  THREADS.isRunning = false;
  document.getElementById('thrTrafficGenBtn').style.display = '';
  document.getElementById('thrTrafficStopBtn').style.display = 'none';
}

// ── 결과 렌더링 (공통) ──

function threadsRenderResults(containerId, type) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const accId = document.getElementById(type === 'daily' ? 'thrDailyAcc' : 'thrTrafficAcc')?.value || '';
  let html = '';
  if (THREADS.results.length > 0) {
    html += `<div style="display:flex;gap:8px;margin:12px 0;">
      <button class="ka-btn ka-btn-primary" onclick="threadsBulkSaveNotion('${type}')">전체 Notion 저장</button>
      <button class="ka-btn" onclick="threadsBulkSchedule('${accId}','${type}')">전체 스케줄 등록</button>
    </div>`;
  }
  THREADS.results.forEach((r, i) => {
    const charColor = r.char_count > 500 ? '#ef4444' : '#22c55e';
    html += `<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:12px;color:var(--text-secondary);">${r.keyword ? r.keyword + ' — ' : ''}${type === 'daily' ? '일상글' : '물길글'} #${r.num}</span>
        <span style="font-size:12px;color:${charColor};">${r.char_count}/500자</span>
      </div>
      <div style="white-space:pre-wrap;font-size:13px;line-height:1.6;margin-bottom:10px;padding:10px;background:var(--bg);border-radius:6px;">${r.full_text || r.text}</div>
      <div style="display:flex;gap:6px;">
        <button class="ka-btn" onclick="threadsPublishOne('${accId}',${i})" style="font-size:11px;">즉시 게시</button>
        <button class="ka-btn" onclick="threadsScheduleOne('${accId}',${i},'${type}')" style="font-size:11px;">스케줄 등록</button>
        <button class="ka-btn" onclick="threadsSaveNotion(${i},'${type}')" style="font-size:11px;">Notion 저장</button>
        <button class="ka-btn" onclick="threadsCopyText(${i})" style="font-size:11px;">복사</button>
      </div>
    </div>`;
  });
  el.innerHTML = html;
}

async function threadsPublishOne(accId, idx) {
  const item = THREADS.results[idx];
  if (!item) return;
  if (!confirm('이 포스트를 즉시 게시하시겠습니까?')) return;
  try {
    const r = await fetch('/api/threads/publish', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accId, text: item.full_text || item.text })
    });
    const d = await r.json();
    if (d.ok) showToast('게시 완료!');
    else showToast('게시 실패: ' + (d.error || ''));
  } catch(e) { showToast('게시 오류: ' + e.message); }
}

async function threadsScheduleOne(accId, idx, type) {
  const item = THREADS.results[idx];
  if (!item) return;
  try {
    await fetch('/api/threads/schedule', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accId, text: item.full_text || item.text, type, keyword: item.keyword || '', page_id: item.page_id || '' })
    });
    showToast('스케줄 등록 완료');
  } catch(e) { showToast('스케줄 등록 실패'); }
}

async function threadsSaveNotion(idx, type) {
  const item = THREADS.results[idx];
  if (!item) return;
  try {
    const r = await fetch('/api/threads/save-notion', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ keyword: item.keyword || '쓰레드', text: item.full_text || item.text, type, page_id: item.page_id || '' })
    });
    const d = await r.json();
    if (d.success) showToast('Notion 저장 완료');
    else showToast('저장 실패: ' + d.error);
  } catch(e) { showToast('저장 오류: ' + e.message); }
}

async function threadsBulkSaveNotion(type) {
  for (let i = 0; i < THREADS.results.length; i++) await threadsSaveNotion(i, type);
  showToast('전체 Notion 저장 완료');
}

async function threadsBulkSchedule(accId, type) {
  for (const item of THREADS.results) {
    await fetch('/api/threads/schedule', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accId, text: item.full_text || item.text, type, keyword: item.keyword || '' })
    });
  }
  showToast('전체 스케줄 등록 완료');
}

function threadsCopyText(idx) {
  const item = THREADS.results[idx];
  if (!item) return;
  navigator.clipboard.writeText(item.full_text || item.text).then(() => showToast('복사됨'));
}

// ── 댓글 탭 ──

function threadsRenderComment(el) {
  const accOptions = THREADS.accounts.map(a => `<option value="${a.id}">${a.persona?.name || a.username || a.id}</option>`).join('');
  el.innerHTML = `
  <div class="ka-section">
    <div class="ka-section-title">댓글 생성 <span style="background:#f59e0b;color:#000;padding:2px 8px;border-radius:4px;font-size:10px;margin-left:6px;">Beta</span></div>
    <div style="margin-bottom:10px;">
      <label style="font-size:12px;color:var(--text-secondary);">계정 (페르소나 말투)</label>
      <select id="thrCommentAcc" class="ka-input" style="width:100%;">${accOptions}</select>
    </div>
    <div style="margin-bottom:10px;">
      <label style="font-size:12px;color:var(--text-secondary);">게시물 내용 (복사해서 붙여넣기)</label>
      <textarea id="thrCommentPost" class="ka-input" rows="4" placeholder="댓글을 달 게시물의 텍스트를 붙여넣으세요" style="width:100%;"></textarea>
    </div>
    <button class="ka-btn ka-btn-primary" onclick="threadsGenComment()">댓글 생성</button>
    <div id="thrCommentResults" style="margin-top:12px;"></div>
  </div>`;
  threadsLoadAccounts();
}

async function threadsGenComment() {
  const accId = document.getElementById('thrCommentAcc')?.value || '';
  const postContent = document.getElementById('thrCommentPost')?.value || '';
  if (!postContent) { showToast('게시물 내용을 입력하세요'); return; }
  const resEl = document.getElementById('thrCommentResults');
  resEl.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">댓글 생성 중...</div>';
  try {
    const r = await fetch('/api/threads/generate-comment', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accId, post_content: postContent })
    });
    const d = await r.json();
    const comments = d.comments || [];
    resEl.innerHTML = comments.map((c, i) => `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:13px;">${c}</span>
        <button class="ka-btn" onclick="navigator.clipboard.writeText('${c.replace(/'/g,"\\'")}').then(()=>showToast('복사됨'))" style="font-size:11px;padding:4px 10px;">복사</button>
      </div>
    `).join('');
  } catch(e) { resEl.innerHTML = ''; showToast('댓글 생성 실패: ' + e.message); }
}

// ── 스케줄 탭 ──

function threadsRenderQueue(el) {
  el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">로딩 중...</div>';
  fetch('/api/threads/queue').then(r => r.json()).then(d => {
    const queue = d.queue || [];
    if (queue.length === 0) { el.innerHTML = '<div class="ka-section"><div class="ka-section-title">게시 큐</div><p style="color:var(--text-secondary);font-size:13px;">대기 중인 게시물이 없습니다.</p></div>'; return; }
    let html = '<div class="ka-section"><div class="ka-section-title">게시 큐</div>';
    queue.forEach(q => {
      const statusColor = q.status === 'published' ? '#22c55e' : q.status === 'failed' ? '#ef4444' : '#f59e0b';
      const statusText = q.status === 'published' ? '게시완료' : q.status === 'failed' ? '실패' : '대기중';
      html += `<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span style="font-size:12px;color:var(--text-secondary);">${q.type === 'daily' ? '일상글' : '물길글'}${q.keyword ? ' — ' + q.keyword : ''}</span>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="color:${statusColor};font-size:12px;">● ${statusText}</span>
            ${q.status === 'pending' ? `<button class="ka-btn" onclick="threadsQueueDelete('${q.id}')" style="font-size:10px;padding:2px 8px;color:#ef4444;">취소</button>` : ''}
          </div>
        </div>
        <div style="font-size:12px;white-space:pre-wrap;max-height:60px;overflow:hidden;color:var(--text-secondary);">${(q.text || '').substring(0, 100)}...</div>
        ${q.published_at ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">게시: ${q.published_at}</div>` : ''}
        ${q.error ? `<div style="font-size:11px;color:#ef4444;margin-top:4px;">오류: ${q.error}</div>` : ''}
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  }).catch(e => { el.innerHTML = '<div style="color:#ef4444;">큐 로딩 실패</div>'; });
}

