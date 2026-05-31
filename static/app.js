/* ── Константы ───────────────────────────────────────────────────────────── */
const BOOK_TYPES = [
  'детская', 'мировая классика', 'публицистика',
  'русская классика', 'русская проза', 'советская', 'современная проза',
];

/* ── Состояние ───────────────────────────────────────────────────────────── */
let currentPage  = 1;
let totalPages   = 1;
let searchTimer  = null;
let selectedFiles = [];

const filters = { q: '', section: '', age: '', genre: '', sort: 'exl' };

/* ── Инициализация ───────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadBooks();
  loadBuyList();
  loadGenres();
});

/* ── Вкладки ─────────────────────────────────────────────────────────────── */
function switchTab(tab, el) {
  document.querySelectorAll('section[id^="tab-"]').forEach(s => s.style.display = 'none');
  document.querySelectorAll('.app-nav .nav-link').forEach(a => a.classList.remove('active'));
  document.getElementById('tab-' + tab).style.display = '';
  el.classList.add('active');
  if (tab === 'quizzes') { loadQuizzes(); }
  if (tab === 'sprints') {
    // Если только что создали спринт — переключить на нужного ребёнка/год
    if (window._sprintAutoChild) {
      const sel = document.getElementById('sprint-child');
      if (sel) sel.value = window._sprintAutoChild;
      window._sprintAutoChild = null;
    }
    if (window._sprintAutoYear) {
      const sel = document.getElementById('sprint-year');
      if (sel) sel.value = window._sprintAutoYear;
      window._sprintAutoYear = null;
    }
    loadSprints();
  }
}

/* ── Статистика ──────────────────────────────────────────────────────────── */
async function loadStats() {
  try {
    const s = await api('/api/stats');
    document.getElementById('stat-total').textContent = s.total.toLocaleString('ru');
    document.getElementById('stat-exl').textContent   = s.with_exl.toLocaleString('ru');
    document.getElementById('stat-buy').textContent   = s.to_buy;
    document.getElementById('stats-bar').classList.remove('d-none');
    if (s.to_buy > 0) {
      const badge = document.getElementById('buy-badge');
      badge.textContent = s.to_buy;
      badge.classList.remove('d-none');
    }
  } catch(e) { console.warn('stats:', e); }
}

/* ── Библиотека ──────────────────────────────────────────────────────────── */
async function loadBooks(page = 1) {
  currentPage = page;
  const params = new URLSearchParams({
    q:       filters.q,
    section: filters.section,
    age:     filters.age,
    genre:   filters.genre,
    sort:    filters.sort,
    page,
    per_page: 48,
  });

  const grid = document.getElementById('books-grid');
  grid.innerHTML = '<div class="empty-state"><div class="spinner-border text-secondary" role="status"></div></div>';

  try {
    const data = await api('/api/books?' + params);
    totalPages = data.pages;
    renderBooks(data.books);
    renderPagination(data.page, data.pages);
    const cnt = document.getElementById('results-count');
    const active = filters.q || filters.section || filters.age || filters.genre;
    cnt.textContent = active ? `Найдено: ${data.total} книг` : `Всего: ${data.total} книг`;
  } catch(e) {
    grid.innerHTML = `<div class="empty-state"><i class="bi bi-exclamation-circle"></i><p>${e.message}</p></div>`;
  }
}

function renderBooks(books) {
  const grid = document.getElementById('books-grid');
  if (!books.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><i class="bi bi-search"></i><p>Ничего не найдено</p></div>';
    return;
  }
  grid.innerHTML = books.map(b => bookCard(b)).join('');
}

function bookCard(b) {
  const exlHtml = b.exl_no != null
    ? `<span class="book-exl">EXL №${b.exl_no}</span>`
    : `<span class="book-exl no-exl">без EXL</span>`;

  const authorHtml = b.author
    ? `<div class="book-author">${esc(b.author)}</div>`
    : '';

  const badges = [
    b.section ? `<span class="book-badge badge-section">${b.section}</span>` : '',
    b.age     ? `<span class="book-badge badge-age">${b.age}</span>`         : '',
    ...(b.genres || []).slice(0, 2).map(g => `<span class="book-badge badge-genre">${esc(g)}</span>`),
  ].filter(Boolean).join('');

  const dateStr = b.date_added ? `<div class="book-date">внесена ${fmtDate(b.date_added)}</div>` : '';

  return `
    <div class="book-card">
      ${exlHtml}
      <div class="book-title">${esc(b.title)}</div>
      ${authorHtml}
      <div class="book-meta">${badges}</div>
      ${dateStr}
    </div>`;
}

/* ── Пагинация ───────────────────────────────────────────────────────────── */
function renderPagination(page, pages) {
  const el = document.getElementById('pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }

  const range = [1];
  for (let i = Math.max(2, page - 2); i <= Math.min(pages - 1, page + 2); i++) range.push(i);
  if (pages > 1) range.push(pages);
  const uniq = [...new Set(range)];

  let html = `<button class="page-btn" onclick="loadBooks(${page-1})" ${page===1?'disabled':''}>‹</button>`;
  let prev = 0;
  for (const p of uniq) {
    if (p - prev > 1) html += `<span class="page-btn" style="cursor:default">…</span>`;
    html += `<button class="page-btn ${p===page?'active':''}" onclick="loadBooks(${p})">${p}</button>`;
    prev = p;
  }
  html += `<button class="page-btn" onclick="loadBooks(${page+1})" ${page===pages?'disabled':''}>›</button>`;
  el.innerHTML = html;
}

/* ── Фильтры ─────────────────────────────────────────────────────────────── */
function debounceSearch() {
  const val = document.getElementById('search-input').value;
  document.getElementById('search-clear').style.display = val ? '' : 'none';
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { filters.q = val; loadBooks(1); }, 350);
}

function clearSearch() {
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').style.display = 'none';
  filters.q = '';
  loadBooks(1);
}

function applyFilters() {
  filters.section = document.getElementById('filter-section').value;
  filters.age     = document.getElementById('filter-age').value;
  filters.genre   = document.getElementById('filter-genre').value;
  filters.sort    = document.getElementById('sort-select').value;
  loadBooks(1);
}

/* ── Авторы (для автодополнения в форме добавления) ─────────────────────── */
async function loadAuthors() {
  try {
    const authors = await api('/api/authors');
    const dl = document.getElementById('authors-list');
    if (!dl) return;
    dl.innerHTML = authors.map(a => `<option value="${esc(a)}">`).join('');
  } catch(e) { console.warn('authors:', e); }
}

/* ── Жанры (динамическая загрузка для фильтра) ───────────────────────────── */
async function loadGenres() {
  try {
    const genres = await api('/api/genres');
    const sel = document.getElementById('filter-genre');
    const current = sel.value;
    sel.innerHTML = '<option value="">Все жанры</option>' +
      genres.map(g => `<option value="${esc(g.name)}">${esc(g.name)} <span class="text-muted">(${g.count})</span></option>`).join('');
    if (current) sel.value = current;
  } catch(e) { console.warn('genres:', e); }
}

