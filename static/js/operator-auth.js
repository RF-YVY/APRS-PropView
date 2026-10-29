/* Browser-local operator sessions. The server remains the permission authority. */
(() => {
    'use strict';
    const nativeFetch = window.fetch.bind(window);
    let state = { authenticated: false, configured: false, expires_at: null };
    let panel, label, loginButton, logoutButton, sessionToggle, sessionInfo, error, expiryHandled = false;
    let statusPending = false;
    const auth = window.pvOperator = {
        get authenticated() { return state.authenticated && (state.enabled === false || state.expires_at * 1000 > Date.now()); },
        openLogin() { if (state.enabled !== false) panel?.showModal(); },
    };

    function render() {
        const active = auth.authenticated;
        document.documentElement.classList.toggle('operator-authenticated', active);
        const access = document.getElementById('operator-access');
        if (access) access.hidden = state.enabled !== true;
        const toggle = document.getElementById('cfg-security-enabled');
        if (toggle) toggle.checked = state.enabled === true || !!document.getElementById('security-setup-dialog')?.open;
        const securityStatus = document.getElementById('security-status');
        if (securityStatus) securityStatus.textContent = state.enabled
            ? 'User login is on. Other browsers must sign in to change settings or transmit.'
            : 'User login is off. The application is unlocked.';
        if (!label || state.enabled === false) return;
        label.textContent = active
            ? `${state.local_session ? 'Local operator' : 'Operator'} · ${Math.max(0, Math.ceil((state.expires_at * 1000 - Date.now()) / 60000))} min left`
            : 'Public viewer · read-only';
        loginButton.textContent = active ? 'Extend session' : 'Operator sign in';
        logoutButton.hidden = !active;
        sessionToggle.title = label.textContent;
        sessionToggle.setAttribute('aria-label', 'Operator session: '+label.textContent);

        if (!active && state.authenticated && !expiryHandled) {
            expiryHandled = true;
            // Clear privileged forms, message history and active browser GPS jobs.
            window.location.reload();
        }
    }

    async function refresh() {
        if (statusPending) return;
        statusPending = true;
        try {
            const response = await nativeFetch('/api/auth/status', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
            if (response.ok) {
                const data = await response.json();
                const lostSession = state.authenticated && !data.authenticated;
                const changedMode = typeof state.enabled === 'boolean' && state.enabled !== data.enabled;
                state = data;
                render();
                if (lostSession || changedMode) window.location.reload();
            }
        } catch (_) { /* A backend restart must not extend a session. */ }
        finally { statusPending = false; }
    }
    auth.ready = (async () => {
        const token = new URLSearchParams(window.location.hash.slice(1)).get('propview-local');
        if (token) {
            // Erase the single-use capability before any UI/third-party navigation.
            window.history.replaceState(null, '', window.location.pathname + window.location.search);
            try {
                const response = await nativeFetch('/api/auth/local-login', { method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-PropView-Login': '1' },
                    body: JSON.stringify({ token }) });
                if (response.ok) state = await response.json();
            } catch (_) { /* A failed/expired launch never grants operator access. */ }
        }
        await refresh();
    })();

    // The cookie is HttpOnly. Only a per-session CSRF token is available to JS.
    window.fetch = async (input, options = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, window.location.href);
        const localAPI = url.origin === window.location.origin && url.pathname.startsWith('/api/');
        const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        const write = !['GET', 'HEAD', 'OPTIONS'].includes(method);
        if (localAPI && !url.pathname.startsWith('/api/auth/')) await auth.ready;
        if (localAPI && write && !url.pathname.startsWith('/api/auth/')) {
            await auth.ready;
            if (auth.authenticated) {
                const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
                headers.set('X-PropView-CSRF', state.csrf_token);
                options = { ...options, headers };
            }
        }
        const response = await nativeFetch(input, options);
        if (localAPI && response.status === 401 && write) {
            await refresh();
            if (error) error.textContent = 'Operator access expired or is required. Sign in, then repeat your action.';
            auth.openLogin();
        }
        return response;
    };

    document.addEventListener('DOMContentLoaded', () => {
        const access = document.createElement('div');
        access.id = 'operator-access';
        access.hidden = true;
        access.innerHTML = `<button type="button" id="operator-session-toggle" aria-label="Login and operator session" title="Login and operator session" aria-expanded="false" aria-controls="operator-session-info"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg><span>User login</span></button><div id="operator-session-info" role="region" aria-label="Operator session" hidden><span id="operator-role"></span><div class="operator-session-actions"><button type="button" id="operator-login">Operator sign in</button><button type="button" id="operator-logout" hidden>Lock now</button></div></div>`;
        const toolbar=document.getElementById('map-controls');
        (toolbar || document.body).appendChild(access);
        if(!toolbar)access.classList.add('operator-access-floating');
        sessionToggle=document.getElementById('operator-session-toggle');
        sessionInfo=document.getElementById('operator-session-info');
        const closeSession=()=>{sessionInfo.hidden=true;sessionToggle.setAttribute('aria-expanded','false');};
        sessionToggle.addEventListener('click',()=>{sessionInfo.hidden=!sessionInfo.hidden;sessionToggle.setAttribute('aria-expanded',String(!sessionInfo.hidden));});
        document.addEventListener('click',event=>{if(!access.contains(event.target))closeSession();});
        access.addEventListener('keydown',event=>{if(event.key==='Escape'){closeSession();sessionToggle.focus();event.stopPropagation();}});

        panel = document.createElement('dialog');
        panel.id = 'operator-login-dialog';
        panel.setAttribute('aria-labelledby', 'operator-login-title');
        panel.innerHTML = `<form id="operator-login-form">
            <h2 id="operator-login-title">Operator sign in</h2>
            <p>Unlock settings and transmit controls in this browser only. Other viewers stay read-only.</p>
            <p id="operator-local-help">First setup or lost password? On the host computer, choose <b>Set/reset operator password</b> from the PropView tray menu or Start menu. For a headless host, run main.py --set-operator-password with the same deployment data directory. No online recovery service is needed.</p>
            <label>Operator password<input id="operator-password" type="password" autocomplete="current-password" maxlength="256" required></label>
            <label>Stay signed in<select id="operator-duration"><option value="900">15 minutes</option><option value="3600" selected>1 hour</option><option value="28800">8 hours</option></select></label>
            <p>Use HTTPS for internet access. Use a trusted private VPN for remote access when HTTPS is unavailable.</p>
            <p id="operator-login-error" role="alert"></p>
            <div><button type="button" id="operator-login-cancel">Cancel</button><button type="submit" id="operator-login-submit">Sign in</button></div>
        </form>`;
        document.body.appendChild(panel);
        label = document.getElementById('operator-role');
        loginButton = document.getElementById('operator-login');
        logoutButton = document.getElementById('operator-logout');
        error = document.getElementById('operator-login-error');
        loginButton.addEventListener('click', () => { closeSession(); error.textContent = ''; auth.openLogin(); });
        document.getElementById('operator-login-cancel').addEventListener('click', () => panel.close());
        panel.addEventListener('close', () => { document.getElementById('operator-password').value = ''; });
        logoutButton.addEventListener('click', async () => {
            logoutButton.disabled = true;
            try {
                const response = await nativeFetch('/api/auth/logout', { method: 'POST', headers: { 'X-PropView-CSRF': state.csrf_token } });
                if (!response.ok && response.status !== 401) throw new Error('Could not lock this session. Please retry.');
                window.location.reload();
            } catch (e) { error.textContent = e.message; auth.openLogin(); }
            finally { logoutButton.disabled = false; }
        });
        document.getElementById('operator-login-form').addEventListener('submit', async event => {
            event.preventDefault();
            const submit = document.getElementById('operator-login-submit');
            submit.disabled = true;
            error.textContent = 'Signing in…';
            try {
                const response = await nativeFetch('/api/auth/login', { method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-PropView-Login': '1' },
                    body: JSON.stringify({ password: document.getElementById('operator-password').value,
                        duration: Number(document.getElementById('operator-duration').value) }) });
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || 'Could not sign in.');
                state = data;
                window.location.reload();
            } catch (e) { error.textContent = e.message; }
            finally { submit.disabled = false; document.getElementById('operator-password').value = ''; }
        });
        const securityToggle = document.getElementById('cfg-security-enabled');
        const setup = document.createElement('dialog');
        setup.id = 'security-setup-dialog';
        setup.setAttribute('aria-labelledby', 'security-setup-title');
        setup.innerHTML = `<form id="security-setup-form">
            <h2 id="security-setup-title">Enable User login</h2>
            <p>Set a password to protect settings and transmit controls. This browser will be signed in; other browsers must sign in separately.</p>
            <label>New password (6–256 characters)<input id="security-new-password" type="password" autocomplete="new-password" minlength="6" maxlength="256" required></label>
            <label>Confirm password<input id="security-confirm-password" type="password" autocomplete="new-password" minlength="6" maxlength="256" required></label>
            <p id="security-setup-error" role="alert"></p>
            <div><button type="button" id="security-setup-cancel">Cancel</button><button type="submit" id="security-setup-submit">Enable User login</button></div>
        </form>`;
        document.body.appendChild(setup);
        setup.addEventListener('close', () => {
            setup.querySelector('form').reset();
            document.getElementById('security-setup-error').textContent = '';
            render();
        });
        document.getElementById('security-setup-cancel').addEventListener('click', () => setup.close());
        async function saveSecurity(enabled, password) {
            await auth.ready;
            const response = await nativeFetch('/api/auth/security', { method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-PropView-CSRF': state.csrf_token },
                body: JSON.stringify({ enabled, password }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Could not save security settings.');
            window.location.reload();
        }
        securityToggle?.addEventListener('change', async () => {
            if (securityToggle.checked) {
                setup.showModal();
            } else {
                securityToggle.disabled = true;
                try { await saveSecurity(false); }
                catch (e) { render(); document.getElementById('security-status').textContent = e.message; }
                finally { securityToggle.disabled = false; }
            }
        });
        document.getElementById('security-setup-form').addEventListener('submit', async event => {
            event.preventDefault();
            const error = document.getElementById('security-setup-error');
            const password = document.getElementById('security-new-password').value;
            if (password !== document.getElementById('security-confirm-password').value) {
                error.textContent = 'Passwords do not match.';
                return;
            }
            const submit = document.getElementById('security-setup-submit');
            submit.disabled = true;
            try { await saveSecurity(true, password); }
            catch (e) { error.textContent = e.message; }
            finally { submit.disabled = false; }
        });
        render();
        setInterval(render, 1000);
        setInterval(refresh, 15000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    });
})();
