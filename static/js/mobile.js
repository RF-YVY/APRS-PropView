'use strict';
/* ================================================================
   APRS PropView — Mobile Companion
   Single-file SPA connecting to the same backend WebSocket + REST.
   ================================================================ */

// Public viewing is always read-only; operator sessions are enforced by the backend.
document.getElementById('m-app').style.display = 'flex';

// ── State ──────────────────────────────────────────────────
const MOBILE_TAB_KEY = 'pvMobileTab';
const MOBILE_MSG_FILTER_KEY = 'pvMobileMsgFilter';
const MOBILE_MSG_SORT_KEY = 'pvMobileMsgSort';
const MOBILE_MAP_THEME_KEY = 'pvMobileMapTheme';
const DESKTOP_UI_STATE_KEY = 'pvDesktopUIState';
const MOBILE_UI_SKINS = new Set(['standard', 'mission-control', 'industrial', 'neon-grid', 'terminal-green', 'radio', 'iview', 'hackr']);
const MOBILE_ACCENT_COLORS = {
    blue: '#58a6ff', cyan: '#39d5ff', green: '#3fb950',
    amber: '#d29922', purple: '#bc8cff', red: '#f85149',
};

const S = {
    ws: null, connected: false, myCall: '', messages: [], msgFilter: 'all', msgSort: 'asc',
    rfStations: Object.create(null), isStations: Object.create(null),
    map: null, mapReady: false, rfMarkers: Object.create(null), isMarkers: Object.create(null),
    rfLayer: null, isLayer: null, lineLayer: null, rfLines: Object.create(null), isLines: Object.create(null), myMarker: null, myPos: null, baseTileLayer: null,
    startTime: 0, ghostMinutes: 60, stationMeta: Object.create(null),
    unreadCount: 0, activeTab: 'mtab-home', propData: null,
    messagesLoaded: false, stationsLoaded: false, replyContext: null, selectedConversation: '', msgSearch: '',
    aprsIsConnected: false, aprsIsVerified: false,
    gpsWatchId: null, lastGpsPost: 0, config: null, showLines: true, mapTheme: 'dark',
    motionEnabled: true, animationMode: 'basic', animationCanvas: null, animationContext: null,
    animationFlows: [], animationFrame: null,
};

// ── Helpers ────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function applySavedUITheme() {
    let state = {};
    try { state = JSON.parse(localStorage.getItem(DESKTOP_UI_STATE_KEY) || '{}'); } catch { state = {}; }
    const mode = (state.uiMode || state.uiTheme) === 'light' ? 'light' : 'dark';
    const skin = MOBILE_UI_SKINS.has(state.uiSkin) ? state.uiSkin : 'standard';
    const accent = state.uiAccent || 'blue';
    const accentColor = accent === 'custom'
        ? (state.uiAccentCustom || MOBILE_ACCENT_COLORS.blue)
        : (MOBILE_ACCENT_COLORS[accent] || MOBILE_ACCENT_COLORS.blue);
    const root = document.documentElement;
    root.dataset.uiMode = mode;
    root.dataset.uiSkin = skin;
    root.dataset.uiAccent = accent;
    root.classList.toggle('ui-light', mode === 'light');
    root.style.setProperty('--user-accent', accentColor);
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.content = getComputedStyle(root).getPropertyValue('--bg').trim() || (mode === 'light' ? '#f5f7fb' : '#0d1117');
}
// Also escapes quotes, so the result is safe inside attribute values.
function escHtml(s) { return String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])); }
function timeAgo(ts) {
    if (!ts) return '--';
    const s = Math.floor(Date.now() / 1000 - ts);
    if (s < 60) return s + 's';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    return Math.floor(s / 86400) + 'd';
}
function fmtDist(km) { if (!km) return '--'; return (km * 0.621371).toFixed(1) + ' mi'; }
function fmtTime(ts) { if (!ts) return ''; return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function normalizeCall(value) { return (value || '').trim().toUpperCase(); }
function conversationCall(msg) {
    const from = normalizeCall(msg.from);
    const to = normalizeCall(msg.to);
    if (msg.direction === 'tx') return to;
    if (from && from !== S.myCall) return from;
    return to === S.myCall ? from : to;
}
function messageKey(msg) {
    const from = normalizeCall(msg.from);
    const to = normalizeCall(msg.to);
    if (msg.direction === 'tx' && msg.message_id) return `tx:${from}|${to}|${msg.message_id}`;
    if (msg.message_id) return `rx:${from}|${to}|${msg.message_id}`;
    return `${msg.direction || 'rx'}:${from}|${to}|${msg.text || ''}|${msg.timestamp || ''}`;
}
function upsertMessage(msg) {
    if (!msg) return false;
    const key = messageKey(msg);
    const idx = S.messages.findIndex(m => messageKey(m) === key);
    if (idx >= 0) {
        S.messages[idx] = { ...S.messages[idx], ...msg };
        return false;
    }
    S.messages.unshift(msg);
    return true;
}
function syncQuickActions() {
    document.querySelectorAll('.m-quick-actions button[data-quick-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.quickTab === S.activeTab);
    });
}
function syncMsgFilterButtons() {
    document.querySelectorAll('.msg-filter-bar button[data-f]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.f === S.msgFilter);
    });
}

// ── Tab switching ──────────────────────────────────────────
function activateTab(tab) {
    if (tab === 'mtab-messages' && !window.pvOperator?.authenticated) tab = 'mtab-home';
    S.activeTab = tab;
    localStorage.setItem(MOBILE_TAB_KEY, tab);

    document.querySelectorAll('.m-nav button').forEach(b => b.classList.remove('active'));
    document.querySelector(`.m-nav button[data-tab="${tab}"]`)?.classList.add('active');
    document.querySelectorAll('.m-tab').forEach(t => t.classList.remove('active'));
    $(tab)?.classList.add('active');
    syncQuickActions();

    if (tab === 'mtab-map' && !S.mapReady) initMap();
    if (tab === 'mtab-map' && S.map) setTimeout(() => S.map.invalidateSize(), 50);
    if (tab === 'mtab-messages') { S.unreadCount = 0; updateBadge(); }
    if (tab === 'mtab-prop') loadLeaderboard();
}

document.querySelector('.m-nav').addEventListener('click', e => {
    const btn = e.target.closest('button[data-tab]');
    if (!btn) return;
    activateTab(btn.dataset.tab);
});

document.addEventListener('click', e => {
    const btn = e.target.closest('button[data-quick-tab]');
    if (!btn) return;
    activateTab(btn.dataset.quickTab);
});

// ── Message filter ─────────────────────────────────────────
document.querySelector('.msg-filter-bar').addEventListener('click', e => {
    const btn = e.target.closest('button[data-f]');
    if (!btn) return;
    S.msgFilter = btn.dataset.f;
    localStorage.setItem(MOBILE_MSG_FILTER_KEY, S.msgFilter);
    syncMsgFilterButtons();
    renderMessages();
});