/* ── Летнее чтение: переключатель ───────────────────────────────────────── */
function switchSummerTab(tab, btn) {
  document.querySelectorAll('#summerPills .nav-link').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('summer-tab-photo').style.display = tab === 'photo' ? '' : 'none';
  document.getElementById('summer-tab-text').style.display  = tab === 'text'  ? '' : 'none';
  document.getElementById('check-results').style.display = 'none';
  document.getElementById('check-results').innerHTML = '';
}

/* ── Летнее чтение: текстовый ввод ──────────────────────────────────────── */
function onTextInput() {
  const val = (document.getElementById('text-input').value || '').trim();
  document.getElementById('check-text-btn').disabled = !val;
}

function clearTextInput() {
  document.getElementById('text-input').value = '';
  document.getElementById('check-text-btn').disabled = true;
  document.getElementById('check-results').style.display = 'none';
  document.getElementById('check-results').innerHTML = '';
}

async function checkListText() {
  const text = (document.getElementById('text-input').value || '').trim();
  if (!text) return;

  const btn     = document.getElementById('check-text-btn');
  const spinner = document.getElementById('check-spinner');
  const results = document.getElementById('check-results');

  btn.disabled = true;
  spinner.style.display = '';
  results.style.display = 'none';
  results.innerHTML = '';

  try {
    const data = await fetch('/api/check-reading-list-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        child: document.getElementById('child-input').value,
        year:  document.getElementById('year-input').value,
      }),
    }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))));
    spinner.style.display = 'none';
    results.style.display = '';
    results.innerHTML = renderCheckResults(data);
  } catch(e) {
    spinner.style.display = 'none';
    results.style.display = '';
    results.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

/* ── Летнее чтение: фото ─────────────────────────────────────────────────── */
function handleDrop(e) {
  e.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  const files = [...e.dataTransfer.files];
  if (files.length) setFiles(files);
}

function handleFileSelect(input) {
  if (input.files.length) setFiles([...input.files]);
}

function setFiles(files) {
  selectedFiles = files;
  document.getElementById('drop-zone').classList.add('has-file');

  if (files.length === 1) {
    const preview = document.getElementById('preview-img');
    const reader = new FileReader();
    reader.onload = e => { preview.src = e.target.result; preview.style.display = 'block'; };
    reader.readAsDataURL(files[0]);
    document.querySelector('.drop-text').textContent = files[0].name;
  } else {
    document.getElementById('preview-img').style.display = 'none';
    document.querySelector('.drop-text').textContent = `Выбрано ${files.length} фото`;
  }

  document.getElementById('check-btn').disabled = false;
  document.getElementById('reset-btn').style.display = '';
}

function resetSummer() {
  selectedFiles = [];
  document.getElementById('file-input').value = '';
  document.getElementById('drop-zone').classList.remove('has-file');
  document.getElementById('preview-img').style.display = 'none';
  document.getElementById('preview-img').src = '';
  document.querySelector('.drop-text').textContent = 'Перетащите фото или нажмите для выбора';
  document.getElementById('check-btn').disabled = true;
  document.getElementById('reset-btn').style.display = 'none';
  document.getElementById('check-results').style.display = 'none';
  document.getElementById('check-results').innerHTML = '';
}

async function checkList() {
  if (!selectedFiles.length) return;

  const btn     = document.getElementById('check-btn');
  const spinner = document.getElementById('check-spinner');
  const results = document.getElementById('check-results');

  btn.disabled = true;
  spinner.style.display = '';
  results.style.display = 'none';
  results.innerHTML = '';

  const fd = new FormData();
  selectedFiles.forEach(f => fd.append('files', f));
  fd.append('child', document.getElementById('child-input').value);
  fd.append('year',  document.getElementById('year-input').value);

  try {
    const data = await fetch('/api/check-reading-list', { method: 'POST', body: fd })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))));
    spinner.style.display = 'none';
    results.style.display = '';
    results.innerHTML = renderCheckResults(data);
  } catch(e) {
    spinner.style.display = 'none';
    results.style.display = '';
    results.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle me-2"></i>${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

function renderCheckResults(data) {
  const { found, fuzzy, not_found, total, child, year } = data;
  const nF = found.length, nZ = fuzzy.length, nN = not_found.length;

  let title = '📋 Результат';
  if (child) title += ` — ${child}`;
  if (year)  title += ` ${year}`;

  let html = `
    <h5 class="mb-3">${esc(title)}</h5>
    <div class="summary-strip">
      <div class="sum-item"><span class="sum-dot dot-green"></span><strong>${nF}</strong> есть в библиотеке</div>
      <div class="sum-item"><span class="sum-dot dot-yellow"></span><strong>${nZ}</strong> уточнить</div>
      <div class="sum-item"><span class="sum-dot dot-red"></span><strong>${nN}</strong> купить</div>
      <div class="sum-item ms-auto text-muted">Всего: ${total}</div>
    </div>`;

  if (nF) {
    html += `<div class="result-section result-found">
      <div class="result-header"><span>✅</span> Уже есть в библиотеке (${nF})</div>`;
    found.forEach(e => {
      const m = e.match;
      const exl     = m?.exl_no != null ? `<span class="result-exl">EXL №${m.exl_no}</span>` : '';
      const section = m?.section ? `<span class="result-location">📍 ${esc(m.section)}</span>` : '';
      const date    = m?.date_added ? `внесена ${fmtDate(m.date_added)}` : '';
      html += `<div class="result-item">
        <div class="result-title">${esc(m?.title || e.query_title)}${exl}</div>
        <div class="result-sub">${[section, date].filter(Boolean).join(' · ')}</div>
      </div>`;
    });
    html += '</div>';
  }

  if (nZ) {
    html += `<div class="result-section result-fuzzy">
      <div class="result-header"><span>❓</span> Возможно есть — уточните (${nZ})</div>`;
    fuzzy.forEach(e => {
      const m = e.match;
      const pct     = Math.round(e.score * 100);
      const exl     = m?.exl_no != null ? `<span class="result-exl">EXL №${m.exl_no}</span>` : '';
      const section = m?.section ? `<span class="result-location">📍 ${esc(m.section)}</span>` : '';
      html += `<div class="result-item">
        <div class="result-title">${esc(e.query_title)}</div>
        <div class="result-sub">→ «${esc(m?.title || '')}»${exl} <span class="result-pct">${pct}%</span> ${section}</div>
      </div>`;
    });
    html += '</div>';
  }

  if (nN) {
    // Сохраняем список для кнопки «Добавить в Notion»
    const forWhom = child || null;
    window._lastNotFound = not_found.map(e => ({
      title:    e.query_title,
      author:   e.query_author || null,
      to_buy:   true,
      for_whom: forWhom,
    }));

    html += `<div class="result-section result-buy">
      <div class="result-header">
        <span>❌</span> Нет в библиотеке — купить (${nN})
        <div class="ms-auto d-flex gap-2">
          <button class="btn btn-sm btn-outline-danger" onclick="copySummerBuyList(this)">
            <i class="bi bi-clipboard me-1"></i>Скопировать
          </button>
          <button class="btn btn-sm btn-danger" id="add-to-buy-btn" onclick="addNotFoundToBuyList()">
            <i class="bi bi-cart-plus me-1"></i>Добавить в Notion
          </button>
        </div>
      </div>`;
    not_found.forEach(e => {
      const author = e.query_author ? `<span class="text-muted"> — ${esc(e.query_author)}</span>` : '';
      html += `<div class="result-item"><div class="result-title">${esc(e.query_title)}${author}</div></div>`;
    });
    html += '</div>';
  }

  // Кнопка «Создать спринт»
  const allBooks = [
    ...found.map(e => ({ title: e.match?.title || e.query_title, author: e.match?.author || e.query_author || '' })),
    ...fuzzy.map(e => ({ title: e.match?.title || e.query_title, author: e.match?.author || e.query_author || '' })),
    ...not_found.map(e => ({ title: e.query_title, author: e.query_author || '' })),
  ];
  window._lastSprintBooks = allBooks;
  window._lastSprintChild = child || '';
  window._lastSprintYear  = year  || new Date().getFullYear();

  html += `
    <div class="mt-3 p-3 bg-white border rounded-3 shadow-sm">
      <div class="d-flex align-items-center gap-3 flex-wrap">
        <div class="d-flex align-items-center gap-2">
          <i class="bi bi-calendar3 text-primary"></i>
          <strong>Создать спринт на лето</strong>
        </div>
        <div class="d-flex align-items-center gap-2 ms-auto flex-wrap">
          <select class="form-select form-select-sm" id="sprint-child-select" style="width:130px">
            <option value="Максим" ${(child||'') === 'Максим' ? 'selected' : ''}>Максим</option>
            <option value="Майя"   ${(child||'') === 'Майя'   ? 'selected' : ''}>Майя</option>
            <option value="Миша"   ${(child||'') === 'Миша'   ? 'selected' : ''}>Миша</option>
          </select>
          <select class="form-select form-select-sm" id="sprint-year-select" style="width:90px">
            <option value="2026" ${(year||'') == '2026' ? 'selected' : ''}>2026</option>
            <option value="2025" ${(year||'') == '2025' ? 'selected' : ''}>2025</option>
            <option value="2027" ${(year||'') == '2027' ? 'selected' : ''}>2027</option>
          </select>
          <button class="btn btn-sm btn-primary" id="create-sprint-btn" onclick="createSprintFromResults()">
            <i class="bi bi-inbox me-1"></i>В беклог (${allBooks.length} книг)
          </button>
        </div>
      </div>
      <p class="text-muted small mb-0 mt-2">Книги будут равномерно распределены по июню, июлю и августу в Notion</p>
    </div>`;

  return html;
}

async function createSprintFromResults() {
  const books = window._lastSprintBooks || [];
  const child = document.getElementById('sprint-child-select')?.value || 'Максим';
  const year  = parseInt(document.getElementById('sprint-year-select')?.value) || 2026;
  if (!books.length) return;

  const btn = document.getElementById('create-sprint-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Создаю…';

  try {
    const r = await fetch('/api/sprints/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ books, child, year, status: 'Беклог' }),
    }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))));

    btn.innerHTML = `<i class="bi bi-check2 me-1"></i>Добавлено в беклог (${r.added} книг)`;
    btn.classList.replace('btn-primary', 'btn-success');
    toast(`${r.added} книг добавлено в беклог для ${child}`);

    // Обновить спринт-таб
    window._sprintAutoChild = child;
    window._sprintAutoYear  = year;
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-calendar-plus me-1"></i>Создать спринт';
    toast('Ошибка: ' + e.message);
  }
}

