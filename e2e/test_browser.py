"""End-to-end browser scenarios for StudentHub (Playwright).

Run against a fresh demo database:
    DB_PATH=/tmp/e2e.db PORT=8711 python run.py
    BASE_URL=http://localhost:8711 python e2e/test_browser.py
Optional: E2E_TIMEZONE=UTC sets the browser timezone if it differs from the server's.
"""
import asyncio
import os
import re
from datetime import date, timedelta
from urllib.parse import quote, urlparse

from playwright.async_api import async_playwright, expect

BASE = os.getenv("BASE_URL", "http://localhost:8000")
SH = os.getenv("SHOTS_DIR", "e2e/screenshots/")
os.makedirs(SH, exist_ok=True)
DESKTOP = {'width': 1440, 'height': 900}
MOBILE = {'width': 390, 'height': 844}
# Browser timezone must match the server's, or "today" differs around midnight
TZ = {'timezone_id': os.environ['E2E_TIMEZONE']} if os.getenv('E2E_TIMEZONE') else {}
log = []


def ok(msg):
    log.append('PASS ' + msg); print('PASS', msg, flush=True)


def watch_errors(pg, errors):
    """Collect page JS errors, ignoring console noise from expected 4xx responses."""
    pg.on('pageerror', lambda e: errors.append(f'PAGEERROR {pg.url}: {e}'))
    pg.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text
          and errors.append(f'CONSOLE {pg.url}: {m.text}'))


async def login(pg, u, p):
    await pg.goto(BASE + '/login')
    await pg.fill('#username', u); await pg.fill('#password', p); await pg.click('#loginBtn')
    await pg.wait_for_url(BASE + '/'); await pg.wait_for_selector('.kpi')


async def toast(pg, text):
    await expect(pg.locator('.toast', has_text=text).last).to_be_visible(timeout=5000)


async def api_get(pg, url):
    return await pg.evaluate("u => fetch(u).then(r => r.json())", url)


async def no_page_overflow(pg):
    """True if the page has no horizontal scroll (tables scroll inside their containers)."""
    return await pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