$('m-msg-sort').addEventListener('change', e => {
    S.msgSort = e.target.value === 'desc' ? 'desc' : 'asc';
    localStorage.setItem(MOBILE_MSG_SORT_KEY, S.msgSort);
    renderMessages();
});

$('m-btn-refresh').addEventListener('click', async () => {
    await Promise.all([loadMobileMessages(), loadWeather()]);
});

// ── Send message ───────────────────────────────────────────
$('m-btn-send').addEventListener('click', sendMsg);
$('m-msg-text').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendMsg(); } });
$('m-msg-to').addEventListener('input', e => { e.target.value = e.target.value.toUpperCase(); });
$('m-msg-to').addEventListener('input', e => {
    const to = e.target.value.trim().toUpperCase();
    if (S.replyContext && to !== S.replyContext.to) S.replyContext = null;
});

async function sendMsg() {
    const to = $('m-msg-to').value.trim().toUpperCase();
    const text = $('m-msg-text').value.trim();
    const replySource = S.replyContext && S.replyContext.to === to ? S.replyContext.source : '';
    if (!to || !text) return;
    $('m-btn-send').disabled = true;
    try {
        const r = await fetch('/api/messages/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ to, text, reply_source: replySource || undefined }),
        });
        const j = await r.json();
        if (j.success) {
            S.selectedConversation = to;
            if (j.message) upsertMessage(j.message);
            $('m-msg-text').value = '';
            S.replyContext = null;
            renderMessages();
            $('m-msg-text').focus();
        }
        else alert(j.message || 'Send failed');
    } catch { alert('Network error'); }
    finally { $('m-btn-send').disabled = false; }
}

// ── Tap message to reply ───────────────────────────────────
$('m-msg-list').addEventListener('click', e => {
    const bub = e.target.closest('.msg-bubble');
    if (!bub || !bub.dataset.replyCall) return;
    $('m-msg-to').value = bub.dataset.replyCall.toUpperCase();
    S.replyContext = {
        to: bub.dataset.replyCall.toUpperCase(),
        source: bub.dataset.replySource || '',
    };
    $('m-msg-text').focus();
});

$('m-msg-conversation')?.addEventListener('change', e => {
    S.selectedConversation = normalizeCall(e.target.value);
    if (S.selectedConversation) $('m-msg-to').value = S.selectedConversation;
    renderMessages();
});

$('m-msg-search')?.addEventListener('input', e => {
    S.msgSearch = normalizeCall(e.target.value);
    renderMessages();
});

document.addEventListener('click', async e => {
    const action = e.target.closest('[data-thread-action]');
    if (!action) return;
    const call = S.selectedConversation;
    if (!call) return;
    if (action.dataset.threadAction === 'message') {
        $('m-msg-to').value = call;
        $('m-msg-text').focus();
        return;
    }
    if (action.dataset.threadAction === 'remove-contact') {
        if (!confirm(`Remove ${call} from saved message contacts?`)) return;
        await deleteMobileContact(call);
        return;
    }
    if (action.dataset.threadAction === 'clear-thread') {
        if (!confirm(`Clear message history with ${call}?`)) return;
        await clearMobileConversation(call);
    }
});

async function deleteMobileContact(call) {
    try {
        await fetch(`/api/messages/contacts/${encodeURIComponent(call)}`, { method: 'DELETE' });
        renderMessages();
    } catch {
        alert('Unable to remove contact.');
    }
}

async function clearMobileConversation(call) {
    try {
        const r = await fetch(`/api/messages/conversation/${encodeURIComponent(call)}`, { method: 'DELETE' });
        const j = await r.json();
        if (!r.ok || !j.success) throw new Error(j.message || 'Clear failed');
        S.messages = S.messages.filter(m => conversationCall(m) !== call);
        S.selectedConversation = '';
        renderMessages();
    } catch (err) {
        alert(err.message || 'Unable to clear conversation.');
    }
}

// ── Render messages ────────────────────────────────────────
function renderMessages() {
    const list = $('m-msg-list');
    let msgs = S.messages;
    if (S.msgFilter === 'mine') msgs = msgs.filter(m => m.from?.toUpperCase() === S.myCall || m.to?.toUpperCase() === S.myCall);
    else if (S.msgFilter === 'rx') msgs = msgs.filter(m => m.direction === 'rx');
    else if (S.msgFilter === 'tx') msgs = msgs.filter(m => m.direction === 'tx');

    if (!msgs.length) {
        if (!S.messagesLoaded) {
            list.innerHTML = '<div class="m-empty"><div class="title">Loading messages</div><div class="copy">Checking recent APRS message history and waiting for live traffic.</div></div>';
            return;
        }
        const copy = S.connected
            ? 'Send a message or wait for incoming APRS traffic.'
            : 'The live connection is offline. Messages will refresh after reconnect.';
        list.innerHTML = `<div class="m-empty"><div class="title">No messages yet</div><div class="copy">${copy}</div></div>`;
        return;
    }

    const sorted = [...msgs].sort((a, b) => {
        const diff = Number(a.timestamp || 0) - Number(b.timestamp || 0);
        return S.msgSort === 'desc' ? -diff : diff;
    });
    list.innerHTML = sorted.map(m => {
        const isTx = m.direction === 'tx';
        let ackHtml = '';
        if (isTx) {
            if (m.acked) ackHtml = '<span class="ack-icon">✓</span>';
            else if (m.rejected) ackHtml = '<span class="rej-icon">✗</span>';
            else ackHtml = '⏳';
        }
        const src = m.source === 'rf' ? 'RF' : (m.source === 'aprs_is' ? 'IS' : (m.source === 'both' ? 'RF+IS' : 'TX'));
        const replyCall = !isTx ? (m.from || '') : '';
        const replySource = !isTx ? (m.source || '') : '';
        return `<div class="msg-bubble ${isTx ? 'tx' : 'rx'}" data-reply-call="${escHtml(replyCall)}" data-reply-source="${escHtml(replySource)}">
            <div class="from">${escHtml(m.from || '?')} → ${escHtml(m.to || '?')}</div>
            ${escHtml(m.text || '')}
            <div class="meta"><span>${fmtTime(m.timestamp)}</span><span>${src}</span>${ackHtml}</div>
        </div>`;
    }).join('');
    list.scrollTop = S.msgSort === 'asc' ? list.scrollHeight : 0;
}

function filteredMessages() {
    let msgs = S.messages;
    if (S.msgFilter === 'mine') msgs = msgs.filter(m => normalizeCall(m.from) === S.myCall || normalizeCall(m.to) === S.myCall);
    else if (S.msgFilter === 'rx') msgs = msgs.filter(m => m.direction === 'rx');
    else if (S.msgFilter === 'tx') msgs = msgs.filter(m => m.direction === 'tx');
    return msgs;
}