async function addNotFoundToBuyList() {
  const books = window._lastNotFound || [];
  if (!books.length) return;

  const btn = document.getElementById('add-to-buy-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Сохраняю…'; }

  let added = 0, errors = 0;
  for (const book of books) {
    try {
      const r = await fetch('/api/add-book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(book),
      });
      if (!r.ok) throw new Error((await r.json()).detail);
      added++;
    } catch(e) {
      errors++;
      console.error('add-to-buy error:', e);
    }
  }

  if (btn) {
    if (errors === 0) {
      btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Добавлено!';
      btn.classList.replace('btn-danger', 'btn-success');
    } else {
      btn.innerHTML = `<i class="bi bi-exclamation-triangle me-1"></i>${added} из ${books.length}`;
      btn.disabled = false;
    }
  }

  if (added > 0) {
    loadStats();
    loadBuyList();
    toast(`${added} книг добавлено в список покупок в Notion`);
  }
  if (errors > 0) toast(`Ошибка: не удалось добавить ${errors} книг`);
}

function copySummerBuyList(btn) {
  const items = document.querySelectorAll('.result-buy .result-item .result-title');
  const text = [...items].map((el, i) => `${i+1}. ${el.textContent.trim()}`).join('\n');
  navigator.clipboard.writeText(text).then(() => toast('Список скопирован!'));
}

/* ── Список купить ───────────────────────────────────────────────────────── */
async function loadBuyList() {
  try {
    const books = await api('/api/buy-list');
    const el = document.getElementById('buy-list-content');
    if (!books.length) {
      el.innerHTML = '<div class="empty-state"><i class="bi bi-check2-circle text-success"></i><p>Всё куплено!</p></div>';
      return;
    }
    const FOR_WHOM_COLORS = {
      'Альбина': 'bg-purple-subtle text-purple',
      'Максим':  'bg-primary-subtle text-primary',
      'Майя':    'bg-pink text-white',
      'Миша':    'bg-success-subtle text-success',
    };
    el.innerHTML = books.map((b, i) => {
      const fwLabel = b.for_whom || '';
      const fwBadge = fwLabel
        ? `<span class="badge rounded-pill me-1" style="font-size:.68rem;background:${fwLabel==='Альбина'?'#6f42c1':fwLabel==='Максим'?'#0d6efd':fwLabel==='Майя'?'#d63384':fwLabel==='Миша'?'#198754':'#fd7e14'};color:#fff">${fwLabel}</span>`
        : `<span class="badge rounded-pill bg-secondary me-1" style="font-size:.68rem;cursor:pointer"
              onclick="quickSetForWhom('${esc(b.page_id)}', this)">?</span>`;
      return `
      <div class="buy-item" id="buy-item-${esc(b.page_id)}">
        <span class="buy-num">${i+1}</span>
        <div class="buy-info">
          <span class="buy-title">${esc(b.title)}</span>
          ${b.author ? `<span class="buy-author">${esc(b.author)}</span>` : ''}
        </div>
        ${fwBadge}
        <span class="buy-badge">купить</span>
        ${b.page_id ? `
        <button class="btn btn-sm btn-outline-secondary ms-1" title="Убрать из списка"
                onclick="removeBuyItem('${esc(b.page_id)}', this)">
          <i class="bi bi-x-lg"></i>
        </button>` : ''}
      </div>`;
    }).join('');
  } catch(e) { console.warn('buy-list:', e); }
}

async function quickSetForWhom(pageId, badge) {
  if (!name) return;
  try {
    await fetch('/api/book/set-for-whom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: pageId, name: name.trim() }),
    });
    loadBuyList();
  } catch(e) { toast('Ошибка: ' + e.message); }
}

async function removeBuyItem(pageId, btn) {
  if (!pageId) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    await fetch('/api/book/unbuy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: pageId }),
    });
    const row = document.getElementById(`buy-item-${pageId}`);
    if (row) row.remove();
    loadStats();
    toast('Убрано из списка покупок');
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-x-lg"></i>';
    toast('Ошибка: ' + e.message);
  }
}

