/**
 * APRS Messaging — send/receive APRS messages with alert banner.
 */

window.pvMessages = (function () {
    'use strict';

    let messages = [];
    let myCallsign = '';

    function init() {
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
        });

        // Filter change
        document.getElementById('msg-filter')?.addEventListener('change', renderMessages);

        // Clear button
        document.getElementById('btn-clear-msgs')?.addEventListener('click', () => {
            messages = [];
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

        // Char counter
        document.getElementById('msg-text')?.addEventListener('input', (e) => {
            const len = e.target.value.length;
            e.target.title = `${len}/67 characters`;
        });
    }

    function switchToMessagesTab() {
        // Deactivate all
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        // Activate messages tab
        const btn = document.querySelector('.tab-btn[data-tab="tab-messages"]');
        if (btn) btn.classList.add('active');
        document.getElementById('tab-messages')?.classList.add('active');
    }

    async function loadMessages() {
        try {
            const resp = await fetch('/api/messages?limit=500');
            const data = await resp.json();
            if (data.messages) {
                messages = data.messages;
                renderMessages();
            }
        } catch (e) {
            console.error('Failed to load messages:', e);
        }
    }

    function addMessage(msg) {
        if (!msg) return;

        // Update my callsign from statusbar
        const callEl = document.getElementById('station-call');
        if (callEl) myCallsign = callEl.textContent.toUpperCase();

        messages.unshift(msg);

        // Show alert banner for messages addressed to us
        if (
            msg.direction === 'rx' &&
            msg.to &&
            msg.to.toUpperCase() === myCallsign
        ) {
            showBanner(msg.from, msg.text);
        }

        renderMessages();
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

        if (!to) { toEl.focus(); return; }
        if (!text) { textEl.focus(); return; }

        btn.disabled = true;

        try {
            const resp = await fetch('/api/messages/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ to, text }),
            });
            const result = await resp.json();

            if (result.success) {
                textEl.value = '';
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

    function renderMessages() {
        const list = document.getElementById('msg-list');
        const countEl = document.getElementById('msg-count');
        if (!list) return;

        // Update my callsign
        const callEl = document.getElementById('station-call');
        if (callEl) myCallsign = callEl.textContent.toUpperCase();

        const filter = document.getElementById('msg-filter')?.value || 'all';
        let filtered = messages;

        if (filter === 'mine') {
            filtered = messages.filter(m =>
                m.from?.toUpperCase() === myCallsign ||
                m.to?.toUpperCase() === myCallsign
            );
        } else if (filter === 'rx') {
            filtered = messages.filter(m => m.direction === 'rx');
        } else if (filter === 'tx') {
            filtered = messages.filter(m => m.direction === 'tx');
        }

        if (countEl) countEl.textContent = `${filtered.length} messages`;

        if (filtered.length === 0) {
            list.innerHTML = '<div class="msg-empty">No messages yet. Send a message or wait for incoming messages.</div>';
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
            const sourceTag = msg.source === 'rf' ? 'RF' : (msg.source === 'aprs_is' ? 'IS' : 'TX');

            let statusIcon = '';
            if (isMine) {
                if (msg.acked) statusIcon = '<span class="msg-status acked" title="Acknowledged">✓</span>';
                else if (msg.rejected) statusIcon = '<span class="msg-status rejected" title="Rejected">✗</span>';
                else statusIcon = '<span class="msg-status pending" title="Pending ACK">⏳</span>';
            }

            return `
                <div class="msg-item ${dirClass}">
                    <div class="msg-header">
                        <span class="msg-dir">${dirIcon}</span>
                        <span class="msg-from">${escHtml(msg.from || '?')}</span>
                        <span class="msg-arrow">→</span>
                        <span class="msg-to">${escHtml(msg.to || '?')}</span>
                        ${statusIcon}
                        <span class="msg-source-tag ${sourceTag.toLowerCase()}">${sourceTag}</span>
                        <span class="msg-time" title="${dateStr} ${timeStr}">${timeStr}</span>
                    </div>
                    <div class="msg-body">${escHtml(msg.text || '')}</div>
                </div>
            `;
        }).join('');
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
    };
})();