function buildConversations(msgs) {
    const convs = new Map();
    for (const msg of msgs) {
        const call = conversationCall(msg);
        if (!call) continue;
        const current = convs.get(call) || { call, messages: [], newest: 0, unread: 0 };
        current.messages.push(msg);
        current.newest = Math.max(current.newest, Number(msg.timestamp || 0));
        if (msg.direction === 'rx' && normalizeCall(msg.to) === S.myCall) current.unread += 1;
        convs.set(call, current);
    }
    return [...convs.values()].sort((a, b) => b.newest - a.newest);
}

function renderConversations(convs) {
    const select = $('m-msg-conversation');
    if (!select) return;
    const search = S.msgSearch || '';
    const visible = search
        ? convs.filter(c => c.call.includes(search))
        : convs;
    if (!visible.length) {
        select.innerHTML = '<option value="">No conversations</option>';
        S.selectedConversation = '';
        return;
    }
    if (!S.selectedConversation || !visible.some(c => c.call === S.selectedConversation)) {
        S.selectedConversation = visible[0].call;
    }
    select.innerHTML = visible.map(c => {
        const latest = [...c.messages].sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))[0] || {};
        const unread = c.unread ? ` (${c.unread} new)` : '';
        const preview = latest.text ? ` - ${String(latest.text).slice(0, 28)}` : '';
        return `<option value="${escHtml(c.call)}">${escHtml(c.call + unread + preview)}</option>`;
    }).join('');
    select.value = S.selectedConversation;
}

function renderMessages() {
    const list = $('m-msg-list');
    const header = $('m-msg-thread-header');
    const msgs = filteredMessages();
    const convs = buildConversations(msgs);
    renderConversations(convs);
    if (!S.selectedConversation && msgs.length) {
        if (header) header.textContent = convs.length ? 'No matching conversation.' : 'No conversation selected.';
        list.innerHTML = convs.length
            ? '<div class="m-empty"><div class="title">No match</div><div class="copy">Adjust the callsign search to choose a conversation.</div></div>'
            : '<div class="m-empty"><div class="title">No messages yet</div><div class="copy">Send a message or wait for incoming APRS traffic.</div></div>';
        return;
    }

    if (!msgs.length) {
        if (header) header.textContent = 'No conversation selected.';
        if (!S.messagesLoaded) {
            list.innerHTML = '<div class="m-empty"><div class="title">Loading messages</div><div class="copy">Checking recent APRS message history and waiting for live traffic.</div></div>';
            return;
        }
        const copy = S.connected
            ? 'Send a message or wait for incoming APRS traffic.'
            : 'The live connection is offline. Messages will refresh after reconnect.';
        list.innerHTML = `<div class="m-empty"><div class="title">No messages yet</div><div class="copy">${copy}</div></div>`;
        return;
    }

    const thread = msgs.filter(m => conversationCall(m) === S.selectedConversation);
    if (header) {
        const count = thread.length;
        header.innerHTML = `
            <span><strong>${escHtml(S.selectedConversation || 'Conversation')}</strong> &middot; ${count} message${count === 1 ? '' : 's'}</span>
            <span class="msg-thread-actions">
                <button type="button" data-thread-action="message">Reply</button>
                <button type="button" data-thread-action="remove-contact">Remove</button>
                <button type="button" class="danger" data-thread-action="clear-thread">Clear</button>
            </span>`;
    }

    const sorted = [...thread].sort((a, b) => {
        const diff = Number(a.timestamp || 0) - Number(b.timestamp || 0);
        return S.msgSort === 'desc' ? -diff : diff;
    });
    list.innerHTML = sorted.map(m => {
        const isTx = m.direction === 'tx';
        let ackHtml = '';
        if (isTx) {
            if (m.acked) ackHtml = '<span class="ack-icon">✓</span>';
            else if (m.rejected) ackHtml = '<span class="rej-icon">×</span>';
            else ackHtml = '…';
        }
        const src = m.source === 'rf' ? 'RF' : (m.source === 'aprs_is' ? 'IS' : (m.source === 'both' ? 'RF+IS' : 'TX'));
        const replyCall = !isTx ? (m.from || '') : '';
        const replySource = !isTx ? (m.source || '') : '';
        return `<div class="msg-bubble ${isTx ? 'tx' : 'rx'}" data-reply-call="${escHtml(replyCall)}" data-reply-source="${escHtml(replySource)}">
            <div class="from">${escHtml(m.from || '?')} → ${escHtml(m.to || '?')}</div>
            ${escHtml(m.text || '')}
            <div class="meta"><span>${fmtTime(m.timestamp)}</span><span>${src}</span>${ackHtml}</div>
        </div>`;
    }).join('');
    list.scrollTop = S.msgSort === 'asc' ? list.scrollHeight : 0;
}

async function loadMobileMessages() {
    try {
        const r = await fetch('/api/messages?limit=500');
        const d = await r.json();
        if (d.messages) S.messages = d.messages;
    } catch { /* silent */ }
    finally {
        S.messagesLoaded = true;
        renderMessages();
    }
}

function updateBadge() {
    const b = $('m-msg-badge');
    const qa = $('m-qa-msg-badge');
    if (S.unreadCount > 0) {
        b.textContent = S.unreadCount;
        b.style.display = 'block';
        if (qa) {
            qa.textContent = S.unreadCount;
            qa.style.display = 'block';
        }
    } else {
        b.style.display = 'none';
        if (qa) qa.style.display = 'none';
    }
    updateHomeSummary();
}

function updateHomeSummary() {
    const isText = S.connected
        ? (S.aprsIsConnected ? (S.aprsIsVerified ? 'Online' : 'Read-only') : 'Offline')
        : 'Reconnecting';
    const setText = (id, value) => { const el = $(id); if (el) el.textContent = value; };
    setText('m-home-is', isText);
    setText('m-home-call', `Station ${S.myCall || '--'}`);
    setText('m-home-msg', String(S.unreadCount || 0));
    setText('m-home-msg-copy', S.unreadCount ? 'Unread messages waiting' : 'No unread messages');
    setText('m-home-rf', String(Object.keys(S.rfStations || {}).length));
    setText('m-home-max', S.propData ? fmtDist(S.propData.max_distance_km || 0) : '--');
    const rf = S.propData?.rf_stations_1h || 0;
    const maxD = S.propData?.max_distance_km || 0;
    let level = 'Quiet';
    if (rf >= 10 && maxD >= 200) level = 'Strong';
    else if (rf >= 5 && maxD >= 100) level = 'Active';
    else if (rf >= 2) level = 'Light';
    setText('m-home-prop', level);
    setText('m-home-prop-copy', S.propData
        ? `${rf} RF stations in 1h · ${fmtDist(maxD)} max path.`
        : 'Waiting for live propagation data.');
}

