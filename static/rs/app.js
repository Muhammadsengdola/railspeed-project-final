/* RailSpeed shared UI: theme, menus, toast, AI chat */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  window.rsToast = function (msg, ms = 2600) {
    const t = $('#rs-toast'); if (!t) return;
    t.textContent = msg;
    t.classList.remove('opacity-0'); t.classList.add('opacity-100');
    clearTimeout(t._h); t._h = setTimeout(() => { t.classList.add('opacity-0'); t.classList.remove('opacity-100'); }, ms);
  };

  // theme
  $$('[data-rs-theme-toggle]').forEach(btn => btn.addEventListener('click', () => {
    const dark = document.documentElement.classList.toggle('dark');
    try { localStorage.setItem('rs-theme', dark ? 'dark' : 'light'); } catch (e) {}
  }));

  // language (English comes in a later round)
  $$('[data-rs-lang]').forEach(b => b.addEventListener('click', () => rsToast('ภาษาอังกฤษจะเปิดใช้ในรอบถัดไป ตอนนี้ใช้ภาษาไทยก่อนนะครับ')));

  // dropdown / mobile menus
  $$('[data-rs-menu]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const m = document.getElementById(btn.dataset.rsMenu); if (m) m.classList.toggle('hidden');
  }));
  document.addEventListener('click', e => {
    const um = $('#user-menu');
    if (um && !um.classList.contains('hidden') && !um.contains(e.target)) um.classList.add('hidden');
  });

  // confirm buttons: <button data-confirm="...">
  document.addEventListener('submit', e => {
    const b = e.submitter; const f = e.target;
    const msg = (b && b.dataset.confirm) || f.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  }, true);

  // ---------- AI chat ----------
  // History is kept in sessionStorage: it survives page changes and reloads in this tab,
  // and disappears when the tab/browser is closed or the user logs out.
  const box = $('#rs-chat-box'), log = $('#rs-chat-log'), form = $('#rs-chat-form'), input = $('#rs-chat-input');
  const KEY = 'rs-chat-v1';
  const owner = form ? (form.dataset.owner || 'guest') : null;
  let state = { owner, open: false, items: [] };
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) || 'null');
    if (saved && saved.owner === owner && Array.isArray(saved.items)) state = saved;
  } catch (e) {}
  const save = () => {
    state.items = state.items.slice(-40);
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  };

  // a different person logging in on this tab must not see the old chat
  $$('form[action$="/logout/"]').forEach(f => f.addEventListener('submit', () => {
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  }));

  const open = (focus = true) => {
    if (!box) return;
    box.classList.remove('hidden'); box.classList.add('flex');
    log.scrollTop = log.scrollHeight;
    if (focus && input) input.focus();
    state.open = true; save();
  };
  const close = () => {
    if (!box) return;
    box.classList.add('hidden'); box.classList.remove('flex');
    state.open = false; save();
  };
  $$('[data-rs-chat-open]').forEach(b => b.addEventListener('click', () => open()));
  $$('[data-rs-chat-close]').forEach(b => b.addEventListener('click', close));

  function bubble(text, who) {
    const wrap = document.createElement('div');
    if (who === 'user') {
      wrap.className = 'flex justify-end self-end max-w-[85%]';
      wrap.innerHTML = '<div class="p-3 rounded-2xl rounded-br-sm bg-coach-seat-first text-white"><p class="text-body-md leading-relaxed whitespace-pre-line"></p></div>';
    } else {
      wrap.className = 'flex items-start gap-2 max-w-[92%]';
      wrap.innerHTML = '<div class="w-7 h-7 rounded-full bg-primary-container shrink-0 flex items-center justify-center mt-1"><span class="material-symbols-outlined text-amber-signal" style="font-size:16px">smart_toy</span></div><div class="p-3 rounded-2xl rounded-tl-sm bg-surface border border-line text-ink"><p class="text-body-md leading-relaxed whitespace-pre-line"></p></div>';
    }
    wrap.querySelector('p').textContent = text;
    log.appendChild(wrap); log.scrollTop = log.scrollHeight;
    return wrap.querySelector('p');
  }

  // restore the conversation after a page change
  if (log && form) {
    state.items.forEach(it => bubble(it.content, it.role === 'user' ? 'user' : 'bot'));
    if (state.open) open(false);
  }

  // suggested questions: one click sends them
  $$('[data-rs-ask]').forEach(b => b.addEventListener('click', () => {
    if (!form || form.querySelector('button[type=submit]').disabled) return;
    input.value = b.dataset.rsAsk;
    form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true }));
  }));

  if (form) form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = input.value.trim(); if (!text) return;
    input.value = ''; bubble(text, 'user');
    state.items.push({ role: 'user', content: text }); save();
    const p = bubble('กำลังพิมพ์...', 'bot');
    const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    // only real questions/answers go to the AI, not error notices
    const history = state.items.filter(i => i.role !== 'error').slice(-10).map(i => ({ role: i.role, content: i.content }));
    try {
      const r = await fetch(form.dataset.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value },
        body: JSON.stringify({ messages: history })
      });
      const data = await r.json();
      const reply = data.reply || 'ขออภัย เกิดข้อผิดพลาด';
      p.textContent = reply;
      state.items.push({ role: r.ok ? 'assistant' : 'error', content: reply });
    } catch (err) {
      p.textContent = 'เชื่อมต่อไม่ได้ ลองใหม่อีกครั้งครับ';
      state.items.push({ role: 'error', content: p.textContent });
    }
    save();
    btn.disabled = false; input.focus();
  });
})();