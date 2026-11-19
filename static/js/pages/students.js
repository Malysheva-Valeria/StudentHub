SH.boot('students', ['Навчальний процес', 'Студенти'], async (user) => {
    const { api, qs, refs, options, esc, $, $$, icon, toast, toastError, confirmDialog, formModal, pagination, statusBadge, gradeBadge, rateBar, debounce, todayIso, LABELS } = SH;
    const isAdmin = user.role === 'admin';
    const url = new URLSearchParams(location.search);
    const state = { search: '', group_id: url.get('group_id') || '', status: url.get('status') || '', gender: '', sort: 'name', page: 1, limit: 20 };

    const groups = await refs.groups();
    $('#fGroup').innerHTML = options(groups, { empty: 'Усі групи', selected: state.group_id });
    $('#fStatus').value = state.status;

    const tbody = $('#studentsTable tbody');

    async function load() {
        tbody.innerHTML = '<tr><td colspan="7" class="loader"><span class="spinner"></span></td></tr>';
        try {
            const data = await api.get(`/api/students${qs(state)}`);
            if (!data.items.length) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">Студентів не знайдено</td></tr>';
            } else {
                tbody.innerHTML = data.items.map((s) => `
                    <tr data-id="${s.id}">
                        <td><a href="/student?id=${s.id}"><b>${esc(s.last_name)} ${esc(s.first_name)}</b></a> <span class="muted">${esc(s.middle_name || '')}</span></td>
                        <td>${esc(s.record_book)}</td>
                        <td>${esc(s.group_name || '—')}</td>
                        <td>${statusBadge(s.status)}</td>
                        <td class="num">${gradeBadge(s.avg_grade)}</td>
                        <td style="min-width:160px">${rateBar(s.attendance_rate)}</td>
                        <td><div class="row-actions">
                            <a class="btn-icon" href="/student?id=${s.id}" title="Картка студента" aria-label="Картка">${icon('eye')}</a>
                            ${isAdmin ? `<button class="btn-icon" data-edit title="Редагувати" aria-label="Редагувати">${icon('edit')}</button>
                            <button class="btn-icon danger" data-del title="Видалити" aria-label="Видалити">${icon('trash')}</button>` : ''}
                        </div></td>
                    </tr>`).join('');
            }
            pagination($('#pager'), data, (p) => { state.page = p; load(); });
            current = data.items;
        } catch (e) { toastError(e); tbody.innerHTML = '<tr><td colspan="7" class="table-empty">Не вдалося завантажити дані</td></tr>'; }
    }
    let current = [];

    const reload = () => { state.page = 1; load(); };
    $('#fSearch').addEventListener('input', debounce((e) => { state.search = e.target.value.trim(); reload(); }));
    $('#fGroup').addEventListener('change', (e) => { state.group_id = e.target.value; reload(); });
    $('#fStatus').addEventListener('change', (e) => { state.status = e.target.value; reload(); });
    $('#fGender').addEventListener('change', (e) => { state.gender = e.target.value; reload(); });
    $$('th.sortable').forEach((th) => th.addEventListener('click', () => {
        state.sort = th.dataset.sort;
        $$('th.sortable').forEach((t) => { t.textContent = t.textContent.replace(/ [↑↓]$/, ''); });
        th.textContent += state.sort === 'name' || state.sort === 'group' ? ' ↑' : ' ↓';
        reload();
    }));
    $('#btnExport')?.addEventListener('click', () => SH.download(`/api/students/export${qs({ search: state.search, group_id: state.group_id, status: state.status, gender: state.gender })}`));

    function studentForm(s = {}) {
        return formModal({
            title: s.id ? 'Редагування студента' : 'Новий студент',
            values: s,
            fields: [
                { name: 'last_name', label: 'Прізвище', required: true },
                { name: 'first_name', label: 'Імʼя', required: true },
                { name: 'middle_name', label: 'По батькові' },
                { name: 'gender', label: 'Стать', type: 'select', required: true, empty: 'Оберіть…', options: [{ value: 'M', label: 'Чоловіча' }, { value: 'F', label: 'Жіноча' }] },
                { name: 'record_book', label: 'Номер залікової книжки', required: true },
                { name: 'group_id', label: 'Група', type: 'select', numeric: true, empty: 'Без групи', options: groups.map((g) => ({ value: g.id, label: g.name })) },
                { name: 'birth_date', label: 'Дата народження', type: 'date', max: todayIso() },
                { name: 'enrolled_at', label: 'Дата зарахування', type: 'date', default: todayIso() },
                { name: 'email', label: 'Email', type: 'email' },
                { name: 'phone', label: 'Телефон', placeholder: '+380…' },
                { name: 'status', label: 'Статус', type: 'select', full: true, default: 'active',
                    options: Object.entries(LABELS.status).map(([value, label]) => ({ value, label })) },
            ],
            submit: (d) => (s.id ? api.patch(`/api/students/${s.id}`, d) : api.post('/api/students', d)),
        });
    }

    $('#btnAdd')?.addEventListener('click', async () => {
        if (await studentForm()) { toast('Студента додано', 'success'); refs.invalidate('groups'); load(); }
    });

    tbody.addEventListener('click', async (e) => {
        const tr = e.target.closest('tr[data-id]');
        if (!tr) return;
        const s = current.find((x) => x.id === Number(tr.dataset.id));
        if (e.target.closest('[data-edit]')) {
            if (await studentForm(s)) { toast('Зміни збережено', 'success'); load(); }
        } else if (e.target.closest('[data-del]')) {
            if (!(await confirmDialog(`Видалити студента ${s.last_name} ${s.first_name}? Студента з оцінками чи відвідуваністю видалити не можна — змініть його статус.`))) return;
            try { await api.del(`/api/students/${s.id}`); toast('Студента видалено', 'success'); load(); } catch (err) { toastError(err); }
        }
    });

    load();
});