// ── Map ────────────────────────────────────────────────────
function initMap() {
    if (S.mapReady) return;
    const lat = S.myPos ? S.myPos[0] : 39.8;
    const lng = S.myPos ? S.myPos[1] : -98.6;
    const zoom = S.myPos ? 8 : 4;

    S.map = L.map('m-map', { zoomControl: false, attributionControl: true }).setView([lat, lng], zoom);
    L.control.zoom({ position: 'topright' }).addTo(S.map);
    const tileCfg = getMapTileConfig();
    const tileOpts = {
        maxZoom: tileCfg.maxZoom,
        className: tileCfg.className || '',
        attribution: tileCfg.attribution,
    };
    if (tileCfg.url.includes('{s}')) tileOpts.subdomains = tileCfg.subdomains;
    S.baseTileLayer = L.tileLayer(tileCfg.url, tileOpts).addTo(S.map);

    S.lineLayer = L.layerGroup().addTo(S.map);
    S.rfLayer = L.layerGroup().addTo(S.map);
    S.isLayer = L.layerGroup().addTo(S.map);
    initMobilePacketAnimation();

    if (S.myPos) {
        S.myMarker = L.circleMarker(S.myPos, {
            radius: 8, color: '#3fb950', fillColor: '#3fb950', fillOpacity: 0.6, weight: 2,
        }).addTo(S.map).bindPopup(`<b style="color:#3fb950">${escHtml(S.myCall)}</b><br>My Station`);
    }

    S.mapReady = true;
    for (const st of Object.values(S.rfStations)) addMapMarker(st);
    for (const st of Object.values(S.isStations)) addMapMarker(st);
    redrawAllLines();
}

function getMapTileConfig() {
    const web = S.config?.web || {};
    if (web.map_tile_source === 'custom' && web.map_tile_url) {
        return {
            url: web.map_tile_url,
            attribution: web.map_tile_attribution || '',
            maxZoom: Math.min(22, Math.max(1, parseInt(web.map_tile_max_zoom || 19, 10))),
            subdomains: 'abc',
        };
    }
    // Both themes use the key-free OSM service; dark styling is local.
    return {
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
        maxZoom: 19,
        className: S.mapTheme === 'light' ? '' : 'mobile-dark-tiles',
    };
}

function updateMapThemeButton() {
    const darkBtn = $('m-map-theme-dark');
    const lightBtn = $('m-map-theme-light');
    const customTiles = !!(S.config?.web?.map_tile_source === 'custom' && S.config?.web?.map_tile_url);
    if (darkBtn) {
        darkBtn.classList.toggle('active', S.mapTheme !== 'light');
        darkBtn.title = customTiles ? 'Custom tile source is configured; theme toggle uses default tiles only.' : 'Use dark mobile map tiles';
    }
    if (lightBtn) {
        lightBtn.classList.toggle('active', S.mapTheme === 'light');
        lightBtn.title = customTiles ? 'Custom tile source is configured; theme toggle uses default tiles only.' : 'Use light mobile map tiles';
    }
}

function applyMobileMapTheme() {
    updateMapThemeButton();
    if (!S.mapReady || !S.map) return;
    const tileCfg = getMapTileConfig();
    const tileOpts = {
        maxZoom: tileCfg.maxZoom,
        className: tileCfg.className || '',
        attribution: tileCfg.attribution,
    };
    if (tileCfg.url.includes('{s}')) tileOpts.subdomains = tileCfg.subdomains;
    if (S.baseTileLayer) S.map.removeLayer(S.baseTileLayer);
    S.baseTileLayer = L.tileLayer(tileCfg.url, tileOpts).addTo(S.map);
    if (S.lineLayer) S.lineLayer.bringToFront();
    if (S.rfLayer) S.rfLayer.bringToFront();
    if (S.isLayer) S.isLayer.bringToFront();
}

function setMobileMapTheme(theme) {
    S.mapTheme = theme === 'light' ? 'light' : 'dark';
    localStorage.setItem(MOBILE_MAP_THEME_KEY, S.mapTheme);
    applyMobileMapTheme();
}

function lineColorFor(st) {
    if (st.source !== 'rf') return '#58a6ff';
    const km = Number(st.distance_km || 0);
    if (km > 200) return '#bc8cff';
    if (km > 100) return '#3fb950';
    if (km > 50) return '#d29922';
    return '#f85149';
}

function updateStationLine(st) {
    if (!S.mapReady || !S.lineLayer || !S.showLines || !S.myPos || !window.pvUI.validPosition(st.latitude, st.longitude)) return;
    if (st.latitude === 0 && st.longitude === 0) return;
    const source = st.source === 'rf' ? 'rf' : 'aprs_is';
    const lines = source === 'rf' ? S.rfLines : S.isLines;
    const key = st.callsign;
    const opts = {
        color: lineColorFor(st),
        weight: source === 'rf' ? 2.5 : 1.5,
        opacity: source === 'rf' ? 0.72 : 0.38,
        dashArray: source === 'rf' ? null : '4 7',
        interactive: false,
    };
    const points = [S.myPos, [st.latitude, st.longitude]];
    if (lines[key]) {
        lines[key].setLatLngs(points);
        lines[key].setStyle(opts);
    } else {
        lines[key] = L.polyline(points, opts).addTo(S.lineLayer);
    }
}

function redrawAllLines() {
    if (!S.lineLayer) return;
    S.lineLayer.clearLayers();
    S.rfLines = Object.create(null);
    S.isLines = Object.create(null);
    if (!S.showLines) return;
    Object.values(S.rfStations).forEach(updateStationLine);
    Object.values(S.isStations).forEach(updateStationLine);
}

function setLinesVisible(show) {
    S.showLines = !!show;
    $('m-btn-lines')?.classList.toggle('active', S.showLines);
    $('m-map-lines')?.classList.toggle('active', S.showLines);
    redrawAllLines();
}

