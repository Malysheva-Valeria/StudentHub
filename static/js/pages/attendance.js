SH.boot('attendance', ['Навчальний процес', 'Відвідуваність'], async (user) => {
    const { api, qs, refs, options, esc, $, $$, icon, toast, toastError, todayIso, busy, LABELS } = SH;
    const isAdmin = user.role === 'admin';
    const [groups, allSubjects] = await Promise.all([refs.groups(), refs.subjects()]);
    const canManage = (sid) => isAdmin || allSubjects.find((s) => s.id === Number(sid))?.teacher_id === user.id;
    const STATUSES = ['present', 'late', 'absent', 'excused'];

    // sel: current filter values; loaded: params of the sheet on screen.
    // Saving always uses loaded, so changing filters can't overwrite another lesson.
    const sel = { group: '', subject: '', date: todayIso() };
    let loaded = null;
    let rows = [];
    let dirty = false;
    let seq = 0;

    $('#aGroup').innerHTML = options(groups, { empty: 'Оберіть групу' });
    $('#aSubject').innerHTML = '<option value="">Спершу оберіть групу</option>';
    $('#aDate').value = sel.date;
    $('#aDate').max = todayIso();

    /** Confirm before discarding unsaved marks. */
    const confirmLeave = () => !dirty
        || SH.confirmDialog('Є незбережені відмітки. Продовжити без збереження?', { okText: 'Продовжити', danger: false });

    /** Filter change handler; reverts the value if the user cancels. */
    const onFilter = (el, key, after) => el.addEventListener('change', async () => {
        if (!(await confirmLeave())) { el.value = sel[key]; return; }
        sel[key] = el.value;
        after();
    });

    onFilter($('#aGroup'), 'group', async () => {
        sel.subject = '';
        empty();
        if (!sel.group) { $('#aSubject').innerHTML = '<option value="">Спершу оберіть групу</option>'; return; }
        let subs;
        try { subs = await api.get(`/api/groups/${sel.group}/subjects`); } catch (err) { toastError(err); return; }
        $('#aSubject').innerHTML = subs.length
            ? options(subs, { empty: 'Оберіть дисципліну', label: (s) => `${s.name}${!isAdmin && canManage(s.id) ? ' (моя)' : ''}` })
            : '<option value="">Групі не призначено дисциплін</option>';
    });
    onFilter($('#aSubject'), 'subject', () => load());
    onFilter($('#aDate'), 'date', () => load());

    function empty() {
        seq += 1; loaded = null; rows = []; dirty = false;
        $('#sheet').innerHTML = '<div class="table-empty">Оберіть групу, дисципліну та дату</div>';
        $('#sheetStats').classList.add('hidden');
    }

    async function load() {
        if (!sel.group || !sel.subject || !sel.date) { empty(); return; }
        const target = { ...sel };
        const my = ++seq;
        $('#sheet').innerHTML = '<div class="loader"><span class="spinner"></span></div>';
        try {
            const data = await api.get(`/api/attendance/sheet${qs({ group_id: target.group, subject_id: target.subject, date: target.date })}`);
            if (my !== seq) return; // stale response: another lesson was selected meanwhile
            loaded = target;
            rows = data.rows.map((r) => ({ ...r, status: r.status || (data.marked ? null : 'present') }));
            dirty = false;
            render(data.marked);
        } catch (e) {
            if (my !== seq) return;
            // Show an error (e.g. invalid date) instead of an endless spinner
            loaded = null; rows = []; dirty = false;
            $('#sheet').innerHTML = `<div class="table-empty">Не вдалося завантажити відомість: ${esc(e.message)}</div>`;
            $('#sheetStats').classList.add('hidden');
        }
    }

    function stats() {
        const c = Object.fromEntries(STATUSES.map((s) => [s, rows.filter((r) => r.status === s).length]));
        const rate = rows.length ? Math.round(((c.present + c.late) / rows.length) * 100) : 0;
        $('#sheetStats').innerHTML = `
            <div class="stat-chip"><div class="v">${rows.length}</div><div class="l">Студентів</div></div>
            <div class="stat-chip"><div class="v" style="color:#039855">${c.present}</div><div class="l">Присутні</div></div>
            <div class="stat-chip"><div class="v" style="color:#b54708">${c.late}</div><div class="l">Запізнились</div></div>
            <div class="stat-chip"><div class="v" style="color:#d92d20">${c.absent}</div><div class="l">Відсутні</div></div>
            <div class="stat-chip"><div class="v" style="color:#0284c7">${c.excused}</div><div class="l">Поважна причина</div></div>
            <div class="stat-chip"><div class="v">${rate}%</div><div class="l">Відвідуваність</div></div>`;
        $('#sheetStats').classList.remove('hidden');
    }

    /** Mark the selected status in a row (class + aria-checked). */
    function showStatus(tr, status) {
        $$('[data-status]', tr).forEach((x) => {
            const on = x.dataset.status === status;
            x.classList.toggle('on', on);
            x.setAttribute('aria-checked', String(on));
        });
    }

    function render(marked) {
        const editable = canManage(loaded.subject);
        if (!rows.length) { $('#sheet').innerHTML = '<div class="table-empty">У групі немає студентів, які навчаються на дату заняття</div>'; $('#sheetStats').classList.add('hidden'); return; }
        $('#sheet').innerHTML = `
            <div class="filters" style="justify-content:space-between">
                <span class="muted">${marked ? 'Відмітки за це заняття вже збережено — можна змінити.' : 'Нове заняття: за замовчуванням усі присутні.'}
                ${editable ? '' : '<b> Лише перегляд — ви не ведете цю дисципліну.</b>'}</span>
                ${editable ? `<div class="actions"><button class="btn btn-sm" id="allPresent">${icon('check')} Усі присутні</button>
                <button class="btn btn-primary" id="btnSave">${icon('save')} Зберегти</button></div>` : ''}
            </div>
            <div class="table-wrap"><table class="table"><thead><tr><th>#</th><th>Студент</th><th>Залікова</th><th>Статус</th></tr></thead>
            <tbody>${rows.map((r, i) => `<tr data-sid="${r.student_id}"><td>${i + 1}</td>
                <td><a href="/student?id=${r.student_id}">${esc(r.last_name)} ${esc(r.first_name)}</a></td><td>${esc(r.record_book)}</td>
                <td><div class="status-switch" role="radiogroup" aria-label="Статус ${esc(r.last_name)}">${STATUSES.map((s) =>
                    `<button type="button" class="${s} ${r.status === s ? 'on' : ''}" data-status="${s}" role="radio" aria-checked="${r.status === s}" ${editable ? '' : 'disabled'}>${LABELS.attendance[s]}</button>`).join('')}</div></td></tr>`).join('')}
            </tbody></table></div>`;
        stats();
        if (!editable) return;

        $('#sheet tbody').addEventListener('click', (e) => {
            const b = e.target.closest('[data-status]');
            if (!b) return;
            const tr = b.closest('tr');
            rows.find((r) => r.student_id === Number(tr.dataset.sid)).status = b.dataset.status;
            showStatus(tr, b.dataset.status);
            dirty = true; stats();
        });
        $('#allPresent').addEventListener('click', () => {
            rows.forEach((r) => { r.status = 'present'; });
            $$('#sheet tbody tr').forEach((tr) => showStatus(tr, 'present'));
            dirty = true; stats();
        });
        $('#btnSave').addEventListener('click', (e) => busy(e.currentTarget, async () => {
            const missing = rows.filter((r) => !r.status);
            if (missing.length) { toast(`Не відмічено студентів: ${missing.length}`, 'error'); return; }
            const lesson = loaded;
            try {
                const r = await api.post('/api/attendance/bulk', {
                    subject_id: Number(lesson.subject), date: lesson.date,
                    records: rows.map(({ student_id, status }) => ({ student_id, status })),
                });
                dirty = false;
                toast(`Відвідуваність збережено (${r.saved})`, 'success');
                load();
            } catch (err) { toastError(err); }
        }));
    }

    window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
});