function copyBuyList() {
  const items = document.querySelectorAll('.buy-title');
  if (!items.length) return;
  const text = [...items].map((el, i) => `${i+1}. ${el.textContent.trim()}`).join('\n');
  navigator.clipboard.writeText(text).then(() => toast('Список скопирован!'));
}

/* ── Добавить книгу: модаль ──────────────────────────────────────────────── */
function openAddBookModal() {
  document.getElementById('add-book-form').reset();
  window._extractedBooks = [];
  document.getElementById('extracted-books-list').innerHTML = '';
  document.getElementById('cover-drop-zone').classList.remove('has-file');
  document.getElementById('cover-file-input').value = '';
  document.getElementById('cover-spinner').style.display = 'none';
  renderTypesCheckboxes('add-types-container');
  switchAddTab('manual', document.getElementById('pill-manual-btn'));
  loadAuthors();   // заполнить datalist актуальными авторами из библиотеки
  new bootstrap.Modal(document.getElementById('addBookModal')).show();
}

function switchAddTab(tab, btn) {
  document.querySelectorAll('#addBookPills .nav-link').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('add-tab-manual').style.display = tab === 'manual' ? '' : 'none';
  document.getElementById('add-tab-photo').style.display  = tab === 'photo'  ? '' : 'none';
}

function renderTypesCheckboxes(containerId, selected = []) {
  const el = document.getElementById(containerId);
  el.innerHTML = BOOK_TYPES.map(t => {
    const id = `cht-${containerId}-${t.replace(/ /g, '_')}`;
    return `
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" id="${id}" value="${t}" ${selected.includes(t)?'checked':''}>
        <label class="form-check-label small" for="${id}">${t}</label>
      </div>`;
  }).join('');
}

function getAddFormData() {
  const types = [...document.querySelectorAll('#add-types-container input[type=checkbox]:checked')]
    .map(cb => cb.value);
  return {
    title:    document.getElementById('add-title').value.trim(),
    author:   document.getElementById('add-author').value.trim(),
    section:  document.getElementById('add-section').value,
    age:      document.getElementById('add-age').value,
    language: document.getElementById('add-language').value,
    year:     parseInt(document.getElementById('add-year').value)  || null,
    pages:    parseInt(document.getElementById('add-pages').value) || null,
    isbn:     document.getElementById('add-isbn').value.trim(),
    to_buy:   document.getElementById('add-to-buy').checked,
    types,
  };
}

async function submitAddBook() {
  const isManual = document.getElementById('pill-manual-btn').classList.contains('active');

  if (isManual) {
    const book = getAddFormData();
    if (!book.title) { document.getElementById('add-title').focus(); toast('Введите название книги'); return; }
    await _saveBooks([book]);
  } else {
    const books = (window._extractedBooks || []).filter(b => !b._removed);
    if (!books.length) { toast('Нет книг для добавления'); return; }
    await _saveBooks(books.map(({ _idx, _removed, ...rest }) => rest));
  }
}

async function _saveBooks(books) {
  const btn     = document.getElementById('add-submit-btn');
  const spinner = document.getElementById('add-modal-spinner');
  btn.disabled = true;
  spinner.style.display = 'inline-block';

  let added = 0, errors = 0;
  for (const book of books) {
    try {
      const r = await fetch('/api/add-book', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(book),
      });
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail); }
      added++;
    } catch(e) {
      errors++;
      console.error('add-book error:', e);
    }
  }

  btn.disabled = false;
  spinner.style.display = 'none';

  if (added > 0) {
    bootstrap.Modal.getInstance(document.getElementById('addBookModal')).hide();
    loadStats();
    loadBooks(1);
    loadBuyList();
    toast(added === 1 ? 'Книга добавлена в Notion!' : `Добавлено ${added} книг в Notion!`);
  }
  if (errors > 0) toast(`Ошибка: не удалось добавить ${errors} книг`);
}

/* ── Добавить с фото обложки ─────────────────────────────────────────────── */
function handleCoverDrop(e) {
  e.preventDefault();
  document.getElementById('cover-drop-zone').classList.remove('drag-over');
  const files = [...e.dataTransfer.files];
  if (files.length) processCoverFiles(files);
}

async function processCoverFiles(filesOrList) {
  const files = filesOrList instanceof FileList ? [...filesOrList] : filesOrList;
  if (!files.length) return;

  const spinner = document.getElementById('cover-spinner');
  const list    = document.getElementById('extracted-books-list');
  spinner.style.display = '';
  list.innerHTML = '';

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));

  try {
    const books = await fetch('/api/extract-book-cover', { method: 'POST', body: fd })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))));
    spinner.style.display = 'none';
    renderExtractedBooks(books);
    document.getElementById('cover-drop-zone').classList.add('has-file');
  } catch(e) {
    spinner.style.display = 'none';
    list.innerHTML = `<div class="alert alert-danger">${esc(e.message)}</div>`;
  }
}

function renderExtractedBooks(books) {
  const container = document.getElementById('extracted-books-list');
  if (!books.length) {
    container.innerHTML = '<div class="alert alert-warning">Не удалось распознать книги на фото</div>';
    return;
  }
  window._extractedBooks = books.map((b, i) => ({ ...b, _idx: i }));
  container.innerHTML = books.map((b, i) => `
    <div class="extracted-card mb-3" id="extracted-card-${i}">
      <div class="d-flex align-items-start gap-3">
        <div class="flex-grow-1">
          <div class="mb-2">
            <label class="form-label form-label-sm mb-1 fw-semibold">Название</label>
            <input type="text" class="form-control form-control-sm" value="${esc(b.title || '')}"
                   onchange="updateExtracted(${i}, 'title', this.value)">
          </div>
          <div class="row g-2 mb-2">
            <div class="col-sm-6">
              <label class="form-label form-label-sm mb-1">Автор</label>
              <input type="text" class="form-control form-control-sm" value="${esc(b.author || '')}"
                     onchange="updateExtracted(${i}, 'author', this.value)"
                     placeholder="не указан" list="authors-list">
            </div>
            <div class="col-sm-3">
              <label class="form-label form-label-sm mb-1">Год</label>
              <input type="number" class="form-control form-control-sm" value="${b.year || ''}"
                     onchange="updateExtracted(${i}, 'year', this.value ? +this.value : null)"
                     min="1800" max="2030">
            </div>
            <div class="col-sm-3">
              <label class="form-label form-label-sm mb-1">Язык</label>
              <input type="text" class="form-control form-control-sm" value="${esc(b.language || '')}"
                     onchange="updateExtracted(${i}, 'language', this.value)">
            </div>
          </div>
          <div class="d-flex flex-wrap gap-1">
            ${BOOK_TYPES.map(t => {
              const id = `ext-${i}-${t.replace(/ /g,'_')}`;
              return `<div class="form-check form-check-inline mb-0">
                <input class="form-check-input" type="checkbox" id="${id}" value="${t}"
                       ${(b.types||[]).includes(t)?'checked':''}
                       onchange="toggleExtractedType(${i}, '${t}', this.checked)">
                <label class="form-check-label small" for="${id}">${t}</label>
              </div>`;
            }).join('')}
          </div>
        </div>
        <button class="btn btn-sm btn-outline-danger flex-shrink-0 mt-1" onclick="removeExtractedBook(${i})" title="Удалить">
          <i class="bi bi-trash3"></i>
        </button>
      </div>
    </div>`).join('');
}