function resizeMobileAnimationCanvas() {
    if (!S.animationCanvas || !S.animationContext || !S.map) return;
    const size = S.map.getSize();
    const dpr = Math.min(1.5, Math.max(1, Number(devicePixelRatio) || 1));
    S.animationCanvas.width = Math.max(1, Math.round(size.x * dpr));
    S.animationCanvas.height = Math.max(1, Math.round(size.y * dpr));
    S.animationCanvas.style.width = `${size.x}px`;
    S.animationCanvas.style.height = `${size.y}px`;
    S.animationContext.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function initMobilePacketAnimation() {
    if (!S.map || S.animationCanvas) return;
    const canvas = document.createElement('canvas');
    canvas.className = 'm-packet-animation-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    S.map.getContainer().appendChild(canvas);
    S.animationCanvas = canvas;
    S.animationContext = canvas.getContext('2d');
    resizeMobileAnimationCanvas();
    S.map.on('resize move zoom', resizeMobileAnimationCanvas);
    updateMobileMotionButton();
}

function updateMobileMotionButton() {
    const button = $('m-map-motion');
    if (!button) return;
    button.classList.toggle('active', S.motionEnabled && S.animationMode !== 'off');
    button.disabled = S.animationMode === 'off';
    button.title = S.animationMode === 'off'
        ? 'Packet animation is disabled in desktop Map & Display settings.'
        : `${S.animationMode === 'enhanced' ? 'Enhanced' : 'Basic'} live packet motion on this mobile map`;
}

function pulseMobileMarker(marker, color) {
    const visual = marker?.getElement()?.querySelector('.aprs-emoji-marker');
    if (!visual) return;
    visual.style.setProperty('--mobile-packet-color', color);
    visual.classList.remove('mobile-packet-pulse');
    void visual.offsetWidth;
    visual.classList.add('mobile-packet-pulse');
    setTimeout(() => visual.classList.remove('mobile-packet-pulse'), 900);
}

function mobilePacketRoute(packet) {
    if (!S.myPos) return [];
    if (packet.source === 'tx') return [L.latLng(S.myPos)];
    const call = normalizeCall(packet.from_call);
    const marker = S.rfMarkers[call] || S.isMarkers[call];
    if (!marker) return [];
    const route = [marker.getLatLng()];
    if (S.animationMode === 'enhanced' && packet.source === 'rf') {
        String(packet.path || '').split(',').map(normalizeCall).forEach((hop) => {
            const clean = hop.replace(/\*$/, '');
            const hopMarker = S.rfMarkers[clean] || S.isMarkers[clean];
            if (hopMarker && clean !== call) route.push(hopMarker.getLatLng());
        });
    }
    route.push(L.latLng(S.myPos));
    return route;
}

function pointAlongMobileRoute(points, progress) {
    if (points.length < 2) return points[0];
    const lengths = [];
    let total = 0;
    for (let i = 1; i < points.length; i++) {
        const length = points[i - 1].distanceTo(points[i]);
        lengths.push(length); total += length;
    }
    let target = total * progress;
    for (let i = 0; i < lengths.length; i++) {
        if (target <= lengths[i]) {
            const ratio = lengths[i] ? target / lengths[i] : 0;
            return L.point(points[i].x + (points[i + 1].x - points[i].x) * ratio, points[i].y + (points[i + 1].y - points[i].y) * ratio);
        }
        target -= lengths[i];
    }
    return points[points.length - 1];
}

function renderMobilePacketAnimations(now) {
    S.animationFrame = null;
    if (!S.animationContext || !S.map) return;
    resizeMobileAnimationCanvas();
    const ctx = S.animationContext;
    const size = S.map.getSize();
    ctx.clearRect(0, 0, size.x, size.y);
    const active = [];
    for (const flow of S.animationFlows) {
        const progress = Math.min(1, Math.max(0, (now - flow.startedAt) / flow.duration));
        const points = flow.route.map((latlng) => S.map.latLngToContainerPoint(latlng));
        if (points.length < 2) continue;
        ctx.save();
        ctx.strokeStyle = flow.color;
        ctx.globalAlpha = .22;
        ctx.lineWidth = flow.mode === 'enhanced' ? 2.2 : 1.7;
        if (flow.internet) ctx.setLineDash([3, 8]);
        ctx.beginPath(); ctx.moveTo(points[0].x, points[0].y); points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y)); ctx.stroke();
        ctx.setLineDash([]);
        const head = pointAlongMobileRoute(points, progress);
        if (flow.mode === 'enhanced') {
            const tail = pointAlongMobileRoute(points, Math.max(0, progress - .2));
            const gradient = ctx.createLinearGradient(tail.x, tail.y, head.x, head.y);
            gradient.addColorStop(0, 'transparent'); gradient.addColorStop(1, flow.color);
            ctx.globalAlpha = .95; ctx.strokeStyle = gradient; ctx.lineWidth = 4;
            ctx.beginPath(); ctx.moveTo(tail.x, tail.y); ctx.lineTo(head.x, head.y); ctx.stroke();
        }
        ctx.globalAlpha = 1; ctx.fillStyle = flow.color; ctx.shadowColor = flow.color; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.arc(head.x, head.y, flow.mode === 'enhanced' ? 4.5 : 3.5, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
        if (progress < 1) active.push(flow);
    }
    S.animationFlows = active;
    if (active.length) S.animationFrame = requestAnimationFrame(renderMobilePacketAnimations);
}

function animateMobilePacket(packet = {}) {
    if (!S.motionEnabled || S.animationMode === 'off' || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const route = mobilePacketRoute(packet);
    const color = packet.source === 'aprs_is' ? '#58a6ff' : (packet.source === 'tx' ? '#ff7b72' : '#f85149');
    const call = normalizeCall(packet.from_call);
    pulseMobileMarker(packet.source === 'tx' ? S.myMarker : (S.rfMarkers[call] || S.isMarkers[call]), color);
    if (route.length < 2) return;
    if (S.animationFlows.length >= 10) S.animationFlows.shift();
    S.animationFlows.push({ route, color, mode: S.animationMode, internet: packet.source === 'aprs_is', startedAt: performance.now(), duration: S.animationMode === 'enhanced' ? 1700 : 1200 });
    if (!S.animationFrame) S.animationFrame = requestAnimationFrame(renderMobilePacketAnimations);
}

function startMessageTo(call, source = '') {
    const dest = normalizeCall(call);
    if (!dest) return;
    S.selectedConversation = dest;
    $('m-msg-to').value = dest;
    S.replyContext = source ? { to: dest, source } : null;
    activateTab('mtab-messages');
    renderMessages();
    setTimeout(() => $('m-msg-text')?.focus(), 80);
}
window.startMessageTo = startMessageTo;

function showStationOnMap(call, source = '') {
    const normalized = normalizeCall(call);
    const station = source === 'rf' ? S.rfStations[normalized] : S.isStations[normalized];
    if (!window.pvUI.validPosition(station?.latitude, station?.longitude)) return;
    activateTab('mtab-map');
    if (!S.mapReady) initMap();
    setTimeout(() => {
        S.map?.setView([station.latitude, station.longitude], 12);
        const markers = source === 'rf' ? S.rfMarkers : S.isMarkers;
        markers[normalized]?.openPopup();
    }, 80);
}

// Map popup "Send Message": data attributes instead of an inline onclick, so
// packet text never becomes script. Capture phase, because Leaflet stops click
// propagation inside popups.
document.addEventListener('click', e => {
    const button = e.target.closest?.('[data-message-call]');
    if (button) startMessageTo(button.dataset.messageCall, button.dataset.messageSource || '');
}, true);

document.addEventListener('click', e => {
    const action = e.target.closest('[data-station-action]');
    if (!action) return;
    const card = action.closest('.stn-card');
    const call = normalizeCall(card?.dataset.call);
    const source = card?.dataset.source || '';
    if (!call) return;
    if (action.dataset.stationAction === 'message') startMessageTo(call, source);
    if (action.dataset.stationAction === 'map') showStationOnMap(call, source);
});

function addMapMarker(st) {
    if (!window.pvUI.validPosition(st.latitude, st.longitude)) return;
    if (st.latitude === 0 && st.longitude === 0) return;

    const source = st.source;
    const call = st.callsign;
    const markers = source === 'rf' ? S.rfMarkers : S.isMarkers;
    const layer = source === 'rf' ? S.rfLayer : S.isLayer;
    if (!layer) return;

    const symT = st.symbol_table || '/';
    const symC = st.symbol_code || '-';
    const bc = source === 'rf' ? '#f85149' : '#58a6ff';
    const spr = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symT, symC, 16) : '📍';
    const popSpr = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symT, symC, 32) : '📍';
    const symN = (typeof getAPRSSymbolName === 'function') ? getAPRSSymbolName(symT, symC) : '';

    const iconHtml = `<div class="aprs-emoji-marker aprs-emoji-${source}" style="border-color:${bc};">${spr}</div>`;
    const icon = L.divIcon({ className: 'aprs-icon-wrapper', html: iconHtml, iconSize: [24, 24], iconAnchor: [12, 12], popupAnchor: [0, -12] });

    const srcLabel = source === 'rf' ? 'RF' : 'APRS-IS';
    const srcClass = source === 'rf' ? 'popup-rf' : 'popup-is';
    const popup = `<div class="popup-call ${srcClass}">${escHtml(call)}</div>
        <div class="popup-detail">Source: ${srcLabel}<br>Type: ${popSpr} ${escHtml(symN)}<br>
        Distance: ${fmtDist(st.distance_km)}<br>Last: ${fmtTime(st.last_heard)}<br>
        Pkts: ${st.packet_count || 1}${st.last_path ? '<br>Path: ' + escHtml(st.last_path) : ''}${st.last_comment ? '<br>' + escHtml(st.last_comment) : ''}</div>
        <div class="popup-actions">
            <button type="button" class="popup-action-btn" data-message-call="${escHtml(call)}" data-message-source="${escHtml(source)}">Send Message</button>
            <a class="popup-action-btn" href="https://aprs.fi/info/a/${encodeURIComponent(call)}" target="_blank" rel="noopener noreferrer">aprs.fi</a>
        </div>`;

    if (markers[call]) {
        markers[call].setLatLng([st.latitude, st.longitude]).setPopupContent(popup).setIcon(icon);
    } else {
        markers[call] = L.marker([st.latitude, st.longitude], { icon }).bindPopup(popup).addTo(layer);
    }
    S.stationMeta[call] = { source, last_heard: st.last_heard || 0 };
    updateStationLine(st);
}

