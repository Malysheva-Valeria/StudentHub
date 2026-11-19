SH.boot('grades', ['Навчальний процес', 'Оцінки'], async (user) => {
    const { api, qs, refs, options, esc, $, $$, icon, toast, toastError, confirmDialog, modal, pagination, gradeBadge, ectsBadge, fmtDate, fmtNum, todayIso, debounce, busy, showFieldErrors, LABELS } = SH;
    const isAdmin = user.role === 'admin';
    const [groups, allSubjects] = await Promise.all([refs.groups(), refs.subjects()]);
    const canManage = (subjectId) => isAdmin || allSubjects.find((s) => s.id === Number(subjectId))?.teacher_id === user.id;
    const subjectById = (id) => allSubjects.find((s) => s.id === Number(id));

    /**
     * Grade types for a subject: current and module always, final only for its control form.
     * The existing type (selected) is always included so editing the score doesn't change it.
     */
    const typeOptions = (subject, selected) => Object.entries(LABELS.gradeType)
        .filter(([type]) => type === 'current' || type === 'module' || type === subject?.control || type === selected)
        .map(([value, label]) => `<option value="${value}" ${value === selected ? 'selected' : ''}>${label}</option>`).join('');

    // ---------- Tabs ----------
    $$('.tabs button').forEach((b) => b.addEventListener('click', () => {
        $$('.tabs button').forEach((x) => { x.classList.toggle('active', x === b); x.setAttribute('aria-selected', String(x === b)); });
        $$('[data-panel]').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== b.dataset.tab));
        if (b.dataset.tab === 'list') loadList();
    }));

    // ---------- Journal ----------
    const j = { group: '', subject: '' };
    $('#jGroup').innerHTML = options(groups, { empty: 'Оберіть групу' });
    $('#jSubject').innerHTML = '<option value="">Спершу оберіть групу</option>';
    let journalData = null;

    $('#jGroup').addEventListener('change', async (e) => {
        j.group = e.target.value; j.subject = '';
        if (!j.group) { $('#jSubject').innerHTML = '<option value="">Спершу оберіть групу</option>'; renderJournalEmpty(); return; }
        let subs;
        try { subs = await api.get(`/api/groups/${j.group}/subjects`); } catch (err) { toastError(err); return; }
        const mine = subs.filter((s) => canManage(s.id));
        $('#jSubject').innerHTML = subs.length
            ? options(subs, { empty: 'Оберіть дисципліну', label: (s) => `${s.name}${canManage(s.id) && !isAdmin ? ' (моя)' : ''}` })
            : '<option value="">Групі не призначено дисциплін</option>';
        if (mine.length === 1 && !isAdmin) { $('#jSubject').value = mine[0].id; j.subject = String(mine[0].id); loadJournal(); } else renderJournalEmpty();
    });
    $('#jSubject').addEventListener('change', (e) => { j.subject = e.target.value; loadJournal(); });

    function renderJournalEmpty() { journalData = null; $('#journal').innerHTML = '<div class="table-empty">Оберіть групу та дисципліну</div>'; }

    async function loadJournal() {
        if (!j.group || !j.subject) { renderJournalEmpty(); return; }
        $('#journal').innerHTML = '<div class="loader"><span class="spinner"></span></div>';
        try {
            journalData = await api.get(`/api/grades/journal${qs({ group_id: j.group, subject_id: j.subject })}`);
            renderJournal();
        } catch (e) {
            journalData = null;
            $('#journal').innerHTML = `<div class="table-empty">Не вдалося завантажити журнал: ${esc(e.message)}</div>`;
        }
    }

    function renderJournal() {
        const { columns, rows } = journalData;
        const editable = canManage(j.subject);
        if (!rows.length) { $('#journal').innerHTML = '<div class="table-empty">У групі немає активних студентів</div>'; return; }
        const head = columns.map((c) => `<th class="date" title="${esc(LABELS.gradeType[c.type])}">${fmtDate(c.date).slice(0, 5)}<br><span class="muted">${esc(LABELS.gradeTypeShort[c.type])}</span></th>`).join('');
        // Transferred students (former) go last; only their existing grades are editable
        const body = rows.map((r, i) => `<tr data-student="${r.id}" class="${r.former ? 'former' : ''}">
            <td class="sticky name" title="${esc(r.last_name)} ${esc(r.first_name)}${r.former ? ' — переведено до іншої групи' : ''}">${i + 1}. <a href="/student?id=${r.id}">${esc(r.last_name)} ${esc(r.first_name)}</a>${r.former ? ' <span class="badge">переведено</span>' : ''}</td>
            ${columns.map((c) => {
                const cell = r.cells[c.key];
                const clickable = editable && (cell || !r.former);
                return `<td class="cell" data-col="${esc(c.key)}" ${cell ? `data-grade="${cell.id}"` : ''} style="${clickable ? 'cursor:pointer' : ''}">${cell ? gradeBadge(cell.value) : ''}</td>`;
            }).join('')}
            <td class="center"><b>${fmtNum(r.avg)}</b></td><td class="center hide-sm">${ectsBadge(r.ects)}</td></tr>`).join('');
        $('#journal').innerHTML = `
            ${editable ? '' : '<div class="stats-row"><span class="muted">Перегляд: ви не ведете цю дисципліну, тому редагування недоступне.</span></div>'}
            <div class="table-wrap"><table class="table journal"><thead><tr><th class="sticky name">Студент</th>${head}<th class="center">Сер.</th><th class="center hide-sm">ECTS</th></tr></thead>
            <tbody>${body}</tbody></table></div>
            ${columns.length ? '' : '<div class="table-empty">Оцінок ще немає. Натисніть «Нове заняття», щоб виставити оцінки.</div>'}`;
        const wrap = $('#journal .table-wrap'); wrap.scrollLeft = wrap.scrollWidth;
    }

    $('#journal').addEventListener('click', async (e) => {
        const td = e.target.closest('td.cell');
        if (!td || e.target.closest('a') || !canManage(j.subject)) return;
        if (!td.dataset.grade && td.parentElement.classList.contains('former')) return; // no new grades for transferred students
        const studentId = Number(td.parentElement.dataset.student);
        const [date, type] = td.dataset.col.split('|');
        if (td.dataset.grade) {
            const g = await api.get(`/api/grades/${td.dataset.grade}`);
            if (await editGrade(g)) loadJournal();
        } else if (await addGrade({ student_id: studentId, subject_id: Number(j.subject), group_id: Number(j.group), date, type })) loadJournal();
    });

    // New lesson: bulk grading for a group
    $('#btnLesson').addEventListener('click', async () => {
        if (!j.group || !j.subject) { toast('Оберіть групу та дисципліну', 'error'); return; }
        if (!canManage(j.subject)) { toast('Ви можете виставляти оцінки лише зі своїх дисциплін', 'error'); return; }
        // Current group members enrolled on or before the lesson date
        const students = (journalData?.rows || []).filter((r) => !r.former);
        const saved = await modal({
            title: 'Оцінки за заняття',
            body: `<div class="form-grid">
                <div class="field"><label for="lsDate">Дата</label><input id="lsDate" type="date" value="${todayIso()}" max="${todayIso()}"></div>
                <div class="field"><label for="lsType">Тип оцінки</label><select id="lsType">${typeOptions(subjectById(j.subject))}</select></div></div>
                <p class="small muted" style="margin-top:0">Залиште поле порожнім, якщо студент не оцінювався.</p>
                <table class="table journal"><tbody>${students.map((r) => `<tr data-enrolled="${esc(r.enrolled_at)}"><td>${esc(r.last_name)} ${esc(r.first_name)}</td>
                    <td class="num"><input class="grade-input" type="number" min="0" max="100" data-sid="${r.id}" aria-label="Бал ${esc(r.last_name)}"></td></tr>`).join('')}</tbody></table>
                <p class="small muted hidden" id="lsHidden"></p>`,
            footer: '<button class="btn" data-close>Скасувати</button><button class="btn btn-primary" data-save>Зберегти</button>',
            onMount: (m, close) => {
                const visibleInputs = () => [...m.querySelectorAll('tr[data-enrolled]:not(.hidden) .grade-input')];
                const filterByDate = () => {
                    const date = m.querySelector('#lsDate').value;
                    let hidden = 0;
                    m.querySelectorAll('tr[data-enrolled]').forEach((tr) => {
                        const later = Boolean(date) && tr.dataset.enrolled > date;
                        tr.classList.toggle('hidden', later);
                        if (later) { tr.querySelector('.grade-input').value = ''; hidden += 1; }
                    });
                    m.querySelector('#lsHidden').textContent = hidden ? `Не показано зарахованих після цієї дати: ${hidden}` : '';
                    m.querySelector('#lsHidden').classList.toggle('hidden', !hidden);
                };
                filterByDate();
                m.querySelector('#lsDate').addEventListener('change', filterByDate);
                visibleInputs()[0]?.focus();
                m.querySelector('tbody').addEventListener('keydown', (e) => {
                    if (e.key !== 'Enter' || !e.target.matches('.grade-input')) return;
                    e.preventDefault();
                    const all = visibleInputs();
                    (all[all.indexOf(e.target) + 1] || m.querySelector('[data-save]')).focus();
                });
                m.querySelector('[data-save]').addEventListener('click', (e) => busy(e.currentTarget, async () => {
                    const records = visibleInputs().filter((i) => i.value !== '').map((i) => ({ student_id: Number(i.dataset.sid), value: Number(i.value) }));
                    const bad = records.find((r) => !Number.isInteger(r.value) || r.value < 0 || r.value > 100);
                    if (bad) { toast('Бали мають бути цілими числами від 0 до 100', 'error'); return; }
                    if (!records.length) { toast('Введіть хоча б одну оцінку', 'error'); return; }
                    try {
                        const r = await api.post('/api/grades/bulk', { subject_id: Number(j.subject), date: m.querySelector('#lsDate').value, type: m.querySelector('#lsType').value, records });
                        close(r.saved);
                    } catch (err) { toastError(err); }
                }));
            },
        });
        if (saved) { toast(`Збережено оцінок: ${saved}`, 'success'); loadJournal(); }
    });

    // ---------- Grade forms ----------
    // data-field matches keys in server error details
    function gradeFields(g = {}) {
        return `
            <div class="field" data-field="value"><label for="gValue">Бал (0–100) *</label><input id="gValue" type="number" min="0" max="100" value="${esc(g.value ?? '')}"><div class="error"></div></div>
            <div class="field" data-field="type"><label for="gType">Тип *</label><select id="gType">${typeOptions(subjectById(g.subject_id), g.type)}</select><div class="error"></div></div>
            <div class="field" data-field="date"><label for="gDate">Дата *</label><input id="gDate" type="date" max="${todayIso()}" value="${esc(g.date || todayIso())}"><div class="error"></div></div>
            <div class="field"><label>ECTS</label><div id="gEcts" style="padding-top:6px">${g.value !== undefined ? ectsBadge(SH.ects(g.value)) : '—'}</div></div>
            <div class="field full" data-field="comment"><label for="gComment">Коментар</label><input id="gComment" maxlength="300" value="${esc(g.comment || '')}"><div class="error"></div></div>`;
    }
    /** Request error: details under fields, message in a toast. */
    function showGradeError(m, err) {
        showFieldErrors(m, err.details || {});
        toastError(err);
    }
    function readGrade(m) {
        return { value: m.querySelector('#gValue').value === '' ? null : Number(m.querySelector('#gValue').value),
            type: m.querySelector('#gType').value, date: m.querySelector('#gDate').value, comment: m.querySelector('#gComment').value.trim() || null };
    }
    function bindEcts(m) {
        m.querySelector('#gValue').addEventListener('input', (e) => { m.querySelector('#gEcts').innerHTML = e.target.value === '' ? '—' : ectsBadge(SH.ects(Number(e.target.value))); });
    }

    /** New grade: subject -> group (only those taking it) -> student. pre: prefilled values from the journal. */
    async function addGrade(pre = {}) {
        const mySubjects = allSubjects.filter((s) => canManage(s.id));
        if (!mySubjects.length) { toast('За вами не закріплено жодної дисципліни', 'error'); return null; }
        const subjectId = canManage(pre.subject_id) ? pre.subject_id : '';
        return modal({
            title: 'Нова оцінка',
            body: `<div class="form-grid">
                <div class="field full" data-field="subject_id"><label for="gSubject">Дисципліна *</label><select id="gSubject">${options(mySubjects, { empty: 'Оберіть дисципліну', selected: subjectId })}</select><div class="error"></div></div>
                <div class="field"><label for="gGroup">Група *</label><select id="gGroup" disabled><option value="">Спершу оберіть дисципліну</option></select></div>
                <div class="field" data-field="student_id"><label for="gStudent">Студент *</label><select id="gStudent" disabled><option value="">Спершу оберіть групу</option></select><div class="error"></div></div>
                ${gradeFields({ date: pre.date, subject_id: subjectId, type: pre.type })}</div>`,
            footer: '<button class="btn" data-close>Скасувати</button><button class="btn btn-primary" data-save>Зберегти</button>',
            onMount: async (m, close) => {
                const el = (sel) => m.querySelector(sel);
                const fill = (select, html, enabled) => { select.innerHTML = html; select.disabled = !enabled; };
                let groupsRequest = 0;
                bindEcts(m);

                const loadStudents = async (selected) => {
                    const gid = el('#gGroup').value;
                    if (!gid) { fill(el('#gStudent'), '<option value="">Спершу оберіть групу</option>', false); return; }
                    const { items } = await api.get(`/api/students${qs({ group_id: gid, status: 'active', limit: 500 })}`);
                    fill(el('#gStudent'), items.length
                        ? options(items, { empty: 'Оберіть студента', selected, label: (s) => `${s.last_name} ${s.first_name}` })
                        : '<option value="">У групі немає активних студентів</option>', items.length > 0);
                };
                const loadGroups = async (selectedGroup, selectedStudent) => {
                    const subject = subjectById(el('#gSubject').value);
                    el('#gType').innerHTML = typeOptions(subject, el('#gType').value);
                    if (!subject) {
                        fill(el('#gGroup'), '<option value="">Спершу оберіть дисципліну</option>', false);
                    } else {
                        // Disable the old list while loading; ignore responses for a previously selected subject
                        const req = ++groupsRequest;
                        fill(el('#gGroup'), '<option value="">Завантаження…</option>', false);
                        fill(el('#gStudent'), '<option value="">Спершу оберіть групу</option>', false);
                        const { group_ids: ids } = await api.get(`/api/subjects/${subject.id}`);
                        if (req !== groupsRequest) return;
                        const list = groups.filter((g) => ids.includes(g.id));
                        fill(el('#gGroup'), list.length
                            ? options(list, { empty: 'Оберіть групу', selected: selectedGroup })
                            : '<option value="">Дисципліна не призначена жодній групі</option>', list.length > 0);
                    }
                    await loadStudents(selectedStudent);
                };
                el('#gSubject').addEventListener('change', () => loadGroups());
                el('#gGroup').addEventListener('change', () => loadStudents());
                await loadGroups(pre.group_id, pre.student_id);
                (el('#gStudent').value ? el('#gValue') : el('#gSubject').value ? el('#gGroup') : el('#gSubject')).focus();

                el('[data-save]').addEventListener('click', (e) => busy(e.currentTarget, async () => {
                    const d = { ...readGrade(m), student_id: Number(el('#gStudent').value) || null, subject_id: Number(el('#gSubject').value) || null };
                    const missing = Object.fromEntries(['subject_id', 'student_id', 'value', 'date']
                        .filter((k) => d[k] === null || d[k] === '').map((k) => [k, 'Обовʼязкове поле']));
                    showFieldErrors(m, missing);
                    if (Object.keys(missing).length) return;
                    // On error (e.g. 409 duplicate) keep the modal open
                    try { close(await api.post('/api/grades', d)); toast('Оцінку збережено', 'success'); } catch (err) { showGradeError(m, err); }
                }));
            },
        });
    }

    async function editGrade(g) {
        return modal({
            title: `${g.student_name} · ${g.subject_name}`,
            body: `<div class="form-grid">${gradeFields(g)}</div>`,
            footer: `<button class="btn btn-danger" data-del style="margin-right:auto">${icon('trash')} Видалити</button><button class="btn" data-close>Скасувати</button><button class="btn btn-primary" data-save>Зберегти</button>`,
            onMount: (m, close) => {
                bindEcts(m);
                m.querySelector('#gValue').focus();
                m.querySelector('[data-save]').addEventListener('click', (e) => busy(e.currentTarget, async () => {
                    try { close(await api.patch(`/api/grades/${g.id}`, readGrade(m))); toast('Оцінку змінено', 'success'); } catch (err) { showGradeError(m, err); }
                }));
                m.querySelector('[data-del]').addEventListener('click', async (e) => {
                    const btn = e.currentTarget;
                    if (!(await confirmDialog('Видалити цю оцінку?'))) return;
                    await busy(btn, async () => {
                        try { await api.del(`/api/grades/${g.id}`); toast('Оцінку видалено', 'success'); close(true); } catch (err) { toastError(err); }
                    });
                });
            },
        });
    }

    $('#btnAdd').addEventListener('click', async () => {
        if (await addGrade({ group_id: j.group, subject_id: j.subject })) { loadJournal(); if (!$('[data-panel="list"]').classList.contains('hidden')) loadList(); }
    });

    // ---------- All grades list ----------
    const l = { search: '', group_id: '', subject_id: '', type: '', from: '', to: '', page: 1, limit: 25 };
    $('#lGroup').innerHTML = options(groups, { empty: 'Усі групи' });
    $('#lSubject').innerHTML = options(allSubjects, { empty: 'Усі дисципліни' });
    let listItems = [];

    async function loadList() {
        $('#listRows').innerHTML = '<tr><td colspan="9" class="loader"><span class="spinner"></span></td></tr>';
        try {
            const data = await api.get(`/api/grades${qs(l)}`);
            listItems = data.items;
            $('#listStats').innerHTML = `<div class="stat-chip"><div class="v">${data.total}</div><div class="l">Оцінок</div></div>
                <div class="stat-chip"><div class="v">${fmtNum(data.avg)}</div><div class="l">Середній бал</div></div>`;
            $('#listRows').innerHTML = data.items.map((g) => `<tr data-id="${g.id}">
                <td>${fmtDate(g.date)}</td><td><a href="/student?id=${g.student_id}">${esc(g.student_name)}</a></td><td>${esc(g.group_name || '—')}</td>
                <td>${esc(g.subject_name)}</td><td>${esc(LABELS.gradeType[g.type])}</td><td class="center">${gradeBadge(g.value)}</td>
                <td class="center">${ectsBadge(g.ects)}</td><td class="small">${esc(g.teacher_name || '—')}</td>
                <td><div class="row-actions">${canManage(g.subject_id) ? `<button class="btn-icon" data-edit title="Редагувати" aria-label="Редагувати">${icon('edit')}</button>` : ''}</div></td></tr>`).join('')
                || '<tr><td colspan="9" class="table-empty">Оцінок не знайдено</td></tr>';
            pagination($('#pager'), data, (p) => { l.page = p; loadList(); });
        } catch (e) { toastError(e); }
    }
    const reList = () => { l.page = 1; loadList(); };
    $('#lSearch').addEventListener('input', debounce((e) => { l.search = e.target.value.trim(); reList(); }));
    [['#lGroup', 'group_id'], ['#lSubject', 'subject_id'], ['#lType', 'type'], ['#lFrom', 'from'], ['#lTo', 'to']].forEach(([sel, key]) =>
        $(sel).addEventListener('change', (e) => { l[key] = e.target.value; reList(); }));
    $('#listRows').addEventListener('click', async (e) => {
        if (!e.target.closest('[data-edit]')) return;
        const g = listItems.find((x) => x.id === Number(e.target.closest('tr').dataset.id));
        if (await editGrade(g)) loadList();
    });
});
