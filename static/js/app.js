/**
 * Main application — initializes all components and wires them together.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────
    let serverConfig = null;
    let uptimeStart = 0;
    const SETTINGS_COLLAPSE_KEY = 'pvSettingsCollapsed';
    const UI_STATE_KEY = 'pvDesktopUIState';
    const UPDATE_BANNER_DISMISS_KEY = 'pvUpdateBannerDismissed';
    const DEFAULT_UI_THEME = 'dark';
    const ALERT_AUDIO_SLOTS = [
        ['my_station_opening', 'My Station Band Opening'],
        ['regional_watch', 'Regional Band Watch'],
        ['first_heard', 'First-Heard Station'],
        ['anomaly', 'Propagation Anomaly'],
        ['sporadic_e', 'Sporadic-E'],
        ['message_received', 'APRS Message Received'],
        ['weather_warning', 'Weather Warning'],
        ['weather_watch', 'Weather Watch'],
    ];
    const ALERT_AUDIO_FIELD_BY_KEY = {
        my_station_opening: 'audio_my_station_opening_file',
        regional_watch: 'audio_regional_watch_file',
        first_heard: 'audio_first_heard_file',
        anomaly: 'audio_anomaly_file',
        sporadic_e: 'audio_sporadic_e_file',
        message_received: 'audio_message_received_file',
        weather_warning: 'audio_weather_warning_file',
        weather_watch: 'audio_weather_watch_file',
    };
    const RF_PORT_TYPES = {
        serial: 'Serial KISS/TNC2',
        tcp: 'TCP KISS',
    };
    let lastStatus = null;
    let manualBeaconPending = false;
    let liveSyncPending = false;
    let updateCheckPending = false;
    let gpsWatchId = null;
    let lastGpsPost = 0;
    let settingsLoading = false;
    let settingsDirty = false;
    let lastNonSettingsTab = 'tab-rf';

    async function loadConfig(force) {
        if (force || !window.pvConfigPromise) {
            window.pvConfigPromise = fetch('/api/config')
                .then((resp) => {
                    if (!resp.ok) throw new Error(`Config request failed: ${resp.status}`);
                    return resp.json();
                })
                .then((cfg) => {
                    serverConfig = cfg;
                    return cfg;
                })
                .catch((err) => {
                    window.pvConfigPromise = null;
                    throw err;
                });
        }
        const cfg = await window.pvConfigPromise;
        serverConfig = cfg;
        return cfg;
    }

    window.pvConfigPromise = loadConfig(false);

    // ── Distance unit helpers (mi / km) ────────────────────────
    // Default to miles; persisted in localStorage
    window.pvDistUnit = localStorage.getItem('pvDistUnit') || 'mi';
    const KM_TO_MI = 0.621371;

    /** Convert km to the active display unit. */
    window.convertDist = function (km) {
        if (km == null) return null;
        return window.pvDistUnit === 'mi' ? km * KM_TO_MI : km;
    };

    /** Format km as a display string in the active unit. */
    window.formatDist = function (km, decimals) {
        if (decimals === undefined) decimals = 1;
        if (km == null || km === 0) return 'N/A';
        const val = window.pvDistUnit === 'mi' ? km * KM_TO_MI : km;
        return `${val.toFixed(decimals)} ${window.pvDistUnit}`;
    };

    /** Format a numeric bearing as an 8-point compass label. */
    window.formatBearing = function (heading) {
        if (heading == null || Number.isNaN(Number(heading))) return '';
        const sectors = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const normalized = ((Number(heading) % 360) + 360) % 360;
        return sectors[Math.floor((normalized + 22.5) / 45) % 8];
    };

    /** Return the current unit label ('mi' or 'km'). */
    window.distLabel = function () { return window.pvDistUnit; };

    /** Toggle the distance unit and refresh all displays. */
    window.toggleDistUnit = function () {
        window.pvDistUnit = window.pvDistUnit === 'mi' ? 'km' : 'mi';
        localStorage.setItem('pvDistUnit', window.pvDistUnit);
        _refreshAllDistanceDisplays();
    };

    /** Convert a km value to the active unit for settings fields that store in km. */
    window.distToDisplay = function (km) {
        return window.pvDistUnit === 'mi' ? Math.round(km * KM_TO_MI) : km;
    };

    /** Convert a display-unit value back to km for settings fields. */
    window.displayToDist = function (val) {
        return window.pvDistUnit === 'mi' ? val / KM_TO_MI : val;
    };

    /** Refresh every distance-related display after a unit toggle. */
    function _refreshAllDistanceDisplays() {
        const u = window.pvDistUnit;
        // Update all .dist-unit spans
        document.querySelectorAll('.dist-unit').forEach(el => { el.textContent = u; });
        // Update distance filter dropdowns (values stay in km, labels change)
        const miLabels = { '50': '31 mi', '100': '62 mi', '200': '124 mi', '500': '311 mi' };
        const kmLabels = { '50': '50 km', '100': '100 km', '200': '200 km', '500': '500 km' };
        const labels = u === 'mi' ? miLabels : kmLabels;
        document.querySelectorAll('#rf-dist-filter option, #is-dist-filter option').forEach(opt => {
            if (labels[opt.value]) opt.textContent = labels[opt.value];
        });
        // Re-render station lists
        if (window.pvStations) window.pvStations.render();
        // Refresh map legend
        if (window.pvMap) window.pvMap.refreshLegend();
        // Refresh map popups (will update on next open)
    }

    // ── Initialize ─────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        initUIThemeControls();

        // Apply saved distance unit to all labels
        _refreshAllDistanceDisplays();

        // Init tab switching
        initTabs();
        document.addEventListener('click', (e) => {
            if (e.target?.closest?.('#btn-close-settings')) {
                e.preventDefault();
                closeSettingsPane();
            }
        }, true);
        document.querySelector('.tab-btn.active')?.dispatchEvent(new Event('click'));

        // Organize settings UI before control bindings are attached
        initAlertAudioControls();
        initSettingsOrganizer();

        // Init station manager
        window.pvStations.init();

        // Init map (will be re-centered once we get config)
        window.pvMap.init();

        // Init APRS icon picker
        window.pvIconPicker.init();

        // Init analytics module
        window.pvAnalytics.init();

        // Init messaging module
        window.pvMessages.init();

        // Init weather module
        window.pvWeather.init();
        initWeatherSettingsUi();
        initWxNowControls();
        initStatusDxControls();
        initRfPortsControls();
        initTncProfileSettings();
        initUpdateCheckerUi();
        initGpsControls();
        initSettingsDirtyTracking();

        // Wire up WebSocket events
        wireWebSocket();

        // Sidebar toggle
        initSidebarToggle();
        initManualBeaconButton();

        // Force callsign field to uppercase on input
        document.getElementById('cfg-callsign')?.addEventListener('input', (e) => {
            const start = e.target.selectionStart;
            const end = e.target.selectionEnd;
            e.target.value = e.target.value.toUpperCase();
            e.target.setSelectionRange(start, end);
        });

        // Connect WebSocket
        window.pvWebSocket.connect();

        // Start uptime timer
        setInterval(updateUptime, 1000);

        // Refresh relative station timestamps without rebuilding whole lists
        setInterval(() => {
            window.pvStations.refreshRelativeTimes();
        }, 15000);
        setInterval(() => {
            window.pvStations.render();
        }, 60000);

        // Periodically ghost stale markers (every 30s)
        window._ghostMinutes = 60; // default, overwritten by loadSettings
        window._expireMinutes = 0; // default, overwritten by loadSettings
        setInterval(() => {
            window.pvMap?.ghostStaleMarkers(window._ghostMinutes);
            window.pvMap?.updateObservedRange();
        }, 15000);

        // Periodically expire stale stations (every 60s)
        setInterval(() => {
            if (window._expireMinutes > 0) {
                window.pvMap?.expireStaleStations(window._expireMinutes);
            }
        }, 30000);

        setInterval(() => {
            refreshLiveData();
        }, 30000);

        window.addEventListener('beforeunload', (e) => {
            if (!settingsDirty) return;
            e.preventDefault();
            e.returnValue = '';
        });
    });

    // ── Tab switching ──────────────────────────────────────────

    function _activateDesktopTab(tabId, persist = true) {
        const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        if (!btn) return;

        if (tabId !== 'tab-settings' && tabId !== 'tab-messages') {
            lastNonSettingsTab = tabId;
        }

        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(tabId)?.classList.add('active');

        if (persist) {
            const uiState = _loadUIState();
            uiState.activeTab = tabId;
            _saveUIState(uiState);
        }

        const panel = document.getElementById('side-panel');
        if (panel?.classList.contains('collapsed')) {
            panel.classList.remove('collapsed');
            const toggle = document.getElementById('sidebar-toggle');
            if (toggle) toggle.textContent = '>';
            if (toggle) toggle.textContent = 'â–¶';
            if (toggle) toggle.textContent = '>';
            setTimeout(() => window.pvMap?.map?.invalidateSize(), 300);
        }
    }

    function closeSettingsPane() {
        _activateDesktopTab(lastNonSettingsTab || 'tab-rf');
    }
    window.pvCloseSettingsPane = closeSettingsPane;

    function closeMessagesPane() {
        _activateDesktopTab(lastNonSettingsTab || 'tab-rf');
    }
    window.pvCloseMessagesPane = closeMessagesPane;

    function initTabs() {
        window.pvActivateTab = _activateDesktopTab;

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                _activateDesktopTab(btn.dataset.tab);
                return;
                // Deactivate all
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                // Activate selected
                btn.classList.add('active');
                document.getElementById(tabId)?.classList.add('active');

                // If sidebar was collapsed, expand it
                const panel = document.getElementById('side-panel');
                if (panel?.classList.contains('collapsed')) {
                    panel.classList.remove('collapsed');
                    const toggle = document.getElementById('sidebar-toggle');
                    if (toggle) toggle.textContent = '▶';
                    setTimeout(() => window.pvMap?.map?.invalidateSize(), 300);
                }
            });
        });

        const savedTab = _loadUIState().activeTab;
        if (savedTab && document.getElementById(savedTab)) {
            _activateDesktopTab(savedTab, false);
        }
    }

    // ── Sidebar toggle ─────────────────────────────────────────

    function initSidebarToggle() {
        const toggle = document.getElementById('sidebar-toggle');
        const panel = document.getElementById('side-panel');
        if (!toggle || !panel) return;

        toggle.addEventListener('click', () => {
            const isCollapsed = panel.classList.contains('collapsed');
            if (isCollapsed) {
                // Expanding: keep tab content hidden until width transition finishes
                panel.classList.remove('collapsed');
                toggle.textContent = '▶';
                // Show tabs after width transition completes (250ms + buffer)
                setTimeout(() => {
                    panel.querySelectorAll('.tab-bar, .tab-content').forEach(el => el.style.removeProperty('display'));
                    window.pvMap?.map?.invalidateSize();
                }, 280);
            } else {
                // Collapsing
                panel.classList.add('collapsed');
                toggle.textContent = '◀';
                setTimeout(() => window.pvMap?.map?.invalidateSize(), 300);
            }
        });
    }

    function initSettingsOrganizer() {
        const panel = document.querySelector('.settings-panel');
        if (!panel) return;

        const collapsed = new Set(_loadCollapsedSettings());
        const sections = Array.from(panel.querySelectorAll('.settings-section'));
        if (!sections.length) return;

        const toolbar = document.createElement('div');
        toolbar.className = 'settings-toolbar';
        toolbar.innerHTML = `
            <div class="settings-toolbar-search">
                <input type="search" class="settings-search-input" placeholder="Find a setting or section">
            </div>
            <div class="settings-toolbar-actions">
                <button type="button" class="settings-toolbar-btn" data-settings-action="expand">Expand all</button>
                <button type="button" class="settings-toolbar-btn" data-settings-action="collapse">Collapse all</button>
                <button type="button" class="settings-toolbar-btn" data-settings-action="reset">Show all</button>
            </div>
        `;

        const searchInput = toolbar.querySelector('.settings-search-input');
        const quickNav = document.createElement('div');
        quickNav.className = 'settings-quicknav';
        const sectionRefs = [];
        const noResults = document.createElement('div');
        noResults.className = 'settings-no-results';
        noResults.textContent = 'No settings matched that search.';

        function updateStickyOffsets() {
            const headerHeight = panel.querySelector('.settings-pane-header')?.offsetHeight || 0;
            const toolbarHeight = toolbar.offsetHeight || 0;
            toolbar.style.top = `${headerHeight}px`;
            quickNav.style.top = `${headerHeight + toolbarHeight}px`;
            panel.style.setProperty('--settings-sticky-offset', `${headerHeight + toolbarHeight + (quickNav.offsetHeight || 0) + 10}px`);
        }

        function scrollSectionIntoView(section) {
            const toolbarHeight = toolbar.offsetHeight || 0;
            const quickNavHeight = quickNav.offsetHeight || 0;
            const headerHeight = panel.querySelector('.settings-pane-header')?.offsetHeight || 0;
            const extraGap = 8;
            const targetTop =
                panel.scrollTop +
                section.getBoundingClientRect().top -
                panel.getBoundingClientRect().top -
                headerHeight -
                toolbarHeight -
                quickNavHeight -
                extraGap;

            panel.scrollTo({
                top: Math.max(0, targetTop),
                behavior: 'smooth',
            });
        }

        sections.forEach((section, index) => {
            const heading = section.querySelector('h3');
            if (!heading) return;

            const key = section.dataset.settingsKey || `section-${index}`;
            section.dataset.settingsKey = key;
            const title = heading.textContent.trim();
            const summary = (section.dataset.summary || '').trim();
            section.dataset.searchText = `${title} ${summary} ${section.textContent}`.toLowerCase();

            const header = document.createElement('div');
            header.className = 'settings-section-header';

            const titleWrap = document.createElement('div');
            const titleEl = document.createElement('h3');
            titleEl.textContent = title;
            titleWrap.appendChild(titleEl);

            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'settings-section-toggle';
            toggle.addEventListener('click', () => {
                section.classList.toggle('collapsed');
                _syncSettingsSectionState(section, toggle, collapsed);
                _saveCollapsedSettings(collapsed);
            });

            header.appendChild(titleWrap);
            header.appendChild(toggle);

            const body = document.createElement('div');
            body.className = 'settings-section-body';
            Array.from(section.childNodes).forEach((node) => {
                if (node !== heading) body.appendChild(node);
            });

            section.innerHTML = '';
            section.appendChild(header);
            section.appendChild(body);

            if (collapsed.has(key)) section.classList.add('collapsed');
            _syncSettingsSectionState(section, toggle, collapsed, false);

            const navBtn = document.createElement('button');
            navBtn.type = 'button';
            navBtn.className = 'settings-quicknav-btn';
            navBtn.innerHTML = `<span class="settings-quicknav-title">${_escapeHTML(title)}</span>`;
            navBtn.addEventListener('click', () => {
                if (section.classList.contains('collapsed')) {
                    section.classList.remove('collapsed');
                    _syncSettingsSectionState(section, toggle, collapsed);
                    _saveCollapsedSettings(collapsed);
                }
                updateStickyOffsets();
                scrollSectionIntoView(section);
            });
            quickNav.appendChild(navBtn);
            sectionRefs.push({ section, navBtn, toggle });
        });

        toolbar.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-settings-action]');
            if (!btn) return;

            const visibleRefs = sectionRefs.filter(({ section }) => !section.classList.contains('settings-hidden'));
            if (btn.dataset.settingsAction === 'expand') {
                visibleRefs.forEach(({ section, toggle }) => {
                    section.classList.remove('collapsed');
                    _syncSettingsSectionState(section, toggle, collapsed, false);
                });
                _saveCollapsedSettings(collapsed);
                return;
            }

            if (btn.dataset.settingsAction === 'collapse') {
                visibleRefs.forEach(({ section, toggle }) => {
                    section.classList.add('collapsed');
                    _syncSettingsSectionState(section, toggle, collapsed, false);
                });
                _saveCollapsedSettings(collapsed);
                return;
            }

            if (searchInput) searchInput.value = '';
            sectionRefs.forEach(({ section, navBtn }) => {
                section.classList.remove('settings-hidden');
                navBtn.classList.remove('settings-hidden');
            });
            noResults.classList.remove('visible');
        });

        searchInput?.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();
            let visibleCount = 0;

            sectionRefs.forEach(({ section, navBtn }) => {
                const matches = !query || (section.dataset.searchText || '').includes(query);
                section.classList.toggle('settings-hidden', !matches);
                navBtn.classList.toggle('settings-hidden', !matches);
                if (matches) visibleCount += 1;
            });

            noResults.classList.toggle('visible', visibleCount === 0);
        });

        const anchor = panel.querySelector('.settings-section');
        panel.insertBefore(toolbar, anchor);
        panel.insertBefore(quickNav, anchor);
        panel.insertBefore(noResults, anchor);
        updateStickyOffsets();
        window.addEventListener('resize', updateStickyOffsets);
    }

    function _syncSettingsSectionState(section, toggle, collapsedSet, updateStorage = true) {
        const key = section.dataset.settingsKey;
        const isCollapsed = section.classList.contains('collapsed');
        toggle.textContent = isCollapsed ? 'Expand' : 'Collapse';
        toggle.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
        if (isCollapsed) collapsedSet.add(key);
        else collapsedSet.delete(key);
        if (updateStorage) _saveCollapsedSettings(collapsedSet);
    }

    function _loadCollapsedSettings() {
        try {
            const raw = localStorage.getItem(SETTINGS_COLLAPSE_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function _saveCollapsedSettings(collapsedSet) {
        localStorage.setItem(SETTINGS_COLLAPSE_KEY, JSON.stringify(Array.from(collapsedSet)));
    }

    function _loadUIState() {
        try {
            const raw = localStorage.getItem(UI_STATE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function _saveUIState(state) {
        localStorage.setItem(UI_STATE_KEY, JSON.stringify(state || {}));
    }

    function getUITheme() {
        return _loadUIState().uiTheme === 'light' ? 'light' : DEFAULT_UI_THEME;
    }

    function applyUITheme(theme) {
        const normalized = theme === 'light' ? 'light' : DEFAULT_UI_THEME;
        const isLight = normalized === 'light';
        document.documentElement.classList.toggle('ui-theme-light', isLight);

        const metaTheme = document.querySelector('meta[name="theme-color"]');
        if (metaTheme) metaTheme.setAttribute('content', isLight ? '#f5f7fa' : '#0d1117');

        const toggle = document.getElementById('btn-toggle-ui-theme');
        if (toggle) {
            toggle.textContent = isLight ? '☀️' : '🌙';
            toggle.title = isLight ? 'Switch to dark UI' : 'Switch to light UI';
            toggle.setAttribute('aria-label', toggle.title);
        }

        const select = document.getElementById('cfg-ui-theme');
        if (select) select.value = normalized;
    }

    function setUITheme(theme) {
        const normalized = theme === 'light' ? 'light' : DEFAULT_UI_THEME;
        const uiState = _loadUIState();
        uiState.uiTheme = normalized;
        _saveUIState(uiState);
        applyUITheme(normalized);
    }

    function toggleUITheme() {
        const next = getUITheme() === 'light' ? DEFAULT_UI_THEME : 'light';
        setUITheme(next);
    }

    function initUIThemeControls() {
        applyUITheme(getUITheme());

        document.getElementById('btn-toggle-ui-theme')?.addEventListener('click', toggleUITheme);
        document.getElementById('cfg-ui-theme')?.addEventListener('change', (e) => {
            setUITheme(e.target.value);
        });
    }

    function _escapeHTML(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getAlertAudioUrl(alertKey) {
        const file = serverConfig?.alerts?.[ALERT_AUDIO_FIELD_BY_KEY[alertKey]];
        return file ? `/api/alert-audio/file/${encodeURIComponent(file)}` : '';
    }

    async function playAlertAudio(alertKey) {
        const url = getAlertAudioUrl(alertKey);
        if (!url) return;
        try {
            const audio = new Audio(`${url}?t=${Date.now()}`);
            const deviceId = serverConfig?.alerts?.audio_output_device_id || '';
            if (deviceId && typeof audio.setSinkId === 'function') {
                await audio.setSinkId(deviceId);
            }
            audio.volume = 1;
            await audio.play();
        } catch (e) {
            console.warn(`Unable to play ${alertKey} alert audio:`, e);
        }
    }

    window.pvAlertAudio = {
        play: playAlertAudio,
    };

    function initAlertAudioControls() {
        const container = document.getElementById('cfg-alerts-audio-slots');
        if (!container) return;
        container.innerHTML = ALERT_AUDIO_SLOTS.map(([key, label]) => `
            <div class="alert-audio-row" data-alert-audio-key="${key}">
                <div class="alert-audio-name">${_escapeHTML(label)}</div>
                <div class="alert-audio-file" id="cfg-alerts-audio-file-${key}">Silent</div>
                <input type="hidden" id="cfg-alerts-audio-value-${key}">
                <input type="file" id="cfg-alerts-audio-pick-${key}" accept=".wav,.mp3,audio/wav,audio/mpeg">
                <button type="button" class="settings-toolbar-btn" id="cfg-alerts-audio-clear-${key}">Clear</button>
            </div>
        `).join('');

        ALERT_AUDIO_SLOTS.forEach(([key]) => {
            document.getElementById(`cfg-alerts-audio-pick-${key}`)?.addEventListener('change', (e) => {
                const file = e.target.files?.[0];
                if (file) uploadAlertAudio(key, file);
                e.target.value = '';
            });
            document.getElementById(`cfg-alerts-audio-clear-${key}`)?.addEventListener('click', () => {
                setAlertAudioSlot(key, '');
                markSettingsDirty('Unsaved audio setting. Save Configuration to keep this change.');
            });
        });
    }

    function setAlertAudioSlot(key, filename) {
        setVal(`cfg-alerts-audio-value-${key}`, filename || '');
        const label = document.getElementById(`cfg-alerts-audio-file-${key}`);
        if (label) {
            label.textContent = filename || 'Silent';
            label.title = filename || 'No audio file selected';
        }
    }

    async function uploadAlertAudio(key, file) {
        const statusEl = document.getElementById('settings-status');
        if (!/\.(wav|mp3)$/i.test(file.name || '')) {
            showSystemNotification('Select a .wav or .mp3 alert sound.', 'error');
            return;
        }
        try {
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.className = 'settings-status warning';
                statusEl.textContent = `Uploading ${file.name}...`;
            }
            const data = await readFileAsDataUrl(file);
            const resp = await fetch('/api/alert-audio/upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ alert_key: key, filename: file.name, data }),
            });
            const result = await resp.json();
            if (!resp.ok || !result.success) {
                throw new Error(result.message || 'Unable to upload alert audio.');
            }
            setAlertAudioSlot(key, result.filename || '');
            markSettingsDirty('Unsaved audio setting. Save Configuration to keep this change.');
            if (statusEl) {
                statusEl.className = 'settings-status success';
                statusEl.textContent = 'Audio uploaded. Save Configuration to keep this alert sound.';
            }
        } catch (e) {
            console.error('Alert audio upload failed:', e);
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.className = 'settings-status error';
                statusEl.textContent = e.message || 'Audio upload failed.';
            }
        }
    }

    function readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error || new Error('Unable to read file.'));
            reader.readAsDataURL(file);
        });
    }

    async function refreshAudioOutputDevices(selectedId) {
        const select = document.getElementById('cfg-alerts-audio-device');
        if (!select || !navigator.mediaDevices?.enumerateDevices) return;
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const outputs = devices.filter((device) => device.kind === 'audiooutput');
            const current = selectedId || select.value || '';
            select.innerHTML = '<option value="">System default</option>' + outputs.map((device, index) => {
                const label = device.label || `Audio output ${index + 1}`;
                return `<option value="${_escapeHTML(device.deviceId)}">${_escapeHTML(label)}</option>`;
            }).join('');
            if (current && outputs.some((device) => device.deviceId === current)) {
                select.value = current;
            }
        } catch (e) {
            console.warn('Unable to enumerate audio output devices:', e);
        }
    }

    // ── WebSocket event wiring ─────────────────────────────────

    function wireWebSocket() {
        const ws = window.pvWebSocket;

        ws.on('status', (msg) => {
            handleStatus(msg.data);
        });

        ws.on('stats', (msg) => {
            if (msg.data) {
                setTextById('stat-rf-rx', msg.data.rf_rx || 0);
                setTextById('stat-rf-tx', msg.data.rf_tx || 0);
                setTextById('stat-is-rx', msg.data.is_rx || 0);
                setTextById('stat-is-tx', msg.data.is_tx || 0);
                setTextById('stat-digi', msg.data.digipeated || 0);
                setTextById('stat-gated', (msg.data.gated_rf_to_is || 0) + (msg.data.gated_is_to_rf || 0));
            }
        });

        ws.on('initial_stations', (msg) => {
            window.pvStations.loadInitialStations(msg.rf || [], msg.aprs_is || []);
        });

        ws.on('station_update', (msg) => {
            if (msg.station) {
                window.pvStations.updateStation(msg.station);
            }
        });

        ws.on('packet', (msg) => {
            if (msg.data) {
                window.pvStations.addPacket(msg.data);
            }
        });

        ws.on('propagation', (msg) => {
            if (msg.data) {
                updatePropagation(msg.data);
                if (window.pvMap) window.pvMap.updateObservedRange(msg.data.timestamp);
            }
        });

        ws.on('gps_location', (msg) => {
            handleGpsStatus(msg.data);
        });

        ws.on('alert', (msg) => {
            if (msg.data) {
                playAlertAudio(msg.data.type);
                if (msg.data.type === 'my_station_opening' || msg.data.type === 'regional_watch') {
                    showBandAlertNotification(msg.data);
                } else if (msg.data.message) {
                    showSystemNotification(msg.data.message, 'info');
                }
                window.pvAnalytics.loadAlerts();
            }
        });

        ws.on('first_heard', (msg) => {
            if (msg.data) {
                playAlertAudio('first_heard');
                showSystemNotification(`New station heard: ${msg.data.callsign}`, 'info');
            }
        });

        ws.on('anomaly', (msg) => {
            // Auto-refresh anomaly section if visible
            const anomalySection = document.getElementById('sec-anomaly');
            if (anomalySection && anomalySection.classList.contains('active')) {
                window.pvAnalytics.loadAnomaly();
            }
        });

        ws.on('sporadic_e', (msg) => {
            if (msg.data && msg.data.es_level !== 'none') {
                showSystemNotification(`Possible Sporadic-E — ${msg.data.es_level}`, 'info');
            }
        });

        ws.on('message', (msg) => {
            if (msg.data) {
                const myCall = (document.getElementById('station-call')?.textContent || '').toUpperCase();
                const toCall = (msg.data.to || '').toUpperCase();
                if (msg.data.direction === 'rx' && toCall === myCall) {
                    playAlertAudio('message_received');
                }
                window.pvMessages.addMessage(msg.data);
            }
        });

        ws.on('message_ack', (msg) => {
            if (msg.data) {
                window.pvMessages.handleAck(msg.data);
            }
        });

        ws.on('message_rej', (msg) => {
            if (msg.data) {
                window.pvMessages.handleRej(msg.data);
            }
        });

        ws.on('station_removed', (msg) => {
            if (msg.data && msg.data.callsign) {
                window.pvMap?.removeStation(msg.data.callsign, msg.data.source);
                window.pvStations?.removeStation(msg.data.callsign, msg.data.source);
            }
        });

        ws.on('connected', () => {
            // Fetch propagation history for charts
            fetchPropagationHistory();
            window.pvMessages?.render();
            updateAprsIsIndicator(lastStatus);
        });

        ws.on('disconnected', () => {
            window.pvStations?.render();
            window.pvMessages?.render();
            updateAprsIsIndicator(lastStatus);
        });
    }

    // ── Status handling ────────────────────────────────────────

    function updateAprsIsIndicator(status) {
        const chip = document.getElementById('aprs-is-chip');
        const chipText = document.getElementById('aprs-is-chip-text');
        if (!chip || !chipText) return;

        const wsConnected = !!window.pvWebSocket?.isConnected;
        const isConnected = !!status?.aprs_is_connected;
        const isVerified = !!status?.aprs_is_verified;

        let state = 'offline';
        let label = 'Offline';

        if (!wsConnected) {
            state = 'reconnecting';
            label = 'UI reconnecting';
        } else if (isConnected && isVerified) {
            state = 'online';
            label = 'Connected';
        } else if (isConnected) {
            state = 'read-only';
            label = 'Read-only';
        } else {
            state = 'offline';
            label = 'Disconnected';
        }

        chip.classList.remove('online', 'read-only', 'reconnecting', 'offline');
        chip.classList.add(state);
        chipText.textContent = label;
    }

    function getManualBeaconLabel(beacon) {
        if (!beacon) return 'Waiting for status...';
        if (beacon.can_transmit) {
            if (beacon.rf_available && beacon.aprs_is_available) return 'RF + APRS-IS ready';
            if (beacon.rf_available) return 'RF ready';
            if (beacon.aprs_is_available) return 'APRS-IS ready';
        }
        if (!beacon.has_position) return 'Set station position first';
        if (beacon.aprs_is_connected && !beacon.aprs_is_verified) return 'APRS-IS read-only, RF unavailable';
        return 'No transmit path available';
    }

    function updateManualBeaconControls(status) {
        const btn = document.getElementById('btn-manual-beacon');
        const statusEl = document.getElementById('manual-beacon-status');
        const modeEl = document.getElementById('manual-beacon-mode');
        if (!btn || !statusEl || !modeEl) return;

        const beacon = status?.beacon || null;
        const mode = modeEl.value || 'both';
        const canTransmit =
            !!beacon?.has_position &&
            (
                (mode === 'both' && (beacon.rf_available || beacon.aprs_is_available)) ||
                (mode === 'rf' && beacon.rf_available) ||
                (mode === 'aprs_is' && beacon.aprs_is_available)
            );
        let label = getManualBeaconLabel(beacon);
        if (beacon?.has_position) {
            if (mode === 'rf') label = beacon.rf_available ? 'RF ready' : 'RF unavailable';
            if (mode === 'aprs_is') label = beacon.aprs_is_available ? 'APRS-IS ready' : 'APRS-IS unavailable';
        }

        btn.disabled = manualBeaconPending || !canTransmit;
        btn.textContent = manualBeaconPending ? 'Sending Beacon...' : 'Transmit Beacon';
        modeEl.disabled = manualBeaconPending;
        statusEl.textContent = label;
        statusEl.title = beacon?.message || label;
        statusEl.classList.toggle('ready', canTransmit);
        statusEl.classList.toggle('blocked', !!beacon && !canTransmit);
    }

    async function refreshSystemStatus() {
        try {
            const resp = await fetch('/api/status');
            if (!resp.ok) return;
            handleStatus(await resp.json());
        } catch (e) {
            console.error('Failed to refresh system status:', e);
        }
    }

    function initManualBeaconButton() {
        const btn = document.getElementById('btn-manual-beacon');
        const modeEl = document.getElementById('manual-beacon-mode');
        if (!btn || !modeEl) return;

        updateManualBeaconControls(lastStatus);
        modeEl.addEventListener('change', () => updateManualBeaconControls(lastStatus));
        btn.addEventListener('click', async () => {
            if (manualBeaconPending) return;

            manualBeaconPending = true;
            updateManualBeaconControls(lastStatus);

            try {
                const resp = await fetch('/api/beacon/transmit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: modeEl.value || 'both' }),
                });
                const result = await resp.json();
                if (!resp.ok || !result.success) {
                    throw new Error(result.message || 'Beacon transmit failed.');
                }
                showSystemNotification(result.message || 'Beacon transmitted.', 'success');
                await refreshSystemStatus();
            } catch (e) {
                showSystemNotification(e.message || 'Beacon transmit failed.', 'error');
            } finally {
                manualBeaconPending = false;
                updateManualBeaconControls(lastStatus);
            }
        });
    }

    function handleStatus(status) {
        if (!status) return;

        lastStatus = status;
        serverConfig = status;
        uptimeStart = Date.now() / 1000 - (status.uptime_seconds || 0);

        // Update station callsign
        const callEl = document.getElementById('station-call');
        if (callEl) callEl.textContent = status.station || 'N0CALL';

        // Update connection indicators
        const rfEl = document.getElementById('rf-status');
        const isEl = document.getElementById('is-status');
        if (rfEl) {
            rfEl.classList.toggle('connected', status.rf_connected);
            rfEl.classList.toggle('disconnected', !status.rf_connected);
        }
        if (isEl) {
            isEl.classList.toggle('connected', status.aprs_is_connected);
            isEl.classList.toggle('disconnected', !status.aprs_is_connected);
        }
        updateAprsIsIndicator(status);
        updateManualBeaconControls(status);

        // Update stats
        if (status.stats) {
            setTextById('stat-rf-rx', status.stats.rf_rx || 0);
            setTextById('stat-rf-tx', status.stats.rf_tx || 0);
            setTextById('stat-is-rx', status.stats.is_rx || 0);
            setTextById('stat-is-tx', status.stats.is_tx || 0);
            setTextById('stat-digi', status.stats.digipeated || 0);
            setTextById('stat-gated', (status.stats.gated_rf_to_is || 0) + (status.stats.gated_is_to_rf || 0));
        }

        handleGpsStatus(status.gps);

        // Set map position from configured station when live GPS is not driving the map.
        const gpsCurrent = status.gps?.current;
        const gpsDrivesMap = !!(status.gps?.enabled && status.gps?.map_update_enabled && gpsCurrent);
        if (!gpsDrivesMap && status.latitude && status.longitude && status.latitude !== 0) {
            window.pvMap.setMyPosition(status.latitude, status.longitude, status.station);
        }
    }

    function handleGpsStatus(gps) {
        if (!gps) return;
        const current = gps.current;
        const textEl = document.getElementById('gps-status-text');
        if (current) {
            const age = Math.max(0, Math.round(Date.now() / 1000 - (current.timestamp || 0)));
            const applied = current.applied_to_station ? 'station' : 'map';
            if (textEl) {
                textEl.textContent = `${current.source}: ${current.latitude.toFixed(5)}, ${current.longitude.toFixed(5)} (${applied}, ${age}s ago)`;
            }
            if (gps.enabled && gps.map_update_enabled) {
                window.pvMap?.setMyPosition(current.latitude, current.longitude, lastStatus?.station || 'GPS');
            }
            if (current.applied_to_station) {
                setVal('cfg-latitude', current.latitude.toFixed(5));
                setVal('cfg-longitude', current.longitude.toFixed(5));
                markSettingsDirty('GPS updated station latitude/longitude. Save to keep these coordinates after restart.');
            }
        } else if (textEl) {
            textEl.textContent = gps.source_status?.message || (gps.enabled ? 'Waiting for GPS fix' : 'Disabled');
        }
    }

    // ── Propagation updates ────────────────────────────────────

    function updatePropagation(data) {
        if (!data) return;

        // ── My Station meter (direct-heard only) ───────────
        const myScore = data.my_score || 0;
        const myLevel = data.my_level || 'none';
        const myBar = document.getElementById('prop-bar-my');
        if (myBar) {
            myBar.style.width = `${Math.min(myScore, 100)}%`;
            myBar.className = `prop-bar ${myLevel}`;
        }
        setTextById('prop-level-my', myLevel.toUpperCase());
        setTextById('prop-score-my', `Score: ${myScore.toFixed(0)}`);

        // ── Regional meter (all RF) ────────────────────────
        const score = data.score || 0;
        const level = data.level || 'none';
        const regBar = document.getElementById('prop-bar-reg');
        if (regBar) {
            regBar.style.width = `${Math.min(score, 100)}%`;
            regBar.className = `prop-bar ${level}`;
        }
        setTextById('prop-level-reg', level.toUpperCase());
        setTextById('prop-score-reg', `Score: ${score.toFixed(0)}`);

        // Header stats
        setTextById('rf-count-1h', data.rf_stations_1h || 0);
        setTextById('is-count-1h', data.is_stations_1h || 0);
        setTextById('max-distance', data.max_distance_km ? window.convertDist(data.max_distance_km).toFixed(0) : '0');

        // Propagation tab cards
        setTextById('prop-rf-1h', data.rf_stations_1h || 0);
        setTextById('prop-direct-1h', data.my_stations_1h || 0);
        setTextById('prop-rf-6h', data.rf_stations_6h || 0);
        setTextById('prop-rf-24h', data.rf_stations_24h || 0);
        setTextById('prop-max-dist', window.formatDist(data.max_distance_km || 0, 0));
        setTextById('prop-max-dist-direct', window.formatDist(data.my_max_distance_km || 0, 0));
        setTextById('prop-avg-dist', window.formatDist(data.avg_distance_km || 0, 0));
        setTextById('prop-is-1h', data.is_stations_1h || 0);

        // Draw distance distribution chart
        if (data.distances && data.distances.length > 0) {
            drawDistanceChart(data.distances);
        }
    }

    // ── Charts ─────────────────────────────────────────────────

    function drawDistanceChart(distances) {
        const canvas = document.getElementById('distance-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 15, bottom: 30, left: 45 };

        ctx.clearRect(0, 0, w, h);

        if (distances.length === 0) return;

        // Create histogram bins
        const maxDist = Math.max(...distances, 50);
        const binSize = Math.max(10, Math.ceil(maxDist / 15 / 10) * 10);
        const numBins = Math.ceil(maxDist / binSize) + 1;
        const bins = new Array(numBins).fill(0);

        distances.forEach(d => {
            const bin = Math.floor(d / binSize);
            if (bin < numBins) bins[bin]++;
        });

        const maxCount = Math.max(...bins, 1);
        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;
        const barW = chartW / numBins - 2;

        // Draw axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Draw bars
        bins.forEach((count, i) => {
            if (count === 0) return;
            const x = padding.left + (i * (chartW / numBins)) + 1;
            const barH = (count / maxCount) * chartH;
            const y = h - padding.bottom - barH;

            // Gradient by distance
            const dist = (i + 0.5) * binSize;
            let color;
            if (dist > 200) color = '#bc8cff';
            else if (dist > 100) color = '#3fb950';
            else if (dist > 50) color = '#d29922';
            else color = '#f85149';

            ctx.fillStyle = color;
            ctx.fillRect(x, y, barW, barH);

            // Count label
            if (count > 0) {
                ctx.fillStyle = '#e6edf3';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(count, x + barW / 2, y - 4);
            }
        });

        // X-axis labels
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        for (let i = 0; i <= numBins; i += Math.max(1, Math.floor(numBins / 6))) {
            const x = padding.left + (i * (chartW / numBins));
            const label = `${Math.round(window.convertDist(i * binSize))}`;
            ctx.fillText(label, x, h - padding.bottom + 14);
        }

        // Labels
        ctx.fillStyle = '#6e7681';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`Distance (${window.distLabel()})`, w / 2, h - 4);

        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Stations', 0, 0);
        ctx.restore();
    }

    function drawPropHistoryChart(history) {
        const canvas = document.getElementById('prop-history-chart');
        if (!canvas || !history || history.length === 0) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 15, bottom: 30, left: 45 };

        ctx.clearRect(0, 0, w, h);

        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;

        const counts = history.map(p => p.rf_station_count || 0);
        const maxCount = Math.max(...counts, 1);
        const times = history.map(p => p.timestamp);
        const minTime = Math.min(...times);
        const maxTime = Math.max(...times);
        const timeRange = maxTime - minTime || 1;

        // Draw axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Draw line chart for station count
        ctx.beginPath();
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2;
        history.forEach((point, i) => {
            const x = padding.left + ((point.timestamp - minTime) / timeRange) * chartW;
            const y = h - padding.bottom - ((point.rf_station_count || 0) / maxCount) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Fill area under curve
        ctx.lineTo(padding.left + chartW, h - padding.bottom);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.closePath();
        ctx.fillStyle = 'rgba(88, 166, 255, 0.1)';
        ctx.fill();

        // Draw max distance on secondary axis
        const maxDists = history.map(p => p.max_distance_km || 0);
        const maxDistVal = Math.max(...maxDists, 1);

        ctx.beginPath();
        ctx.strokeStyle = '#3fb950';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        history.forEach((point, i) => {
            const x = padding.left + ((point.timestamp - minTime) / timeRange) * chartW;
            const y = h - padding.bottom - ((point.max_distance_km || 0) / maxDistVal) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // X-axis time labels
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        const numLabels = 6;
        for (let i = 0; i <= numLabels; i++) {
            const t = minTime + (timeRange * i / numLabels);
            const x = padding.left + (chartW * i / numLabels);
            const d = new Date(t * 1000);
            ctx.fillText(d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), x, h - padding.bottom + 14);
        }

        // Legend
        ctx.fillStyle = '#58a6ff';
        ctx.fillRect(padding.left + 10, padding.top + 2, 12, 3);
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Stations', padding.left + 26, padding.top + 7);

        ctx.fillStyle = '#3fb950';
        ctx.fillRect(padding.left + 90, padding.top + 2, 12, 3);
        ctx.fillStyle = '#8b949e';
        ctx.fillText('Max Dist', padding.left + 106, padding.top + 7);
    }

    async function fetchPropagationHistory() {
        try {
            const resp = await fetch('/api/propagation/history?hours=24');
            const data = await resp.json();
            if (data.history) {
                drawPropHistoryChart(data.history);
            }
        } catch (e) {
            console.error('Failed to fetch propagation history:', e);
        }
    }

    // ── Uptime ─────────────────────────────────────────────────

    function updateUptime() {
        if (!uptimeStart) return;
        const seconds = Math.floor(Date.now() / 1000 - uptimeStart);
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        const str = `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        setTextById('footer-uptime', `Uptime: ${str}`);
    }

    // ── Helpers ────────────────────────────────────────────────

    function setTextById(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function showSystemNotification(message, type = 'info') {
        const div = document.createElement('div');
        div.className = `alert-notification system-notification ${type}`;
        const icon = type === 'error' ? '⚠️' : '📡';
        div.innerHTML = `<span class="alert-notif-icon">${icon}</span> ${_escapeHTML(message || '')}`;
        document.body.appendChild(div);
        setTimeout(() => { div.classList.add('fade-out'); }, 3200);
        setTimeout(() => { div.remove(); }, 3800);
    }

    function showBandAlertNotification(alert) {
        // Create a floating notification banner
        const div = document.createElement('div');
        div.className = 'alert-notification';
        const title = alert.type === 'my_station_opening' ? 'My Station Band Opening!' : 'Regional Band Watch';
        div.innerHTML = `<span class="alert-notif-icon">🚨</span> <b>${_escapeHTML(title)}</b> ` +
            `RF: ${alert.rf_stations ?? 0} stations · Max: ${window.formatDist(alert.max_distance_km || 0, 0)} · ` +
            `${_escapeHTML((alert.level || 'unknown').toUpperCase())}`;
        document.body.appendChild(div);
        // Auto-dismiss after 15 seconds
        setTimeout(() => { div.classList.add('fade-out'); }, 12000);
        setTimeout(() => { div.remove(); }, 15000);
    }

    async function refreshLiveData() {
        if (liveSyncPending) return;
        liveSyncPending = true;
        try {
            const [statusResp, stationsResp] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/stations/all?hours=0'),
            ]);
            if (statusResp.ok) handleStatus(await statusResp.json());
            if (stationsResp.ok) {
                const data = await stationsResp.json();
                window.pvStations?.syncStations(data.rf || [], data.aprs_is || []);
            }
        } catch (e) {
            console.error('Failed to refresh live data:', e);
        } finally {
            liveSyncPending = false;
        }
    }

    // ── About info ──────────────────────────────────────────────

    async function loadAboutInfo() {
        try {
            const resp = await fetch('/api/version');
            const data = await resp.json();
            const v = data.version || '1.0.0';
            const el1 = document.getElementById('about-version');
            const el2 = document.getElementById('about-version-detail');
            if (el1) el1.textContent = 'v' + v;
            if (el2) el2.textContent = v;
        } catch (e) { /* keep static defaults */ }

        await loadUpdateStatus();
    }

    function initUpdateCheckerUi() {
        const btn = document.getElementById('btn-check-updates');
        if (btn) {
            btn.addEventListener('click', () => {
                loadUpdateStatus(true);
            });
        }

        document.getElementById('update-alert-close')?.addEventListener('click', () => {
            dismissUpdateBanner();
        });
    }

    function dismissUpdateBanner() {
        const banner = document.getElementById('update-alert-banner');
        const latestVersion = banner?.dataset.latestVersion;
        if (latestVersion) {
            localStorage.setItem(`${UPDATE_BANNER_DISMISS_KEY}:${latestVersion}`, '1');
        }
        if (banner) {
            banner.style.display = 'none';
        }
    }

    function syncUpdateBanner(data) {
        const banner = document.getElementById('update-alert-banner');
        const textEl = document.getElementById('update-alert-text');
        const linkEl = document.getElementById('update-alert-link');
        if (!banner || !textEl || !linkEl) return;

        if (!data?.update_available) {
            banner.style.display = 'none';
            banner.dataset.latestVersion = '';
            return;
        }

        const latestVersion = data.latest_version || '';
        if (latestVersion && localStorage.getItem(`${UPDATE_BANNER_DISMISS_KEY}:${latestVersion}`) === '1') {
            banner.style.display = 'none';
            banner.dataset.latestVersion = latestVersion;
            return;
        }

        banner.dataset.latestVersion = latestVersion;
        textEl.textContent = `A newer APRS PropView release is available: v${latestVersion}.`;
        linkEl.href = data.release_url || 'https://github.com/RF-YVY/APRS-PropView/releases';
        banner.style.display = 'flex';
    }

    async function loadUpdateStatus(force) {
        if (updateCheckPending) return;
        updateCheckPending = true;

        const messageEl = document.getElementById('about-update-message');
        const detailEl = document.getElementById('about-update-detail');
        const linkEl = document.getElementById('about-update-link');
        const footerEl = document.getElementById('footer-update');
        const buttonEl = document.getElementById('btn-check-updates');

        if (buttonEl) buttonEl.disabled = true;
        if (messageEl && force) messageEl.textContent = 'Checking GitHub releases...';
        if (detailEl && force) detailEl.textContent = '';

        try {
            const url = force ? '/api/update-status?force=true' : '/api/update-status';
            const resp = await fetch(url);
            if (!resp.ok) {
                throw new Error(`Update check failed with HTTP ${resp.status}`);
            }
            const data = await resp.json();
            renderUpdateStatus(data, { messageEl, detailEl, linkEl, footerEl });
        } catch (e) {
            console.error('Failed to check for updates:', e);
            if (messageEl) messageEl.textContent = 'Could not check for updates right now.';
            if (detailEl) detailEl.textContent = 'Open the GitHub releases page to verify manually.';
            if (footerEl) footerEl.style.display = 'none';
            syncUpdateBanner(null);
        } finally {
            if (buttonEl) buttonEl.disabled = false;
            updateCheckPending = false;
        }
    }

    function renderUpdateStatus(data, els) {
        const { messageEl, detailEl, linkEl, footerEl } = els;
        const currentVersion = data?.current_version || '1.5.2';
        const latestVersion = data?.latest_version || currentVersion;
        const releaseUrl = data?.release_url || 'https://github.com/RF-YVY/APRS-PropView/releases';
        const publishedAt = data?.published_at ? formatReleaseDate(data.published_at) : '';

        if (linkEl) linkEl.href = releaseUrl;
        syncUpdateBanner(data);

        if (data?.update_available) {
            if (messageEl) messageEl.textContent = `Update available: v${latestVersion}`;
            if (detailEl) {
                detailEl.textContent = publishedAt
                    ? `You are running v${currentVersion}. GitHub shows v${latestVersion}, published ${publishedAt}.`
                    : `You are running v${currentVersion}. GitHub shows v${latestVersion}.`;
            }
            if (footerEl) {
                footerEl.style.display = 'inline-flex';
                footerEl.textContent = `Update available: v${latestVersion}`;
                footerEl.classList.add('is-available');
            }
            return;
        }

        if (data?.current_is_newer_than_release) {
            if (messageEl) messageEl.textContent = 'You are on the newest version.';
            if (detailEl) {
                detailEl.textContent = publishedAt
                    ? `You are running v${currentVersion}. The newest published release is v${latestVersion}, from ${publishedAt}.`
                    : `You are running v${currentVersion}. The newest published release is v${latestVersion}.`;
            }
            if (footerEl) {
                footerEl.style.display = 'none';
                footerEl.textContent = '';
                footerEl.classList.remove('is-available');
            }
            return;
        }

        if (messageEl) {
            messageEl.textContent = data?.error
                ? 'Could not check for updates right now.'
                : 'You are on the newest version.';
        }
        if (detailEl) {
            if (data?.error) {
                detailEl.textContent = data.message || 'Open the GitHub releases page to verify manually.';
            } else if (publishedAt) {
                detailEl.textContent = `Latest release checked: v${latestVersion}, published ${publishedAt}.`;
            } else {
                detailEl.textContent = `Latest release checked: v${latestVersion}.`;
            }
        }
        if (footerEl) {
            footerEl.style.display = 'none';
            footerEl.textContent = '';
            footerEl.classList.remove('is-available');
        }
    }

    function formatReleaseDate(value) {
        try {
            return new Date(value).toLocaleDateString([], {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
            });
        } catch {
            return value;
        }
    }

    // ── Font management ──────────────────────────────────────────

    function applyFont(fontFamily) {
        if (fontFamily) {
            document.documentElement.style.setProperty('--font-family', fontFamily);
        } else {
            document.documentElement.style.removeProperty('--font-family');
        }
    }

    function initGpsControls() {
        document.getElementById('cfg-gps-source')?.addEventListener('change', updateGpsSourceVisibility);
        document.getElementById('btn-gps-browser')?.addEventListener('click', toggleBrowserGps);
        updateGpsSourceVisibility();
    }

    function updateGpsSourceVisibility() {
        const source = getVal('cfg-gps-source') || 'browser';
        document.querySelectorAll('.gps-source-setting').forEach(row => {
            row.classList.toggle('visible', row.classList.contains(`gps-source-${source}`));
        });
        const browserCapable = source === 'browser' || source === 'any';
        const btn = document.getElementById('btn-gps-browser');
        if (btn) {
            btn.disabled = !browserCapable;
            btn.title = getGpsBrowserButtonTitle(source, browserCapable);
            if (!browserCapable) btn.textContent = getGpsSourceButtonText(source);
            else if (gpsWatchId === null) btn.textContent = getGpsBrowserStartText(source);
            else btn.textContent = getGpsBrowserStopText(source);
        }
        if (!browserCapable && gpsWatchId !== null) {
            navigator.geolocation.clearWatch(gpsWatchId);
            gpsWatchId = null;
            const textEl = document.getElementById('gps-status-text');
            if (textEl) textEl.textContent = 'Browser GPS stopped; selected source is waiting for its own input.';
        }
    }

    function getGpsBrowserStartText(source) {
        return source === 'any' ? 'Start Browser GPS' : 'Start GPS';
    }

    function getGpsBrowserStopText(source) {
        return source === 'any' ? 'Stop Browser GPS' : 'Stop GPS';
    }

    function getGpsSourceButtonText(source) {
        const labels = {
            self_packet: 'Using APRS packets',
            nmea_serial: 'Using NMEA serial',
            nmea_tcp: 'Using NMEA TCP',
            nmea_udp: 'Using NMEA UDP',
        };
        return labels[source] || 'Browser GPS unavailable';
    }

    function getGpsBrowserButtonTitle(source, browserCapable) {
        if (browserCapable) return 'Start or stop this browser/device location sharing';
        const titles = {
            self_packet: 'This source uses your own APRS position packets.',
            nmea_serial: 'This source reads from the configured NMEA serial GPS port.',
            nmea_tcp: 'This source reads from the configured NMEA TCP stream.',
            nmea_udp: 'This source listens for NMEA UDP sentences on the configured port.',
        };
        return titles[source] || 'Select Browser or Any Source to use browser/device location.';
    }

    function initSettingsDirtyTracking() {
        const panel = document.querySelector('.settings-panel');
        if (!panel) return;

        panel.addEventListener('input', (e) => {
            if (isSettingsControl(e.target)) markSettingsDirty();
        });
        panel.addEventListener('change', (e) => {
            if (isSettingsControl(e.target)) markSettingsDirty();
        });
    }

    function isSettingsControl(el) {
        return !!(
            el &&
            el.id &&
            el.id.startsWith('cfg-') &&
            el.id !== 'cfg-is-filter'
        );
    }

    function markSettingsDirty(message) {
        if (settingsLoading) return;
        settingsDirty = true;
        const statusEl = document.getElementById('settings-status');
        document.querySelectorAll('.btn-save-settings').forEach((btn) => btn.classList.add('dirty'));
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.className = 'settings-status warning dirty';
            statusEl.textContent = message || 'Unsaved settings. Save Configuration to apply these changes and keep them after restart.';
        }
    }

    function defaultRfPort(type) {
        const normalized = type === 'tcp' ? 'tcp' : 'serial';
        if (normalized === 'tcp') {
            return {
                name: 'KISS TCP 127.0.0.1:8001',
                enabled: true,
                type: 'tcp',
                host: '127.0.0.1',
                tcp_port: 8001,
                mode: 'kiss',
            };
        }
        return {
            name: 'KISS Serial COM3',
            enabled: true,
            type: 'serial',
            port: 'COM3',
            baudrate: 9600,
            mode: 'kiss',
            flow_control: 'none',
            init_profile: 'none',
            init_commands: '',
        };
    }

    function rfPortsFromConfig(cfg) {
        if (Array.isArray(cfg?.rf_ports) && cfg.rf_ports.length) {
            return cfg.rf_ports.map((port) => ({ ...defaultRfPort(port.type), ...port }));
        }

        const ports = [];
        if (cfg?.kiss_serial?.enabled) {
            ports.push({
                ...defaultRfPort('serial'),
                name: `KISS Serial ${cfg.kiss_serial.port || 'COM3'}`,
                port: cfg.kiss_serial.port || 'COM3',
                baudrate: cfg.kiss_serial.baudrate || 9600,
                mode: cfg.kiss_serial.mode || 'kiss',
                flow_control: cfg.kiss_serial.flow_control || 'none',
                init_profile: cfg.kiss_serial.init_profile || 'none',
                init_commands: cfg.kiss_serial.init_commands || '',
            });
        }
        if (cfg?.kiss_tcp?.enabled) {
            ports.push({
                ...defaultRfPort('tcp'),
                name: `KISS TCP ${cfg.kiss_tcp.host || '127.0.0.1'}:${cfg.kiss_tcp.port || 8001}`,
                host: cfg.kiss_tcp.host || '127.0.0.1',
                tcp_port: cfg.kiss_tcp.port || 8001,
            });
        }
        return ports;
    }

    function initRfPortsControls() {
        const list = document.getElementById('cfg-rf-ports-list');
        list?.addEventListener('input', (e) => {
            if (e.target?.classList?.contains('rf-port-field')) markSettingsDirty();
        });
        list?.addEventListener('change', (e) => {
            if (e.target?.classList?.contains('rf-port-field')) markSettingsDirty();
        });
        document.getElementById('btn-rf-port-add-serial')?.addEventListener('click', () => {
            const ports = collectRfPorts();
            ports.push(defaultRfPort('serial'));
            renderRfPorts(ports);
            markSettingsDirty();
        });
        document.getElementById('btn-rf-port-add-tcp')?.addEventListener('click', () => {
            const ports = collectRfPorts();
            ports.push(defaultRfPort('tcp'));
            renderRfPorts(ports);
            markSettingsDirty();
        });
    }

    function renderRfPorts(ports) {
        const list = document.getElementById('cfg-rf-ports-list');
        if (!list) return;
        const items = Array.isArray(ports) ? ports : [];
        if (!items.length) {
            list.innerHTML = '<div class="rf-ports-empty">No RF ports configured.</div>';
            return;
        }

        list.innerHTML = items.map((rawPort, index) => {
            const port = { ...defaultRfPort(rawPort.type), ...rawPort };
            const type = port.type === 'tcp' ? 'tcp' : 'serial';
            const name = port.name || (type === 'tcp' ? `KISS TCP ${port.host}:${port.tcp_port}` : `KISS Serial ${port.port}`);
            return `
                <div class="rf-port-card" data-rf-port-index="${index}">
                    <div class="rf-port-card-header">
                        <label class="rf-port-enabled">
                            <input type="checkbox" class="rf-port-field" data-field="enabled" ${port.enabled ? 'checked' : ''}>
                            <span>${_escapeHTML(name)}</span>
                        </label>
                        <button type="button" class="settings-toolbar-btn rf-port-remove">Remove</button>
                    </div>
                    <div class="rf-port-fields">
                        <div class="settings-row">
                            <label>Name</label>
                            <input type="text" class="rf-port-field" data-field="name" value="${_escapeHTML(name)}" maxlength="40">
                        </div>
                        <div class="settings-row">
                            <label>Type</label>
                            <select class="rf-port-field" data-field="type">
                                <option value="serial" ${type === 'serial' ? 'selected' : ''}>${RF_PORT_TYPES.serial}</option>
                                <option value="tcp" ${type === 'tcp' ? 'selected' : ''}>${RF_PORT_TYPES.tcp}</option>
                            </select>
                        </div>
                        ${type === 'tcp' ? rfPortTcpFields(port) : rfPortSerialFields(port)}
                    </div>
                </div>
            `;
        }).join('');

        list.querySelectorAll('.rf-port-remove').forEach((btn) => {
            btn.addEventListener('click', () => {
                const card = btn.closest('.rf-port-card');
                const index = parseInt(card?.dataset.rfPortIndex || '-1', 10);
                const ports = collectRfPorts();
                ports.splice(index, 1);
                renderRfPorts(ports);
                markSettingsDirty();
            });
        });
        list.querySelectorAll('[data-field="type"]').forEach((select) => {
            select.addEventListener('change', () => {
                const ports = collectRfPorts();
                renderRfPorts(ports.map((port) => ({ ...defaultRfPort(port.type), ...port })));
                markSettingsDirty();
            });
        });
    }

    function rfPortSerialFields(port) {
        return `
            <div class="settings-row">
                <label>Serial Port</label>
                <input type="text" class="rf-port-field" data-field="port" value="${_escapeHTML(port.port || 'COM3')}">
            </div>
            <div class="settings-row">
                <label>Baudrate</label>
                <input type="number" class="rf-port-field" data-field="baudrate" value="${parseInt(port.baudrate, 10) || 9600}" min="300" max="921600">
            </div>
            <div class="settings-row">
                <label>Mode</label>
                <select class="rf-port-field" data-field="mode">
                    <option value="kiss" ${(port.mode || 'kiss') === 'kiss' ? 'selected' : ''}>KISS frames</option>
                    <option value="tnc2_monitor" ${port.mode === 'tnc2_monitor' ? 'selected' : ''}>TNC2 monitor text</option>
                </select>
            </div>
            <div class="settings-row">
                <label>Flow control</label>
                <select class="rf-port-field" data-field="flow_control">
                    <option value="none" ${(port.flow_control || 'none') === 'none' ? 'selected' : ''}>None</option>
                    <option value="xonxoff" ${port.flow_control === 'xonxoff' ? 'selected' : ''}>Xon/Xoff</option>
                    <option value="rtscts" ${port.flow_control === 'rtscts' ? 'selected' : ''}>RTS/CTS</option>
                    <option value="dsrdtr" ${port.flow_control === 'dsrdtr' ? 'selected' : ''}>DSR/DTR</option>
                </select>
            </div>
            <div class="settings-row">
                <label>Radio/TNC profile</label>
                <select class="rf-port-field" data-field="init_profile">
                    <option value="none" ${(port.init_profile || 'none') === 'none' ? 'selected' : ''}>Generic / already configured</option>
                    <option value="kenwood_thd7" ${port.init_profile === 'kenwood_thd7' ? 'selected' : ''}>Kenwood TH-D7 / TH-D7E</option>
                    <option value="kenwood_tmd700" ${port.init_profile === 'kenwood_tmd700' ? 'selected' : ''}>Kenwood TM-D700</option>
                    <option value="kenwood_thd72" ${port.init_profile === 'kenwood_thd72' ? 'selected' : ''}>Kenwood TH-D72</option>
                    <option value="generic_tnc2_kiss" ${port.init_profile === 'generic_tnc2_kiss' ? 'selected' : ''}>Generic TNC2 KISS startup</option>
                </select>
            </div>
            <div class="settings-row settings-row-stacked rf-port-init-row">
                <label>Extra init commands</label>
                <textarea class="rf-port-field" data-field="init_commands" rows="3">${_escapeHTML(port.init_commands || '')}</textarea>
            </div>
        `;
    }

    function rfPortTcpFields(port) {
        return `
            <div class="settings-row">
                <label>Host</label>
                <input type="text" class="rf-port-field" data-field="host" value="${_escapeHTML(port.host || '127.0.0.1')}">
            </div>
            <div class="settings-row">
                <label>TCP Port</label>
                <input type="number" class="rf-port-field" data-field="tcp_port" value="${parseInt(port.tcp_port, 10) || 8001}" min="1" max="65535">
            </div>
        `;
    }

    function collectRfPorts() {
        return Array.from(document.querySelectorAll('#cfg-rf-ports-list .rf-port-card')).map((card) => {
            const field = (name) => card.querySelector(`.rf-port-field[data-field="${name}"]`);
            const type = field('type')?.value === 'tcp' ? 'tcp' : 'serial';
            const enabled = !!field('enabled')?.checked;
            const name = (field('name')?.value || '').trim();
            if (type === 'tcp') {
                return {
                    name,
                    enabled,
                    type,
                    host: (field('host')?.value || '127.0.0.1').trim(),
                    tcp_port: parseInt(field('tcp_port')?.value, 10) || 8001,
                };
            }
            return {
                name,
                enabled,
                type,
                port: (field('port')?.value || 'COM3').trim(),
                baudrate: parseInt(field('baudrate')?.value, 10) || 9600,
                mode: field('mode')?.value || 'kiss',
                flow_control: field('flow_control')?.value || 'none',
                init_profile: field('init_profile')?.value || 'none',
                init_commands: field('init_commands')?.value || '',
            };
        });
    }

    function clearSettingsDirty() {
        settingsDirty = false;
        document.querySelectorAll('.btn-save-settings').forEach((btn) => btn.classList.remove('dirty'));
    }

    function toggleBrowserGps() {
        if (gpsWatchId !== null) {
            navigator.geolocation.clearWatch(gpsWatchId);
            gpsWatchId = null;
            const btn = document.getElementById('btn-gps-browser');
            if (btn) btn.textContent = getGpsBrowserStartText(getVal('cfg-gps-source') || 'browser');
            const textEl = document.getElementById('gps-status-text');
            if (textEl) textEl.textContent = 'Browser GPS stopped';
            return;
        }

        if (!navigator.geolocation) {
            showSystemNotification('This browser does not support geolocation.', 'error');
            return;
        }

        gpsWatchId = navigator.geolocation.watchPosition(
            async (position) => {
                const now = Date.now();
                if (now - lastGpsPost < 5000) return;
                lastGpsPost = now;
                try {
                    const resp = await fetch('/api/gps/location', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            source: 'browser',
                            latitude: position.coords.latitude,
                            longitude: position.coords.longitude,
                            accuracy_m: position.coords.accuracy,
                            map_update_enabled: getChk('cfg-gps-map-update'),
                            update_station_position: getVal('cfg-gps-update-station') === 'true',
                            station_position_locked: getChk('cfg-gps-position-locked'),
                        }),
                    });
                    const result = await resp.json();
                    if (!resp.ok || !result.success) {
                        throw new Error(result.message || 'GPS update rejected.');
                    }
                    handleGpsStatus(result.gps);
                } catch (e) {
                    const textEl = document.getElementById('gps-status-text');
                    if (textEl) textEl.textContent = e.message || 'GPS update failed';
                }
            },
            (error) => {
                const textEl = document.getElementById('gps-status-text');
                if (textEl) textEl.textContent = error.message || 'GPS permission denied';
                showSystemNotification(error.message || 'GPS permission denied.', 'error');
            },
            { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
        );

        const btn = document.getElementById('btn-gps-browser');
        if (btn) btn.textContent = getGpsBrowserStopText(getVal('cfg-gps-source') || 'browser');
    }

    // Apply saved font on initial load
    (async function initFont() {
        try {
            const cfg = await loadConfig(false);
            applyFont(cfg.web?.font_family || '');
            window._ghostMinutes = cfg.web?.ghost_after_minutes ?? 60;
            window._expireMinutes = cfg.web?.expire_after_minutes ?? 0;
        } catch (e) { /* use default */ }
    })();

    // ── Settings load/save ─────────────────────────────────────

    async function loadSettings() {
        settingsLoading = true;
        try {
            const cfg = await loadConfig(true);

            // Station
            setVal('cfg-callsign', cfg.station?.callsign);
            setVal('cfg-ssid', cfg.station?.ssid);
            setVal('cfg-latitude', cfg.station?.latitude);
            setVal('cfg-longitude', cfg.station?.longitude);
            setVal('cfg-symbol-table', cfg.station?.symbol_table);
            setVal('cfg-symbol-code', cfg.station?.symbol_code);
            setVal('cfg-phg', cfg.station?.phg || '');
            setVal('cfg-equipment', cfg.station?.equipment || '');
            setVal('cfg-comment', cfg.station?.comment);
            setVal('cfg-beacon-interval', Math.round((cfg.station?.beacon_interval || 0) / 60));
            setVal('cfg-beacon-path', cfg.station?.beacon_path || 'WIDE1-1');

            // GPS
            setChk('cfg-gps-enabled', cfg.gps?.enabled);
            setVal('cfg-gps-source', cfg.gps?.source || 'browser');
            setVal('cfg-gps-update-station', String(!!cfg.gps?.update_station_position));
            setChk('cfg-gps-map-update', cfg.gps?.map_update_enabled ?? true);
            setChk('cfg-gps-position-locked', cfg.gps?.station_position_locked ?? true);
            setVal('cfg-gps-serial-port', cfg.gps?.serial_port || 'COM4');
            setVal('cfg-gps-serial-baud', cfg.gps?.serial_baudrate || 9600);
            setVal('cfg-gps-tcp-host', cfg.gps?.tcp_host || '127.0.0.1');
            setVal('cfg-gps-tcp-port', cfg.gps?.tcp_port || 10110);
            setVal('cfg-gps-udp-host', cfg.gps?.udp_host || '0.0.0.0');
            setVal('cfg-gps-udp-port', cfg.gps?.udp_port || 10110);
            updateGpsSourceVisibility();

            // Digipeater
            setChk('cfg-digi-enabled', cfg.digipeater?.enabled);
            setVal('cfg-digi-aliases', (cfg.digipeater?.aliases || []).join(', '));
            setVal('cfg-digi-dedupe', parseFloat(((cfg.digipeater?.dedupe_interval || 0) / 60).toFixed(1)));

            // IGate
            setChk('cfg-igate-enabled', cfg.igate?.enabled);
            setChk('cfg-igate-rf2is', cfg.igate?.rf_to_is);
            setChk('cfg-igate-is2rf', cfg.igate?.is_to_rf);

            // APRS-IS
            setChk('cfg-is-enabled', cfg.aprs_is?.enabled);
            setVal('cfg-is-server', cfg.aprs_is?.server);
            setVal('cfg-is-port', cfg.aprs_is?.port);
            setVal('cfg-is-passcode', cfg.aprs_is?.passcode);
            parseFilterIntoFields(cfg.aprs_is?.filter || '');

            // KISS Serial
            setChk('cfg-ks-enabled', cfg.kiss_serial?.enabled);
            setVal('cfg-ks-mode', cfg.kiss_serial?.mode || 'kiss');
            setVal('cfg-ks-profile', cfg.kiss_serial?.init_profile || 'none');
            setVal('cfg-ks-port', cfg.kiss_serial?.port);
            setVal('cfg-ks-baud', cfg.kiss_serial?.baudrate);
            setVal('cfg-ks-flow', cfg.kiss_serial?.flow_control || 'none');
            setVal('cfg-ks-init', cfg.kiss_serial?.init_commands || '');

            // KISS TCP
            setChk('cfg-kt-enabled', cfg.kiss_tcp?.enabled);
            setVal('cfg-kt-host', cfg.kiss_tcp?.host);
            setVal('cfg-kt-port', cfg.kiss_tcp?.port);
            renderRfPorts(rfPortsFromConfig(cfg));

            // Web
            setVal('cfg-web-host', cfg.web?.host);
            setVal('cfg-web-port', cfg.web?.port);
            setVal('cfg-web-font', cfg.web?.font_family || '');
            setVal('cfg-ui-theme', getUITheme());
            applyUITheme(getUITheme());
            applyFont(cfg.web?.font_family || '');
            setVal('cfg-map-tile-source', cfg.web?.map_tile_source || 'osm');
            setVal('cfg-map-tile-url', cfg.web?.map_tile_url || '');
            setVal('cfg-map-tile-attribution', cfg.web?.map_tile_attribution || '');
            setVal('cfg-map-tile-max-zoom', cfg.web?.map_tile_max_zoom ?? 19);
            window.pvMap?.setMapTileConfig(cfg.web || {});
            setVal('cfg-web-ghost', cfg.web?.ghost_after_minutes ?? 60);
            window._ghostMinutes = cfg.web?.ghost_after_minutes ?? 60;
            window.pvMap?.ghostStaleMarkers(window._ghostMinutes);
            setVal('cfg-web-expire', cfg.web?.expire_after_minutes ?? 0);
            setVal('cfg-web-pin', cfg.web?.mobile_pin || '');
            setChk('cfg-web-update-check-enabled', cfg.web?.update_check_enabled ?? true);
            setVal('cfg-web-update-check-hours', cfg.web?.update_check_interval_hours ?? 24);
            window._expireMinutes = cfg.web?.expire_after_minutes ?? 0;

            // Tracking
            setVal('cfg-track-age', Math.round((cfg.tracking?.max_station_age || 0) / 60));
            setVal('cfg-track-cleanup', Math.round((cfg.tracking?.cleanup_interval || 0) / 60));
            setVal('cfg-msg-retention', cfg.messaging?.message_retention_days ?? 30);

            setChk('cfg-status-enabled', cfg.status?.enabled);
            setVal('cfg-status-interval', Math.round((cfg.status?.beacon_interval || 1800) / 60));
            setVal('cfg-status-window', cfg.status?.report_window_minutes ?? 60);
            setVal('cfg-status-max-length', cfg.status?.max_length ?? 67);
            setVal('cfg-status-mode', cfg.status?.mode || 'both');
            setVal('cfg-status-path', cfg.status?.path || 'WIDE1-1');
            refreshStatusDxPreview();

            setChk('cfg-wxnow-enabled', cfg.wxnow?.enabled);
            setVal('cfg-wxnow-file', cfg.wxnow?.file_path || '');
            setVal('cfg-wxnow-ssid', cfg.wxnow?.ssid ?? 13);
            setVal('cfg-wxnow-interval', Math.round((cfg.wxnow?.beacon_interval || 600) / 60));
            setVal('cfg-wxnow-max-age', cfg.wxnow?.max_age_minutes ?? 15);
            setVal('cfg-wxnow-mode', cfg.wxnow?.mode || 'both');
            setVal('cfg-wxnow-path', cfg.wxnow?.path || 'WIDE1-1');
            setVal('cfg-wxnow-position', String(cfg.wxnow?.include_position ?? true));
            refreshWxNowStatus();

            // Alerts
            setChk('cfg-alerts-enabled', cfg.alerts?.enabled);
            setChk('cfg-alerts-anomaly-enabled', cfg.alerts?.anomaly_alert_enabled ?? true);
            setChk('cfg-alerts-es-enabled', cfg.alerts?.sporadic_e_alert_enabled ?? true);
            setVal('cfg-alerts-my-min-stations', cfg.alerts?.my_min_stations);
            setVal('cfg-alerts-my-min-dist', Math.round(window.distToDisplay(cfg.alerts?.my_min_distance_km || 0)));
            setVal('cfg-alerts-reg-min-stations', cfg.alerts?.regional_min_stations);
            setVal('cfg-alerts-reg-min-dist', Math.round(window.distToDisplay(cfg.alerts?.regional_min_distance_km || 0)));
            setVal('cfg-alerts-cooldown', Math.round((cfg.alerts?.cooldown_seconds || 0) / 60));
            setVal('cfg-alerts-quiet-start', cfg.alerts?.quiet_start || '');
            setVal('cfg-alerts-quiet-end', cfg.alerts?.quiet_end || '');
            setVal('cfg-alerts-audio-device', cfg.alerts?.audio_output_device_id || '');
            refreshAudioOutputDevices(cfg.alerts?.audio_output_device_id || '');
            ALERT_AUDIO_SLOTS.forEach(([key]) => {
                setAlertAudioSlot(key, cfg.alerts?.[ALERT_AUDIO_FIELD_BY_KEY[key]] || '');
            });

            // Propagation meters
            setVal('cfg-prop-my-count', cfg.propagation?.my_station_full_count ?? 10);
            setVal('cfg-prop-my-dist', Math.round(window.distToDisplay(cfg.propagation?.my_station_full_dist_km || 200)));
            setVal('cfg-prop-reg-count', cfg.propagation?.regional_full_count ?? 10);
            setVal('cfg-prop-reg-dist', Math.round(window.distToDisplay(cfg.propagation?.regional_full_dist_km || 200)));
            setChk('cfg-alerts-msg-discord', cfg.alerts?.msg_discord_enabled);
            setChk('cfg-alerts-msg-email', cfg.alerts?.msg_email_enabled);
            setChk('cfg-alerts-msg-sms', cfg.alerts?.msg_sms_enabled);
            setChk('cfg-alerts-discord', cfg.alerts?.discord_enabled);
            setVal('cfg-alerts-discord-url', cfg.alerts?.discord_webhook_url);
            setChk('cfg-alerts-email', cfg.alerts?.email_enabled);
            setVal('cfg-alerts-smtp', cfg.alerts?.email_smtp_server);
            setVal('cfg-alerts-smtp-port', cfg.alerts?.email_smtp_port);
            setVal('cfg-alerts-email-from', cfg.alerts?.email_from);
            setVal('cfg-alerts-email-to', cfg.alerts?.email_to);
            setVal('cfg-alerts-email-pw', cfg.alerts?.email_password);
            setChk('cfg-alerts-sms', cfg.alerts?.sms_enabled);
            setVal('cfg-alerts-sms-addr', cfg.alerts?.sms_gateway_address);

            // Weather
            setChk('cfg-wx-enabled', cfg.weather?.enabled);
            setVal('cfg-wx-location', cfg.weather?.location_code);
            setVal('cfg-wx-current-provider', cfg.weather?.current_provider || 'open_meteo');
            setVal('cfg-wx-alert-provider', normalizeWeatherAlertProvider(cfg.weather?.alert_provider || 'auto'));
            setVal('cfg-wx-weatherbit-key', cfg.weather?.weatherbit_api_key || '');
            setVal('cfg-wx-weatherbit-poll', cfg.weather?.weatherbit_poll_minutes ?? 30);
            setVal('cfg-wx-range', cfg.weather?.alert_range_miles);
            setVal('cfg-wx-refresh', cfg.weather?.refresh_minutes);
            setChk('cfg-wx-radar-enabled', cfg.weather?.radar_enabled);
            setVal('cfg-wx-radar-provider', cfg.weather?.radar_provider || 'rainviewer');
            setVal('cfg-wx-radar-opacity', cfg.weather?.radar_opacity ?? 0.55);
            setChk('cfg-wx-radar-animate', cfg.weather?.radar_animate ?? true);
            setChk('cfg-wx-alert-overlay-enabled', cfg.weather?.alert_overlay_enabled);
            setCheckboxGroupValues('cfg-wx-alert-group', cfg.weather?.alert_overlay_groups);
            setVal('cfg-wx-alert-scope-mode', cfg.weather?.alert_scope_mode || 'point');
            setVal('cfg-wx-alert-scope-zone', cfg.weather?.alert_scope_zone || '');
            setChk('cfg-wx-elevated-enabled', cfg.weather?.elevated_alert_polling_enabled);
            setVal('cfg-wx-elevated-seconds', cfg.weather?.elevated_alert_polling_seconds ?? 60);
            setVal('cfg-wx-elevated-cooldown', cfg.weather?.elevated_alert_cooldown_minutes ?? 15);
            setVal('cfg-wx-elevated-events', (cfg.weather?.elevated_trigger_events || []).join(', '));
            updateWeatherOverlayOpacityLabel();
            updateWeatherAlertGroupSummary();
            updateWeatherProviderUi();
            updateWeatherAlertScopePreview();

            // MQTT
            setChk('cfg-mqtt-enabled', cfg.mqtt?.enabled);
            setVal('cfg-mqtt-broker', cfg.mqtt?.broker);
            setVal('cfg-mqtt-port', cfg.mqtt?.port);
            setVal('cfg-mqtt-topic', cfg.mqtt?.topic_prefix);
            setVal('cfg-mqtt-user', cfg.mqtt?.username);
            setVal('cfg-mqtt-pass', cfg.mqtt?.password);

        } catch (e) {
            console.error('Failed to load settings:', e);
        } finally {
            settingsLoading = false;
            clearSettingsDirty();
            const statusEl = document.getElementById('settings-status');
            if (statusEl && statusEl.classList.contains('dirty')) {
                statusEl.style.display = 'none';
            }
        }

        // Update icon picker preview with loaded symbol
        window.pvIconPicker.updatePreviewFromConfig();
    }

    async function saveSettings() {
        const buttons = Array.from(document.querySelectorAll('.btn-save-settings'));
        const statusEl = document.getElementById('settings-status');
        buttons.forEach((btn) => { btn.disabled = true; });

        const body = {
            station: {
                callsign: (getVal('cfg-callsign') || '').toUpperCase(),
                ssid: getVal('cfg-ssid'),
                latitude: getVal('cfg-latitude'),
                longitude: getVal('cfg-longitude'),
                symbol_table: getVal('cfg-symbol-table'),
                symbol_code: getVal('cfg-symbol-code'),
                phg: (getVal('cfg-phg') || '').toUpperCase(),
                equipment: getVal('cfg-equipment'),
                comment: getVal('cfg-comment'),
                beacon_interval: (parseInt(getVal('cfg-beacon-interval')) || 0) * 60,
                beacon_path: getVal('cfg-beacon-path'),
            },
            digipeater: {
                enabled: getChk('cfg-digi-enabled'),
                aliases: getVal('cfg-digi-aliases'),
                dedupe_interval: Math.round((parseFloat(getVal('cfg-digi-dedupe')) || 0) * 60),
            },
            igate: {
                enabled: getChk('cfg-igate-enabled'),
                rf_to_is: getChk('cfg-igate-rf2is'),
                is_to_rf: getChk('cfg-igate-is2rf'),
            },
            aprs_is: {
                enabled: getChk('cfg-is-enabled'),
                server: getVal('cfg-is-server'),
                port: getVal('cfg-is-port'),
                passcode: getVal('cfg-is-passcode'),
                filter: buildFilterString(),
            },
            kiss_serial: {
                enabled: getChk('cfg-ks-enabled'),
                mode: getVal('cfg-ks-mode') || 'kiss',
                init_profile: getVal('cfg-ks-profile') || 'none',
                port: getVal('cfg-ks-port'),
                baudrate: getVal('cfg-ks-baud'),
                flow_control: getVal('cfg-ks-flow') || 'none',
                init_commands: getVal('cfg-ks-init') || '',
            },
            kiss_tcp: {
                enabled: getChk('cfg-kt-enabled'),
                host: getVal('cfg-kt-host'),
                port: getVal('cfg-kt-port'),
            },
            rf_ports: collectRfPorts(),
            gps: {
                enabled: getChk('cfg-gps-enabled'),
                source: getVal('cfg-gps-source') || 'browser',
                map_update_enabled: getChk('cfg-gps-map-update'),
                update_station_position: getVal('cfg-gps-update-station') === 'true',
                station_position_locked: getChk('cfg-gps-position-locked'),
                serial_port: getVal('cfg-gps-serial-port') || 'COM4',
                serial_baudrate: parseInt(getVal('cfg-gps-serial-baud')) || 9600,
                tcp_host: getVal('cfg-gps-tcp-host') || '127.0.0.1',
                tcp_port: parseInt(getVal('cfg-gps-tcp-port')) || 10110,
                udp_host: getVal('cfg-gps-udp-host') || '0.0.0.0',
                udp_port: parseInt(getVal('cfg-gps-udp-port')) || 10110,
            },
            web: {
                host: getVal('cfg-web-host'),
                port: getVal('cfg-web-port'),
                font_family: getVal('cfg-web-font') || '',
                map_tile_source: getVal('cfg-map-tile-source') || 'osm',
                map_tile_url: getVal('cfg-map-tile-url') || '',
                map_tile_attribution: getVal('cfg-map-tile-attribution') || '',
                map_tile_max_zoom: parseInt(getVal('cfg-map-tile-max-zoom')) || 19,
                ghost_after_minutes: parseInt(getVal('cfg-web-ghost')) || 0,
                expire_after_minutes: parseInt(getVal('cfg-web-expire')) || 0,
                mobile_pin: getVal('cfg-web-pin') || '',
                update_check_enabled: getChk('cfg-web-update-check-enabled'),
                update_check_interval_hours: parseInt(getVal('cfg-web-update-check-hours')) || 24,
            },
            tracking: {
                max_station_age: (parseInt(getVal('cfg-track-age')) || 0) * 60,
                cleanup_interval: (parseInt(getVal('cfg-track-cleanup')) || 0) * 60,
            },
            messaging: {
                message_retention_days: parseInt(getVal('cfg-msg-retention')) || 30,
            },
            status: {
                enabled: getChk('cfg-status-enabled'),
                beacon_interval: (parseInt(getVal('cfg-status-interval')) || 30) * 60,
                mode: getVal('cfg-status-mode') || 'both',
                path: getVal('cfg-status-path') || '',
                report_window_minutes: parseInt(getVal('cfg-status-window')) || 60,
                max_length: parseInt(getVal('cfg-status-max-length')) || 67,
            },
            wxnow: {
                enabled: getChk('cfg-wxnow-enabled'),
                file_path: getVal('cfg-wxnow-file') || '',
                ssid: parseInt(getVal('cfg-wxnow-ssid')) || 13,
                beacon_interval: (parseInt(getVal('cfg-wxnow-interval')) || 10) * 60,
                max_age_minutes: parseInt(getVal('cfg-wxnow-max-age')) || 15,
                include_position: getVal('cfg-wxnow-position') !== 'false',
                mode: getVal('cfg-wxnow-mode') || 'both',
                path: getVal('cfg-wxnow-path') || '',
                symbol_table: '/',
                symbol_code: '_',
            },
            alerts: {
                enabled: getChk('cfg-alerts-enabled'),
                anomaly_alert_enabled: getChk('cfg-alerts-anomaly-enabled'),
                sporadic_e_alert_enabled: getChk('cfg-alerts-es-enabled'),
                my_min_stations: getVal('cfg-alerts-my-min-stations'),
                my_min_distance_km: Math.round(window.displayToDist(parseFloat(getVal('cfg-alerts-my-min-dist')) || 0)),
                regional_min_stations: getVal('cfg-alerts-reg-min-stations'),
                regional_min_distance_km: Math.round(window.displayToDist(parseFloat(getVal('cfg-alerts-reg-min-dist')) || 0)),
                cooldown_seconds: (parseInt(getVal('cfg-alerts-cooldown')) || 0) * 60,
                quiet_start: getVal('cfg-alerts-quiet-start') || '',
                quiet_end: getVal('cfg-alerts-quiet-end') || '',
                msg_notify_enabled: getChk('cfg-alerts-msg-discord') || getChk('cfg-alerts-msg-email') || getChk('cfg-alerts-msg-sms'),
                msg_discord_enabled: getChk('cfg-alerts-msg-discord'),
                msg_email_enabled: getChk('cfg-alerts-msg-email'),
                msg_sms_enabled: getChk('cfg-alerts-msg-sms'),
                audio_output_device_id: getVal('cfg-alerts-audio-device') || '',
                audio_my_station_opening_file: getVal('cfg-alerts-audio-value-my_station_opening') || '',
                audio_regional_watch_file: getVal('cfg-alerts-audio-value-regional_watch') || '',
                audio_first_heard_file: getVal('cfg-alerts-audio-value-first_heard') || '',
                audio_anomaly_file: getVal('cfg-alerts-audio-value-anomaly') || '',
                audio_sporadic_e_file: getVal('cfg-alerts-audio-value-sporadic_e') || '',
                audio_message_received_file: getVal('cfg-alerts-audio-value-message_received') || '',
                audio_weather_warning_file: getVal('cfg-alerts-audio-value-weather_warning') || '',
                audio_weather_watch_file: getVal('cfg-alerts-audio-value-weather_watch') || '',
                discord_enabled: getChk('cfg-alerts-discord'),
                discord_webhook_url: getVal('cfg-alerts-discord-url'),
                email_enabled: getChk('cfg-alerts-email'),
                email_smtp_server: getVal('cfg-alerts-smtp'),
                email_smtp_port: getVal('cfg-alerts-smtp-port'),
                email_from: getVal('cfg-alerts-email-from'),
                email_to: getVal('cfg-alerts-email-to'),
                email_password: getVal('cfg-alerts-email-pw'),
                sms_enabled: getChk('cfg-alerts-sms'),
                sms_gateway_address: getVal('cfg-alerts-sms-addr'),
            },
            weather: {
                enabled: getChk('cfg-wx-enabled'),
                location_code: getVal('cfg-wx-location'),
                current_provider: getVal('cfg-wx-current-provider') || 'open_meteo',
                alert_provider: normalizeWeatherAlertProvider(getVal('cfg-wx-alert-provider') || 'auto'),
                weatherbit_api_key: getVal('cfg-wx-weatherbit-key') || '',
                weatherbit_poll_minutes: parseInt(getVal('cfg-wx-weatherbit-poll')) || 30,
                alert_range_miles: getVal('cfg-wx-range'),
                refresh_minutes: getVal('cfg-wx-refresh'),
                radar_enabled: getChk('cfg-wx-radar-enabled'),
                radar_provider: getVal('cfg-wx-radar-provider') || 'rainviewer',
                radar_opacity: parseFloat(getVal('cfg-wx-radar-opacity')) || 0.55,
                radar_animate: getChk('cfg-wx-radar-animate'),
                alert_overlay_enabled: getChk('cfg-wx-alert-overlay-enabled'),
                alert_overlay_groups: getCheckboxGroupValues('cfg-wx-alert-group'),
                alert_scope_mode: getVal('cfg-wx-alert-scope-mode') || 'point',
                alert_scope_zone: getVal('cfg-wx-alert-scope-zone'),
                elevated_alert_polling_enabled: getChk('cfg-wx-elevated-enabled'),
                elevated_alert_polling_seconds: parseInt(getVal('cfg-wx-elevated-seconds')) || 60,
                elevated_alert_cooldown_minutes: parseInt(getVal('cfg-wx-elevated-cooldown')) || 15,
                elevated_trigger_events: parseCsvList(getVal('cfg-wx-elevated-events')),
            },
            propagation: {
                my_station_full_count: parseInt(getVal('cfg-prop-my-count')) || 10,
                my_station_full_dist_km: Math.round(window.displayToDist(parseFloat(getVal('cfg-prop-my-dist')) || 200)),
                regional_full_count: parseInt(getVal('cfg-prop-reg-count')) || 10,
                regional_full_dist_km: Math.round(window.displayToDist(parseFloat(getVal('cfg-prop-reg-dist')) || 200)),
            },
            mqtt: {
                enabled: getChk('cfg-mqtt-enabled'),
                broker: getVal('cfg-mqtt-broker'),
                port: parseInt(getVal('cfg-mqtt-port')) || 1883,
                topic_prefix: getVal('cfg-mqtt-topic'),
                username: getVal('cfg-mqtt-user'),
                password: getVal('cfg-mqtt-pass'),
            },
        };

        try {
            const resp = await fetch('/api/config/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const result = await resp.json();

            if (statusEl) {
                statusEl.style.display = 'block';
                const cls = result.success
                    ? (result.needRestart ? 'warning' : 'success')
                    : 'error';
                statusEl.className = 'settings-status ' + cls;
                statusEl.textContent = result.message || (result.success ? 'Saved!' : 'Error saving.');
                const delay = result.needRestart ? 10000 : 5000;
            }
            if (result.success) {
                clearSettingsDirty();
                window.pvConfigPromise = null;
                serverConfig = { ...(serverConfig || {}), alerts: { ...body.alerts } };
                const delay = result.needRestart ? 10000 : 5000;
                setTimeout(() => {
                    if (!settingsDirty) statusEl.style.display = 'none';
                }, delay);
                window.pvWeather?.fetchWeather(true);
                window.pvMap?.setMapTileConfig(body.web);
                loadUpdateStatus(false);
            }
        } catch (e) {
            console.error('Failed to save settings:', e);
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.className = 'settings-status error';
                statusEl.textContent = 'Network error saving configuration.';
                setTimeout(() => {
                    if (!settingsDirty) statusEl.style.display = 'none';
                }, 5000);
            }
        } finally {
            buttons.forEach((btn) => { btn.disabled = false; });
        }
    }

    function setVal(id, val) {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    }

    function setChk(id, val) {
        const el = document.getElementById(id);
        if (el) el.checked = !!val;
    }

    function getVal(id) {
        const el = document.getElementById(id);
        return el ? el.value : '';
    }

    function getChk(id) {
        const el = document.getElementById(id);
        return el ? el.checked : false;
    }

    function initWxNowControls() {
        document.getElementById('btn-wxnow-browse')?.addEventListener('click', selectWxNowFile);
        document.getElementById('btn-wxnow-test')?.addEventListener('click', transmitWxNowNow);
    }

    function initStatusDxControls() {
        document.getElementById('btn-status-test')?.addEventListener('click', transmitStatusDxNow);
        ['cfg-status-window', 'cfg-status-max-length'].forEach((id) => {
            document.getElementById(id)?.addEventListener('change', refreshStatusDxPreview);
        });
    }

    async function refreshStatusDxPreview() {
        const preview = document.getElementById('cfg-status-preview');
        if (!preview) return;
        try {
            const resp = await fetch('/api/status-dx/status');
            const data = await resp.json();
            const text = data.preview_text || data.last_text || 'No RF stations heard';
            preview.textContent = `>${text}`;
            if (data.last_error) preview.title = data.last_error;
        } catch (e) {
            preview.textContent = 'Preview unavailable';
        }
    }

    async function transmitStatusDxNow() {
        const preview = document.getElementById('cfg-status-preview');
        const button = document.getElementById('btn-status-test');
        if (button) button.disabled = true;
        if (preview) preview.textContent = 'Transmitting...';
        try {
            const resp = await fetch('/api/status-dx/transmit', { method: 'POST' });
            const result = await resp.json();
            if (preview) {
                preview.textContent = result.text ? `>${result.text}` : (result.message || 'Transmit failed');
                preview.title = result.message || '';
            }
        } catch (e) {
            console.error('Failed to transmit Status/DX packet:', e);
            if (preview) preview.textContent = 'Transmit failed';
        } finally {
            if (button) button.disabled = false;
            setTimeout(refreshStatusDxPreview, 2500);
        }
    }

    async function selectWxNowFile() {
        const status = document.getElementById('cfg-wxnow-status');
        if (status) status.textContent = 'Opening file picker...';
        try {
            const resp = await fetch('/api/wxnow/select-file', { method: 'POST' });
            const result = await resp.json();
            if (result.success && result.file_path) {
                setVal('cfg-wxnow-file', result.file_path);
                markSettingsDirty();
                if (status) status.textContent = 'Selected';
            } else if (status) {
                status.textContent = result.message || 'No file selected';
            }
        } catch (e) {
            console.error('Failed to select WXnow file:', e);
            if (status) status.textContent = 'File picker failed';
        }
    }

    async function refreshWxNowStatus() {
        const status = document.getElementById('cfg-wxnow-status');
        if (!status) return;
        try {
            const resp = await fetch('/api/wxnow/status');
            const data = await resp.json();
            if (!data.configured) {
                status.textContent = 'No file selected';
            } else if (!data.file_exists) {
                status.textContent = 'File not found';
            } else if (data.stale) {
                const mins = Math.floor((data.age_seconds || 0) / 60);
                status.textContent = `Stale (${mins} min old)`;
            } else {
                const mins = Math.floor((data.age_seconds || 0) / 60);
                status.textContent = data.enabled ? `Ready (${mins} min old)` : `Disabled (${mins} min old)`;
            }
        } catch (e) {
            status.textContent = 'Status unavailable';
        }
    }

    async function transmitWxNowNow() {
        const status = document.getElementById('cfg-wxnow-status');
        const button = document.getElementById('btn-wxnow-test');
        if (button) button.disabled = true;
        if (status) status.textContent = 'Transmitting...';
        try {
            const resp = await fetch('/api/wxnow/transmit', { method: 'POST' });
            const result = await resp.json();
            if (status) status.textContent = result.message || (result.success ? 'Transmitted' : 'Transmit failed');
        } catch (e) {
            console.error('Failed to transmit WXnow packet:', e);
            if (status) status.textContent = 'Transmit failed';
        } finally {
            if (button) button.disabled = false;
            setTimeout(refreshWxNowStatus, 2500);
        }
    }

    function setCheckboxGroupValues(name, values) {
        const useAll = values == null;
        const wanted = new Set((values || []).map(String));
        document.querySelectorAll(`input[name="${name}"]`).forEach((el) => {
            el.checked = useAll ? true : wanted.has(el.value);
        });
    }

    function getCheckboxGroupValues(name) {
        return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`))
            .map((el) => el.value);
    }

    function initWeatherSettingsUi() {
        document.getElementById('cfg-wx-radar-opacity')?.addEventListener('input', updateWeatherOverlayOpacityLabel);
        document.getElementById('cfg-wx-alert-provider')?.addEventListener('change', updateWeatherProviderUi);
        document.querySelectorAll('input[name="cfg-wx-alert-group"]').forEach((el) => {
            el.addEventListener('change', updateWeatherAlertGroupSummary);
        });
        document.getElementById('cfg-wx-alert-scope-mode')?.addEventListener('change', updateWeatherAlertScopePreview);
        document.getElementById('cfg-wx-alert-scope-zone')?.addEventListener('input', updateWeatherAlertScopePreview);
        document.getElementById('btn-wx-resolve-scope')?.addEventListener('click', resolveWeatherAlertScope);
        updateWeatherOverlayOpacityLabel();
        updateWeatherAlertGroupSummary();
        updateWeatherProviderUi();
        updateWeatherAlertScopePreview();
    }

    function updateWeatherProviderUi() {
        const provider = normalizeWeatherAlertProvider(getVal('cfg-wx-alert-provider') || 'auto');
        setVal('cfg-wx-alert-provider', provider);
        document.querySelectorAll('.wx-provider-key').forEach((el) => {
            el.style.display = el.classList.contains(`wx-provider-${provider}`) ? 'flex' : 'none';
        });

        const note = document.getElementById('cfg-wx-provider-note');
        if (!note) return;
        const notes = {
            auto: 'Auto uses NWS official alerts for US locations and Open-Meteo risk indicators elsewhere. Open-Meteo risk is not an official government warning feed.',
            weatherbit: 'Weatherbit requires your API key. The free tier is limited, so polling defaults to 30 minutes to stay under about 50 requests per day.',
            disabled: 'Weather alerts are disabled. Current conditions and radar can still run if weather and radar are enabled.',
        };
        note.textContent = notes[provider] || notes.auto;
    }
    window.pvUpdateWeatherProviderUi = updateWeatherProviderUi;

    function normalizeWeatherAlertProvider(provider) {
        if (provider === 'nws' || provider === 'open_meteo_risk') return 'auto';
        return ['auto', 'weatherbit', 'disabled'].includes(provider) ? provider : 'auto';
    }

    function initTncProfileSettings() {
        const profile = document.getElementById('cfg-ks-profile');
        const mode = document.getElementById('cfg-ks-mode');
        const flow = document.getElementById('cfg-ks-flow');
        const baud = document.getElementById('cfg-ks-baud');
        if (!profile) return;

        profile.addEventListener('change', () => {
            if (profile.value === 'kenwood_thd7' || profile.value === 'kenwood_tmd700') {
                if (flow) flow.value = 'xonxoff';
                if (baud && !baud.value) baud.value = '9600';
            } else if (profile.value === 'kenwood_thd72' || profile.value === 'generic_tnc2_kiss') {
                if (flow && flow.value === 'xonxoff') flow.value = 'none';
                if (baud && !baud.value) baud.value = '9600';
            }
        });

        mode?.addEventListener('change', () => {
            if (mode.value === 'tnc2_monitor' && profile.value === 'none') {
                profile.value = 'kenwood_thd7';
                if (flow) flow.value = 'xonxoff';
            }
        });
    }

    function updateWeatherOverlayOpacityLabel() {
        const input = document.getElementById('cfg-wx-radar-opacity');
        const label = document.getElementById('cfg-wx-radar-opacity-value');
        if (!input || !label) return;
        label.textContent = `${Math.round((parseFloat(input.value) || 0) * 100)}%`;
    }

    function updateWeatherAlertGroupSummary() {
        const label = document.getElementById('cfg-wx-alert-groups-summary');
        const boxes = Array.from(document.querySelectorAll('input[name="cfg-wx-alert-group"]'));
        if (!label || !boxes.length) return;
        const checked = boxes.filter((el) => el.checked);
        if (checked.length === boxes.length) {
            label.textContent = 'All alert types';
        } else if (!checked.length) {
            label.textContent = 'No alert types';
        } else {
            label.textContent = `${checked.length} selected`;
        }
    }

    function updateWeatherAlertScopePreview(resolved) {
        const mode = getVal('cfg-wx-alert-scope-mode') || 'point';
        const zone = (getVal('cfg-wx-alert-scope-zone') || '').trim().toUpperCase();
        const label = document.getElementById('cfg-wx-alert-scope-resolved');
        if (!label) return;
        if (resolved) {
            const parts = [resolved.county, resolved.forecast_zone].filter(Boolean);
            label.textContent = parts.length ? parts.join(' • ') : 'Resolved';
            return;
        }
        label.textContent = mode === 'county_zone'
            ? (zone ? `Using ${zone}` : 'Enter or auto-fill a county/zone UGC')
            : 'Point-based alerts';
    }

    async function resolveWeatherAlertScope() {
        const code = (getVal('cfg-wx-location') || '').trim();
        const status = document.getElementById('cfg-wx-alert-scope-resolved');
        if (!code) {
            if (status) status.textContent = 'Enter a weather location first';
            return;
        }
        if (status) status.textContent = 'Resolving county/zone...';
        try {
            const resp = await fetch('/api/weather/resolve-alert-scope', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code }),
            });
            const data = await resp.json();
            if (data.success && data.scope) {
                const zone = data.scope.county || data.scope.forecast_zone || '';
                setVal('cfg-wx-alert-scope-zone', zone);
                if (getVal('cfg-wx-alert-scope-mode') !== 'county_zone') {
                    setVal('cfg-wx-alert-scope-mode', 'county_zone');
                }
                updateWeatherAlertScopePreview(data.scope);
            } else if (status) {
                status.textContent = data.message || 'Could not resolve county/zone';
            }
        } catch (e) {
            console.error('Failed to resolve weather alert scope:', e);
            if (status) status.textContent = 'Network error';
        }
    }

    function parseCsvList(value) {
        return String(value || '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
    }

    // ── APRS-IS filter helpers ──────────────────────────────────

    /**
     * Parse a stored filter string like "r/35.1234/-80.5678/160.9 b/CALL" into
     * the range-miles field and extra-filters field.
     * APRS-IS range filter: r/lat/lon/range_km
     */
    function parseFilterIntoFields(filterStr) {
        const rangeEl = document.getElementById('cfg-is-range-miles');
        const extraEl = document.getElementById('cfg-is-extra-filters');
        if (!rangeEl || !extraEl) return;

        // Match r/lat/lon/km pattern
        const rMatch = filterStr.match(/r\/([\-\d.]+)\/([\-\d.]+)\/([\d.]+)/);
        const parts = filterStr.split(/\s+/).filter(Boolean);

        if (rMatch) {
            const rangeKm = parseFloat(rMatch[3]);
            const rangeMiles = Math.round(rangeKm / 1.60934);
            rangeEl.value = rangeMiles;
            // Everything except the r/ part goes into extra filters
            const extras = parts.filter(p => !p.startsWith('r/')).join(' ');
            extraEl.value = extras;
        } else {
            rangeEl.value = '';
            extraEl.value = filterStr;
        }
        updateFilterPreview();
    }

    /**
     * Build the combined APRS-IS filter string from range-miles + lat/lon + extras.
     */
    function buildFilterString() {
        const miles = parseFloat(getVal('cfg-is-range-miles'));
        const lat = parseFloat(getVal('cfg-latitude'));
        const lng = parseFloat(getVal('cfg-longitude'));
        const extras = getVal('cfg-is-extra-filters').trim();

        let parts = [];

        if (miles > 0 && !isNaN(lat) && !isNaN(lng) && (lat !== 0 || lng !== 0)) {
            const rangeKm = (miles * 1.60934).toFixed(1);
            parts.push(`r/${lat.toFixed(4)}/${lng.toFixed(4)}/${rangeKm}`);
        }

        if (extras) {
            parts.push(extras);
        }

        return parts.join(' ');
    }

    /**
     * Update the preview spans showing the generated filter.
     */
    function updateFilterPreview() {
        const combined = buildFilterString();

        const miles = parseFloat(getVal('cfg-is-range-miles'));
        const lat = parseFloat(getVal('cfg-latitude'));
        const lng = parseFloat(getVal('cfg-longitude'));

        const rangePreview = document.getElementById('cfg-is-range-preview');
        const combinedPreview = document.getElementById('cfg-is-filter-combined');

        if (rangePreview) {
            if (miles > 0 && !isNaN(lat) && !isNaN(lng) && (lat !== 0 || lng !== 0)) {
                const rangeKm = (miles * 1.60934).toFixed(1);
                rangePreview.textContent = `r/${lat.toFixed(4)}/${lng.toFixed(4)}/${rangeKm}`;
                rangePreview.title = `${miles} mi = ${rangeKm} km around ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
            } else if (miles > 0) {
                rangePreview.textContent = 'Set lat/lon first';
                rangePreview.title = '';
            } else {
                rangePreview.textContent = '\u2014';
                rangePreview.title = '';
            }
        }

        if (combinedPreview) {
            combinedPreview.textContent = combined || '\u2014';
            combinedPreview.title = combined;
        }

        // Also update hidden field
        setVal('cfg-is-filter', combined);
    }

    // Live-update preview when any relevant field changes
    ['cfg-is-range-miles', 'cfg-is-extra-filters', 'cfg-latitude', 'cfg-longitude'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updateFilterPreview);
        document.getElementById(id)?.addEventListener('change', updateFilterPreview);
    });

    // ── Init settings ──────────────────────────────────────────

    // Load settings when settings tab is clicked
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'tab-settings') {
                loadSettings();
            }
            if (btn.dataset.tab === 'tab-analytics') {
                window.pvAnalytics.loadAllData();
            }
            if (btn.dataset.tab === 'tab-messages') {
                window.pvMessages.loadMessages();
            }
            if (btn.dataset.tab === 'tab-about') {
                loadAboutInfo();
            }
        });
    });

    // Save button
    document.querySelectorAll('.btn-save-settings').forEach((btn) => {
        btn.addEventListener('click', saveSettings);
    });
    document.getElementById('btn-close-settings')?.addEventListener('click', closeSettingsPane);
    document.getElementById('btn-close-messages')?.addEventListener('click', closeMessagesPane);

    // Live font preview when changed in settings
    document.getElementById('cfg-web-font')?.addEventListener('change', (e) => {
        applyFont(e.target.value || '');
    });

    // Clear packets button
    document.getElementById('btn-clear-packets')?.addEventListener('click', () => {
        window.pvStations.clearPackets();
    });

    // Help modal
    document.getElementById('btn-open-help')?.addEventListener('click', () => {
        document.getElementById('help-modal').style.display = 'flex';
    });
    document.getElementById('help-modal-close')?.addEventListener('click', () => {
        document.getElementById('help-modal').style.display = 'none';
    });
    document.getElementById('help-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'help-modal') e.target.style.display = 'none';
    });

})();
