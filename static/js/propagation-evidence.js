/** Observation freshness and the evidence behind the propagation meters. */
(() => {
    let latest = null;
    let receiverStatus = null;
    let dialog;
    let baseline = null;
    window.pvHistoryQuery = () => new URLSearchParams({
        path_type: localStorage.getItem('pvHistoryPath') || 'direct',
        port: localStorage.getItem('pvHistoryPort') || ''
    }).toString();
    function render() {
        if (!latest || !dialog?.open) return;
        const data = latest, e = data.evidence || {};
        const directConfidence = e.confidence?.direct || {};
        const regionalConfidence = e.confidence?.regional || {};
        const lines = [
            `Observation state: ${(e.state || 'unknown').replaceAll('_', ' ')}`,
            `Receiver: ${receiverStatus?.rf_connected ? 'connected' : 'disconnected or unavailable'}`,
            `Direct evidence confidence: ${(directConfidence.level || 'unknown').toUpperCase()} (${directConfidence.score ?? 0}/100, ${directConfidence.sample_count ?? 0} stations). ${directConfidence.reason || ''}`,
            `Regional evidence confidence: ${(regionalConfidence.level || 'unknown').toUpperCase()} (${regionalConfidence.score ?? 0}/100, ${regionalConfidence.sample_count ?? 0} stations). ${regionalConfidence.reason || ''}`,
            `In the last ${e.window_minutes || 60} minutes: ${data.my_stations_1h || 0} direct stations; ${data.regional_stations_1h || 0} stations across all RF paths.`,
            `Longest direct reception: ${window.formatDist(data.my_max_distance_km || 0)}.`,
            e.last_rf_packet_age_seconds == null ? 'No RF packet received during this session.' : `Last RF packet: ${e.last_rf_packet_age_seconds} seconds before this sample.`,
            `Current session: ${e.observing_minutes || 0} minutes. Sample: ${new Date(data.timestamp*1000).toLocaleTimeString()}.`,
            baseline?.baseline_samples ? `Regional baseline for this hour: ${baseline.baseline_count_mean} stations, longest path ${window.formatDist(baseline.baseline_dist_mean || 0)} (${baseline.baseline_samples} samples).` : 'Regional baseline: insufficient historical samples.',
            e.score_basis || '', e.regional_definition || '',
            e.state === 'awaiting_live' ? 'Showing stored receptions; waiting for live RF during this session.' : '',
            'The score describes observed APRS activity. A quiet or disconnected receiver does not establish poor propagation.'
        ];
        dialog.querySelector('[data-evidence]').textContent = lines.join('\n\n');
    }
    window.pvEvidence = {
        update(data, status) { latest = data; receiverStatus = status; render(); },
        status(status) { receiverStatus = status; render(); }
    };
    document.addEventListener('DOMContentLoaded', () => {
        dialog = document.createElement('dialog');
        dialog.style.cssText = 'max-width:580px;background:var(--bg-panel,#161b22);color:var(--text-primary,#eee);border:1px solid #666;border-radius:12px;padding:24px';
        dialog.innerHTML = '<h2>Propagation evidence</h2><p data-evidence style="white-space:pre-line"></p><button type="button">Close</button>';
        dialog.querySelector('button').onclick = () => dialog.close();
        document.body.appendChild(dialog);
        for (const id of ['prop-meter-my','prop-meter-reg']) {
            const meter = document.getElementById(id);
            if (!meter) continue;
            meter.tabIndex = 0; meter.setAttribute('role','button');
            meter.setAttribute('aria-label','Explain propagation score and reception freshness');
            meter.title = 'Show supporting RF observations';
            meter.onclick = async () => {
                dialog.showModal(); render();
                try { const response = await fetch('/api/analytics/anomaly'); if (response.ok) baseline = await response.json(); } catch (_) {}
                render();
            };
            meter.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); meter.click(); } };
        }
    });
})();
