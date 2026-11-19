SH.boot('groups', ['Навчальний процес', 'Групи'], async (user) => {
    const { api, refs, esc, $, icon, toast, toastError, confirmDialog, formModal, gradeBadge, userOptions } = SH;
    const isAdmin = user.role === 'admin';
    let groups = [];

    async function load() {
        refs.invalidate('groups');
        groups = await refs.groups();
        $('#rows').innerHTML = groups.map((g) => `
            <tr data-id="${g.id}">
                <td><a href="/students?group_id=${g.id}"><b>${esc(g.name)}</b></a></td>
                <td class="center">${g.course}</td>
                <td>${esc(g.specialty)}</td>
                <td>${esc(g.curator_name || '—')}</td>
                <td class="num">${g.students_count}</td>
                <td class="num">${gradeBadge(g.avg_grade)}</td>
                <td><div class="row-actions">
                    <a class="btn-icon" href="/students?group_id=${g.id}" title="Студенти групи" aria-label="Студенти групи">${icon('students')}</a>
                    ${isAdmin ? `<button class="btn-icon" data-edit title="Редагувати" aria-label="Редагувати">${icon('edit')}</button>
                    <button class="btn-icon danger" data-del title="Видалити" aria-label="Видалити">${icon('trash')}</button>` : ''}
                </div></td>
            </tr>`).join('') || '<tr><td colspan="7" class="table-empty">Груп ще немає</td></tr>';
    }

    async function groupForm(g) {
        const [teachers, subjects] = await Promise.all([refs.teachers(), refs.subjects()]);
        const full = g ? await api.get(`/api/groups/${g.id}`) : {};
        return formModal({
            title: g ? `Група ${g.name}` : 'Нова група',
            values: full,
            fields: [
                { name: 'name', label: 'Назва групи', required: true, placeholder: 'КН-21' },
                { name: 'course', label: 'Курс', type: 'number', min: 1, max: 6, required: true, default: 1 },
                { name: 'specialty', label: 'Спеціальність', required: true, full: true, placeholder: '122 Компʼютерні науки' },
                { name: 'curator_id', label: 'Куратор', type: 'select', numeric: true, full: true, empty: 'Не призначено',
                    options: userOptions(teachers, full.curator_id) },
                { name: 'subject_ids', label: 'Дисципліни групи', type: 'checkboxes', full: true,
                    options: subjects.map((s) => ({ value: s.id, label: s.name })) },
            ],
            submit: (d) => (g ? api.put(`/api/groups/${g.id}`, d) : api.post('/api/groups', d)),
        });
    }

    $('#btnAdd')?.addEventListener('click', async () => { if (await groupForm()) { toast('Групу створено', 'success'); load(); } });
    $('#rows').addEventListener('click', async (e) => {
        const tr = e.target.closest('tr[data-id]');
        if (!tr) return;
        const g = groups.find((x) => x.id === Number(tr.dataset.id));
        if (e.target.closest('[data-edit]')) {
            if (await groupForm(g)) { toast('Зміни збережено', 'success'); refs.invalidate('subjects'); load(); }
        } else if (e.target.closest('[data-del]')) {
            if (!(await confirmDialog(`Видалити групу ${g.name}? Групу зі студентами видалити не можна — спершу переведіть їх до іншої групи.`))) return;
            try { await api.del(`/api/groups/${g.id}`); toast('Групу видалено', 'success'); load(); } catch (err) { toastError(err); }
        }
    });
    load();
});
