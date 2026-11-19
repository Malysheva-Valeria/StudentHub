SH.boot('users', ['Адміністрування', 'Користувачі'], async (user) => {
    const { api, esc, $, icon, toast, toastError, confirmDialog, formModal, fmtDate, LABELS, refs } = SH;
    if (user.role !== 'admin') {
        $('#page').innerHTML = '<div class="card table-empty">Розділ доступний лише адміністратору. <a href="/">На головну</a></div>';
        return;
    }
    let users = [];

    async function load() {
        users = await api.get('/api/users');
        $('#rows').innerHTML = users.map((u) => `<tr data-id="${u.id}">
            <td><b>${esc(u.full_name)}</b>${u.id === user.id ? ' <span class="badge blue">це ви</span>' : ''}</td><td>${esc(u.username)}</td>
            <td><span class="badge ${u.role === 'admin' ? 'orange' : 'blue'}">${esc(LABELS.role[u.role])}</span></td>
            <td>${u.is_active ? '<span class="badge green">Активний</span>' : '<span class="badge red">Заблокований</span>'}</td>
            <td>${fmtDate(u.created_at)}</td>
            <td><div class="row-actions"><button class="btn-icon" data-edit title="Редагувати" aria-label="Редагувати">${icon('edit')}</button>
                ${u.id !== user.id ? `<button class="btn-icon danger" data-del title="Видалити" aria-label="Видалити">${icon('trash')}</button>` : ''}</div></td></tr>`).join('');
    }

    const roleOpts = [{ value: 'teacher', label: 'Викладач' }, { value: 'admin', label: 'Адміністратор' }];

    $('#btnAdd').addEventListener('click', async () => {
        const ok = await formModal({
            title: 'Новий користувач',
            fields: [
                { name: 'full_name', label: 'ПІБ', required: true, full: true },
                { name: 'username', label: 'Логін', required: true, autocomplete: 'off' },
                { name: 'password', label: 'Пароль (мін. 6)', type: 'password', required: true, autocomplete: 'new-password' },
                { name: 'role', label: 'Роль', type: 'select', required: true, full: true, options: roleOpts, default: 'teacher' },
            ],
            submit: (d) => api.post('/api/users', d),
        });
        if (ok) { toast('Користувача створено', 'success'); refs.invalidate('teachers'); load(); }
    });

    $('#rows').addEventListener('click', async (e) => {
        const tr = e.target.closest('tr[data-id]');
        if (!tr) return;
        const u = users.find((x) => x.id === Number(tr.dataset.id));
        if (e.target.closest('[data-edit]')) {
            const ok = await formModal({
                title: `Редагування: ${u.username}`,
                values: { ...u, is_active: String(u.is_active) },
                fields: [
                    { name: 'full_name', label: 'ПІБ', required: true, full: true },
                    { name: 'role', label: 'Роль', type: 'select', required: true, options: roleOpts },
                    { name: 'is_active', label: 'Статус', type: 'select', numeric: true, options: [{ value: '1', label: 'Активний' }, { value: '0', label: 'Заблокований' }] },
                    { name: 'password', label: 'Новий пароль (залиште порожнім, щоб не змінювати)', type: 'password', full: true, autocomplete: 'new-password' },
                ],
                submit: (d) => { if (!d.password) delete d.password; return api.patch(`/api/users/${u.id}`, d); },
            });
            if (ok) { toast('Зміни збережено', 'success'); refs.invalidate('teachers'); load(); }
        } else if (e.target.closest('[data-del]')) {
            if (!(await confirmDialog(`Видалити користувача ${u.full_name}? Якщо він уже вів облік або має дисципліни чи групи — його краще заблокувати.`))) return;
            try { await api.del(`/api/users/${u.id}`); toast('Користувача видалено', 'success'); load(); } catch (err) { toastError(err); }
        }
    });
    load();
});
