/* StudentHub frontend core: API, layout, modals, toasts */
(function () {
    'use strict';

    // ---------- Icons (lucide-style SVG) ----------
    const ICONS = {
        dashboard: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
        students: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        groups: '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/>',
        subjects: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
        grades: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
        attendance: '<path d="M8 2v4"/><path d="M16 2v4"/><rect x="3" y="4" width="18" height="18" rx="2"/><path d="m9 16 2 2 4-4"/>',
        reports: '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
        users: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
        search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
        plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
        edit: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
        trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
        eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
        x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
        print: '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
        menu: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
        cap: '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
        chart: '<path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/>',
        star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
        alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        teacher: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
        userPlus: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/>',
        key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
        check: '<path d="M20 6 9 17l-5-5"/>',
        save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
        back: '<path d="m15 18-6-6 6-6"/>',
    };
    const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;

    // ---------- Utils ----------
    const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
    const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
    // "Today" (institution timezone) and the ECTS scale come from /api/auth/me; local values are fallbacks.
    let serverToday = null;
    let ectsScale = [
        { min: 90, ects: 'A' }, { min: 82, ects: 'B' }, { min: 74, ects: 'C' }, { min: 64, ects: 'D' },
        { min: 60, ects: 'E' }, { min: 35, ects: 'FX' }, { min: 0, ects: 'F' },
    ];
    const localTodayIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
    const todayIso = () => serverToday || localTodayIso();
    const fmtDate = (iso) => { if (!iso) return '—'; const [y, m, d] = String(iso).slice(0, 10).split('-'); return `${d}.${m}.${y}`; };
    const fmtNum = (v, digits = 1) => (v === null || v === undefined ? '—' : Number(v).toFixed(digits).replace(/\.0$/, ''));
    const initials = (name) => String(name || '?').split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
    const MONTHS = ['Січ', 'Лют', 'Бер', 'Кві', 'Тра', 'Чер', 'Лип', 'Сер', 'Вер', 'Жов', 'Лис', 'Гру'];
    const monthLabel = (ym) => { const [y, m] = ym.split('-'); return `${MONTHS[Number(m) - 1]} ${y}`; };

    const LABELS = {
        status: { active: 'Навчається', academic_leave: 'Академвідпустка', expelled: 'Відрахований', graduated: 'Випускник' },
        statusColor: { active: 'green', academic_leave: 'orange', expelled: 'red', graduated: 'blue' },
        gradeType: { current: 'Поточна', module: 'Модульна', exam: 'Екзамен', credit: 'Залік' },
        gradeTypeShort: { current: 'П', module: 'М', exam: 'Екз', credit: 'Зал' },
        control: { exam: 'Екзамен', credit: 'Залік' },
        attendance: { present: 'Присутній', late: 'Запізнення', absent: 'Відсутній', excused: 'Поважна' },
        role: { admin: 'Адміністратор', teacher: 'Викладач' },
        gender: { M: 'Чоловіча', F: 'Жіноча' },
    };

    function ects(score) {
        if (score === null || score === undefined) return null;
        const s = Math.round(score);  // matches server round_half_up for non-negative scores
        return (ectsScale.find((e) => s >= e.min) || ectsScale[ectsScale.length - 1]).ects;
    }
    const gradeBadge = (v) => (v === null || v === undefined ? '<span class="muted">—</span>'
        : `<span class="grade ${ects(v)}" title="ECTS: ${ects(v)}">${esc(fmtNum(v))}</span>`);
    const ectsBadge = (e) => (e ? `<span class="grade ${e}">${e}</span>` : '<span class="muted">—</span>');
    function rateBar(rate) {
        if (rate === null || rate === undefined) return '<span class="muted">—</span>';
        const cls = rate >= 85 ? 'green' : rate >= 75 ? 'orange' : 'red';
        return `<div class="rate"><div class="progress ${cls}"><span style="width:${Math.min(rate, 100)}%"></span></div><span>${fmtNum(rate)}%</span></div>`;
    }
    const statusBadge = (s) => `<span class="badge ${LABELS.statusColor[s] || ''}">${esc(LABELS.status[s] || s)}</span>`;

    // ---------- API ----------
    class ApiError extends Error {
        constructor(status, data) { super(data?.error || `Помилка ${status}`); this.status = status; this.details = data?.details; }
    }
    async function api(method, url, body) {
        const opts = { method, headers: {}, credentials: 'same-origin' };
        if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
        let res;
        try { res = await fetch(url, opts); } catch { throw new ApiError(0, { error: 'Немає звʼязку із сервером' }); }
        if (res.status === 401 && !url.startsWith('/api/auth/login')) {
            location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
            throw new ApiError(401, { error: 'Сесія завершилась' });
        }
        if (res.status === 204) return null;
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new ApiError(res.status, data);
        return data;
    }
    api.get = (u) => api('GET', u);
    api.post = (u, b) => api('POST', u, b ?? {});
    api.put = (u, b) => api('PUT', u, b);       // full replace (groups, subjects)
    api.patch = (u, b) => api('PATCH', u, b);   // partial update (students, grades, users)
    api.del = (u) => api('DELETE', u);
    const qs = (obj) => {
        const p = new URLSearchParams();
        Object.entries(obj).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, v); });
        const s = p.toString();
        return s ? `?${s}` : '';
    };

    // Cached reference data
    const cache = {};
    const lookup = (key, url) => { cache[key] = cache[key] || api.get(url); return cache[key]; };
    const refs = {
        groups: () => lookup('groups', '/api/groups'),
        subjects: () => lookup('subjects', '/api/subjects'),
        teachers: () => lookup('teachers', '/api/users/teachers'),
        invalidate: (key) => { delete cache[key]; },
    };
    /** Teacher/curator options: active users plus the current assignee even if blocked, so saving doesn't drop it. */
    const userOptions = (users, currentId) => users
        .filter((u) => u.is_active || u.id === Number(currentId))
        .map((u) => ({ value: u.id, label: u.is_active ? u.full_name : `${u.full_name} (заблоковано)` }));

    /** Disable the button while the request runs to prevent double submit. */
    async function busy(button, fn) {
        if (button.disabled) return undefined;
        button.disabled = true;
        try { return await fn(); } finally { button.disabled = false; }
    }

    const options = (items, { value = 'id', label = 'name', empty, selected } = {}) =>
        (empty !== undefined ? `<option value="">${esc(empty)}</option>` : '')
        + items.map((i) => `<option value="${esc(i[value])}" ${String(i[value]) === String(selected ?? '') ? 'selected' : ''}>${esc(typeof label === 'function' ? label(i) : i[label])}</option>`).join('');

    // ---------- Toasts ----------
    function toast(message, type = 'info') {
        let box = $('.toasts');
        if (!box) { box = document.createElement('div'); box.className = 'toasts'; document.body.append(box); }
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.setAttribute('role', 'status');
        el.innerHTML = `${type === 'success' ? icon('check') : type === 'error' ? icon('alert') : ''}<span>${esc(message)}</span>`;
        box.append(el);
        setTimeout(() => el.remove(), 3500);
    }
    const toastError = (e) => toast(e?.message || 'Сталася помилка', 'error');

    // ---------- Modals ----------
    // Stack of open modals: only the top one handles Escape/Tab.
    const modalStack = [];
    const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusables = (root) => $$(FOCUSABLE, root).filter((el) => el.offsetParent !== null);

    document.addEventListener('keydown', (e) => {
        const top = modalStack[modalStack.length - 1];
        if (!top) return;
        if (e.key === 'Escape') {
            e.preventDefault(); e.stopPropagation();
            top.close(null);
        } else if (e.key === 'Tab') {
            // Focus trap: Tab / Shift+Tab cycle within the modal
            const items = focusables(top.el);
            if (!items.length) { e.preventDefault(); return; }
            const first = items[0]; const last = items[items.length - 1];
            if (!top.el.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
            else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }, true);

    function modal({ title, body, footer, size = '', onMount }) {
        return new Promise((resolve) => {
            const opener = document.activeElement;
            const back = document.createElement('div');
            back.className = 'modal-backdrop';
            back.innerHTML = `<div class="modal ${size}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
                <div class="modal-head"><h2>${esc(title)}</h2><button class="btn-icon" data-close aria-label="Закрити">${icon('x')}</button></div>
                <div class="modal-body">${body}</div>
                ${footer ? `<div class="modal-foot">${footer}</div>` : ''}</div>`;
            const el = back.querySelector('.modal');
            const entry = { el, close: null };
            let closed = false;
            const close = (val) => {
                if (closed) return;
                closed = true;
                back.remove();
                modalStack.splice(modalStack.indexOf(entry), 1);
                // Restore focus to the opener if it's still in the DOM
                if (opener && document.contains(opener)) opener.focus();
                resolve(val);
            };
            entry.close = close;
            back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
            back.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => close(null)));
            modalStack.push(entry);
            document.body.append(back);
            onMount?.(el, close);
            // Focus the first element if onMount didn't set focus
            if (!el.contains(document.activeElement)) {
                const items = focusables(el);
                (items.find((x) => !x.closest('.modal-head')) || items[0])?.focus();
            }
        });
    }

    function confirmDialog(message, { title = 'Підтвердження', okText = 'Видалити', danger = true } = {}) {
        return modal({
            title, size: 'sm', body: `<p style="margin:0">${esc(message)}</p>`,
            footer: `<button class="btn" data-close>Скасувати</button><button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-ok>${esc(okText)}</button>`,
            onMount: (m, close) => { const ok = m.querySelector('[data-ok]'); ok.focus(); ok.addEventListener('click', () => close(true)); },
        }).then(Boolean);
    }

    /** Show errors ({ field: message }) in .field[data-field] .error elements; an empty object clears them. */
    function showFieldErrors(root, errors = {}) {
        $$('.field[data-field]', root).forEach((el) => {
            const msg = errors[el.dataset.field];
            el.querySelector('.error').textContent = msg || '';
            el.querySelector('input, select, textarea')?.classList.toggle('invalid', Boolean(msg));
        });
    }

    /**
     * Modal form.
     * fields: [{ name, label, type: text|number|date|email|select|textarea|password|checkboxes, options, required, full, min, max, step, placeholder }]
     * submit(values) returns a Promise; server validation errors are shown next to fields.
     */
    function formModal({ title, fields, values = {}, submitText = 'Зберегти', submit }) {
        const fieldHtml = (f) => {
            const v = values[f.name] ?? f.default ?? '';
            const req = f.required ? 'required' : '';
            const id = `f_${f.name}`;
            let input;
            if (f.type === 'select') {
                input = `<select id="${id}" name="${f.name}" ${req}>${f.empty !== undefined ? `<option value="">${esc(f.empty)}</option>` : ''}${
                    f.options.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
            } else if (f.type === 'textarea') {
                input = `<textarea id="${id}" name="${f.name}" rows="3" ${req}>${esc(v)}</textarea>`;
            } else if (f.type === 'checkboxes') {
                const sel = new Set((values[f.name] || []).map(String));
                input = `<div class="checkbox-list" data-checkboxes="${f.name}">${f.options.map((o) =>
                    `<label><input type="checkbox" value="${esc(o.value)}" ${sel.has(String(o.value)) ? 'checked' : ''}> ${esc(o.label)}</label>`).join('') || '<span class="muted">Немає варіантів</span>'}</div>`;
            } else {
                input = `<input id="${id}" name="${f.name}" type="${f.type || 'text'}" value="${esc(v)}" ${req}
                    ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''}
                    ${f.step ? `step="${f.step}"` : ''} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ''}
                    ${f.autocomplete ? `autocomplete="${f.autocomplete}"` : ''}>`;
            }
            return `<div class="field ${f.full ? 'full' : ''}" data-field="${f.name}"><label for="${id}">${esc(f.label)}${f.required ? ' *' : ''}</label>${input}<div class="error"></div></div>`;
        };
        return modal({
            title,
            body: `<form class="form-grid" novalidate>${fields.map(fieldHtml).join('')}<button type="submit" hidden></button></form>`,
            footer: `<button class="btn" data-close>Скасувати</button><button class="btn btn-primary" data-submit>${esc(submitText)}</button>`,
            onMount: (m, close) => {
                const form = m.querySelector('form');
                const btn = m.querySelector('[data-submit]');
                const first = form.querySelector('input, select, textarea');
                first?.focus();
                const showErrors = (errors) => showFieldErrors(form, errors);
                const collect = () => {
                    const out = {};
                    for (const f of fields) {
                        if (f.type === 'checkboxes') {
                            out[f.name] = $$(`[data-checkboxes="${f.name}"] input:checked`, form).map((i) => Number(i.value));
                            continue;
                        }
                        const el = form.elements[f.name];
                        let v = el.value.trim();
                        if (v === '') v = null;
                        else if (f.type === 'number' || f.numeric) v = Number(v);
                        out[f.name] = v;
                    }
                    return out;
                };
                const doSubmit = async () => {
                    if (btn.disabled) return; // request already in flight
                    const data = collect();
                    const local = {};
                    fields.forEach((f) => { if (f.required && (data[f.name] === null || data[f.name] === undefined)) local[f.name] = 'Обовʼязкове поле'; });
                    showErrors(local);
                    if (Object.keys(local).length) return;
                    await busy(btn, async () => {
                        try {
                            const result = await submit(data);
                            close(result ?? true);
                        } catch (e) {
                            if (e.details) showErrors(e.details);
                            toastError(e);
                        }
                    });
                };
                btn.addEventListener('click', doSubmit);
                form.addEventListener('submit', (e) => { e.preventDefault(); doSubmit(); });
            },
        });
    }

    // ---------- Pagination ----------
    function pagination(container, { page, pages, total }, onPage) {
        if (!container) return;
        // Page no longer exists (e.g. last item deleted): go to the last page
        if (pages >= 1 && page > pages) { onPage(pages); return; }
        const nums = [];
        for (let p = Math.max(1, page - 2); p <= Math.min(pages, page + 2); p += 1) nums.push(p);
        container.innerHTML = `<span class="muted">Усього: ${total}</span><div class="pages">
            <button class="btn" data-p="${page - 1}" ${page <= 1 ? 'disabled' : ''} aria-label="Попередня">‹</button>
            ${nums.map((p) => `<button class="btn ${p === page ? 'active' : ''}" data-p="${p}">${p}</button>`).join('')}
            <button class="btn" data-p="${page + 1}" ${page >= pages ? 'disabled' : ''} aria-label="Наступна">›</button></div>`;
        container.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => onPage(Number(b.dataset.p))));
    }

    // ---------- Page layout ----------
    const NAV = [
        { section: 'Головне' },
        { id: 'dashboard', href: '/', label: 'Головна', icon: 'dashboard' },
        { section: 'Навчальний процес' },
        { id: 'students', href: '/students', label: 'Студенти', icon: 'students' },
        { id: 'groups', href: '/groups', label: 'Групи', icon: 'groups' },
        { id: 'subjects', href: '/subjects', label: 'Дисципліни', icon: 'subjects' },
        { id: 'grades', href: '/grades', label: 'Оцінки', icon: 'grades' },
        { id: 'attendance', href: '/attendance', label: 'Відвідуваність', icon: 'attendance' },
        { section: 'Аналітика' },
        { id: 'reports', href: '/reports', label: 'Звіти', icon: 'reports' },
        { section: 'Адміністрування', admin: true },
        { id: 'users', href: '/users', label: 'Користувачі', icon: 'users', admin: true },
    ];

    let currentUser = null;

    function renderLayout(pageId, crumbs) {
        const isAdmin = currentUser.role === 'admin';
        const nav = NAV.filter((n) => !n.admin || isAdmin).map((n) => (n.section
            ? `<div class="nav-title">${esc(n.section)}</div>`
            : `<a href="${n.href}" class="${n.id === pageId ? 'active' : ''}">${icon(n.icon)}<span>${esc(n.label)}</span></a>`)).join('');

        const content = $('#page');
        const layout = document.createElement('div');
        layout.className = 'layout';
        layout.innerHTML = `
            <aside class="sidebar" aria-label="Навігація">
                <div class="brand"><div class="brand-logo">${icon('cap')}</div>StudentHub</div>
                <nav class="nav">${nav}</nav>
                <div class="sidebar-footer">
                    <div class="avatar">${esc(initials(currentUser.full_name))}</div>
                    <div class="user-meta"><div class="name" title="${esc(currentUser.full_name)}">${esc(currentUser.full_name)}</div><div class="role">${esc(LABELS.role[currentUser.role])}</div></div>
                    <button class="btn-icon" id="btnPassword" title="Змінити пароль" aria-label="Змінити пароль">${icon('key')}</button>
                    <button class="btn-icon" id="btnLogout" title="Вийти" aria-label="Вийти">${icon('logout')}</button>
                </div>
            </aside>
            <div class="main">
                <header class="topbar">
                    <button class="btn-icon menu-toggle" id="menuToggle" aria-label="Меню">${icon('menu')}</button>
                    <div class="breadcrumbs">${crumbs.map((c, i) => (i === crumbs.length - 1 ? `<b>${esc(c)}</b>` : `<span>${esc(c)}</span><span>›</span>`)).join('')}</div>
                    <div class="spacer"></div>
                    <div class="global-search">
                        ${icon('search')}<input id="globalSearch" type="search" placeholder="Пошук студента…" autocomplete="off" aria-label="Пошук студента"><kbd>Ctrl K</kbd>
                        <div class="search-results hidden" id="searchResults"></div>
                    </div>
                </header>
                <main class="content"></main>
            </div>`;
        layout.querySelector('.content').append(content);
        content.classList.remove('hidden');
        document.body.prepend(layout);

        $('#btnLogout').addEventListener('click', async () => { await api.post('/api/auth/logout').catch(() => {}); location.href = '/login'; });
        $('#btnPassword').addEventListener('click', changePassword);
        $('#menuToggle').addEventListener('click', () => document.body.classList.toggle('nav-open'));
        document.addEventListener('click', (e) => {
            if (document.body.classList.contains('nav-open') && !e.target.closest('.sidebar') && !e.target.closest('#menuToggle')) document.body.classList.remove('nav-open');
        });
        initGlobalSearch();
        // Print buttons (no inline handlers, for CSP)
        document.addEventListener('click', (e) => { if (e.target.closest('[data-print]')) window.print(); });
        document.title = `${crumbs[crumbs.length - 1]} · StudentHub`;
    }

    function initGlobalSearch() {
        const input = $('#globalSearch');
        const box = $('#searchResults');
        // items belong to itemsQuery and are reset on input, so Enter never opens a stale result
        let items = []; let itemsQuery = null; let focus = -1;
        let seq = 0; // request counter: stale responses are ignored
        const render = () => {
            box.innerHTML = items.length
                ? items.map((s, i) => `<a href="/student?id=${s.id}" class="${i === focus ? 'focused' : ''}"><span>${esc(s.last_name)} ${esc(s.first_name)}</span><span class="muted">${esc(s.group_name || '')}</span></a>`).join('')
                : '<div class="empty">Нічого не знайдено</div>';
            box.classList.remove('hidden');
        };
        const clear = () => { items = []; itemsQuery = null; focus = -1; seq += 1; box.classList.add('hidden'); };
        const search = debounce(async () => {
            const q = input.value.trim();
            if (q.length < 2) return;
            const my = ++seq;
            try {
                const data = await api.get(`/api/students${qs({ search: q, limit: 8 })}`);
                if (my !== seq) return;
                items = data.items; itemsQuery = q; focus = -1; render();
            } catch { /* ignore */ }
        }, 250);
        input.addEventListener('input', () => { clear(); search(); });
        input.addEventListener('keydown', (e) => {
            const current = itemsQuery === input.value.trim() ? items : [];
            if (e.key === 'ArrowDown' && current.length) { focus = Math.min(focus + 1, current.length - 1); render(); e.preventDefault(); }
            if (e.key === 'ArrowUp' && current.length) { focus = Math.max(focus - 1, 0); render(); e.preventDefault(); }
            if (e.key === 'Enter' && current[Math.max(focus, 0)]) location.href = `/student?id=${current[Math.max(focus, 0)].id}`;
            if (e.key === 'Escape') { box.classList.add('hidden'); input.blur(); }
        });
        input.addEventListener('blur', () => setTimeout(() => box.classList.add('hidden'), 150));
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); input.select(); }
        });
    }

    function changePassword() {
        formModal({
            title: 'Зміна пароля',
            fields: [
                { name: 'current_password', label: 'Поточний пароль', type: 'password', required: true, full: true, autocomplete: 'current-password' },
                { name: 'new_password', label: 'Новий пароль (мін. 6 символів)', type: 'password', required: true, full: true, autocomplete: 'new-password' },
            ],
            submit: (d) => api.post('/api/auth/change-password', d),
        }).then((ok) => ok && toast('Пароль змінено', 'success'));
    }

    /** Entry point for every page. */
    async function boot(pageId, crumbs, init) {
        try {
            const me = await api.get('/api/auth/me');
            currentUser = me.user;
            if (me.today) serverToday = me.today;
            if (Array.isArray(me.ects) && me.ects.length) ectsScale = me.ects;
        } catch { return; }
        renderLayout(pageId, crumbs);
        if (currentUser.role !== 'admin') $$('.admin-only').forEach((el) => el.remove());
        try { await init(currentUser); } catch (e) { toastError(e); console.error(e); }
    }

    // Chart.js defaults matching the theme
    function chartDefaults() {
        if (!window.Chart) return;
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        Chart.defaults.color = '#6b7286';
        Chart.defaults.plugins.legend.labels.boxWidth = 10;
        Chart.defaults.plugins.legend.labels.boxHeight = 10;
        Chart.defaults.maintainAspectRatio = false;
        Chart.defaults.locale = 'uk-UA';
    }

    function download(url) {
        const a = document.createElement('a');
        a.href = url; a.download = ''; document.body.append(a); a.click(); a.remove();
    }

    window.SH = {
        api, qs, refs, options, userOptions, busy, toast, toastError, modal, confirmDialog, formModal, showFieldErrors, pagination, boot, icon,
        esc, $, $$, debounce, todayIso, fmtDate, fmtNum, initials, monthLabel, LABELS, ects, gradeBadge, ectsBadge,
        rateBar, statusBadge, chartDefaults, download, get user() { return currentUser; },
    };
})();