function updateExtracted(idx, field, value) {
  if (window._extractedBooks?.[idx]) window._extractedBooks[idx][field] = value;
}

function toggleExtractedType(idx, type, checked) {
  if (!window._extractedBooks?.[idx]) return;
  const types = window._extractedBooks[idx].types || [];
  if (checked) { if (!types.includes(type)) types.push(type); }
  else { const i = types.indexOf(type); if (i >= 0) types.splice(i, 1); }
  window._extractedBooks[idx].types = types;
}

function removeExtractedBook(idx) {
  const card = document.getElementById(`extracted-card-${idx}`);
  if (card) card.style.display = 'none';
  if (window._extractedBooks?.[idx]) window._extractedBooks[idx]._removed = true;
}

/* ── Спринты ─────────────────────────────────────────────────────────────── */

let _sprintView = 'kanban';

function switchSprintView(view) {
  _sprintView = view;
  document.getElementById('sprint-kanban').style.display = view === 'kanban' ? '' : 'none';
  document.getElementById('sprint-diary').style.display  = view === 'diary'  ? '' : 'none';
  document.getElementById('view-kanban-btn').className = view === 'kanban'
    ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline-secondary';
  document.getElementById('view-diary-btn').className = view === 'diary'
    ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline-secondary';
}

let _sprintItemsCache = [];
function _sprintItemById(id) {
  return _sprintItemsCache.find(i => i.id === id) || { id };
}

async function loadSprints() {
  const child = document.getElementById('sprint-child')?.value || 'Максим';
  const year  = document.getElementById('sprint-year')?.value  || '2026';

  document.getElementById('sprint-spinner').style.display = '';
  document.getElementById('sprint-kanban').style.display  = 'none';
  document.getElementById('sprint-diary').style.display   = 'none';
  document.getElementById('sprint-empty').style.display   = 'none';

  try {
    const items = await api(`/api/sprints?child=${encodeURIComponent(child)}&year=${year}`);
    document.getElementById('sprint-spinner').style.display = 'none';

    if (!items.length) {
      document.getElementById('sprint-empty').style.display = '';
      return;
    }
    _sprintItemsCache = items;
    renderProgressBar(items);
    renderKanban(items);
    renderDiary(items.filter(i => i.status === 'Прочитано'));
    switchSprintView(_sprintView);
  } catch(e) {
    document.getElementById('sprint-spinner').style.display = 'none';
    document.getElementById('sprint-empty').style.display = '';
    console.warn('sprints:', e);
  }
}

/* ── Прогресс-бар ────────────────────────────────────────────────────────── */
function renderProgressBar(items) {
  const total = items.length;
  if (!total) { document.getElementById('sprint-progress').style.display = 'none'; return; }

  const done    = items.filter(i => i.status === 'Прочитано').length;
  const reading = items.filter(i => i.status === 'Читаю сейчас').length;
  const planned = items.filter(i => ['Прочту в июне','Прочту в июле','Прочту в августе'].includes(i.status)).length;
  const backlog = items.filter(i => i.status === 'Беклог').length;

  const pct = n => (n / total * 100).toFixed(1);
  document.getElementById('pb-done').style.width    = pct(done)    + '%';
  document.getElementById('pb-reading').style.width = pct(reading) + '%';
  document.getElementById('pb-planned').style.width = pct(planned) + '%';
  document.getElementById('pb-backlog').style.width = pct(backlog) + '%';

  const donePct = Math.round(done / total * 100);
  document.getElementById('progress-label').textContent =
    `Прогресс чтения — ${donePct}% (${done} из ${total} книг прочитано)`;
  document.getElementById('progress-pct').textContent = '';

  document.getElementById('progress-legend').innerHTML = [
    ['bg-success',   done,    'Прочитано'],
    ['bg-warning',   reading, 'Читаю сейчас'],
    ['bg-primary',   planned, 'В плане'],
    ['bg-secondary', backlog, 'Беклог'],
  ].filter(([,n]) => n > 0).map(([cls, n, label]) =>
    `<span class="d-flex align-items-center gap-1 small">
       <span class="rounded-circle ${cls}" style="width:10px;height:10px;display:inline-block"></span>
       <strong>${n}</strong> ${label}
     </span>`
  ).join('');

  document.getElementById('sprint-progress').style.display = '';
}

const KANBAN_COLS = [
  { key: 'Беклог',           label: 'Беклог',       cls: 'sprint-col-backlog',  icon: '📋' },
  { key: 'Прочту в июне',    label: 'Июнь',          cls: 'sprint-col-june',     icon: '☀️' },
  { key: 'Прочту в июле',    label: 'Июль',          cls: 'sprint-col-july',     icon: '🌻' },
  { key: 'Прочту в августе', label: 'Август',        cls: 'sprint-col-august',   icon: '🍂' },
  { key: 'Читаю сейчас',     label: 'Читаю сейчас',  cls: 'sprint-col-reading',  icon: '📖' },
  { key: 'Прочитано',        label: 'Прочитано',     cls: 'sprint-col-done',     icon: '✅' },
];

function renderKanban(items) {
  const byStatus = {};
  KANBAN_COLS.forEach(c => { byStatus[c.key] = []; });
  items.forEach(it => {
    if (byStatus[it.status]) byStatus[it.status].push(it);
    else byStatus['Беклог'].push(it);
  });

  const board = document.getElementById('sprint-board');
  board.innerHTML = KANBAN_COLS.map(col => {
    const colItems = byStatus[col.key] || [];
    const cards = colItems.map(it => sprintCard(it, col.key)).join('');
    return `
      <div class="sprint-col ${col.cls}">
        <div class="sprint-col-header">
          <span>${col.icon} ${col.label}</span>
          <span class="sprint-col-count">${colItems.length}</span>
        </div>
        <div class="sprint-cards">${cards || '<div class="text-muted text-center" style="font-size:.75rem;padding:8px">пусто</div>'}</div>
      </div>`;
  }).join('');

  document.getElementById('sprint-kanban').style.display = '';
}

