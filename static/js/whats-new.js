/* One update notice per installation/version, acknowledged by an operator. */
(() => {
    'use strict';
    let showing = false;
    let ready;
    const initialized = new Promise(resolve => { ready = resolve; });
    window.pvWhatsNew = { ready: initialized, get showing() { return showing; } };
    document.addEventListener('DOMContentLoaded', async () => {
        try {
            await window.pvOperator.ready;
            const response = await fetch('/api/whats-new', { cache: 'no-store' });
            if (!response.ok) return;
            const release = await response.json();
            if (!release.should_show || !Array.isArray(release.changes) || !release.changes.length) return;
            const dialog = document.createElement('dialog');
            dialog.id = 'whats-new-dialog';
            dialog.setAttribute('aria-labelledby', 'whats-new-title');
            const title = document.createElement('h2');
            title.id = 'whats-new-title';
            title.textContent = `What’s new in APRS PropView ${release.version}`;
            const copy = document.createElement('p');
            copy.textContent = 'Welcome to this release. Changes since the previous public version:';
            const changes = document.createElement('ul');
            for (const change of release.changes) {
                const item = document.createElement('li');
                item.textContent = change;
                changes.appendChild(item);
            }
            const error = document.createElement('p');
            error.setAttribute('role', 'alert');
            const done = document.createElement('button');
            done.type = 'button';
            done.textContent = 'Got it';
            dialog.append(title, copy);
            if (typeof release.changelog_url === 'string' && /^\/static\/releases\/v1\.13\.\d+\.html$/.test(release.changelog_url)) {
                const frame = document.createElement('iframe');
                frame.src = release.changelog_url;
                frame.title = 'Full release changelog since v1.11.1';
                frame.style.cssText = 'width:100%;height:55vh;border:1px solid #405361;border-radius:8px';
                dialog.append(frame);
            } else {
                dialog.append(changes);
            }
            dialog.append(error, done);
            document.body.appendChild(dialog);
            async function acknowledge() {
                if (done.disabled) return;
                done.disabled = true;
                try {
                    const response = await fetch('/api/whats-new/acknowledge', { method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ version: release.version }) });
                    if (!response.ok) throw new Error('Could not save dismissal. Sign in or try again.');
                    showing = false;
                    dialog.close();
                    dialog.remove();
                } catch (e) { error.textContent = e.message; }
                finally { done.disabled = false; }
            }
            done.addEventListener('click', acknowledge);
            dialog.addEventListener('cancel', event => { event.preventDefault(); acknowledge(); });
            showing = true;
            dialog.showModal();
        } catch (e) { console.warn('Release notes unavailable:', e); }
        finally { ready(); }
    });
})();
