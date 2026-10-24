/* Activity profiles and packet formatting come from the authenticated server. */
(() => {
    'use strict';
    document.addEventListener('DOMContentLoaded', () => {
        const button = document.getElementById('btn-aprs-spot');
        if (!button) return;
        const dialog = document.createElement('dialog');
        dialog.id = 'aprs-spot-dialog';
        dialog.setAttribute('aria-labelledby', 'spot-title');
        dialog.innerHTML = `<form id="aprs-spot-form">
            <h2 id="spot-title">Send OTA Activity Spot</h2>
            <p>Enter your activation details. The activity supplies the destination and message format.</p>
            <div class="spot-grid">
                <label>Operator callsign<input name="callsign" required maxlength="6" autocomplete="off" spellcheck="false" autocapitalize="characters" placeholder="W1AW"></label>
                <label id="spot-activity-row">Activity<select name="activity"></select></label>
            </div>
            <fieldset id="spot-post-fields">
                <div class="spot-grid">
                    <label><span id="spot-reference-label">Park reference</span><input name="reference" required maxlength="30" autocomplete="off" spellcheck="false"></label>
                    <label>Frequency (MHz)<input name="frequency" required inputmode="decimal" placeholder="14.310" autocomplete="off"></label>
                    <label>Mode<select name="mode"></select></label>
                </div>
                <label>Comment (optional)<input name="comment" maxlength="67" autocomplete="off" placeholder="CQ from the park"></label>
            </fieldset>
            <details id="spot-more"><summary>+ more options</summary>
                <label>APSPOT feature<select name="action"><option value="post">Post an activation spot</option><option value="spots">Get current spots</option><option value="usage">Get service help / examples</option></select></label>
                <fieldset id="spot-lookup-fields" hidden disabled>
                    <div class="spot-grid">
                        <label>Mode filter<select name="filter_mode"></select></label>
                        <label>Maximum results (optional)<input name="count" type="number" min="1" max="999" step="1" placeholder="Default: 3"></label>
                    </div>
                    <p class="spot-help">The service returns up to the requested number of available spots. Lookup supports POTA, SOTA and WWFF.</p>
                </fieldset>
                <fieldset id="spot-help-fields" hidden disabled>
                    <div class="spot-grid">
                        <label>Help for<select name="help_type"><option value="">General help</option><option value="aprs">APRS</option><option value="sms">SMS</option><option value="winlink">Winlink</option></select></label>
                        <label>Activity example (optional)<select name="help_activity"><option value="">All / no example</option></select></label>
                    </div>
                    <p class="spot-help">Help is requested over APRS. Choose a type and activity to receive its example from APSPOT.</p>
                </fieldset>
                <label>Send via<select name="source"><option value="auto">Automatic (RF preferred)</option><option value="rf">RF only</option><option value="aprs_is">APRS-IS only</option></select></label>
                <label class="spot-test" id="spot-test-row"><input name="test" type="checkbox"> Test spot without publishing</label>
                <details><summary>Packet preview <span id="spot-count"></span></summary><pre id="spot-preview">Complete your details to preview the message.</pre></details>
            </details>
            <p id="spot-status" role="status" aria-live="polite"></p>
            <p class="spot-help">Sent as the operator callsign shown above; station settings stay unchanged. Replies appear in Messages. Spotting service registration and an APRS return path may be needed.</p>
            <div class="spot-actions"><button type="button" id="spot-replies">View replies</button><button type="button" id="spot-close">Close</button><button type="submit" class="btn-primary" id="spot-send" disabled>Send spot</button></div>
            <footer>Spotting service and command format: <a href="https://apspot.radio/" target="_blank" rel="noopener noreferrer">APSPOT by Josh, VK2MES</a> &middot; <a href="https://apspot.radio/getting-started/" target="_blank" rel="noopener noreferrer">Usage guide</a></footer>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector('form'), fields = form.elements;
        const status = dialog.querySelector('#spot-status'), send = dialog.querySelector('#spot-send');
        const preview = dialog.querySelector('#spot-preview');
        let generation = 0, timer, sending = false, options = null;
        const payload = () => ({action:fields.action.value, callsign:fields.callsign.value,
            activity:fields.activity.value, reference:fields.reference.value, frequency:fields.frequency.value,
            mode:fields.mode.value, comment:fields.comment.value, source:fields.source.value,
            test:fields.test.checked, filter_mode:fields.filter_mode.value, count:fields.count.value,
            help_type:fields.help_type.value, help_activity:fields.help_activity.value});
        function choices(select, values, emptyLabel) {
            const previous = select.value;
            select.replaceChildren(...(emptyLabel ? [new Option(emptyLabel, '')] : []), ...values.map(value => new Option(value.toUpperCase(), value)));
            if ([...select.options].some(option => option.value === previous)) select.value = previous;
        }
        function updateFields() {
            if (!options) return;
            const action = fields.action.value;
            choices(fields.activity, action === 'spots' ? options.lookup_activities : Object.keys(options.activities));
            const profile = options.activities[fields.activity.value];
            choices(fields.mode, profile.modes);
            choices(fields.filter_mode, profile.modes, 'All modes');
            fields.reference.placeholder = profile.example;
            dialog.querySelector('#spot-reference-label').textContent = profile.label;
            for (const [id, active] of [['spot-post-fields',action === 'post'],['spot-lookup-fields',action === 'spots'],['spot-help-fields',action === 'usage']]) {
                const group = dialog.querySelector('#' + id);
                group.hidden = !active; group.disabled = !active || sending;
            }
            dialog.querySelector('#spot-activity-row').hidden = action === 'usage';
            dialog.querySelector('#spot-test-row').hidden = action !== 'post';
            fields.help_activity.disabled = !fields.help_type.value || sending;
            if (!fields.help_type.value) fields.help_activity.value = '';
        }
        async function validate() {
            const current = ++generation;
            send.disabled = true;
            try {
                const response = await fetch('/api/spot/preview', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
                const data = await response.json();
                if (current !== generation || sending || !dialog.open) return;
                if (!response.ok) throw new Error(data.message || 'Sign in to prepare an APSPOT request.');
                preview.textContent = `${data.spot.callsign} > APSPOT\n${data.spot.text}`;
                dialog.querySelector('#spot-count').textContent = `(${data.spot.characters}/67)`;
                const kind = data.spot.action === 'post' ? (data.spot.test ? 'Test only: APSPOT will not publish this spot (message contains "test").' : 'Ready to post your spot.') : 'Ready to request a reply from APSPOT.';
                status.textContent = data.spot.can_send ? `${kind} ${data.spot.route_message}.` : data.spot.route_message;
                send.textContent = data.spot.action === 'post' ? (data.spot.test ? 'Send test spot' : 'Send spot') : 'Send request';
                send.disabled = !data.spot.can_send;
            } catch (error) {
                if (current === generation) {
                    status.textContent = error.message;
                    preview.textContent = 'Complete valid details to preview the message.';
                    dialog.querySelector('#spot-count').textContent = '';
                }
            }
        }
        form.addEventListener('input', event => {
            ++generation; send.disabled = true; clearTimeout(timer);
            if ([fields.action,fields.activity,fields.help_type].includes(event.target)) updateFields();
            timer = setTimeout(validate, 200);
        });
        button.addEventListener('click', async () => {
            await window.pvOperator.ready;
            if (!window.pvOperator.authenticated) return window.pvOperator.openLogin();
            dialog.showModal(); send.disabled = true;
            status.textContent = 'Preparing APSPOT options...';
            try {
                const response = await fetch('/api/spot/options');
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || 'Sign in to prepare an APSPOT request.');
                options = data;
                fields.callsign.value = data.callsign;
                choices(fields.help_activity,Object.keys(options.activities),'All / no example');
                updateFields(); validate();
                fields.callsign.focus();
            } catch (error) { status.textContent = error.message; }
        });
        dialog.querySelector('#spot-close').onclick = () => dialog.close();
        dialog.querySelector('#spot-replies').onclick = () => { dialog.close(); window.pvMessages?.startNewMessage('APSPOT'); };
        dialog.addEventListener('close', () => { ++generation; clearTimeout(timer); });
        dialog.addEventListener('cancel', event => { if (sending) event.preventDefault(); });
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (sending || send.disabled) return;
            sending = true; ++generation; clearTimeout(timer);
            const body = payload();
            [...fields].forEach(field => field.disabled = true);
            status.textContent = 'Sending to APSPOT...';
            try {
                const response = await fetch('/api/spot/send', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || 'Send failed.');
                status.textContent = `Sent as ${data.spot.callsign}. Check Messages for APSPOT replies. Change the callsign to spot another operator.`;
            } catch (error) { status.textContent = error.message + ' Check Messages before retrying.'; }
            finally {
                sending = false;
                [...fields].forEach(field => field.disabled = false);
                updateFields(); send.disabled = true;
            }
        });
    });
})();