function sprintCard(it, currentStatus) {
  const isDone    = currentStatus === 'Прочитано';
  const isReading = currentStatus === 'Читаю сейчас';

  // Быстрые кнопки — самые полезные переходы для текущего статуса
  const QUICK = {
    'Беклог':           [{ key:'Читаю сейчас', icon:'📖', label:'Читаю' },
                         { key:'Прочитано',    icon:'✅', label:'Прочитано' }],
    'Прочту в июне':    [{ key:'Читаю сейчас', icon:'📖', label:'Читаю' },
                         { key:'Прочитано',    icon:'✅', label:'Прочитано' }],
    'Прочту в июле':    [{ key:'Читаю сейчас', icon:'📖', label:'Читаю' },
                         { key:'Прочитано',    icon:'✅', label:'Прочитано' }],
    'Прочту в августе': [{ key:'Читаю сейчас', icon:'📖', label:'Читаю' },
                         { key:'Прочитано',    icon:'✅', label:'Прочитано' }],
    'Читаю сейчас':     [{ key:'Прочитано',    icon:'✅', label:'Прочитано' },
                         { key:'Беклог',       icon:'📋', label:'В беклог'  }],
    'Прочитано':        [{ key:'Читаю сейчас', icon:'📖', label:'Читаю снова' }],
  };
  const quickBtns = (QUICK[currentStatus] || []).map(b =>
    `<button class="scard-quick-btn" onclick="moveSprintCard('${it.id}','${b.key}')"
             title="→ ${b.key}">${b.icon} ${b.label}</button>`
  ).join('');

  // Дропдаун «все статусы» для любого перемещения
  const dropItems = KANBAN_COLS
    .filter(c => c.key !== currentStatus)
    .map(c => `<li><a class="dropdown-item" style="font-size:.8rem"
                      onclick="moveSprintCard('${it.id}','${c.key}')">
                  ${c.icon} ${c.label}</a></li>`)
    .join('');

  const diaryBtn = (isDone || isReading)
    ? `<button class="scard-quick-btn scard-diary-btn"
               onclick="openDiaryModal(_sprintItemById('${it.id}'))"
               title="Открыть дневник">✏️ Дневник</button>`
    : '';

  // Кнопка теста — показываем если есть квиз для этой книги
  const quiz = findQuizForBook(it.title);
  const quizDone = quiz && isQuizCompleted(quiz.id);
  const quizBtn = quiz
    ? `<button class="scard-quick-btn ${quizDone ? 'scard-quiz-done' : 'scard-quiz-btn'}"
               onclick="openQuizFromSprint(${JSON.stringify(quiz.id)})"
               title="${quizDone ? 'Тест сдан ✅' : 'Пройти тест'}">
         ${quizDone ? '✅ Тест' : '📝 Тест'}</button>`
    : '';

  const rating = it.rating
    ? `<span class="scard-rating">${esc(it.rating)}</span>` : '';

  return `
    <div class="sprint-card${isDone ? ' sprint-card-done' : isReading ? ' sprint-card-reading' : ''}"
         id="scard-${it.id}">
      <button class="sprint-card-del" onclick="deleteSprintCard('${it.id}')" title="Удалить">×</button>
      <div class="sprint-card-title">${esc(it.title)}</div>
      ${it.author ? `<div class="sprint-card-author">${esc(it.author)}</div>` : ''}
      ${rating}
      <div class="sprint-card-actions">
        ${quickBtns}
        ${quizBtn}
        ${diaryBtn}
        <div class="dropdown d-inline-block">
          <button class="scard-quick-btn scard-move-btn dropdown-toggle"
                  data-bs-toggle="dropdown" title="Переместить в…">⋯</button>
          <ul class="dropdown-menu dropdown-menu-end" style="min-width:160px">${dropItems}</ul>
        </div>
      </div>
    </div>`;
}

function openQuizFromSprint(quizId) {
  // Переключаемся на таб тестов и запускаем нужный квиз
  const tabLink = [...document.querySelectorAll('.app-nav .nav-link')]
    .find(a => a.textContent.includes('Тесты'));
  if (tabLink) switchTab('quizzes', tabLink);
  // Небольшая задержка чтобы таб успел отрисоваться
  setTimeout(() => {
    if (_quizzes.length) startQuiz(quizId);
    else loadQuizzes().then(() => startQuiz(quizId));
  }, 100);
}