function removeMapMarker(call, source) {
    const markers = source === 'rf' ? S.rfMarkers : S.isMarkers;
    const layer = source === 'rf' ? S.rfLayer : S.isLayer;
    if (markers[call] && layer) { layer.removeLayer(markers[call]); delete markers[call]; }
    const lines = source === 'rf' ? S.rfLines : S.isLines;
    if (lines[call] && S.lineLayer) { S.lineLayer.removeLayer(lines[call]); delete lines[call]; }
    delete S.stationMeta[call];
}

function ghostStaleMarkers() {
    if (!S.ghostMinutes || S.ghostMinutes <= 0) return;
    const cutoff = Date.now() / 1000 - S.ghostMinutes * 60;
    for (const [call, meta] of Object.entries(S.stationMeta)) {
        const markers = meta.source === 'rf' ? S.rfMarkers : S.isMarkers;
        const marker = markers[call];
        if (!marker) continue;
        const el = marker.getElement();
        if (!el) continue;
        const inner = el.querySelector('.aprs-emoji-marker');
        if (!inner) continue;
        inner.classList.toggle('ghosted', meta.last_heard > 0 && meta.last_heard < cutoff);
    }
}

// ── Stations list ──────────────────────────────────────────
function renderStations() {
    renderStationList(S.rfStations, $('m-rf-list'), $('m-rf-count'));
    renderStationList(S.isStations, $('m-is-list'), $('m-is-count'));
    updateHomeSummary();
}

function renderStationList(stations, container, countEl) {
    const arr = Object.values(stations).sort((a, b) => (b.last_heard || 0) - (a.last_heard || 0));
    if (countEl) countEl.textContent = arr.length;
    if (!container) return;
    if (!arr.length) {
        if (!S.stationsLoaded) {
            container.innerHTML = '<div class="m-empty"><div class="title">Loading stations</div><div class="copy">Waiting for the first live station snapshot.</div></div>';
            return;
        }
        const sourceLabel = countEl?.id === 'm-rf-count' ? 'RF' : 'APRS-IS';
        const copy = S.connected
            ? `No ${sourceLabel} stations are available yet. Check back after more traffic is heard.`
            : `The live connection is offline, so ${sourceLabel} stations will appear after reconnect.`;
        container.innerHTML = `<div class="m-empty"><div class="title">No stations yet</div><div class="copy">${copy}</div></div>`;
        return;
    }
    container.innerHTML = arr.map(st => {
        const sym = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(st.symbol_table || '/', st.symbol_code || '-', 20) : '📍';
        const source = st.source === 'rf' ? 'rf' : 'aprs_is';
        const call = escHtml(st.callsign || '');
        return `<div class="stn-card" data-call="${call}" data-source="${source}">
            <div class="stn-icon">${sym}</div>
            <div class="stn-info">
                <div class="stn-call">${call}</div>
                <div class="stn-detail">${fmtDist(st.distance_km)} · ${st.packet_count || 1} pkts${st.last_comment ? ' · ' + escHtml(st.last_comment).substring(0, 30) : ''}</div>
                <div class="stn-actions">
                    <button type="button" data-station-action="message">Message</button>
                    <button type="button" data-station-action="map">Map</button>
                    <a href="https://aprs.fi/info/a/${encodeURIComponent(st.callsign || '')}" target="_blank" rel="noopener noreferrer">aprs.fi</a>
                </div>
            </div>
            <div class="stn-time" data-last-heard="${st.last_heard || 0}">${timeAgo(st.last_heard)}</div>
        </div>`;
    }).join('');
}

function refreshStationTimes() {
    document.querySelectorAll('.stn-time[data-last-heard]').forEach(el => {
        el.textContent = timeAgo(parseFloat(el.dataset.lastHeard || '0'));
    });
}

function fitMobileMap() {
    if (!S.map) return;
    const points = [];
    if (S.myPos) points.push(S.myPos);
    Object.values(S.rfStations).forEach(st => {
        if (window.pvUI.validPosition(st.latitude, st.longitude)) points.push([st.latitude, st.longitude]);
    });
    Object.values(S.isStations).forEach(st => {
        if (window.pvUI.validPosition(st.latitude, st.longitude)) points.push([st.latitude, st.longitude]);
    });
    if (points.length >= 2) {
        S.map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 11 });
    } else if (points.length === 1) {
        S.map.setView(points[0], 9);
    }
}

