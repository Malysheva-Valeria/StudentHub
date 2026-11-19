SH.boot('dashboard', ['Головна', 'Огляд'], async () => {
    const { api, esc, fmtNum, icon, initials, monthLabel, gradeBadge, LABELS, $ } = SH;
    SH.chartDefaults();
    const d = await api.get('/api/dashboard');
    const k = d.kpi;

    function delta(cur, prev, { suffix = '%' } = {}) {
        if (cur === null || prev === null || cur === undefined || prev === undefined) return '';
        const diff = Math.round((cur - prev) * 10) / 10;
        const cls = diff === 0 ? 'flat' : diff > 0 ? 'up' : 'down';
        const arrow = diff > 0 ? '↑' : diff < 0 ? '↓' : '';
        return `<span class="delta ${cls}">${arrow} ${Math.abs(diff)}${suffix}</span>`;
    }

    const hasMonth = (v) => v !== null && v !== undefined;
    const cards = [
        { title: 'Усього студентів', icon: 'students', value: k.total_students, sub: `${k.groups} груп`, link: '/students' },
        { title: 'Активні студенти', icon: 'check', cls: 'green', value: k.active_students, sub: 'навчаються зараз', link: '/students?status=active' },
        // No data for the current month yet: fall back to the all-time value and label it
        { title: 'Відвідуваність', icon: 'attendance', cls: 'cyan', value: `${fmtNum(k.attendance_month ?? k.attendance_rate)}%`,
            delta: delta(k.attendance_month, k.attendance_prev_month),
            sub: hasMonth(k.attendance_month) ? 'цей місяць vs попередній' : 'за весь час (цього місяця відміток ще немає)', link: '/reports?tab=attendance' },
        { title: 'Середній бал', icon: 'grades', value: fmtNum(k.avg_grade_month ?? k.avg_grade),
            delta: delta(k.avg_grade_month, k.avg_grade_prev_month, { suffix: '' }),
            sub: hasMonth(k.avg_grade_month) ? `цей місяць · загалом ${fmtNum(k.avg_grade)}` : 'за весь час (цього місяця оцінок ще немає)', link: '/reports' },
        { title: 'Успішність', icon: 'star', cls: 'green', value: `${fmtNum(k.success_rate)}%`, sub: 'студентів із балом ≥ 60', link: '/reports' },
        { title: 'Низька відвідуваність', icon: 'alert', cls: 'red', value: k.low_attendance, sub: 'студентів < 75% занять', link: '/reports?tab=attendance' },
        { title: 'Викладачі', icon: 'teacher', cls: 'orange', value: k.teachers, sub: `${k.subjects} дисциплін` },
        // Current school year is incomplete: show both numbers without a percentage change
        { title: 'Нові зарахування', icon: 'userPlus', value: k.new_this_year,
            sub: `з ${SH.fmtDate(k.academic_year_start)} · за минулий навч. рік: ${k.new_prev_year}` },
    ];
    $('#kpis').innerHTML = cards.map((c) => `
        <div class="card kpi">
            <div class="kpi-top"><span class="kpi-icon ${c.cls || ''}">${icon(c.icon)}</span>${esc(c.title)}</div>
            <div class="kpi-value">${c.link ? `<a href="${c.link}" style="color:inherit">${esc(c.value)}</a>` : esc(c.value)} ${c.delta || ''}</div>
            <div class="kpi-sub">${esc(c.sub)}</div>
        </div>`).join('');

    const css = getComputedStyle(document.documentElement);
    const C = { primary: css.getPropertyValue('--primary').trim(), cyan: '#38c6f4', navy: '#2e35b8', red: '#f04438', orange: '#f79009', green: '#12b76a' };
    const grid = { color: '#eef0f5' };

    new Chart($('#trendChart'), {
        type: 'bar',
        data: {
            labels: d.trend.map((t) => monthLabel(t.month)),
            datasets: [
                { label: 'Присутні', data: d.trend.map((t) => t.present), backgroundColor: C.cyan, borderRadius: 4, maxBarThickness: 18 },
                { label: 'Запізнення', data: d.trend.map((t) => t.late), backgroundColor: C.primary, borderRadius: 4, maxBarThickness: 18 },
                { label: 'Пропуски', data: d.trend.map((t) => t.absent + t.excused), backgroundColor: C.navy, borderRadius: 4, maxBarThickness: 18 },
            ],
        },
        options: {
            plugins: { legend: { position: 'top', align: 'end' },
                tooltip: { callbacks: { afterBody: (items) => `Відвідуваність: ${fmtNum(d.trend[items[0].dataIndex].rate)}%` } } },
            scales: { x: { grid: { display: false } }, y: { grid, beginAtZero: true } },
        },
    });

    new Chart($('#genderChart'), {
        type: 'doughnut',
        data: { labels: ['Чоловіча', 'Жіноча'], datasets: [{ data: [d.gender.male, d.gender.female], backgroundColor: [C.primary, C.cyan], borderWidth: 0 }] },
        options: { cutout: '62%', plugins: { legend: { position: 'bottom' },
            tooltip: { callbacks: { label: (c) => {
                const total = d.gender.male + d.gender.female;
                return ` ${c.label}: ${c.raw} (${total ? Math.round((c.raw / total) * 100) : 0}%)`;
            } } } } },
    });

    const ectsColors = { A: C.green, B: C.primary, C: '#7c86f7', D: C.orange, E: '#fdb022', FX: C.red, F: '#b42318' };
    new Chart($('#ectsChart'), {
        type: 'bar',
        data: { labels: Object.keys(d.distribution), datasets: [{ label: 'Студентів', data: Object.values(d.distribution),
            backgroundColor: Object.keys(d.distribution).map((e) => ectsColors[e]), borderRadius: 4 }] },
        options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid, beginAtZero: true, ticks: { precision: 0 } } } },
    });

    new Chart($('#groupsChart'), {
        type: 'bar',
        data: { labels: d.by_group.map((g) => g.name), datasets: [
            { label: 'Сер. бал', data: d.by_group.map((g) => g.avg_grade), backgroundColor: C.primary, borderRadius: 4 },
            { label: 'Відвідуваність, %', data: d.by_group.map((g) => g.attendance_rate), backgroundColor: C.cyan, borderRadius: 4 },
        ] },
        options: { plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false } }, y: { grid, beginAtZero: true, max: 100 } } },
    });

    new Chart($('#gradeTrendChart'), {
        type: 'line',
        data: { labels: d.trend.map((t) => monthLabel(t.month)), datasets: [{
            label: 'Середній бал', data: d.trend.map((t) => t.avg_grade), borderColor: C.primary, backgroundColor: 'rgba(79,91,240,.12)',
            fill: true, tension: 0.35, pointRadius: 3,
        }] },
        options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid, suggestedMin: 55, suggestedMax: 85 } } },
    });

    const empty = '<li class="muted">Немає даних</li>';
    $('#topList').innerHTML = d.top_students.map((s) => `
        <li><div class="who"><span class="avatar">${esc(initials(s.name))}</span><div><a href="/student?id=${s.id}">${esc(s.name)}</a><div class="small muted">${esc(s.group_name || '')}</div></div></div>${gradeBadge(s.avg_grade)}</li>`).join('') || empty;
    $('#riskList').innerHTML = d.at_risk.map((s) => `
        <li><div class="who"><span class="avatar">${esc(initials(s.name))}</span><div><a href="/student?id=${s.id}">${esc(s.name)}</a><div class="small muted">${esc(s.group_name || '')}</div></div></div><span class="badge red">${fmtNum(s.rate)}%</span></li>`).join('') || empty;
    $('#recentList').innerHTML = d.recent_grades.map((g) => `
        <li><div><div>${esc(g.student_name)}</div><div class="small muted">${esc(g.subject_name)} · ${esc(LABELS.gradeType[g.type])} · ${SH.fmtDate(g.date)}</div></div>${gradeBadge(g.value)}</li>`).join('') || empty;
});
