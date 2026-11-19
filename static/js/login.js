(function () {
    const form = document.getElementById('loginForm');
    const err = document.getElementById('loginError');
    const btn = document.getElementById('loginBtn');

    // Same-origin redirect target only (prevents open redirect); leading slashes are collapsed
    // because URL normalization can turn "/./" or "/%2e%2e/" back into "//".
    function safeNext(raw) {
        if (!raw || !raw.startsWith('/') || /[\\\u0000-\u001f\u007f]/.test(raw)) return '/';
        try {
            const url = new URL(raw, location.origin);
            if (url.origin !== location.origin) return '/';
            const path = url.pathname.replace(/^\/+/, '/');
            return path.startsWith('/') && !path.startsWith('//') ? path + url.search : '/';
        } catch { return '/'; }
    }
    const next = safeNext(new URLSearchParams(location.search).get('next'));

    // Demo accounts are shown only when the server runs with demo data
    fetch('/api/auth/config')
        .then((r) => (r.ok ? r.json() : null))
        .then((cfg) => { if (cfg?.demo) document.getElementById('demoAccounts').classList.remove('hidden'); })
        .catch(() => {});

    document.querySelectorAll('[data-u]').forEach((b) => b.addEventListener('click', () => {
        form.username.value = b.dataset.u; form.password.value = b.dataset.p; form.requestSubmit();
    }));

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (btn.disabled) return;
        err.classList.add('hidden');
        const username = form.username.value.trim();
        const password = form.password.value;
        if (!username || !password) { err.textContent = 'Введіть логін і пароль'; err.classList.remove('hidden'); return; }
        btn.disabled = true; btn.textContent = 'Вхід…';
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || 'Помилка входу');
            location.replace(next);
        } catch (ex) {
            err.textContent = ex.message; err.classList.remove('hidden');
            btn.disabled = false; btn.textContent = 'Увійти';
        }
    });
})();