async def open_journal(pg, group, subject):
    await pg.goto(BASE + '/grades'); await pg.select_option('#jGroup', label=group)
    await pg.wait_for_selector('#jSubject option:nth-child(2)', state='attached')
    # teacher's own subjects carry a "(моя)" suffix, so match by prefix
    value = await pg.locator('#jSubject option', has_text=subject).first.get_attribute('value')
    await pg.select_option('#jSubject', value); await pg.wait_for_selector('table.journal')


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport=DESKTOP, accept_downloads=True, **TZ)
        pg = await ctx.new_page()
        errors = []
        watch_errors(pg, errors)

        # 1. Login: error, demo block, return to page, open-redirect protection
        lp = await ctx.new_page(); login_console = []
        lp.on('console', lambda m: m.type == 'error' and login_console.append(m.text))
        await lp.goto(BASE + '/login'); await lp.wait_for_load_state('networkidle')
        await expect(lp.locator('#demoAccounts')).to_be_visible(); ok('демо-облікові записи показано в режимі розробки')
        assert not login_console, login_console; await lp.close()
        ok('сторінка входу без помилок у консолі (не звертається до /api/auth/me)')
        await pg.goto(BASE + '/login')
        await pg.fill('#username', 'admin'); await pg.fill('#password', 'bad'); await pg.click('#loginBtn')
        await expect(pg.locator('#loginError')).to_have_text('Невірний логін або пароль'); ok('помилка при невірному паролі')
        await pg.goto(BASE + '/groups'); await pg.wait_for_url('**/login?next=%2Fgroups')
        await pg.fill('#username', 'admin'); await pg.fill('#password', 'admin123'); await pg.click('#loginBtn')
        await pg.wait_for_url(BASE + '/groups'); ok('після входу повернення на запитану сторінку')
        for evil in ['/%5Cevil.example', '//evil.example', 'https://evil.example/']:
            await pg.goto(BASE + '/login?next=' + evil)
            await pg.fill('#username', 'admin'); await pg.fill('#password', 'admin123'); await pg.click('#loginBtn')
            await pg.wait_for_url(BASE + '/')
        ok('open redirect заблоковано (next=/\\evil, //evil, https://evil → на головну)')
        # paths the browser normalizes to "//evil..." must stay on this site
        for evil in ['/.//evil.example/login', '/%2e%2e//evil.example/login', '/a/..//x', '/%2e//x']:
            await pg.goto(BASE + '/login?next=' + quote(evil, safe=''))
            await pg.fill('#username', 'admin'); await pg.fill('#password', 'admin123')
            async with pg.expect_navigation(): await pg.click('#loginBtn')
            url = urlparse(pg.url)
            assert url.netloc == urlparse(BASE).netloc and not url.path.startswith('//'), (evil, pg.url)
        ok('open redirect через нормалізацію шляху (/.//, /%2e%2e//, /a/..//) заблоковано')

        # 2. Students: CRUD
        await pg.goto(BASE + '/students'); await pg.wait_for_selector('#studentsTable tbody tr[data-id]')
        await expect(pg).to_have_title('Студенти · StudentHub'); ok('заголовок сторінки «Студенти · StudentHub»')
        await pg.click('#btnAdd'); await pg.click('[data-submit]')
        await expect(pg.locator('[data-field="last_name"] .error')).to_have_text('Обовʼязкове поле'); ok('клієнтська валідація форми')
        await pg.fill('#f_last_name', 'Ящук'); await pg.fill('#f_first_name', 'Тарас'); await pg.select_option('#f_gender', 'M')
        await pg.fill('#f_record_book', 'E2E-777'); await pg.select_option('#f_group_id', label='КН-21'); await pg.fill('#f_email', 'wrong')
        await pg.click('[data-submit]')
        await expect(pg.locator('[data-field="email"] .error')).to_have_text('Некоректний email'); ok('серверна валідація підсвічує поле')
        taken = (await api_get(pg, '/api/students?limit=1'))['items'][0]['record_book']
        await pg.fill('#f_record_book', taken.lower()); await pg.fill('#f_email', 'yash@test.ua'); await pg.click('[data-submit]')
        await expect(pg.locator('[data-field="record_book"] .error')).to_contain_text('вже існує')
        await expect(pg.locator('#f_record_book')).to_have_class(re.compile('invalid')); ok('409 на зайняту залікову підсвічує поле')
        await pg.fill('#f_record_book', 'E2E-777'); await pg.click('[data-submit]')
        await toast(pg, 'Студента додано'); ok('студента додано')
        await pg.fill('#fSearch', 'E2E-777'); await expect(pg.locator('#studentsTable tbody tr[data-id]')).to_have_count(1)
        row = pg.locator('#studentsTable tbody tr[data-id]').first
        await expect(row).to_contain_text('Ящук Тарас'); ok('пошук за заліковою')
        await row.locator('[data-edit]').click(); await pg.select_option('#f_status', 'academic_leave'); await pg.click('[data-submit]')
        await toast(pg, 'Зміни збережено'); await expect(row).to_contain_text('Академвідпустка'); ok('редагування студента (PATCH)')
        await pg.select_option('#fGroup', label='КН-21'); await expect(pg.locator('#studentsTable tbody tr[data-id]')).to_have_count(1); ok('комбінація фільтрів')
        async with pg.expect_download() as dl: await pg.click('#btnExport')
        d = await dl.value; assert d.suggested_filename == 'students.csv'; ok('експорт CSV студентів')
        await row.locator('[data-del]').click(); await pg.click('[data-ok]')
        await toast(pg, 'Студента видалено'); await expect(pg.locator('.table-empty')).to_have_text('Студентів не знайдено'); ok('видалення з підтвердженням')

        # 3. Global search
        await pg.fill('#fSearch', ''); await pg.keyboard.press('Control+k')
        await pg.keyboard.type('Бойко'); await pg.wait_for_selector('#searchResults a')
        for _ in range(4): await pg.keyboard.press('Backspace')
        await expect(pg.locator('#searchResults')).to_be_hidden()
        await pg.keyboard.press('Enter'); await pg.wait_for_timeout(500)
        assert pg.url.endswith('/students'), pg.url; ok('глобальний пошук: короткий запит очищає результати, Enter нічого не робить')
        await pg.keyboard.type('ойко'); await pg.wait_for_selector('#searchResults a')
        # Enter right after changing the query must not follow stale results
        await pg.keyboard.press('Control+a'); await pg.keyboard.type('Мельник'); await pg.keyboard.press('Enter')
        await pg.wait_for_timeout(500)
        assert pg.url.endswith('/students'), pg.url; ok('глобальний пошук: Enter не відкриває результат попереднього запиту')
        await expect(pg.locator('#searchResults a').first).to_contain_text('Мельник')
        await pg.keyboard.press('Enter'); await pg.wait_for_url('**/student?id=*'); await pg.wait_for_selector('.profile-head')
        await expect(pg.locator('.profile-head h1')).to_contain_text('Мельник'); ok('глобальний пошук Ctrl+K → картка студента')

        # Student enrolled today, for journal and attendance checks
        kn11 = next(g['id'] for g in await api_get(pg, '/api/groups') if g['name'] == 'КН-11')
        newbie = await pg.evaluate("""g => fetch('/api/students', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({last_name: 'Ящишин', first_name: 'Новий', gender: 'M', record_book: 'E2E-NEW', group_id: g})})
            .then(r => r.json())""", kn11)
        assert newbie['enrolled_at'], newbie

        # 4. Grade journal
        await open_journal(pg, 'КН-11', 'Основи програмування')
        cols_before = await pg.locator('table.journal thead th.date').count()
        await pg.click('#btnLesson'); await pg.wait_for_selector('.modal .grade-input')
        lesson_types = await pg.eval_on_selector_all('#lsType option', 'os => os.map(o => o.value)')
        assert lesson_types == ['current', 'module', 'exam'], lesson_types
        await pg.select_option('#lsType', 'module')
        inputs = pg.locator('.modal .grade-input')
        await inputs.nth(0).fill('95'); await inputs.nth(1).fill('58')
        await pg.click('[data-save]'); await toast(pg, 'Збережено оцінок: 2')
        await expect(pg.locator('table.journal thead th.date')).to_have_count(cols_before + 1)
        ok('нове заняття: масове виставлення, зʼявилась колонка; типи лише за формою контролю')
        first = pg.locator('table.journal tbody tr').first.locator('td.cell').last
        await expect(first).to_contain_text('95'); await first.click()
        await pg.wait_for_selector('#gValue'); await pg.fill('#gValue', '88')
        await expect(pg.locator('#gEcts')).to_contain_text('B'); await pg.click('[data-save]')
        await toast(pg, 'Оцінку змінено'); await expect(pg.locator('table.journal tbody tr').first.locator('td.cell').last).to_contain_text('88')
        ok('редагування оцінки з журналу (PATCH), ECTS оновлюється')

        # 4a. Modal stack: Escape closes only the top modal, Tab focus is trapped
        await pg.locator('table.journal tbody tr').first.locator('td.cell').last.click()
        await pg.wait_for_selector('#gValue')
        await pg.click('.modal [data-del]'); await expect(pg.locator('.modal')).to_have_count(2)
        await pg.keyboard.press('Escape'); await expect(pg.locator('.modal')).to_have_count(1)
        await expect(pg.locator('#gValue')).to_be_visible()
        for _ in range(12):
            await pg.keyboard.press('Tab')
            assert await pg.evaluate("!!document.activeElement.closest('.modal')"), 'фокус вийшов за межі вікна'
        await pg.keyboard.press('Shift+Tab')
        assert await pg.evaluate("!!document.activeElement.closest('.modal')")
        await pg.keyboard.press('Escape'); await expect(pg.locator('.modal')).to_have_count(0)
        ok('Escape закриває лише верхнє вікно, фокус утримується у вікні')

        # 4b. Add grade: subject -> group -> student; duplicate 409 keeps the modal open
        await pg.click('#btnAdd'); await pg.wait_for_selector('#gSubject')
        await expect(pg.locator('#gSubject')).to_have_value(re.compile(r'\d+'))  # preselected from the journal
        await pg.wait_for_selector('#gStudent option:nth-child(2)', state='attached')
        first_name = (await pg.locator('table.journal tbody tr').first.locator('td.sticky a').inner_text()).strip()
        await pg.select_option('#gStudent', label=first_name)
        await pg.select_option('#gType', 'module'); await pg.fill('#gValue', '70')
        await pg.click('.modal [data-save]')
        await toast(pg, 'вже існує')
        await expect(pg.locator('.modal')).to_have_count(1); ok('дубль оцінки → 409, повідомлення, вікно лишається відкритим')
        # enrolled today + past date: server error shown under the date field
        browser_today = await pg.input_value('#gDate')
        past = (date.fromisoformat(browser_today) - timedelta(days=7)).isoformat()
        await pg.select_option('#gStudent', label='Ящишин Новий'); await pg.fill('#gDate', past)
        await pg.click('.modal [data-save]')
        await expect(pg.locator('.modal [data-field="date"] .error')).to_contain_text('пізніше дати заняття')
        await expect(pg.locator('#gDate')).to_have_class(re.compile('invalid'))
        await expect(pg.locator('.modal')).to_have_count(1); ok('помилка сервера (details) підсвічує поле у вікні оцінки')
        await pg.select_option('#gSubject', label='Веб-технології')
        await pg.wait_for_selector('#gGroup option:nth-child(2)', state='attached')
        grp = await pg.eval_on_selector_all('#gGroup option', 'os => os.filter(o => o.value).map(o => o.text)')
        types = await pg.eval_on_selector_all('#gType option', 'os => os.map(o => o.value)')
        assert sorted(grp) == sorted(['КН-31', 'ІПЗ-31', 'ІПЗ-41']), grp
        assert types == ['current', 'module', 'credit'], types
        await pg.select_option('#gSubject', value='')
        assert await pg.is_disabled('#gGroup') and await pg.is_disabled('#gStudent')
        await pg.keyboard.press('Escape'); await expect(pg.locator('.modal')).to_have_count(0)
        ok('нова оцінка: лише групи дисципліни, тип за формою контролю')

        # new lesson on a past date hides later-enrolled students
        await pg.click('#btnLesson'); await pg.wait_for_selector('.modal .grade-input')
        newbie_row = pg.locator('.modal tr', has_text='Ящишин')
        await expect(newbie_row).to_be_visible()
        await pg.fill('#lsDate', past)
        await expect(newbie_row).to_be_hidden(); await expect(pg.locator('#lsHidden')).to_contain_text('1')
        await pg.locator('.modal tr:not(.hidden) .grade-input').first.fill('77')
        await pg.click('.modal [data-save]'); await toast(pg, 'Збережено оцінок: 1')
        ok('нове заняття на минулу дату: лише студенти, зараховані до цієї дати; збереження успішне')
        await pg.screenshot(path=SH + 'e2e_journal.png')

        # "All grades" tab
        await pg.click('.tabs button[data-tab="list"]'); await pg.wait_for_selector('#listRows tr[data-id]')
        await pg.select_option('#lType', 'module'); await pg.wait_for_timeout(500)
        types = await pg.locator('#listRows tr[data-id] td:nth-child(5)').all_inner_texts()
        assert types and all(t == 'Модульна' for t in types), types; ok('фільтр списку оцінок за типом')
        # editing a credit grade keeps its type
        await pg.select_option('#lType', 'credit'); await pg.wait_for_timeout(500)
        credit_row = pg.locator('#listRows tr[data-id]').first
        credit_id = await credit_row.get_attribute('data-id')
        await credit_row.locator('[data-edit]').click(); await pg.wait_for_selector('#gType')
        assert await pg.input_value('#gType') == 'credit'
        await pg.fill('#gValue', '61'); await pg.click('.modal [data-save]'); await toast(pg, 'Оцінку змінено')
        g = await api_get(pg, f'/api/grades/{credit_id}')
        assert g['type'] == 'credit' and g['value'] == 61, g; ok('редагування заліку зберігає тип оцінки')

        # 5. Attendance: cancelling the dialog does not move marks to another lesson
        await pg.goto(BASE + '/attendance')
        # take "today" from the browser (its timezone may differ); wait for the page script to fill it
        await expect(pg.locator('#aDate')).not_to_have_value('')
        today = await pg.input_value('#aDate')
        other = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
        await pg.select_option('#aGroup', label='КН-11')
        await pg.wait_for_selector('#aSubject option:nth-child(2)', state='attached')
        await pg.select_option('#aSubject', label='Основи програмування'); await pg.wait_for_selector('.status-switch')
        gid = await pg.input_value('#aGroup'); sid = await pg.input_value('#aSubject')
        sheet_url = f'/api/attendance/sheet?group_id={gid}&subject_id={sid}&date='
        other_before = await api_get(pg, sheet_url + other)
        await pg.locator('#sheet tbody tr').nth(0).locator('[data-status="absent"]').click()
        await pg.locator('#sheet tbody tr').nth(1).locator('[data-status="late"]').click()
        await expect(pg.locator('#sheet tbody tr').nth(0).locator('[data-status="absent"]')).to_have_attribute('aria-checked', 'true')
        await pg.fill('#aDate', other)  # fill fires a change event
        await expect(pg.locator('.modal')).to_have_count(1); await pg.click('.modal .modal-foot [data-close]')
        await expect(pg.locator('#aDate')).to_have_value(today)
        await pg.select_option('#aGroup', label='КН-21')
        await pg.wait_for_selector('.modal'); await pg.keyboard.press('Escape')
        await expect(pg.locator('#aGroup')).to_have_value(gid)
        await expect(pg.locator('#sheet tbody tr').nth(0).locator('button.on')).to_have_text('Відсутній')
        await expect(pg.locator('#sheetStats')).to_contain_text('Відсутні')
        await pg.click('#btnSave'); await toast(pg, 'Відвідуваність збережено')
        await pg.wait_for_selector('text=вже збережено')
        await expect(pg.locator('#sheet tbody tr').nth(0).locator('button.on')).to_have_text('Відсутній')
        saved = await api_get(pg, sheet_url + today)
        assert saved['rows'][0]['status'] == 'absent' and saved['rows'][1]['status'] == 'late', saved['rows'][:2]
        assert await api_get(pg, sheet_url + other) == other_before, 'змінено відмітки іншого заняття'
        ok('скасування діалогу повертає фільтр; збереження лише для заняття на екрані')
        await pg.click('#allPresent')
        assert await pg.eval_on_selector_all('#sheet [data-status="present"]', 'bs => bs.every(b => b.getAttribute("aria-checked") === "true")')
        assert await pg.eval_on_selector_all('#sheet [data-status="absent"]', 'bs => bs.every(b => b.getAttribute("aria-checked") === "false")')
        ok('«Усі присутні» оновлює aria-checked')
        await pg.screenshot(path=SH + 'e2e_attendance.png')
        await pg.select_option('#aSubject', index=0)  # unsaved changes: confirm the dialog
        await pg.click('.modal [data-ok]'); await expect(pg.locator('#sheet')).to_contain_text('Оберіть групу')
        # past lesson: student enrolled today is excluded and saving succeeds
        await pg.select_option('#aSubject', label='Основи програмування'); await pg.wait_for_selector('.status-switch')
        await expect(pg.locator('#sheet')).to_contain_text('Ящишин')
        await pg.fill('#aDate', other)
        await expect(pg.locator('#sheet .status-switch').first).to_be_visible()
        await expect(pg.locator('#sheet')).not_to_contain_text('Ящишин')
        await pg.click('#btnSave'); await toast(pg, 'Відвідуваність збережено')
        ok('відомість минулого заняття без студента, зарахованого пізніше; збереження успішне')

        # 6. Reports: filters persist in the URL
        await pg.goto(BASE + '/reports'); await pg.wait_for_selector('#reportTable table')
        await pg.select_option('#rGroup', label='КН-21'); await pg.wait_for_timeout(400)
        groups = set(await pg.locator('#reportTable tbody td:nth-child(4)').all_inner_texts()); assert groups == {'КН-21'}, groups
        await pg.select_option('#rSubject', label='Бази даних')
        await pg.select_option('#rPreset', 'month'); await pg.wait_for_timeout(400)
        assert (await pg.input_value('#rFrom')).endswith('-01'); ok('звіт успішності: фільтр групи і періоду')
        await pg.click('.tabs button[data-tab="attendance"]'); await pg.wait_for_selector('#reportTable .rate, #reportTable .table-empty')
        assert 'tab=attendance' in pg.url and 'group_id=' in pg.url and 'from=' in pg.url, pg.url
        await pg.reload(); await pg.wait_for_selector('#reportTable .rate, #reportTable .table-empty')
        await expect(pg.locator('.tabs button.active')).to_have_text('Відвідуваність')
        assert await pg.eval_on_selector('#rGroup', 'e => e.options[e.selectedIndex].text') == 'КН-21'
        assert await pg.eval_on_selector('#rSubject', 'e => e.options[e.selectedIndex].text') == 'Бази даних'
        assert await pg.input_value('#rPreset') == 'month' and (await pg.input_value('#rFrom')).endswith('-01')
        ok('звіти: вкладка і всі фільтри відновлюються з адреси')
        async with pg.expect_download() as dl: await pg.click('#btnCsv')
        assert (await dl.value).suggested_filename == 'attendance-report.csv'; ok('звіт відвідуваності + CSV')
        await pg.click('.tabs button[data-tab="groups"]'); await pg.wait_for_selector('#reportTable tbody tr'); ok('порівняння груп')

        # 7. Groups: create; delete with history -> 409
        await pg.goto(BASE + '/groups'); await pg.wait_for_selector('#rows tr[data-id]')
        await pg.click('#btnAdd'); await pg.fill('#f_name', 'кн-41'); await pg.fill('#f_specialty', '122 Компʼютерні науки'); await pg.fill('#f_course', '4')
        await pg.locator('.checkbox-list label', has_text='Бази даних').locator('input').check()
        await pg.click('[data-submit]'); await toast(pg, 'Групу створено'); await expect(pg.locator('#rows')).to_contain_text('КН-41'); ok('створення групи (назва нормалізується)')
        await pg.locator('#rows tr', has_text='КН-11').locator('[data-del]').click(); await pg.click('[data-ok]')
        await expect(pg.locator('.toast.error').last).to_be_visible(); await expect(pg.locator('#rows')).to_contain_text('КН-11')
        await pg.goto(BASE + '/subjects'); await pg.wait_for_selector('#rows tr[data-id]')
        await pg.locator('#rows tr', has_text='Вища математика').locator('[data-del]').click(); await pg.click('[data-ok]')
        await expect(pg.locator('.toast.error').last).to_be_visible(); await expect(pg.locator('#rows')).to_contain_text('Вища математика')
        ok('видалення групи/дисципліни з історією → помилка, рядок лишається')
        await pg.locator('#rows tr', has_text='Веб-технології').locator('[data-edit]').click(); await pg.wait_for_selector('#f_control')
        await pg.select_option('#f_control', 'exam'); await pg.click('[data-submit]')
        await expect(pg.locator('[data-field="control"] .error')).to_contain_text('підсумкові оцінки')
        await pg.keyboard.press('Escape'); await expect(pg.locator('.modal')).to_have_count(0)
        ok('зміна форми контролю за наявності заліків → помилка під полем')

        # 7a. Blocked teacher stays selectable in the subject form, marked as blocked
        await pg.goto(BASE + '/users'); await pg.wait_for_selector('#rows tr[data-id]')
        await pg.locator('#rows tr', has_text='kovalchuk').locator('[data-del]').click(); await pg.click('[data-ok]')
        await expect(pg.locator('.toast.error').last).to_be_visible(); await expect(pg.locator('#rows')).to_contain_text('kovalchuk')
        await pg.locator('#rows tr', has_text='kovalchuk').locator('[data-edit]').click()
        await pg.select_option('#f_is_active', '0'); await pg.click('[data-submit]'); await toast(pg, 'Зміни збережено')
        await expect(pg.locator('#rows tr', has_text='kovalchuk')).to_contain_text('Заблокований')
        await pg.goto(BASE + '/subjects'); await pg.wait_for_selector('#rows tr[data-id]')
        await pg.locator('#rows tr', has_text='Бази даних').locator('[data-edit]').click(); await pg.wait_for_selector('#f_teacher_id')
        label = await pg.eval_on_selector('#f_teacher_id', 'e => e.options[e.selectedIndex].text')
        assert label == 'Ковальчук Ігор Васильович (заблоковано)', label
        await pg.click('[data-submit]'); await toast(pg, 'Зміни збережено')
        await expect(pg.locator('#rows tr', has_text='Бази даних')).to_contain_text('Ковальчук')
        ok('видалення користувача з історією → помилка; заблокований викладач показаний «(заблоковано)» і не скидається')

        # student outside the teacher's groups, for the access check
        all_groups = await api_get(pg, '/api/groups')
        foreign_gid = next(g['id'] for g in all_groups if g['name'] == 'ІПЗ-41')
        foreign_id = (await api_get(pg, f'/api/students?group_id={foreign_gid}&limit=1'))['items'][0]['id']
        own_gid = next(g['id'] for g in all_groups if g['name'] == 'КН-11')
        own_id = (await api_get(pg, f'/api/students?group_id={own_gid}&limit=1'))['items'][0]['id']

        # 8. Logout and teacher role
        await pg.click('#btnLogout'); await pg.wait_for_url('**/login'); ok('вихід із системи')
        await login(pg, 'teacher', 'teacher123')
        assert await pg.locator('.nav a[href="/users"]').count() == 0; ok('викладач не бачить «Користувачі»')
        await pg.goto(BASE + '/students'); await pg.wait_for_selector('#studentsTable tbody tr[data-id]')
        assert await pg.locator('#btnAdd').count() == 0 and await pg.locator('[data-edit]').count() == 0; ok('викладач не може редагувати студентів')
        assert await pg.locator('#btnExport').count() == 0; ok('викладач не бачить «Експорт CSV»')
        await pg.goto(BASE + f'/student?id={own_id}'); await pg.wait_for_selector('.profile-head')
        kv = await pg.inner_text('.kv')
        assert re.search(r'Дата народження\s+—', kv) and re.search(r'Телефон\s+—', kv), kv; ok('викладач: персональні дані приховано («—»)')
        await pg.goto(BASE + f'/student?id={foreign_id}'); await pg.wait_for_selector('#profile .table-empty')
        ok('викладач: студент поза його групами недоступний')
        await open_journal(pg, 'КН-11', 'Вища математика')
        await expect(pg.locator('#journal')).to_contain_text('Перегляд'); ok('чужа дисципліна — лише перегляд')
        await pg.goto(BASE + '/users'); await expect(pg.locator('#page')).to_contain_text('лише адміністратору'); ok('пряма адреса /users закрита для викладача')

        # 9. Both roles x desktop/mobile (390px): no JS errors, no horizontal scroll
        teacher_state = await ctx.storage_state()
        admin_ctx = await b.new_context(viewport=DESKTOP, **TZ)
        ap = await admin_ctx.new_page(); watch_errors(ap, errors); await login(ap, 'admin', 'admin123')
        admin_state = await admin_ctx.storage_state(); await admin_ctx.close()
        pages = ['/', '/students', '/groups', '/subjects', '/grades', '/attendance', '/reports', '/reports?tab=attendance',
                 '/reports?tab=groups', f'/student?id={own_id}']
        for role, state in (('admin', admin_state), ('teacher', teacher_state)):
            for vp_name, vp in (('desk', DESKTOP), ('mob', MOBILE)):
                c = await b.new_context(viewport=vp, storage_state=state, **TZ)
                mp = await c.new_page(); watch_errors(mp, errors)
                for path in pages + (['/users'] if role == 'admin' else []):
                    await mp.goto(BASE + path); await mp.wait_for_selector('.layout'); await mp.wait_for_load_state('networkidle')
                    await mp.wait_for_timeout(250)
                    assert await no_page_overflow(mp), f'горизонтальна прокрутка: {role} {vp_name} {path}'
                    if path.startswith('/student?'):
                        # profile tables (incl. recent grades) must not scroll internally
                        wide = await mp.eval_on_selector_all('#profile .table-wrap', 'ws => ws.filter(w => w.scrollWidth > w.clientWidth + 1).length')
                        assert wide == 0, f'прокрутка в таблиці картки: {role} {vp_name}'
                        assert await mp.locator('#profile .card', has_text='Останні оцінки').locator('tbody tr').first.locator('.grade').is_visible()
                    name = re.sub(r'[^a-z0-9]+', '_', path.strip('/') or 'home')
                    await mp.screenshot(path=f'{SH}{role}_{vp_name}_{name}.png', full_page=True)
                if vp_name == 'mob':
                    # mobile journal: grade cells visible next to the name column
                    await open_journal(mp, 'КН-21', 'Основи програмування')
                    vis = await mp.evaluate("""() => {
                        const name = document.querySelector('table.journal tbody td.sticky').getBoundingClientRect();
                        return [...document.querySelectorAll('table.journal tbody tr:first-child td.cell')]
                            .some(td => { const r = td.getBoundingClientRect(); return r.left >= name.right - 1 && r.right <= innerWidth; });
                    }""")
                    assert vis, 'на мобільному не видно жодної клітинки журналу'
                    assert await no_page_overflow(mp)
                    await mp.screenshot(path=f'{SH}{role}_mob_journal.png')
                    await mp.click('#menuToggle'); await mp.wait_for_timeout(300); await mp.screenshot(path=f'{SH}{role}_mob_menu.png')
                await c.close()
                ok(f'{role} / {vp_name}: усі сторінки без помилок і горизонтальної прокрутки')

        assert not errors, '\n'.join(errors)
        print('NO JS ERRORS')
        print(f'{len(log)} checks passed')
        await b.close()

asyncio.run(main())