// ── Propagation ────────────────────────────────────────────
function updatePropDisplay(data) {
    if (!data) return;
    S.propData = data;
    const rf = data.rf_stations_1h || 0;
    const maxD = data.max_distance_km || 0;

    const state = data.evidence?.state;
    let level = (data.level || 'none').toUpperCase();
    const color = 'var(--accent-blue)';
    if (state === 'awaiting_live') level = 'HISTORY';
    if (state === 'no_data') level = 'NO DATA';
    if (state === 'stale') level = 'STALE';

    const el = $('m-prop-level');
    if (el) { el.textContent = level; el.style.color = color; }
    const lbl = $('m-prop-label');
    if (lbl) lbl.textContent = `${data.my_stations_1h || 0} direct / ${data.regional_stations_1h || 0} all RF in 1h \u00b7 ${fmtDist(maxD)} max`;

    const rft = $('m-rf-total'); if (rft) rft.textContent = rf;
    const md = $('m-max-dist'); if (md) md.textContent = fmtDist(maxD);
    const pc = $('m-pkt-count'); if (pc) pc.textContent = data.packets_1h || 0;
    updateHomeSummary();
}

async function loadLeaderboard() {
    try {
        const r = await fetch('/api/analytics/longest-paths?hours=24&limit=10');
        const d = await r.json();
        const body = $('m-leader-body');
        if (!body) return;
        if (!d.paths?.length) { body.innerHTML = '<tr><td colspan="3" style="color:var(--text-muted)">No data yet</td></tr>'; return; }
        body.innerHTML = d.paths.map((p, i) => `<tr>
            <td class="rank">${i + 1}</td>
            <td>${escHtml(p.callsign || p.station || '?')}</td>
            <td>${fmtDist(p.distance_km || p.max_distance_km || 0)}</td>
        </tr>`).join('');
    } catch { /* silent */ }
}

// ── Uptime ─────────────────────────────────────────────────
function syncServerUptime(status) {
    const elapsed = status.uptime_seconds;
    if (typeof elapsed !== 'number' || !Number.isFinite(elapsed) || elapsed < 0) return;
    S.startTime = Date.now() / 1000 - elapsed;
    updateUptime();
}

function updateUptime() {
    if (!S.startTime) return;
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - S.startTime));
    const days = Math.floor(diff / 86400);
    const h = Math.floor((diff % 86400) / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const el = $('m-uptime');
    const clock = [h, m, diff % 60].map(value => String(value).padStart(2, '0')).join(':');
    if (el) el.textContent = days ? `${String(days).padStart(2, '0')}:${clock}` : clock;
}

// ── Weather ────────────────────────────────────────────────
async function loadWeather() {
    try {
        const r = await fetch('/api/weather');
        const d = await r.json();
        const banner = $('m-wx-banner');
        const alertEl = $('m-wx-alert');

        if (d.current) {
            const c = d.current;
            const parts = [];
            if (c.temperature !== undefined) parts.push(`${Math.round(c.temperature)}\u00b0F`);
            if (c.description) parts.push(c.description);
            if (c.wind_speed !== undefined) parts.push(`Wind ${Math.round(c.wind_speed)} mph`);
            if (c.humidity !== undefined) parts.push(`${c.humidity}% RH`);
            if (parts.length) { banner.textContent = '\ud83c\udf24\ufe0f ' + parts.join(' \u00b7 '); banner.classList.add('vis'); }
        }

        if (d.alerts?.length) {
            const a = d.alerts[0];
            const severity = (a.severity || '').toLowerCase();
            alertEl.textContent = '\u26a0\ufe0f ' + (a.headline || a.event || 'Weather Alert');
            alertEl.className = 'wx-alert ' + (severity.includes('warning') ? 'warn' : 'watch');
            $('m-home-alert-card')?.classList.add('home-alert');
            const copy = $('m-home-prop-copy');
            if (copy) copy.textContent = a.headline || a.event || 'Weather alert active.';
        } else if (alertEl) {
            alertEl.className = 'wx-alert';
            $('m-home-alert-card')?.classList.remove('home-alert');
        }
    } catch { /* silent */ }
}

