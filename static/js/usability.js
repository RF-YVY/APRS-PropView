/** APRS PropView v1.10 usability helpers: guided setup, presets, diagnostics, and navigation. */
(function () {
    'use strict';

    const VIEW_KEY = 'pvSettingsComplexityV1';
    const ADVANCED_SECTIONS = new Set([
        'smart-beaconing', 'bulletins', 'aprs-objects', 'digipeater', 'igate',
        'tracking', 'messaging', 'status-dx', 'wxnow', 'weather', 'mqtt',
    ]);

    const TERMS = {
        'Direct RF': 'A packet your own radio heard without another station repeating it first. This is the strongest local propagation evidence.',
        'Regional RF': 'RF activity heard anywhere in the received packet paths, including traffic relayed by digipeaters. It describes the wider area.',
        'APRS-IS': 'The internet backbone for APRS. It can supply regional traffic and carry gated packets, but it is separate from what your radio heard directly.',
        'IGate': 'A station that passes selected APRS traffic between RF and APRS-IS. RF to internet is the usual receive-side direction.',
        'Digipeater': 'An RF station that receives and repeats APRS packets so they can travel farther over radio.',
        'Watched path': 'A bearing and distance from your station that PropView checks against recent direct RF evidence for a possible VHF opening.',
        'Maidenhead grid': 'A compact geographic locator used by amateur radio operators. The map grid can fill a watched-path target for you.',
        'Passcode': 'The numeric APRS-IS login passcode associated with a callsign. Receive-only connections can use -1; transmitting requires a valid passcode.',
    };

    const PRESETS = {
        receive_rf: {
            title: 'Receive-only RF monitor', risk: 'safe',
            copy: 'Uses enabled radio/TNC ports for reception. RF transmit, APRS-IS, digipeating, and gating are disabled.',
            fields: { 'cfg-digi-enabled': false, 'cfg-igate-enabled': false, 'cfg-igate-rf2is': false, 'cfg-igate-is2rf': false, 'cfg-is-enabled': false, 'cfg-smart-enabled': false },
            rf: { rx_only_rf: true, rx_only_is: true },
        },
        rf_and_is: {
            title: 'RF + APRS-IS monitor', risk: 'safe',
            copy: 'Receives local RF and regional APRS-IS traffic. Radio ports remain receive-only and gating stays off.',
            fields: { 'cfg-digi-enabled': false, 'cfg-igate-enabled': false, 'cfg-igate-rf2is': false, 'cfg-igate-is2rf': false, 'cfg-is-enabled': true, 'cfg-smart-enabled': false },
            rf: { rx_only_rf: true, rx_only_is: true },
        },
        rx_igate: {
            title: 'Receive-only IGate', risk: 'caution',
            copy: 'Receives RF and gates eligible packets to APRS-IS. Internet-to-RF gating and digipeating stay off. A valid APRS-IS passcode is required.',
            fields: { 'cfg-digi-enabled': false, 'cfg-igate-enabled': true, 'cfg-igate-rf2is': true, 'cfg-igate-is2rf': false, 'cfg-is-enabled': true, 'cfg-smart-enabled': false },
            rf: { rx_only_rf: true, rx_only_is: true },
        },
        digipeater: {
            title: 'RF digipeater', risk: 'transmit',
            copy: 'Enables APRS RF repeating on configured radio ports. Review aliases, RF path policy, and local coordination before saving.',
            fields: { 'cfg-digi-enabled': true, 'cfg-igate-enabled': false, 'cfg-igate-rf2is': false, 'cfg-igate-is2rf': false, 'cfg-is-enabled': false, 'cfg-smart-enabled': false },
            rf: { rx_only_rf: false, rx_only_is: true },
        },
        bidirectional_igate: {
            title: 'Bidirectional IGate', risk: 'transmit',
            copy: 'Enables RF-to-internet and internet-to-RF gating. Review APRS-IS verification, message gating rules, and RF transmit access before saving.',
            fields: { 'cfg-digi-enabled': false, 'cfg-igate-enabled': true, 'cfg-igate-rf2is': true, 'cfg-igate-is2rf': true, 'cfg-is-enabled': true, 'cfg-smart-enabled': false },
            rf: { rx_only_rf: false, rx_only_is: false },
        },
        mobile: {
            title: 'Mobile station', risk: 'transmit',
            copy: 'Enables browser GPS, moving APRS-IS range filtering, and Smart Beaconing. Review beacon timing and transmit routes before saving.',
            fields: { 'cfg-digi-enabled': false, 'cfg-igate-enabled': false, 'cfg-igate-rf2is': false, 'cfg-igate-is2rf': false, 'cfg-is-enabled': true, 'cfg-gps-enabled': true, 'cfg-smart-enabled': true, 'cfg-is-range-mode': 'moving' },
            rf: { rx_only_rf: false, rx_only_is: true },
        },
    };

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
    }

    function activateDesktopTab(tabId) {
        const button = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        if (!button?.classList.contains('active')) button?.click();
    }

    function goToSettings(category = 'overview', sectionKey = '') {
        activateDesktopTab('tab-settings');
        setTimeout(() => {
            window.pvActivateSettingsCategory?.(category, true);
            if (!sectionKey) return;
            const section = document.querySelector(`.settings-section[data-settings-key="${sectionKey}"]`);
            if (!section) return;
            section.classList.remove('collapsed');
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
            section.classList.add('usability-focus');
            setTimeout(() => section.classList.remove('usability-focus'), 1800);
        }, 80);
    }
    window.pvGoToSettings = goToSettings;

    function setControl(id, value) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.type === 'checkbox' || el.type === 'radio') el.checked = !!value;
        else el.value = String(value);
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function setRfReceiveFlags(flags) {
        document.querySelectorAll('.rf-port-card').forEach((card) => {
            for (const [field, value] of Object.entries(flags || {})) {
                const el = card.querySelector(`[data-field="${field}"]`);
                if (el) el.checked = !!value;
            }
        });
    }

    function renderPresetPreview() {
        const select = document.getElementById('setup-mode-preset');
        const preview = document.getElementById('setup-mode-preview');
        const button = document.getElementById('btn-apply-mode-preset');
        const preset = PRESETS[select?.value];
        if (!preview || !button || !preset) return;
        preview.className = `setup-mode-preview ${preset.risk}`;
        preview.innerHTML = `<strong>${escapeHTML(preset.title)}</strong><span>${escapeHTML(preset.copy)}</span>`;
        button.textContent = preset.risk === 'transmit' ? 'Stage Transmit-Capable Preset' : 'Stage Preset';
    }

    function applyPreset() {
        const preset = PRESETS[document.getElementById('setup-mode-preset')?.value];
        if (!preset) return;
        if (['rx_igate', 'digipeater', 'bidirectional_igate', 'mobile'].includes(document.getElementById('setup-mode-preset')?.value)) {
            setComplexity('advanced');
        }
        Object.entries(preset.fields).forEach(([id, value]) => setControl(id, value));
        setRfReceiveFlags(preset.rf);
        window.pvMarkSettingsDirty?.(`${preset.title} staged. Review highlighted settings, then save when ready.`);
        document.getElementById('setup-mode-result').textContent = 'Staged only — nothing was saved or transmitted.';
        updateReadiness();
        window.pvActivateSettingsCategory?.(preset.title.includes('Mobile') ? 'station' : 'radio', true);
    }

    function addOverviewTools() {
        const grid = document.querySelector('.settings-utility-grid');
        if (!grid || document.getElementById('setup-mode-preset')) return;
        const presets = document.createElement('div');
        presets.className = 'settings-utility-panel setup-mode-panel';
        presets.innerHTML = `
            <div class="settings-utility-title">Operating Mode Preset</div>
            <label class="sr-only" for="setup-mode-preset">Operating mode</label>
            <select id="setup-mode-preset">
                <option value="receive_rf">Receive-only RF monitor</option>
                <option value="rf_and_is">RF + APRS-IS monitor</option>
                <option value="rx_igate">Receive-only IGate</option>
                <option value="digipeater">RF digipeater</option>
                <option value="bidirectional_igate">Bidirectional IGate</option>
                <option value="mobile">Mobile station</option>
            </select>
            <div id="setup-mode-preview" class="setup-mode-preview"></div>
            <button type="button" class="btn-small" id="btn-apply-mode-preset">Stage Preset</button>
            <small id="setup-mode-result">Presets change the form only. Save Configuration remains a separate step.</small>`;
        const readiness = document.createElement('div');
        readiness.className = 'settings-utility-panel readiness-panel';
        readiness.innerHTML = `
            <div class="settings-utility-title">Configuration Readiness</div>
            <div id="configuration-readiness" aria-live="polite"></div>
            <button type="button" class="btn-small" id="btn-refresh-readiness">Check Again</button>`;
        grid.append(presets, readiness);
        document.getElementById('setup-mode-preset').addEventListener('change', renderPresetPreview);
        document.getElementById('btn-apply-mode-preset').addEventListener('click', applyPreset);
        document.getElementById('btn-refresh-readiness').addEventListener('click', updateReadiness);
        renderPresetPreview();
    }

    function readBool(id) { return !!document.getElementById(id)?.checked; }
    function readValue(id) { return (document.getElementById(id)?.value || '').trim(); }

    function readinessItems() {
        const blockers = [];
        const warnings = [];
        const call = readValue('cfg-callsign').toUpperCase();
        const lat = Number(readValue('cfg-latitude'));
        const lon = Number(readValue('cfg-longitude'));
        const rfCards = [...document.querySelectorAll('.rf-port-card')].filter((card) => card.querySelector('[data-field="enabled"]')?.checked);
        const aprs = readBool('cfg-is-enabled');
        const pass = readValue('cfg-is-passcode');
        const filter = document.getElementById('cfg-is-filter-combined')?.textContent?.trim();
        const transmitRf = readBool('cfg-digi-enabled') || readBool('cfg-igate-is2rf') || rfCards.some((card) => !card.querySelector('[data-field="rx_only_rf"]')?.checked);
        if (!call || ['N0CALL', 'NOCALL', 'MYCALL', 'TEST'].includes(call)) blockers.push(['Station callsign is still a placeholder.', 'station', 'station']);
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || (lat === 0 && lon === 0)) blockers.push(['Station location is not set.', 'station', 'station']);
        if (!rfCards.length && !aprs) blockers.push(['No receive source is enabled.', 'radio', 'rf-ports']);
        if (aprs && (!filter || filter === '—')) warnings.push(['APRS-IS has no range filter; traffic may be empty or broader than intended.', 'radio', 'aprsis']);
        if ((readBool('cfg-igate-enabled') || readBool('cfg-igate-is2rf')) && (!pass || pass === '-1')) blockers.push(['IGate operation needs a valid APRS-IS passcode.', 'radio', 'aprsis']);
        if (transmitRf) warnings.push(['At least one RF transmit-capable function is staged. Review paths and local coordination.', 'radio', 'rf-ports']);
        if (readBool('cfg-alerts-enabled') && !readBool('cfg-alerts-discord') && !readBool('cfg-alerts-email') && !readBool('cfg-alerts-sms')) warnings.push(['Alerts are enabled without an external notification channel; in-app and audio behavior may still apply.', 'alerts', 'alerts']);
        return { blockers, warnings };
    }

    function updateReadiness() {
        const el = document.getElementById('configuration-readiness');
        if (!el) return;
        const { blockers, warnings } = readinessItems();
        const state = blockers.length ? 'needs-attention' : (warnings.length ? 'review' : 'ready');
        const heading = blockers.length ? `${blockers.length} item${blockers.length === 1 ? '' : 's'} to fix` : (warnings.length ? 'Ready after review' : 'Ready to receive');
        const rows = [...blockers.map((x) => ['blocker', ...x]), ...warnings.map((x) => ['warning', ...x])];
        el.innerHTML = `<div class="readiness-summary ${state}">${heading}</div>${rows.length ? `<ul>${rows.map(([kind, text, category, section]) => `<li class="${kind}"><button type="button" data-go-settings="${category}" data-go-section="${section}">${escapeHTML(text)}</button></li>`).join('')}</ul>` : '<p>Core identity, location, and receive-source checks pass.</p>'}`;
    }

    function setComplexity(mode) {
        const next = mode === 'advanced' ? 'advanced' : 'basic';
        localStorage.setItem(VIEW_KEY, next);
        const panel = document.querySelector('.settings-panel');
        panel?.classList.toggle('settings-basic-mode', next === 'basic');
        document.querySelectorAll('.settings-section').forEach((section) => {
            section.dataset.usabilityLevel = ADVANCED_SECTIONS.has(section.dataset.settingsKey) ? 'advanced' : 'basic';
        });
        const button = document.getElementById('btn-settings-complexity');
        if (button) {
            button.textContent = next === 'basic' ? 'Show Advanced' : 'Show Basic';
            button.setAttribute('aria-pressed', String(next === 'advanced'));
        }
        document.querySelectorAll('.settings-quicknav-btn').forEach((buttonEl) => {
            const category = buttonEl.dataset.settingsCategory;
            const hasBasic = !!document.querySelector(`.settings-section[data-settings-category="${category}"][data-usability-level="basic"]`);
            buttonEl.classList.toggle('complexity-hidden', next === 'basic' && category !== 'overview' && !hasBasic);
        });
        document.querySelectorAll('.settings-category-select option').forEach((option) => {
            const hasBasic = !!document.querySelector(`.settings-section[data-settings-category="${option.value}"][data-usability-level="basic"]`);
            option.hidden = next === 'basic' && option.value !== 'overview' && !hasBasic;
        });
        if (next === 'basic') {
            const activeCategory = panel?.dataset.activeSettingsCategory || 'overview';
            const activeHasBasic = !!document.querySelector(`.settings-section[data-settings-category="${activeCategory}"][data-usability-level="basic"]`);
            if (activeCategory !== 'overview' && !activeHasBasic) window.pvActivateSettingsCategory?.('overview', false);
        }
    }

    function addComplexityToggle() {
        const actions = document.querySelector('.settings-toolbar-actions');
        if (!actions || document.getElementById('btn-settings-complexity')) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.id = 'btn-settings-complexity';
        button.className = 'settings-toolbar-btn settings-complexity-btn';
        button.addEventListener('click', () => setComplexity(document.querySelector('.settings-panel')?.classList.contains('settings-basic-mode') ? 'advanced' : 'basic'));
        actions.prepend(button);
        setComplexity(localStorage.getItem(VIEW_KEY) || 'basic');
    }

    function addAlertAssistant() {
        const body = document.querySelector('[data-settings-key="alerts"] .settings-section-body');
        if (!body || document.getElementById('alert-setup-assistant')) return;
        const card = document.createElement('div');
        card.id = 'alert-setup-assistant';
        card.className = 'alert-setup-assistant';
        card.innerHTML = `
            <strong>Alert Setup Assistant</strong>
            <ol>
                <li>Enable alerts after your RF receiver is producing local data.</li>
                <li>Collect a normal 24-hour baseline, then run <button type="button" data-assistant-action="analyze">Analyze Last 24h</button>.</li>
                <li>Review thresholds and cooldown before applying suggestions.</li>
                <li>Choose audio, Discord, email, or SMS and <button type="button" data-assistant-action="test">send a test alert</button>.</li>
                <li>Save Configuration.</li>
            </ol>
            <p>Start with higher thresholds if routine local traffic is producing too many alerts.</p>`;
        body.prepend(card);
    }

    function diagnosticsModal() {
        let modal = document.getElementById('connection-diagnostics-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'connection-diagnostics-modal';
        modal.className = 'modal-overlay connection-diagnostics-overlay';
        modal.style.display = 'none';
        modal.innerHTML = `<div class="modal-content connection-diagnostics-modal" role="dialog" aria-modal="true" aria-labelledby="connection-diagnostics-title">
            <div class="modal-header"><h3 id="connection-diagnostics-title">Connection Diagnostics</h3><button type="button" class="modal-close" data-close-diagnostics aria-label="Close diagnostics">&times;</button></div>
            <div id="connection-diagnostics-body" class="connection-diagnostics-body">Checking connections...</div>
            <div class="diagnostics-actions"><button type="button" class="btn-small" data-refresh-diagnostics>Check Again</button><button type="button" class="btn-small" data-close-diagnostics>Close</button></div>
        </div>`;
        document.body.appendChild(modal);
        return modal;
    }

    function stateCard(title, state, detail, category, section) {
        const ok = state === 'Connected' || state === 'Ready';
        return `<section class="diagnostic-card ${ok ? 'ok' : 'attention'}"><div><strong>${escapeHTML(title)}</strong><span>${escapeHTML(state)}</span></div><p>${escapeHTML(detail)}</p><button type="button" data-go-settings="${category}" data-go-section="${section}">Open settings</button></section>`;
    }

    async function openDiagnostics() {
        const modal = diagnosticsModal();
        const body = document.getElementById('connection-diagnostics-body');
        modal.style.display = 'flex';
        body.textContent = 'Checking connections...';
        try {
            const response = await fetch('/api/diagnostics');
            const data = await response.json();
            const c = data.connections || {};
            const rf = c.rf_interfaces || [];
            const rfConnected = rf.filter((port) => port.connected);
            const rfDetail = rf.length ? rf.map((port) => `${port.name || port.port || 'RF port'}: ${port.connection_state || (port.connected ? 'connected' : 'offline')}`).join(' · ') : 'No RF ports are configured.';
            const aprs = data.aprs_is || {};
            const isState = aprs.connected ? (aprs.verified ? 'Connected' : 'Read-only') : (!aprs.enabled ? 'Disabled' : 'Offline');
            const isDetail = aprs.connected ? (aprs.verified ? `Connected and verified at ${aprs.server}:${aprs.port}.` : 'Traffic can be received, but the login is not verified for transmit.') : (!aprs.enabled ? 'APRS-IS is disabled in settings.' : 'Check server, network, callsign, passcode, and range filter.');
            body.innerHTML = [
                stateCard('RF interfaces', rfConnected.length ? 'Connected' : (rf.length ? 'Offline' : 'Disabled'), rfDetail, 'radio', 'rf-ports'),
                stateCard('APRS-IS', isState, isDetail, 'radio', 'aprsis'),
                stateCard('Browser live link', data.websocket_connections > 0 ? 'Connected' : 'Offline', `${data.websocket_connections || 0} dashboard connection${data.websocket_connections === 1 ? '' : 's'} currently active.`, 'display', 'web'),
            ].join('');
        } catch (error) {
            body.innerHTML = '<div class="diagnostics-error">Diagnostics could not reach the local server. Reload the page or confirm APRS PropView is running.</div>';
        }
    }

    function terminologyModal() {
        let modal = document.getElementById('terminology-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'terminology-modal';
        modal.className = 'modal-overlay terminology-overlay';
        modal.style.display = 'none';
        modal.innerHTML = `<div class="modal-content terminology-modal" role="dialog" aria-modal="true" aria-labelledby="terminology-title"><div class="modal-header"><h3 id="terminology-title">APRS PropView Terms</h3><button type="button" class="modal-close" data-close-terms aria-label="Close terms">&times;</button></div><dl>${Object.entries(TERMS).map(([term, definition]) => `<div><dt>${escapeHTML(term)}</dt><dd>${escapeHTML(definition)}</dd></div>`).join('')}</dl></div>`;
        document.body.appendChild(modal);
        return modal;
    }

    function addTerminologyLinks() {
        const targets = [
            ['[data-settings-key="aprsis"] h3', 'APRS-IS'],
            ['[data-settings-key="igate"] h3', 'IGate'],
            ['[data-settings-key="digipeater"] h3', 'Digipeater'],
            ['[data-settings-key="watched-paths"] h3', 'Watched path'],
        ];
        targets.forEach(([selector, term]) => {
            const heading = document.querySelector(selector);
            if (!heading || heading.querySelector('.term-help')) return;
            heading.insertAdjacentHTML('beforeend', ` <button type="button" class="term-help" data-term="${escapeHTML(term)}" title="Explain ${escapeHTML(term)}" aria-label="Explain ${escapeHTML(term)}">?</button>`);
        });
        const helpSection = document.querySelector('#help-modal .help-section:last-of-type');
        if (helpSection && !document.getElementById('btn-open-terms')) helpSection.insertAdjacentHTML('beforeend', '<p><button type="button" class="btn-small" id="btn-open-terms">Open APRS terminology guide</button></p>');
    }

    function enhanceEmptyState(el) {
        if (!el || el.dataset.actionableEmpty === '1' || el.querySelector?.('[data-empty-action]')) return;
        const text = (el.textContent || '').toLowerCase();
        let action = null;
        if (text.includes('watched path')) action = ['Add a watched path', 'propagation', 'watched-paths'];
        else if (text.includes('alert')) action = ['Set up alerts', 'alerts', 'alerts'];
        else if (text.includes('weather')) action = ['Configure weather', 'alerts', 'weather'];
        else if (text.includes('station') || text.includes('data yet') || text.includes('packet')) action = ['Check receive setup', 'radio', 'rf-ports'];
        if (!action) return;
        el.dataset.actionableEmpty = '1';
        el.insertAdjacentHTML('beforeend', `<div><button type="button" class="empty-state-action" data-empty-action data-go-settings="${action[1]}" data-go-section="${action[2]}">${action[0]}</button></div>`);
    }

    function initialize() {
        addOverviewTools();
        addComplexityToggle();
        addAlertAssistant();
        addTerminologyLinks();
        diagnosticsModal();
        terminologyModal();
        document.querySelectorAll('.connection-chip').forEach((chip) => {
            chip.setAttribute('role', 'button');
            chip.setAttribute('tabindex', '0');
            chip.setAttribute('aria-label', `${chip.textContent.trim()} — open diagnostics`);
        });
        document.querySelectorAll('.analytics-empty, .empty-state, .rf-ports-empty').forEach(enhanceEmptyState);
        new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
            if (node.nodeType !== 1) return;
            if (node.matches?.('.analytics-empty, .empty-state, .rf-ports-empty')) enhanceEmptyState(node);
            node.querySelectorAll?.('.analytics-empty, .empty-state, .rf-ports-empty').forEach(enhanceEmptyState);
        }))).observe(document.body, { childList: true, subtree: true });
        setTimeout(updateReadiness, 450);
        setTimeout(updateReadiness, 1600);
    }

    document.addEventListener('click', (event) => {
        const jump = event.target.closest('[data-settings-jump], [data-go-settings]');
        if (jump) {
            event.preventDefault();
            goToSettings(jump.dataset.settingsJump || jump.dataset.goSettings, jump.dataset.goSection || '');
            return;
        }
        if (event.target.closest('.connection-chip')) { openDiagnostics(); return; }
        if (event.target.closest('[data-close-diagnostics]')) { diagnosticsModal().style.display = 'none'; return; }
        if (event.target.closest('[data-refresh-diagnostics]')) { openDiagnostics(); return; }
        const term = event.target.closest('[data-term]');
        if (term) {
            const modal = terminologyModal();
            modal.querySelector('dl').innerHTML = `<div><dt>${escapeHTML(term.dataset.term)}</dt><dd>${escapeHTML(TERMS[term.dataset.term] || '')}</dd></div><button type="button" class="btn-small" id="btn-show-all-terms">Show all terms</button>`;
            modal.style.display = 'flex';
            return;
        }
        if (event.target.closest('#btn-open-terms')) {
            const modal = terminologyModal();
            modal.querySelector('dl').innerHTML = Object.entries(TERMS).map(([name, definition]) => `<div><dt>${escapeHTML(name)}</dt><dd>${escapeHTML(definition)}</dd></div>`).join('');
            modal.style.display = 'flex';
            return;
        }
        if (event.target.closest('#btn-show-all-terms')) {
            terminologyModal().querySelector('dl').innerHTML = Object.entries(TERMS).map(([name, definition]) => `<div><dt>${escapeHTML(name)}</dt><dd>${escapeHTML(definition)}</dd></div>`).join('');
            return;
        }
        if (event.target.closest('[data-close-terms]')) { terminologyModal().style.display = 'none'; return; }
        const assistant = event.target.closest('[data-assistant-action]');
        if (assistant?.dataset.assistantAction === 'analyze') document.getElementById('btn-alerts-recommend')?.click();
        if (assistant?.dataset.assistantAction === 'test') document.getElementById('btn-alerts-test')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    document.addEventListener('keydown', (event) => {
        if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('.connection-chip')) {
            event.preventDefault(); openDiagnostics();
        }
        if (event.key === 'Escape') {
            const diagnostics = document.getElementById('connection-diagnostics-modal');
            const terms = document.getElementById('terminology-modal');
            if (diagnostics) diagnostics.style.display = 'none';
            if (terms) terms.style.display = 'none';
        }
    });

    document.addEventListener('input', (event) => {
        if (event.target.closest('.settings-panel')) setTimeout(updateReadiness, 0);
    });
    document.addEventListener('change', (event) => {
        if (event.target.closest('.settings-panel')) setTimeout(updateReadiness, 0);
    });

    document.addEventListener('DOMContentLoaded', initialize);
})();