async function moveSprintCard(id, newStatus) {
  // Гейт: при переходе в «Прочитано» проверяем тест
  if (newStatus === 'Прочитано') {
    const item = _sprintItemById(id);
    const quiz = findQuizForBook(item.title || '');
    if (quiz && !isQuizCompleted(quiz.id)) {
      const go = confirm(
        `📝 Для книги «${item.title}» есть тест!\n\n` +
        `Хочешь сначала пройти тест? (рекомендуется)\n\n` +
        `OK — открыть тест\nОтмена — всё равно пометить прочитанным`
      );
      if (go) { openQuizFromSprint(quiz.id); return; }
    }
  }

  const card = document.getElementById(`scard-${id}`);
  if (card) card.style.opacity = '0.5';
  try {
    await fetch(`/api/sprints/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    loadSprints();
  } catch(e) {
    if (card) card.style.opacity = '1';
    toast('Ошибка: ' + e.message);
  }
}

async function deleteSprintCard(id) {
  if (!confirm('Удалить книгу из спринта?')) return;
  try {
    await fetch(`/api/sprints/${id}`, { method: 'DELETE' });
    const card = document.getElementById(`scard-${id}`);
    if (card) card.remove();
  } catch(e) { toast('Ошибка: ' + e.message); }
}

/* ── Добавить книгу из библиотеки в спринт ───────────────────────────────── */
let _searchTimer2 = null;

function openAddToSprintModal() {
  new bootstrap.Modal(document.getElementById('addToSprintModal')).show();
}

function searchLibraryForSprint(q) {
  clearTimeout(_searchTimer2);
  const res = document.getElementById('sprint-add-results');
  if (!q.trim()) { res.innerHTML = ''; return; }
  _searchTimer2 = setTimeout(async () => {
    res.innerHTML = '<div class="text-center text-muted py-2"><span class="spinner-border spinner-border-sm"></span></div>';
    try {
      const data = await api(`/api/books?q=${encodeURIComponent(q)}&per_page=20&sort=title`);
      if (!data.books.length) {
        res.innerHTML = '<div class="text-muted text-center py-2">Ничего не найдено</div>';
        return;
      }
      res.innerHTML = data.books.map(b => `
        <div class="d-flex align-items-center gap-2 py-2 border-bottom">
          <div class="flex-grow-1">
            <div class="fw-semibold small">${esc(b.title)}</div>
            ${b.author ? `<div class="text-muted" style="font-size:.78rem;font-style:italic">${esc(b.author)}</div>` : ''}
          </div>
          ${b.exl_no != null ? `<span class="badge bg-dark" style="font-size:.65rem">EXL ${b.exl_no}</span>` : ''}
          <button class="btn btn-sm btn-success flex-shrink-0"
                  onclick="addLibBookToSprint(${JSON.stringify(b.title)}, ${JSON.stringify(b.author||'')}, this)">
            <i class="bi bi-plus"></i> В беклог
          </button>
        </div>`).join('');
    } catch(e) { res.innerHTML = `<div class="text-danger small">${e.message}</div>`; }
  }, 300);
}

async function addLibBookToSprint(title, author, btn) {
  const child = document.getElementById('sprint-child')?.value || 'Максим';
  const year  = parseInt(document.getElementById('sprint-year')?.value) || 2026;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    await fetch('/api/sprints/add-book', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, author, child, year }),
    });
    btn.innerHTML = '<i class="bi bi-check2"></i>';
    btn.classList.replace('btn-success', 'btn-outline-success');
    loadSprints();
    toast(`«${title}» добавлена в беклог`);
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-plus"></i> В беклог';
    toast('Ошибка: ' + e.message);
  }
}

/* ── Читательский дневник ────────────────────────────────────────────────── */

function renderDiary(doneItems) {
  const el = document.getElementById('diary-content');
  if (!doneItems.length) {
    el.innerHTML = `<div class="empty-state">
      <i class="bi bi-journal"></i>
      <p>Прочитанных книг пока нет</p>
      <p class="small text-muted">Когда книга будет прочитана — переведи её в колонку «Прочитано» на канбане и заполни дневник</p>
    </div>`;
    return;
  }

  function diaryRow(emoji, label, text) {
    if (!text) return '';
    return `<div class="diary-entry-row">
      <div class="diary-entry-label">${emoji} ${label}</div>
      <div class="diary-entry-text">${esc(text)}</div>
    </div>`;
  }

  el.innerHTML = doneItems.map(it => {
    const hasContent = it.summary || it.heroes || it.main_idea || it.quote || it.opinion || it.questions;
    return `
    <div class="diary-card">
      <div class="d-flex align-items-start justify-content-between gap-2">
        <div class="flex-grow-1">
          <div class="diary-card-title">${esc(it.title)}</div>
          <div class="diary-card-meta">
            ${it.author    ? esc(it.author) + '&nbsp;·&nbsp;' : ''}
            ${it.genre     ? esc(it.genre)  + '&nbsp;·&nbsp;' : ''}
            ${it.date_read ? 'прочитано ' + fmtDate(it.date_read) + '&nbsp;·&nbsp;' : ''}
            ${it.rating    ? esc(it.rating) : ''}
          </div>
        </div>
        <button class="btn btn-sm btn-outline-secondary flex-shrink-0"
                onclick="openDiaryModal(_sprintItemById('${it.id}'))" title="Редактировать">
          <i class="bi bi-pencil-square"></i>
        </button>
      </div>

      ${hasContent ? `
        ${it.summary   ? `<div class="diary-entry-row"><div class="diary-entry-label">📚 О чём книга</div><div class="diary-entry-text">${esc(it.summary)}</div></div>` : ''}
        ${it.heroes    ? `<div class="diary-entry-row"><div class="diary-entry-label">👥 Главные герои</div><div class="diary-entry-text">${esc(it.heroes)}</div></div>` : ''}
        ${it.main_idea ? `<div class="diary-entry-row"><div class="diary-entry-label">💡 Главная мысль</div><div class="diary-entry-text">${esc(it.main_idea)}</div></div>` : ''}
        ${it.quote     ? `<div class="diary-entry-quote">${esc(it.quote)}</div>` : ''}
        ${it.opinion   ? `<div class="diary-entry-row"><div class="diary-entry-label">⭐ Моё мнение</div><div class="diary-entry-text">${esc(it.opinion)}</div></div>` : ''}
        ${it.questions ? `<div class="diary-entry-row"><div class="diary-entry-label">❓ Вопросы к автору</div><div class="diary-entry-text">${esc(it.questions)}</div></div>` : ''}
      ` : `<div class="diary-empty-notes" onclick="openDiaryModal(_sprintItemById('${it.id}'))">
             ✏️ Дневник ещё не заполнен — нажми, чтобы написать</div>`}
    </div>`;
  }).join('');
}

function openDiaryModal(item) {
  // item — объект из sprint items
  if (typeof item === 'string') {
    // Legacy: called with positional args — find item in last loaded list
    const [id, title, author, notes, rating, dateRead] = arguments;
    item = { id, title, author, notes: notes||'', rating: rating||'', date_read: dateRead||'',
             summary:'', heroes:'', main_idea:'', quote:'', questions:'', opinion:'', genre:'' };
  }
  window._diaryItemId = item.id;

  document.getElementById('diary-title').textContent  = item.title  || '';
  document.getElementById('diary-author').textContent = item.author || '';
  document.getElementById('diary-date').value         = item.date_read || '';
  document.getElementById('diary-rating').value       = item.rating    || '';
  document.getElementById('diary-genre').value        = item.genre     || '';
  document.getElementById('diary-summary').value      = item.summary   || '';
  document.getElementById('diary-heroes').value       = item.heroes    || '';
  document.getElementById('diary-main-idea').value    = item.main_idea || '';
  document.getElementById('diary-quote').value        = item.quote     || '';
  document.getElementById('diary-opinion').value      = item.opinion   || '';
  document.getElementById('diary-questions').value    = item.questions || '';

  new bootstrap.Modal(document.getElementById('diaryModal')).show();
}

async function saveDiaryEntry() {
  const id = window._diaryItemId;
  if (!id) return;
  const btn = document.getElementById('diary-save-btn');
  btn.disabled = true;
  try {
    await fetch(`/api/sprints/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date_read: document.getElementById('diary-date').value,
        rating:    document.getElementById('diary-rating').value,
        genre:     document.getElementById('diary-genre').value,
        summary:   document.getElementById('diary-summary').value,
        heroes:    document.getElementById('diary-heroes').value,
        main_idea: document.getElementById('diary-main-idea').value,
        quote:     document.getElementById('diary-quote').value,
        opinion:   document.getElementById('diary-opinion').value,
        questions: document.getElementById('diary-questions').value,
      }),
    });
    bootstrap.Modal.getInstance(document.getElementById('diaryModal')).hide();
    loadSprints();
    toast('Запись в дневник сохранена 📖');
  } catch(e) {
    toast('Ошибка: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

/* ── Обновление из Notion ────────────────────────────────────────────────── */
async function refreshLibrary() {
  toast('Обновляю из Notion…');
  try {
    const r = await fetch('/api/refresh', { method: 'POST' }).then(r => r.json());
    toast(`Загружено ${r.total} книг из ${r.source}`);
    loadStats();
    loadBooks(1);
    loadBuyList();
  } catch(e) { toast('Ошибка обновления'); }
}

/* ── Матчинг книга → квиз ────────────────────────────────────────────────── */
function _normTitle(s) {
  return (s || '').toLowerCase()
    .replace(/ё/g, 'е').replace(/й/g, 'й')
    .replace(/[«»""'.,!?:;—–\-]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

function findQuizForBook(title) {
  if (!_quizzes.length) return null;
  const t = _normTitle(title);
  // Точное совпадение или вхождение
  for (const q of _quizzes) {
    const qt = _normTitle(q.title);
    if (t === qt || t.includes(qt) || qt.includes(t)) return q;
  }
  // Fuzzy: сравниваем первые значимые слова
  const words = t => t.split(' ').filter(w => w.length > 3);
  const bWords = new Set(words(t));
  let best = null, bestScore = 0;
  for (const q of _quizzes) {
    const qWords = words(_normTitle(q.title));
    const hits = qWords.filter(w => bWords.has(w)).length;
    const score = hits / Math.max(qWords.length, 1);
    if (score > bestScore && score >= 0.5) { best = q; bestScore = score; }
  }
  return best;
}

function isQuizCompleted(quizId) {
  const p = _loadQuizProgress()[quizId];
  return p && p.best >= 7;   // ≥7/10 считается сданным
}

/* ── Тесты по произведениям ──────────────────────────────────────────────── */

let _quizzes = [];
let _currentQuiz = null;
let _currentQ = 0;
let _score = 0;
let _answered = false;

const QUIZ_STORAGE_KEY = 'quiz_progress_v1';

function _loadQuizProgress() {
  try { return JSON.parse(localStorage.getItem(QUIZ_STORAGE_KEY) || '{}'); } catch { return {}; }
}
function _saveQuizProgress(progress) {
  localStorage.setItem(QUIZ_STORAGE_KEY, JSON.stringify(progress));
}

async function loadQuizzes() {
  if (_quizzes.length) { renderQuizList(); return; }
  try {
    const r = await fetch('/static/quizzes.json');
    _quizzes = await r.json();
    renderQuizList();
  } catch(e) { console.warn('quizzes:', e); }
}

function renderQuizList() {
  const progress = _loadQuizProgress();
  const container = document.getElementById('quiz-cards');
  if (!container) return;

  container.innerHTML = _quizzes.map(q => {
    const p = progress[q.id];
    const best = p ? p.best : null;
    const attempts = p ? p.attempts : 0;
    const lastDate = p ? fmtDate(p.lastDate) : '';

    let badgeCls = 'quiz-score-none', badgeText = 'Не проходил';
    if (best !== null) {
      if (best === 10)      { badgeCls = 'quiz-score-perfect'; badgeText = '10/10 ⭐ Отлично!'; }
      else if (best >= 8)   { badgeCls = 'quiz-score-high';    badgeText = `${best}/10 Хорошо`; }
      else if (best >= 5)   { badgeCls = 'quiz-score-mid';     badgeText = `${best}/10 Неплохо`; }
      else                  { badgeCls = 'quiz-score-low';     badgeText = `${best}/10 Попробуй ещё`; }
    }

    return `
      <div class="col-12 col-md-6">
        <div class="quiz-card" onclick="startQuiz('${q.id}')">
          <div class="d-flex align-items-start justify-content-between">
            <div class="flex-grow-1">
              <div class="quiz-card-title">${esc(q.title)}</div>
              <div class="quiz-card-author">${esc(q.author)}</div>
            </div>
            <span class="badge bg-secondary ms-2" style="font-size:.65rem">${q.questions.length} вопр.</span>
          </div>
          <div class="quiz-card-score d-flex align-items-center gap-2 flex-wrap">
            <span class="quiz-score-badge ${badgeCls}">${badgeText}</span>
            ${attempts > 0 ? `<span class="text-muted" style="font-size:.72rem">${attempts} попыток · ${lastDate}</span>` : ''}
          </div>
          <div class="mt-2">
            <small class="text-muted">Источник: <a href="${esc(q.sourceUrl)}" target="_blank" onclick="event.stopPropagation()">${esc(q.source)}</a></small>
          </div>
        </div>
      </div>`;
  }).join('');
}

function startQuiz(quizId) {
  _currentQuiz = _quizzes.find(q => q.id === quizId);
  if (!_currentQuiz) return;
  _currentQ = 0;
  _score = 0;

  document.getElementById('quiz-book-title').textContent  = _currentQuiz.title;
  document.getElementById('quiz-book-author').textContent = _currentQuiz.author;
  document.getElementById('quiz-list-view').style.display = 'none';
  document.getElementById('quiz-game-view').style.display = '';
  document.getElementById('quiz-result').style.display    = 'none';
  document.getElementById('quiz-question-card').style.display = '';
  renderQuestion();
}

function renderQuestion() {
  const q = _currentQuiz.questions[_currentQ];
  const total = _currentQuiz.questions.length;
  _answered = false;

  document.getElementById('quiz-question-num').textContent  = `Вопрос ${_currentQ + 1} из ${total}`;
  document.getElementById('quiz-question-text').textContent = q.q;
  document.getElementById('quiz-progress-bar').style.width  = `${_currentQ / total * 100}%`;
  document.getElementById('quiz-progress-text').textContent = `${_currentQ} / ${total}`;
  document.getElementById('quiz-next-btn').classList.add('d-none');

  const fb = document.getElementById('quiz-feedback');
  fb.className = 'quiz-feedback d-none';
  fb.textContent = '';

  document.getElementById('quiz-options').innerHTML = q.options.map((opt, i) =>
    `<div class="quiz-option" data-i="${i}" onclick="answerQuestion(${i})">${esc(opt)}</div>`
  ).join('');
}

function answerQuestion(chosen) {
  if (_answered) return;
  _answered = true;
  const q = _currentQuiz.questions[_currentQ];
  const correct = q.answer;
  const isRight = chosen === correct;
  if (isRight) _score++;

  // Подсветка вариантов
  document.querySelectorAll('.quiz-option').forEach(el => {
    el.classList.add('disabled');
    const i = parseInt(el.dataset.i);
    if (i === correct) el.classList.add('correct');
    else if (i === chosen && !isRight) el.classList.add('wrong');
  });

  // Обратная связь
  const fb = document.getElementById('quiz-feedback');
  fb.className = `quiz-feedback ${isRight ? 'correct' : 'wrong'}`;
  fb.textContent = isRight ? '✅ Правильно!' : `❌ Неверно. Правильный ответ: «${q.options[correct]}»`;

  // Кнопка «Далее»
  const nextBtn = document.getElementById('quiz-next-btn');
  nextBtn.classList.remove('d-none');
  const isLast = _currentQ === _currentQuiz.questions.length - 1;
  nextBtn.textContent = isLast ? 'Посмотреть результат' : 'Следующий вопрос →';
  nextBtn.onclick = isLast ? showQuizResult : nextQuestion;
}

function nextQuestion() {
  _currentQ++;
  renderQuestion();
}

function showQuizResult() {
  const total = _currentQuiz.questions.length;
  document.getElementById('quiz-question-card').style.display = 'none';
  document.getElementById('quiz-result').style.display = '';
  document.getElementById('quiz-progress-bar').style.width = '100%';
  document.getElementById('quiz-progress-text').textContent = `${total} / ${total}`;

  document.getElementById('quiz-result-score').textContent = `${_score} / ${total}`;

  const pct = _score / total;
  const msgs = [
    [1.0,  '🏆 Идеально! Ты отлично знаешь это произведение!'],
    [0.8,  '🎉 Отличный результат! Совсем немного не хватило до идеала.'],
    [0.6,  '👍 Неплохо! Перечитай несколько глав и попробуй ещё раз.'],
    [0.4,  '📖 Попробуй перечитать произведение — это поможет!'],
    [0,    '💪 Не сдавайся! После прочтения книги пройди тест снова.'],
  ];
  document.getElementById('quiz-result-msg').textContent =
    msgs.find(([threshold]) => pct >= threshold)?.[1] || '';

  // Сохраняем прогресс
  const progress = _loadQuizProgress();
  const prev = progress[_currentQuiz.id] || { best: 0, attempts: 0 };
  progress[_currentQuiz.id] = {
    best:     Math.max(prev.best, _score),
    attempts: prev.attempts + 1,
    lastDate: new Date().toISOString().slice(0, 10),
    lastScore: _score,
  };
  _saveQuizProgress(progress);
}

function retryQuiz() {
  startQuiz(_currentQuiz.id);
}

function exitQuiz() {
  document.getElementById('quiz-game-view').style.display = 'none';
  document.getElementById('quiz-list-view').style.display = '';
  renderQuizList();  // обновить значки прогресса
}

function resetAllQuizProgress() {
  if (!confirm('Сбросить весь прогресс тестов?')) return;
  localStorage.removeItem(QUIZ_STORAGE_KEY);
  renderQuizList();
  toast('Прогресс сброшен');
}

/* ── Утилиты ─────────────────────────────────────────────────────────────── */
async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function esc(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
}

let _toastInstance = null;
function toast(msg) {
  const el = document.getElementById('toast');
  document.getElementById('toast-body').textContent = msg;
  if (!_toastInstance) _toastInstance = new bootstrap.Toast(el, { delay: 2500 });
  _toastInstance.show();
}