// ── WebSocket ──────────────────────────────────────────────
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws`;
    S.ws = new WebSocket(url);

    S.ws.onopen = () => {
        S.connected = true;
        $('m-ws-dot').classList.add('ok');
        updateAprsIsChip();
        renderStations();
        renderMessages();
    };

    S.ws.onclose = () => {
        S.connected = false;
        $('m-ws-dot').classList.remove('ok');
        updateAprsIsChip();
        renderStations();
        renderMessages();
        setTimeout(connectWS, 3000);
    };

    S.ws.onerror = () => S.ws.close();

    S.ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }

        switch (msg.type) {
            case 'status':
                handleStatus(msg.data);
                break;

            case 'initial_stations':
                S.stationsLoaded = true;
                (msg.rf || []).forEach(st => { st.source = 'rf'; S.rfStations[st.callsign] = st; if (S.mapReady) addMapMarker(st); });
                (msg.aprs_is || []).forEach(st => { st.source = 'aprs_is'; S.isStations[st.callsign] = st; if (S.mapReady) addMapMarker(st); });
                renderStations();
                break;

            case 'station_update':
                if (msg.station) {
                    S.stationsLoaded = true;
                    const st = msg.station;
                    if (st.source === 'rf') S.rfStations[st.callsign] = st;
                    else S.isStations[st.callsign] = st;
                    if (S.mapReady) addMapMarker(st);
                    renderStations();
                }
                break;

            case 'packet':
                if (msg.data && S.mapReady) animateMobilePacket(msg.data);
                break;

            case 'station_removed':
                if (msg.data) {
                    const { callsign, source } = msg.data;
                    if (source === 'rf') delete S.rfStations[callsign];
                    else delete S.isStations[callsign];
                    if (S.mapReady) removeMapMarker(callsign, source);
                    renderStations();
                }
                break;

            case 'propagation':
                if (msg.data) updatePropDisplay(msg.data);
                break;

            case 'gps_location':
                if (msg.data) handleGpsStatus(msg.data);
                break;

            case 'message':
                if (msg.data) {
                    upsertMessage(msg.data);
                    if (!S.selectedConversation) S.selectedConversation = conversationCall(msg.data);
                    if (S.activeTab !== 'mtab-messages' && msg.data.direction === 'rx' && msg.data.to?.toUpperCase() === S.myCall) {
                        S.unreadCount++;
                        updateBadge();
                    }
                    renderMessages();
                }
                break;

            case 'message_ack':
                if (msg.data) {
                    for (const m of S.messages) {
                        if (m.direction === 'tx' && m.message_id === msg.data.message_id &&
                            m.to?.toUpperCase() === (msg.data.from || '').toUpperCase()) {
                            m.acked = true; break;
                        }
                    }
                    renderMessages();
                }
                break;

            case 'message_rej':
                if (msg.data) {
                    for (const m of S.messages) {
                        if (m.direction === 'tx' && m.message_id === msg.data.message_id &&
                            m.to?.toUpperCase() === (msg.data.from || '').toUpperCase()) {
                            m.rejected = true; break;
                        }
                    }
                    renderMessages();
                }
                break;
        }
    };
}

function updateAprsIsChip() {
    const chip = $('m-is-chip');
    const text = $('m-is-text');
    if (!chip || !text) return;

    let state = 'offline';
    let label = 'Offline';

    if (!S.connected) {
        state = 'reconnecting';
        label = 'UI reconnect';
    } else if (S.aprsIsConnected && S.aprsIsVerified) {
        state = 'online';
        label = 'Connected';
    } else if (S.aprsIsConnected) {
        state = 'read-only';
        label = 'Read-only';
    } else {
        state = 'offline';
        label = 'Disconnected';
    }

    chip.classList.remove('online', 'read-only', 'reconnecting', 'offline');
    chip.classList.add(state);
    text.textContent = label;
    updateHomeSummary();
}

function handleStatus(data) {
    if (!data) return;
    S.myCall = (data.station_info?.callsign || data.station || '').toUpperCase();
    $('m-call').textContent = S.myCall || '—';
    syncServerUptime(data);
    S.aprsIsConnected = !!data.aprs_is_connected;
    S.aprsIsVerified = !!data.aprs_is_verified;
    updateAprsIsChip();
    updateHomeSummary();

    handleGpsStatus(data.gps);

    const gpsCurrent = data.gps?.current;
    const gpsDrivesMap = !!(data.gps?.enabled && data.gps?.map_update_enabled && gpsCurrent);
    const lat = gpsDrivesMap ? gpsCurrent.latitude : (data.station_info?.latitude ?? data.latitude);
    const lng = gpsDrivesMap ? gpsCurrent.longitude : (data.station_info?.longitude ?? data.longitude);
    if (lat && lng && lat !== 0) {
        S.myPos = [lat, lng];
        if (S.mapReady && !S.myMarker) {
            S.myMarker = L.circleMarker(S.myPos, {
                radius: 8, color: '#3fb950', fillColor: '#3fb950', fillOpacity: 0.6, weight: 2,
            }).addTo(S.map).bindPopup(`<b style="color:#3fb950">${escHtml(S.myCall)}</b><br>My Station`);
            S.map.setView(S.myPos, 8);
        } else if (S.mapReady && S.myMarker) {
            S.myMarker.setLatLng(S.myPos);
        }
        if (S.mapReady) redrawAllLines();
    }
}

function handleGpsStatus(gps) {
    if (!gps?.current || !gps.enabled || !gps.map_update_enabled) return;
    S.myPos = [gps.current.latitude, gps.current.longitude];
    if (S.mapReady && S.myMarker) {
        S.myMarker.setLatLng(S.myPos);
    }
    if (S.mapReady) redrawAllLines();
}

function toggleMobileGps() {
    const btn = $('m-btn-gps');
    if (S.gpsWatchId !== null) {
        navigator.geolocation.clearWatch(S.gpsWatchId);
        S.gpsWatchId = null;
        if (btn) btn.textContent = 'Share GPS';
        return;
    }
    if (!navigator.geolocation) {
        alert('This browser does not support geolocation.');
        return;
    }
    S.gpsWatchId = navigator.geolocation.watchPosition(async (position) => {
        const now = Date.now();
        if (now - S.lastGpsPost < 5000) return;
        S.lastGpsPost = now;
        try {
            const resp = await fetch('/api/gps/location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source: 'browser',
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy_m: position.coords.accuracy,
                }),
            });
            const result = await resp.json();
            if (result.success) handleGpsStatus(result.gps);
        } catch { /* keep watching */ }
    }, (error) => {
        alert(error.message || 'GPS permission denied.');
    }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 });
    if (btn) btn.textContent = 'Stop GPS';
}

// ── Init ───────────────────────────────────────────────────
async function init() {
    await window.pvOperator.ready;
    applySavedUITheme();
    S.activeTab = localStorage.getItem(MOBILE_TAB_KEY) || S.activeTab;
    if (!['mtab-home', 'mtab-messages', 'mtab-map', 'mtab-stations', 'mtab-prop', 'mtab-about'].includes(S.activeTab)) {
        S.activeTab = 'mtab-home';
    }
    S.msgFilter = localStorage.getItem(MOBILE_MSG_FILTER_KEY) || S.msgFilter;
    S.msgSort = localStorage.getItem(MOBILE_MSG_SORT_KEY) || S.msgSort;
    S.mapTheme = localStorage.getItem(MOBILE_MAP_THEME_KEY) === 'light' ? 'light' : 'dark';
    if ($('m-msg-sort')) $('m-msg-sort').value = S.msgSort;
    updateMapThemeButton();
    syncMsgFilterButtons();
    try {
        const r = await fetch('/api/config');
        const d = await r.json();
        S.config = d;
        S.ghostMinutes = d.web?.ghost_after_minutes ?? 60;
        S.animationMode = ['off', 'basic', 'enhanced'].includes(d.web?.visual_packet_animation) ? d.web.visual_packet_animation : 'basic';
        S.motionEnabled = S.animationMode !== 'off';
        updateMobileMotionButton();
    } catch { /* silent */ }
    activateTab(S.activeTab);
    renderMessages();
    renderStations();
    connectWS();

    await loadMobileMessages();

    // Load version
    try {
        const r = await fetch('/api/version');
        const d = await r.json();
        $('m-version').textContent = 'Version ' + (d.version || '?');
    } catch { /* silent */ }

    // Weather
    loadWeather();
    setInterval(loadWeather, 300000);

    // Periodic refreshes
    setInterval(updateUptime, 1000);
    setInterval(refreshStationTimes, 15000);
    setInterval(ghostStaleMarkers, 30000);
}

$('m-btn-center').addEventListener('click', () => {
    activateTab('mtab-map');
    if (S.myPos && S.map) {
        S.map.setView(S.myPos, 8);
        if (S.myMarker) S.myMarker.openPopup();
    }
});

$('m-btn-gps').addEventListener('click', toggleMobileGps);
$('m-btn-lines')?.addEventListener('click', () => setLinesVisible(!S.showLines));
$('m-map-lines')?.addEventListener('click', () => setLinesVisible(!S.showLines));
$('m-map-theme-dark')?.addEventListener('click', () => setMobileMapTheme('dark'));
$('m-map-theme-light')?.addEventListener('click', () => setMobileMapTheme('light'));
$('m-map-fit')?.addEventListener('click', fitMobileMap);
$('m-map-motion')?.addEventListener('click', () => {
    if (S.animationMode === 'off') return;
    S.motionEnabled = !S.motionEnabled;
    if (!S.motionEnabled) {
        S.animationFlows = [];
        if (S.animationFrame) cancelAnimationFrame(S.animationFrame);
        S.animationFrame = null;
        if (S.animationContext && S.map) {
            const size = S.map.getSize();
            S.animationContext.clearRect(0, 0, size.x, size.y);
        }
    }
    updateMobileMotionButton();
});

window.addEventListener('storage', event => {
    if (event.key === DESKTOP_UI_STATE_KEY) applySavedUITheme();
});
window.addEventListener('pageshow', applySavedUITheme);
document.addEventListener('DOMContentLoaded', init);
