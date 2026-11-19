SH.boot('reports', ['Аналітика', 'Звіти'], async () => {
    const { api, qs, refs, options, esc, $, $$, toastError, gradeBadge, ectsBadge, rateBar, fmtNum, todayIso } = SH;
    SH.chartDefaults();
    const [groups, subjects] = await Promise.all([refs.groups(), refs.subjects()]);
    const TABS = ['performance', 'attendance', 'groups'];
    // Filters live in the URL so reload / Back restores the same report
    const url = new URLSearchParams(location.search);
    const f = Object.fromEntries(['tab', 'group_id', 'subject_id', 'from', 'to'].map((k) => [k, url.get(k) || '']));
    if (!TABS.includes(f.tab)) f.tab = 'performance';
    const syncUrl = () => history.replaceState(null, '', location.pathname + qs(f));
    let chart = null;

    $('#rGroup').innerHTML = options(groups, { empty: 'Усі групи', selected: f.group_id });
    $('#rSubject').innerHTML = options(subjects, { empty: 'Усі дисципліни', selected: f.subject_id });
    $('#rFrom').value = f.from; $('#rTo').value = f.to;

    $$('.tabs button').forEach((b) => {
        b.classList.toggle('active', b.dataset.tab === f.tab);
        b.setAttribute('aria-selected', String(b.dataset.tab === f.tab));
        b.addEventListener('click', () => {
            f.tab = b.dataset.tab;
            $$('.tabs button').forEach((x) => { x.classList.toggle('active', x === b); x.setAttribute('aria-selected', String(x === b)); });
            load();
        });
    });

    [['#rGroup', 'group_id'], ['#rSubject', 'subject_id'], ['#rFrom', 'from'], ['#rTo', 'to']].forEach(([sel, key]) =>
        $(sel).addEventListener('change', (e) => { f[key] = e.target.value; showPreset(); load(); }));

    /** Quick-pick periods: [from, to]. */
    function presetRanges() {
        const now = new Date(); const y = now.getFullYear(); const m = now.getMonth() + 1;
        const pad = (n) => String(n).padStart(2, '0');
        const studyYear = m >= 9 ? y : y - 1;
        return {
            month: [`${y}-${pad(m)}-01`, todayIso()],
            semester: m >= 9 || m === 1 ? [`${studyYear}-09-01`, todayIso()] : [`${y}-02-01`, todayIso()],
            year: [`${studyYear}-09-01`, todayIso()],
        };
    }
    /** Sync the quick-pick select with the dates (or "custom"). */
    function showPreset() {
        const match = Object.entries(presetRanges()).find(([, [from, to]]) => from === f.from && to === f.to);
        $('#rPreset').value = match ? match[0] : (f.from || f.to ? 'custom' : '');
    }
    showPreset();

    $('#rPreset').addEventListener('change', (e) => {
        [f.from, f.to] = presetRanges()[e.target.value] || ['', ''];
        $('#rFrom').value = f.from; $('#rTo').value = f.to;
        load();
    });

    const params = () => ({ group_id: f.tab === 'groups' ? '' : f.group_id, subject_id: f.subject_id, from: f.from, to: f.to });
    $('#btnCsv').addEventListener('click', () => SH.download(`/api/reports/${f.tab}${qs({ ...params(), format: 'csv' })}`));
    $('#btnPrint').addEventListener('click', () => print());

    const chip = (v, l, color) => `<div class="stat-chip"><div class="v" ${color ? `style="color:${color}"` : ''}>${v}</div><div class="l">${l}</div></div>`;

    function drawChart(cfg) {
        chart?.destroy();
        $('#chartWrap').classList.toggle('hidden', !cfg);
        if (cfg) chart = new Chart($('#reportChart'), cfg);
    }

    let seq = 0; // ignore responses to stale requests
    async function load() {
        syncUrl();
        const my = ++seq;
        $('#wrapGroup').classList.toggle('hidden', f.tab === 'groups');
        $('#reportTable').innerHTML = '<div class="loader"><span class="spinner"></span></div>';
        try {
            const data = await api.get(`/api/reports/${f.tab}${qs(params())}`);
            if (my !== seq) return;
            if (f.tab === 'performance') renderPerformance(data);
            else if (f.tab === 'attendance') renderAttendance(data);
            else renderGroups(data);
        } catch (e) { toastError(e); }
    }

    function renderPerformance({ items, summary: s }) {
        $('#reportStats').innerHTML = chip(s.students, 'Студентів') + chip(fmtNum(s.avg_grade), 'Середній бал')
            + chip(`${fmtNum(s.success)}%`, 'Абсолютна успішність') + chip(`${fmtNum(s.quality)}%`, 'Якість знань')
            + chip(s.excellent, 'Відмінно (90+)', '#039855') + chip(s.good, 'Добре (74–89)', '#4f5bf0')
            + chip(s.satisfactory, 'Задовільно (60–73)', '#b54708') + chip(s.failing, 'Незадовільно', '#d92d20') + chip(s.with_debts, 'З боргами', '#d92d20');
        drawChart({
            type: 'bar',
            data: { labels: ['Відмінно', 'Добре', 'Задовільно', 'Незадовільно'],
                datasets: [{ data: [s.excellent, s.good, s.satisfactory, s.failing], backgroundColor: ['#12b76a', '#4f5bf0', '#f79009', '#f04438'], borderRadius: 4, maxBarThickness: 60 }] },
            options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { grid: { display: false } } } },
        });
        $('#reportTable').innerHTML = items.length ? `<table class="table"><thead><tr><th>#</th><th>Студент</th><th>Залікова</th><th>Група</th>
            <th class="num">Оцінок</th><th class="center">Сер. бал</th><th class="num">Мін</th><th class="num">Макс</th><th class="center">ECTS</th><th>Нац. шкала</th><th class="num">Борги</th></tr></thead>
            <tbody>${items.map((r, i) => `<tr><td>${i + 1}</td><td><a href="/student?id=${r.student_id}">${esc(r.student_name)}</a></td><td>${esc(r.record_book)}</td><td>${esc(r.group_name || '—')}</td>
                <td class="num">${r.grades_count}</td><td class="center">${gradeBadge(r.avg_grade)}</td><td class="num">${r.min_grade ?? '—'}</td><td class="num">${r.max_grade ?? '—'}</td>
                <td class="center">${ectsBadge(r.ects)}</td><td>${esc(r.national || '—')}</td><td class="num">${r.debts ? `<span class="badge red">${r.debts}</span>` : '0'}</td></tr>`).join('')}</tbody></table>`
            : '<div class="table-empty">Немає даних за обраними параметрами</div>';
    }

    function renderAttendance({ items, summary: s }) {
        $('#reportStats').innerHTML = chip(s.students, 'Студентів') + chip(`${fmtNum(s.rate)}%`, 'Відвідуваність') + chip(s.total, 'Відміток')
            + chip(s.present, 'Присутній', '#039855') + chip(s.late, 'Запізнення', '#b54708') + chip(s.absent, 'Пропуски', '#d92d20')
            + chip(s.excused, 'Поважна причина', '#0284c7') + chip(s.low, 'Нижче 75%', '#d92d20');
        drawChart(null);
        const sorted = [...items].sort((a, b) => (a.rate ?? 101) - (b.rate ?? 101));
        $('#reportTable').innerHTML = items.length ? `<table class="table"><thead><tr><th>#</th><th>Студент</th><th>Група</th><th class="num">Занять</th>
            <th class="num">Присутній</th><th class="num">Запізн.</th><th class="num">Пропуски</th><th class="num">Поважні</th><th>Відвідуваність</th></tr></thead>
            <tbody>${sorted.map((r, i) => `<tr><td>${i + 1}</td><td><a href="/student?id=${r.student_id}">${esc(r.student_name)}</a></td><td>${esc(r.group_name || '—')}</td>
                <td class="num">${r.total}</td><td class="num">${r.present}</td><td class="num">${r.late}</td><td class="num">${r.absent}</td><td class="num">${r.excused}</td>
                <td style="min-width:170px">${rateBar(r.rate)}</td></tr>`).join('')}</tbody></table>`
            : '<div class="table-empty">Немає даних за обраними параметрами</div>';
    }

    function renderGroups(items) {
        const graded = items.filter((g) => g.avg_grade !== null);
        const best = graded.sort((a, b) => b.avg_grade - a.avg_grade)[0];
        $('#reportStats').innerHTML = chip(items.length, 'Груп') + chip(items.reduce((a, g) => a + g.students, 0), 'Студентів')
            + (best ? chip(esc(best.name), `Найвищий бал (${fmtNum(best.avg_grade)})`, '#039855') : '');
        drawChart({
            type: 'bar',
            data: { labels: items.map((g) => g.name), datasets: [
                { label: 'Середній бал', data: items.map((g) => g.avg_grade), backgroundColor: '#4f5bf0', borderRadius: 4 },
                { label: 'Відвідуваність, %', data: items.map((g) => g.attendance_rate), backgroundColor: '#38c6f4', borderRadius: 4 }] },
            options: { plugins: { legend: { position: 'top', align: 'end' } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, max: 100 } } },
        });
        $('#reportTable').innerHTML = `<table class="table"><thead><tr><th>Група</th><th class="center">Курс</th><th>Спеціальність</th><th class="num">Студентів</th>
            <th class="center">Сер. бал</th><th>Відвідуваність</th></tr></thead><tbody>${items.map((g) => `<tr>
            <td><a href="/reports?tab=performance&group_id=${g.id}"><b>${esc(g.name)}</b></a></td><td class="center">${g.course}</td><td>${esc(g.specialty)}</td>
            <td class="num">${g.students}</td><td class="center">${gradeBadge(g.avg_grade)}</td><td style="min-width:170px">${rateBar(g.attendance_rate)}</td></tr>`).join('')}</tbody></table>`;
    }

    load();
});
