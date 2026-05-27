/**
 * APRS Messaging — send/receive APRS messages with alert banner.
 */

window.pvMessages = (function () {
    'use strict';

    let messages = [];
    let contacts = [];
    let myCallsign = '';
    let hasLoadedInitialMessages = false;
    let replyContext = null;
    let selectedConversation = '';
    let readTimestamps = {};
    const READ_STORAGE_KEY = 'aprsPropViewMessageReadTimestamps';
    const SORT_STORAGE_KEY = 'aprsPropViewMessageSortOrder';

    function init() {
        loadReadTimestamps();

        // Send button
        document.getElementById('btn-send-msg')?.addEventListener('click', sendMessage);

        // Enter key to send
        document.getElementById('msg-text')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Force callsign uppercase
        document.getElementById('msg-to-call')?.addEventListener('input', (e) => {
            const start = e.target.selectionStart;
            const end = e.target.selectionEnd;
            e.target.value = e.target.value.toUpperCase();
            e.target.setSelectionRange(start, end);
            if (replyContext && e.target.value.trim().toUpperCase() !== replyContext.to) {
                replyContext = null;
            }
        });

        // Filter change
        document.getElementById('msg-filter')?.addEventListener('change', renderMessages);
        const sortEl = document.getElementById('msg-sort-order');
        if (sortEl) {
            sortEl.value = localStorage.getItem(SORT_STORAGE_KEY) || 'desc';
            sortEl.addEventListener('change', () => {
                localStorage.setItem(SORT_STORAGE_KEY, sortEl.value || 'desc');
                renderMessages({ scrollToLatest: true });
            });
        }
        document.getElementById('btn-save-contact')?.addEventListener('click', saveCurrentContact);

        document.getElementById('msg-contact-list')?.addEventListener('click', (e) => {
            const item = e.target.closest('.msg-contact-item');
            if (!item) return;
            const callsign = item.dataset.callsign || '';
            if (e.target.closest('.msg-contact-delete')) {
                e.stopPropagation();
                deleteContact(callsign);
                return;
            }
            const toEl = document.getElementById('msg-to-call');
            const textEl = document.getElementById('msg-text');
            selectConversation(callsign);
            if (toEl) toEl.value = callsign;
            if (textEl) textEl.focus();
        });

        // Clear button — clear on server and locally
        document.getElementById('btn-clear-msgs')?.addEventListener('click', async () => {
            try {
                await fetch('/api/messages', { method: 'DELETE' });
            } catch (e) {
                console.error('Failed to clear messages on server:', e);
            }
            messages = [];
            hasLoadedInitialMessages = true;
            selectedConversation = '';
            readTimestamps = {};
            saveReadTimestamps();
            renderContacts();
            renderMessages();
        });

        // Alert banner click — navigate to messages tab
        document.getElementById('msg-alert-banner')?.addEventListener('click', (e) => {
            if (e.target.id === 'msg-alert-close') {
                hideBanner();
                return;
            }
            switchToMessagesTab();
        });

        // Alert banner close button
        document.getElementById('msg-alert-close')?.addEventListener('click', (e) => {
            e.stopPropagation();
            hideBanner();
        });

        // Click message to populate TO CALL for reply
        document.getElementById('msg-list')?.addEventListener('click', (e) => {
            const item = e.target.closest('.msg-item');
            if (!item) return;
            const fromCall = item.dataset.replyCall;
            if (!fromCall) return;
            const toEl = document.getElementById('msg-to-call');
            const textEl = document.getElementById('msg-text');
            if (toEl) {
                toEl.value = fromCall.toUpperCase();
                replyContext = {
                    to: fromCall.toUpperCase(),
                    source: item.dataset.replySource || '',
                };
                if (textEl) textEl.focus();
            }
        });

        // Char counter
        document.getElementById('msg-text')?.addEventListener('input', (e) => {
            const len = e.target.value.length;
            e.target.title = `${len}/67 characters`;
        });
    }

    function switchToMessagesTab() {
        if (typeof window.pvActivateTab === 'function') {
            window.pvActivateTab('tab-messages');
            return;
        }

        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const btn = document.querySelector('.tab-btn[data-tab="tab-messages"]');
        if (btn) btn.classList.add('active');
        document.getElementById('tab-messages')?.classList.add('active');
    }

    async function loadMessages() {
        try {
            loadReadTimestamps();
            const [resp, contactResp] = await Promise.all([
                fetch('/api/messages?limit=500'),
                fetch('/api/messages/contacts'),
            ]);
            const data = await resp.json();
            const contactData = await contactResp.json();
            if (data.messages) {
                messages = data.messages;
                hasLoadedInitialMessages = true;
            }
            contacts = contactData.contacts || [];
            renderContacts();
            renderMessages();
        } catch (e) {
            console.error('Failed to load messages:', e);
            hasLoadedInitialMessages = true;
            renderMessages();
        }
    }

    function addMessage(msg) {
        if (!msg) return;

        refreshMyCallsign();

        const followLatest = shouldFollowLatestForMessage(msg);
        const isNew = upsertLocalMessage(msg);
        hasLoadedInitialMessages = true;
        if (selectedConversation && conversationCall(msg) === selectedConversation) {
            markConversationRead(selectedConversation);
        }
        if (isNew) refreshContacts();
        renderMessages({ scrollToLatest: followLatest });

        // Show alert banner for messages addressed to us
        if (
            msg.direction === 'rx' &&
            msg.to &&
            msg.to.toUpperCase() === myCallsign
        ) {
            showBanner(msg.from, msg.text);
        }

    }

    function normalizeCall(value) {
        return (value || '').trim().toUpperCase();
    }

    function refreshMyCallsign() {
        const callEl = document.getElementById('station-call');
        if (callEl) myCallsign = normalizeCall(callEl.textContent);
    }

    function loadReadTimestamps() {
        try {
            const raw = localStorage.getItem(READ_STORAGE_KEY);
            readTimestamps = raw ? JSON.parse(raw) : {};
        } catch (e) {
            readTimestamps = {};
        }
    }

    function saveReadTimestamps() {
        try {
            localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(readTimestamps));
        } catch (e) {
            // Non-critical; unread badges can fall back to the current session.
        }
    }

    function conversationCall(msg) {
        const from = normalizeCall(msg.from);
        const to = normalizeCall(msg.to);
        if (msg.direction === 'tx') return to;
        if (from && from !== myCallsign) return from;
        return to === myCallsign ? from : to;
    }

    function getConversationMessages(callsign) {
        const call = normalizeCall(callsign);
        if (!call) return [];
        return messages.filter(msg => conversationCall(msg) === call);
    }

    function hasUnread(callsign) {
        const call = normalizeCall(callsign);
        if (!call) return false;
        const readAt = Number(readTimestamps[call] || 0);
        return messages.some(msg =>
            msg.direction === 'rx' &&
            conversationCall(msg) === call &&
            normalizeCall(msg.to) === myCallsign &&
            Number(msg.timestamp || 0) > readAt
        );
    }

    function markConversationRead(callsign) {
        const call = normalizeCall(callsign);
        if (!call) return;
        const newest = getConversationMessages(call).reduce(
            (maxTs, msg) => Math.max(maxTs, Number(msg.timestamp || 0)),
            Math.floor(Date.now() / 1000)
        );
        readTimestamps[call] = newest;
        saveReadTimestamps();
    }

    function selectConversation(callsign) {
        selectedConversation = normalizeCall(callsign);
        if (!selectedConversation) return;
        const toEl = document.getElementById('msg-to-call');
        if (toEl) toEl.value = selectedConversation;
        markConversationRead(selectedConversation);
        renderContacts();
        renderMessages({ scrollToLatest: true });
    }

    function messageKey(msg) {
        const from = (msg.from || '').toUpperCase();
        const to = (msg.to || '').toUpperCase();
        if (msg.direction === 'tx' && msg.message_id) return `tx:${from}|${to}|${msg.message_id}`;
        if (msg.message_id) return `rx:${from}|${to}|${msg.message_id}`;
        return `${msg.direction || 'rx'}:${from}|${to}|${msg.text || ''}`;
    }

    function upsertLocalMessage(msg) {
        const key = messageKey(msg);
        const index = messages.findIndex(existing => messageKey(existing) === key);
        if (index >= 0) {
            messages[index] = { ...messages[index], ...msg };
            return false;
        }
        messages.unshift(msg);
        return true;
    }

    function handleAck(data) {
        if (!data) return;
        for (const msg of messages) {
            if (
                msg.direction === 'tx' &&
                msg.message_id === data.message_id &&
                msg.to.toUpperCase() === (data.from || '').toUpperCase()
            ) {
                msg.acked = true;
                break;
            }
        }
        renderMessages();
    }

    function handleRej(data) {
        if (!data) return;
        for (const msg of messages) {
            if (
                msg.direction === 'tx' &&
                msg.message_id === data.message_id &&
                msg.to.toUpperCase() === (data.from || '').toUpperCase()
            ) {
                msg.rejected = true;
                break;
            }
        }
        renderMessages();
    }

    async function sendMessage() {
        const toEl = document.getElementById('msg-to-call');
        const textEl = document.getElementById('msg-text');
        const btn = document.getElementById('btn-send-msg');
        if (!toEl || !textEl) return;

        const to = toEl.value.trim().toUpperCase();
        const text = textEl.value.trim();
        const replySource = replyContext && replyContext.to === to ? replyContext.source : '';

        if (!to) { toEl.focus(); return; }
        if (!text) { textEl.focus(); return; }

        btn.disabled = true;

        try {
            const resp = await fetch('/api/messages/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ to, text, reply_source: replySource || undefined }),
            });
            const result = await resp.json();

            if (result.success) {
                textEl.value = '';
                replyContext = null;
                selectConversation(to);
                textEl.focus();
            } else {
                alert(result.message || 'Failed to send message.');
            }
        } catch (e) {
            console.error('Failed to send message:', e);
            alert('Network error sending message.');
        } finally {
            btn.disabled = false;
        }
    }

    async function saveCurrentContact() {
        const toEl = document.getElementById('msg-to-call');
        const callsign = (toEl?.value || '').trim().toUpperCase();
        if (!callsign) {
            toEl?.focus();
            return;
        }
        try {
            const resp = await fetch('/api/messages/contacts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ callsign }),
            });
            const result = await resp.json();
            if (!result.success) {
                alert(result.message || 'Unable to save contact.');
                return;
            }
            await refreshContacts();
        } catch (e) {
            console.error('Failed to save contact:', e);
            alert('Network error saving contact.');
        }
    }

    async function deleteContact(callsign) {
        if (!callsign) return;
        try {
            await fetch(`/api/messages/contacts/${encodeURIComponent(callsign)}`, { method: 'DELETE' });
            contacts = contacts.filter(c => c.callsign !== callsign);
            if (selectedConversation === normalizeCall(callsign)) {
                selectedConversation = contacts.length ? normalizeCall(contacts[0].callsign) : '';
                markConversationRead(selectedConversation);
            }
            renderContacts();
            renderMessages();
        } catch (e) {
            console.error('Failed to delete contact:', e);
            alert('Network error deleting contact.');
        }
    }

    async function refreshContacts() {
        try {
            const resp = await fetch('/api/messages/contacts');
            const data = await resp.json();
            contacts = data.contacts || [];
            renderContacts();
        } catch (e) {
            console.error('Failed to refresh contacts:', e);
        }
    }

    function renderContacts() {
        refreshMyCallsign();
        const list = document.getElementById('msg-contact-list');
        const options = document.getElementById('msg-contact-options');
        if (options) {
            options.innerHTML = contacts.map(c => `<option value="${escHtml(c.callsign)}">${escHtml(c.display_name || '')}</option>`).join('');
        }
        if (!list) return;
        if (!contacts.length) {
            list.innerHTML = '<div class="msg-contact-empty">No contacts</div>';
            return;
        }
        list.innerHTML = contacts.map(c => `
            <div class="msg-contact-item ${normalizeCall(c.callsign) === selectedConversation ? 'active' : ''}" data-callsign="${escHtml(c.callsign)}">
                <button class="msg-contact-call" title="Message ${escHtml(c.callsign)}">
                    <span class="msg-contact-name">${escHtml(c.callsign)}</span>
                    ${hasUnread(c.callsign) ? '<span class="msg-unread-badge" title="Unread message">New</span>' : ''}
                </button>
                <button class="msg-contact-delete" title="Delete contact" aria-label="Delete ${escHtml(c.callsign)}">x</button>
            </div>
        `).join('');
    }

    function renderMessages(options = {}) {
        const list = document.getElementById('msg-list');
        const countEl = document.getElementById('msg-count');
        if (!list) return;

        refreshMyCallsign();

        const filter = document.getElementById('msg-filter')?.value || 'all';
        const conversation = selectedConversation;
        let filtered = getConversationMessages(conversation);

        if (filter === 'mine') {
            filtered = filtered.filter(m =>
                m.from?.toUpperCase() === myCallsign ||
                m.to?.toUpperCase() === myCallsign
            );
        } else if (filter === 'rx') {
            filtered = filtered.filter(m => m.direction === 'rx');
        } else if (filter === 'tx') {
            filtered = filtered.filter(m => m.direction === 'tx');
        }
        const sortOrder = document.getElementById('msg-sort-order')?.value || 'desc';
        filtered = filtered.slice().sort((a, b) => {
            const diff = Number(a.timestamp || 0) - Number(b.timestamp || 0);
            return sortOrder === 'asc' ? diff : -diff;
        });

        if (countEl) countEl.textContent = `${filtered.length} messages`;

        if (filtered.length === 0) {
            if (!hasLoadedInitialMessages) {
                list.innerHTML = '<div class="empty-state loading"><div class="empty-state-title">Loading messages</div><div class="empty-state-copy">Checking recent APRS message history and waiting for live traffic.</div></div>';
                return;
            }
            if (!conversation) {
                list.innerHTML = '<div class="empty-state"><div class="empty-state-title">Select a station</div><div class="empty-state-copy">Choose a contact to view only that conversation.</div></div>';
                return;
            }
            const connected = !!window.pvWebSocket?.isConnected;
            const copy = connected
                ? `No messages with ${escHtml(conversation)} yet.`
                : 'The live connection is offline. Your message history will refresh when the app reconnects.';
            list.innerHTML = `<div class="empty-state"><div class="empty-state-title">No messages yet</div><div class="empty-state-copy">${copy}</div></div>`;
            return;
        }

        list.innerHTML = filtered.map(msg => {
            const isMine = msg.direction === 'tx';
            const isToMe = msg.to?.toUpperCase() === myCallsign;
            const ts = new Date((msg.timestamp || 0) * 1000);
            const timeStr = ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const dateStr = ts.toLocaleDateString([], { month: 'short', day: 'numeric' });

            const dirClass = isMine ? 'msg-tx' : (isToMe ? 'msg-rx-mine' : 'msg-rx');
            const dirIcon = isMine ? '📤' : '📥';
            const sourceTag = msg.source === 'rf' ? 'RF' : (msg.source === 'aprs_is' ? 'IS' : (msg.source === 'both' ? 'RF+IS' : 'TX'));
            const sourceClass = msg.source === 'rf' ? 'rf' : (msg.source === 'aprs_is' ? 'is' : 'tx');
            const replyCall = !isMine ? (msg.from || '') : '';
            const replySource = !isMine ? (msg.source || '') : '';

            let statusIcon = '';
            if (isMine) {
                if (msg.acked) statusIcon = '<span class="msg-status acked" title="Acknowledged">✓</span>';
                else if (msg.rejected) statusIcon = '<span class="msg-status rejected" title="Rejected">✗</span>';
                else statusIcon = '<span class="msg-status pending" title="Pending ACK">⏳</span>';
            }

            return `
                <div class="msg-item ${dirClass}" data-reply-call="${escHtml(replyCall)}" data-reply-source="${escHtml(replySource)}" title="Click to reply">
                    <div class="msg-header">
                        <span class="msg-dir">${dirIcon}</span>
                        <span class="msg-from">${escHtml(msg.from || '?')}</span>
                        <span class="msg-arrow">→</span>
                        <span class="msg-to">${escHtml(msg.to || '?')}</span>
                        ${statusIcon}
                        <span class="msg-source-tag ${sourceClass}">${sourceTag}</span>
                        <span class="msg-time" title="${dateStr} ${timeStr}">${timeStr}</span>
                    </div>
                    <div class="msg-body">${escHtml(msg.text || '')}</div>
                </div>
            `;
        }).join('');

        if (options.scrollToLatest) {
            scrollToLatestMessage();
        }
    }

    function shouldFollowLatestForMessage(msg) {
        if (!selectedConversation || conversationCall(msg) !== selectedConversation) return false;
        if (msg.direction === 'tx') return true;

        const list = document.getElementById('msg-list');
        if (!list) return true;

        const sortOrder = document.getElementById('msg-sort-order')?.value || 'desc';
        if (sortOrder === 'asc') {
            return list.scrollHeight - list.scrollTop - list.clientHeight < 48;
        }
        return list.scrollTop < 48;
    }

    function scrollToLatestMessage() {
        const list = document.getElementById('msg-list');
        if (!list) return;

        requestAnimationFrame(() => {
            const sortOrder = document.getElementById('msg-sort-order')?.value || 'desc';
            list.scrollTop = sortOrder === 'asc' ? list.scrollHeight : 0;
        });
    }

    // ── Alert Banner ───────────────────────────────────────────

    function showBanner(fromCall, previewText) {
        const banner = document.getElementById('msg-alert-banner');
        const callEl = document.getElementById('msg-alert-call');
        const previewEl = document.getElementById('msg-alert-preview');
        if (!banner) return;

        if (callEl) callEl.textContent = fromCall || '???';
        if (previewEl) previewEl.textContent = (previewText || '').substring(0, 50);

        banner.style.display = 'flex';
        banner.classList.add('msg-alert-flash');
        setTimeout(() => banner.classList.remove('msg-alert-flash'), 600);

        // Auto-hide after 30 seconds
        clearTimeout(banner._hideTimer);
        banner._hideTimer = setTimeout(() => hideBanner(), 30000);
    }

    function hideBanner() {
        const banner = document.getElementById('msg-alert-banner');
        if (banner) banner.style.display = 'none';
    }

    // ── Helpers ────────────────────────────────────────────────

    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return {
        init,
        loadMessages,
        addMessage,
        handleAck,
        handleRej,
        switchToMessagesTab,
        render: renderMessages,
    };
})();
