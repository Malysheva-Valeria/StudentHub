SH.boot('students', ['Студенти', 'Картка студента'], async () => {
    const { api, esc, $, icon, initials, fmtDate, fmtNum, gradeBadge, ectsBadge, statusBadge, rateBar, LABELS } = SH;
    const id = Number(new URLSearchParams(location.search).get('id'));
    const box = $('#profile');
    if (!id) { box.innerHTML = '<div class="card table-empty">Не вказано студента. <a href="/students">До списку</a></div>'; return; }

    let s;
    try { s = await api.get(`/api/students/${id}`); } catch (e) {
        box.innerHTML = `<div class="card table-empty">${esc(e.message)}. <a href="/students">До списку студентів</a></div>`;
        return;
    }
    const fullName = [s.last_name, s.first_name, s.middle_name].filter(Boolean).join(' ');
    document.title = `${s.last_name} ${s.first_name} · StudentHub`;
    const a = s.attendance;

    box.innerHTML = `
        <div class="page-head">
            <div><a href="/students" class="small">${icon('back')} До списку</a></div>
            <div class="actions"><button class="btn" data-print>${icon('print')} Друк</button></div>
        </div>
        <div class="grid grid-2">
            <div class="card card-pad">
                <div class="profile-head">
                    <div class="avatar">${esc(initials(`${s.last_name} ${s.first_name}`))}</div>
                    <div><h1>${esc(fullName)}</h1><div class="muted">Група ${esc(s.group_name || '—')} · залікова № ${esc(s.record_book)}</div>
                    <div style="margin-top:6px">${statusBadge(s.status)}</div></div>
                </div>
                <dl class="kv" style="margin-top:20px">
                    <dt>Стать</dt><dd>${esc(LABELS.gender[s.gender])}</dd>
                    <dt>Дата народження</dt><dd>${fmtDate(s.birth_date)}</dd>
                    <dt>Зарахований</dt><dd>${fmtDate(s.enrolled_at)}</dd>
                    <dt>Email</dt><dd>${s.email ? `<a href="mailto:${esc(s.email)}">${esc(s.email)}</a>` : '—'}</dd>
                    <dt>Телефон</dt><dd>${esc(s.phone || '—')}</dd>
                </dl>
            </div>
            <div class="card card-pad">
                <h2>Підсумки</h2>
                <div class="stats-row" style="padding:14px 0;border:0">
                    <div class="stat-chip"><div class="v">${fmtNum(s.avg_grade)}</div><div class="l">Середній бал</div></div>
                    <div class="stat-chip"><div class="v">${s.ects ? s.ects.ects : '—'}</div><div class="l">${esc(s.ects ? s.ects.national : 'ECTS')}</div></div>
                    <div class="stat-chip"><div class="v">${fmtNum(a.rate)}${a.rate !== null ? '%' : ''}</div><div class="l">Відвідуваність</div></div>
                </div>
                <div class="chart-box sm"><canvas id="attChart"></canvas></div>
            </div>
        </div>
        <div class="grid grid-2-eq mt">
            <div class="card">
                <div class="card-head"><h2>Успішність за дисциплінами</h2></div>
                <div class="table-wrap" style="margin-top:12px"><table class="table">
                    <thead><tr><th>Дисципліна</th><th class="num hide-sm">Оцінок</th><th class="center">Сер. бал</th><th class="center">Підсумок</th><th class="center">ECTS</th></tr></thead>
                    <tbody>${s.subjects.map((sb) => `<tr><td class="wrap">${esc(sb.name)}</td><td class="num hide-sm">${sb.grades_count}</td>
                        <td class="center">${gradeBadge(sb.avg_grade)}</td><td class="center">${gradeBadge(sb.final_grade)}</td>
                        <td class="center">${ectsBadge(sb.ects?.ects)}</td></tr>`).join('') || '<tr><td colspan="5" class="table-empty">Оцінок ще немає</td></tr>'}</tbody>
                </table></div>
            </div>
            <div class="card">
                <div class="card-head"><h2>Останні оцінки</h2></div>
                <div class="table-wrap" style="margin-top:12px"><table class="table">
                    <thead><tr><th>Дата</th><th>Дисципліна</th><th class="hide-sm">Тип</th><th class="center">Бал</th></tr></thead>
                    <tbody>${s.recent_grades.map((g) => `<tr><td>${fmtDate(g.date)}</td><td class="wrap">${esc(g.subject_name)}</td>
                        <td class="hide-sm">${esc(LABELS.gradeType[g.type])}</td><td class="center">${gradeBadge(g.value)}</td></tr>`).join('') || '<tr><td colspan="4" class="table-empty">Немає оцінок</td></tr>'}</tbody>
                </table></div>
                <div class="card-body"><h3 style="margin-bottom:8px">Відвідуваність</h3>${rateBar(a.rate)}
                    <div class="small muted" style="margin-top:6px">Занять: ${a.total} · присутній ${a.present} · запізнень ${a.late} · пропусків ${a.absent} · з поважної причини ${a.excused}</div></div>
            </div>
        </div>`;

    SH.chartDefaults();
    if (a.total) {
        new Chart($('#attChart'), {
            type: 'doughnut',
            data: { labels: ['Присутній', 'Запізнення', 'Відсутній', 'Поважна причина'],
                datasets: [{ data: [a.present, a.late, a.absent, a.excused], backgroundColor: ['#12b76a', '#f79009', '#f04438', '#38c6f4'], borderWidth: 0 }] },
            options: { cutout: '60%', plugins: { legend: { position: 'right' } } },
        });
    } else {
        $('#attChart').parentElement.innerHTML = '<div class="table-empty">Немає даних про відвідуваність</div>';
    }
});
