/**
 * Alert audio controls and browser-side playback.
 */

window.pvAlertAudio = (function () {
    'use strict';

    const slots = [
        ['my_station_opening', 'My Station Band Opening'],
        ['regional_watch', 'Regional Band Watch'],
        ['first_heard', 'First-Heard Station'],
        ['anomaly', 'Propagation Anomaly'],
        ['sporadic_e', 'Sporadic-E'],
        ['message_received', 'APRS Message Received'],
        ['weather_warning', 'Weather Warning'],
        ['weather_watch', 'Weather Watch'],
    ];
    const fieldByKey = {
        my_station_opening: 'audio_my_station_opening_file',
        regional_watch: 'audio_regional_watch_file',
        first_heard: 'audio_first_heard_file',
        anomaly: 'audio_anomaly_file',
        sporadic_e: 'audio_sporadic_e_file',
        message_received: 'audio_message_received_file',
        weather_warning: 'audio_weather_warning_file',
        weather_watch: 'audio_weather_watch_file',
    };

    let hooks = {};

    function init(options = {}) {
        hooks = options;
        initControls();
    }

    function getVal(id) {
        if (hooks.getVal) return hooks.getVal(id);
        return document.getElementById(id)?.value || '';
    }

    function setVal(id, value) {
        if (hooks.setVal) return hooks.setVal(id, value);
        const el = document.getElementById(id);
        if (el) el.value = value ?? '';
    }

    function notify(message, type = 'info') {
        if (hooks.showSystemNotification) hooks.showSystemNotification(message, type);
    }

    function markDirty(message) {
        if (hooks.markSettingsDirty) hooks.markSettingsDirty(message);
    }

    function escapeHTML(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function config() {
        return hooks.getServerConfig?.() || {};
    }

    function getAudioUrl(alertKey) {
        const pendingFile = getVal(`cfg-alerts-audio-value-${alertKey}`);
        const file = pendingFile || config()?.alerts?.[fieldByKey[alertKey]];
        return file ? `/api/alert-audio/file/${encodeURIComponent(file)}` : '';
    }

    async function play(alertKey) {
        const url = getAudioUrl(alertKey);
        if (!url) {
            return { ok: false, message: 'No audio file is assigned.' };
        }
        try {
            const audio = new Audio(`${url}?t=${Date.now()}`);
            const deviceId = getVal('cfg-alerts-audio-device') || config()?.alerts?.audio_output_device_id || '';
            if (deviceId && typeof audio.setSinkId === 'function') {
                await audio.setSinkId(deviceId);
            }
            audio.volume = 1;
            await audio.play();
            return { ok: true, message: 'Audio played.' };
        } catch (e) {
            console.warn(`Unable to play ${alertKey} alert audio:`, e);
            return {
                ok: false,
                message: e?.message || 'Audio playback failed. Check browser audio permissions and output device.',
            };
        }
    }

    function initControls() {
        const container = document.getElementById('cfg-alerts-audio-slots');
        if (!container) return;
        container.innerHTML = slots.map(([key, label]) => `
            <div class="alert-audio-row" data-alert-audio-key="${key}">
                <div class="alert-audio-name">${escapeHTML(label)}</div>
                <div class="alert-audio-file" id="cfg-alerts-audio-file-${key}">Silent</div>
                <input type="hidden" id="cfg-alerts-audio-value-${key}">
                <input type="file" id="cfg-alerts-audio-pick-${key}" accept=".wav,.mp3,audio/wav,audio/mpeg">
                <button type="button" class="settings-toolbar-btn" id="cfg-alerts-audio-test-${key}">Test</button>
                <button type="button" class="settings-toolbar-btn" id="cfg-alerts-audio-clear-${key}">Clear</button>
                <div class="alert-audio-status" id="cfg-alerts-audio-status-${key}" aria-live="polite"></div>
            </div>
        `).join('');

        slots.forEach(([key]) => {
            document.getElementById(`cfg-alerts-audio-pick-${key}`)?.addEventListener('change', (e) => {
                const file = e.target.files?.[0];
                if (file) upload(key, file);
                e.target.value = '';
            });
            document.getElementById(`cfg-alerts-audio-test-${key}`)?.addEventListener('click', () => {
                testSlot(key);
            });
            document.getElementById(`cfg-alerts-audio-clear-${key}`)?.addEventListener('click', () => {
                setSlot(key, '');
                setStatus(key, 'Silent');
                markDirty('Unsaved audio setting. Save Configuration to keep this change.');
            });
        });
    }

    function setSlot(key, filename) {
        setVal(`cfg-alerts-audio-value-${key}`, filename || '');
        const label = document.getElementById(`cfg-alerts-audio-file-${key}`);
        if (label) {
            label.textContent = filename || 'Silent';
            label.title = filename || 'No audio file selected';
        }
        const testBtn = document.getElementById(`cfg-alerts-audio-test-${key}`);
        if (testBtn) testBtn.disabled = !filename;
        setStatus(key, filename ? 'Ready to test' : 'Silent');
    }

    function setStatus(key, message, state = '') {
        const el = document.getElementById(`cfg-alerts-audio-status-${key}`);
        if (!el) return;
        el.textContent = message || '';
        el.classList.toggle('error', state === 'error');
        el.classList.toggle('ok', state === 'ok');
    }

    async function testSlot(key) {
        setStatus(key, 'Playing...');
        const result = await play(key);
        const slot = slots.find(([slotKey]) => slotKey === key);
        const label = slot?.[1] || 'Alert audio';
        if (result.ok) {
            setStatus(key, 'Audio played', 'ok');
            notify(`${label} test played.`, 'info');
        } else {
            setStatus(key, result.message, 'error');
            notify(`${label} test failed: ${result.message}`, 'error');
        }
    }

    async function upload(key, file) {
        const statusEl = document.getElementById('settings-status');
        if (!/\.(wav|mp3)$/i.test(file.name || '')) {
            notify('Select a .wav or .mp3 alert sound.', 'error');
            return;
        }
        try {
            setStatus(key, `Uploading ${file.name}...`);
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
            setSlot(key, result.filename || '');
            markDirty('Unsaved audio setting. Save Configuration to keep this change.');
            if (statusEl) {
                statusEl.className = 'settings-status success';
                statusEl.textContent = 'Audio uploaded. Save Configuration to keep this alert sound.';
            }
        } catch (e) {
            console.error('Alert audio upload failed:', e);
            setStatus(key, e.message || 'Audio upload failed.', 'error');
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

    async function refreshOutputDevices(selectedId) {
        const select = document.getElementById('cfg-alerts-audio-device');
        if (!select || !navigator.mediaDevices?.enumerateDevices) return;
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const outputs = devices.filter((device) => device.kind === 'audiooutput');
            const current = selectedId || select.value || '';
            select.innerHTML = '<option value="">System default</option>' + outputs.map((device, index) => {
                const label = device.label || `Audio output ${index + 1}`;
                return `<option value="${escapeHTML(device.deviceId)}">${escapeHTML(label)}</option>`;
            }).join('');
            if (current && outputs.some((device) => device.deviceId === current)) {
                select.value = current;
            }
        } catch (e) {
            console.warn('Unable to enumerate audio output devices:', e);
        }
    }

    return {
        slots,
        fieldByKey,
        init,
        play,
        setSlot,
        refreshOutputDevices,
    };
})();
