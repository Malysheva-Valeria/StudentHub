SH.boot('subjects', ['Навчальний процес', 'Дисципліни'], async (user) => {
    const { api, refs, esc, $, icon, toast, toastError, confirmDialog, formModal, gradeBadge, LABELS, debounce, userOptions } = SH;
    const isAdmin = user.role === 'admin';
    let subjects = [];
    let filter = '';

    function render() {
        const q = filter.toLowerCase();
        const list = subjects.filter((s) => !q || s.name.toLowerCase().includes(q) || (s.code || '').toLowerCase().includes(q));
        $('#rows').innerHTML = list.map((s) => `
            <tr data-id="${s.id}">
                <td><b>${esc(s.name)}</b>${s.teacher_id === user.id ? ' <span class="badge blue">моя</span>' : ''}</td>
                <td>${esc(s.code || '—')}</td>
                <td class="num">${s.credits}</td>
                <td class="num">${s.hours}</td>
                <td class="center">${s.semester}</td>
                <td><span class="badge ${s.control === 'exam' ? 'blue' : 'cyan'}">${esc(LABELS.control[s.control])}</span></td>
                <td>${esc(s.teacher_name || '—')}</td>
                <td class="num">${s.groups_count}</td>
                <td class="num">${gradeBadge(s.avg_grade)}</td>
                <td><div class="row-actions">${isAdmin ? `
                    <button class="btn-icon" data-edit title="Редагувати" aria-label="Редагувати">${icon('edit')}</button>
                    <button class="btn-icon danger" data-del title="Видалити" aria-label="Видалити">${icon('trash')}</button>` : ''}</div></td>
            </tr>`).join('') || '<tr><td colspan="10" class="table-empty">Дисциплін не знайдено</td></tr>';
    }

    async function load() { refs.invalidate('subjects'); subjects = await refs.subjects(); render(); }

    async function subjectForm(s) {
        const [teachers, groups] = await Promise.all([refs.teachers(), refs.groups()]);
        const full = s ? await api.get(`/api/subjects/${s.id}`) : {};
        return formModal({
            title: s ? 'Редагування дисципліни' : 'Нова дисципліна',
            values: full,
            fields: [
                { name: 'name', label: 'Назва', required: true, full: true },
                { name: 'code', label: 'Код' },
                { name: 'control', label: 'Форма контролю', type: 'select', required: true, default: 'exam',
                    options: [{ value: 'exam', label: 'Екзамен' }, { value: 'credit', label: 'Залік' }] },
                { name: 'credits', label: 'Кредити ECTS', type: 'number', min: 0.5, max: 30, step: 0.5, required: true, default: 3 },
                { name: 'hours', label: 'Годин', type: 'number', min: 1, max: 1000, required: true, default: 90 },
                { name: 'semester', label: 'Семестр', type: 'number', min: 1, max: 12, required: true, default: 1 },
                { name: 'teacher_id', label: 'Викладач', type: 'select', numeric: true, empty: 'Не призначено',
                    options: userOptions(teachers, full.teacher_id) },
                { name: 'group_ids', label: 'Групи, що вивчають', type: 'checkboxes', full: true,
                    options: groups.map((g) => ({ value: g.id, label: g.name })) },
            ],
            submit: (d) => (s ? api.put(`/api/subjects/${s.id}`, d) : api.post('/api/subjects', d)),
        });
    }

    $('#fSearch').addEventListener('input', debounce((e) => { filter = e.target.value.trim(); render(); }, 150));
    $('#btnAdd')?.addEventListener('click', async () => { if (await subjectForm()) { toast('Дисципліну додано', 'success'); load(); } });
    $('#rows').addEventListener('click', async (e) => {
        const tr = e.target.closest('tr[data-id]');
        if (!tr) return;
        const s = subjects.find((x) => x.id === Number(tr.dataset.id));
        if (e.target.closest('[data-edit]')) {
            if (await subjectForm(s)) { toast('Зміни збережено', 'success'); load(); }
        } else if (e.target.closest('[data-del]')) {
            if (!(await confirmDialog(`Видалити дисципліну «${s.name}»? Дисципліну, з якої вже є оцінки чи відвідуваність, видалити не можна.`))) return;
            try { await api.del(`/api/subjects/${s.id}`); toast('Дисципліну видалено', 'success'); load(); } catch (err) { toastError(err); }
        }
    });
    load();
});
