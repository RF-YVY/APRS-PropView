/* Illustrated first-run guide. Progress is stored only in this browser. */
(function () {
    'use strict';

    const STORAGE_KEY = 'pvQuickStartSeenV1';
    let step = 0;
    let openedFromFirstRun = false;
    let previousFocus = null;

    function elements() {
        return {
            modal: document.getElementById('quick-start-modal'),
            pages: Array.from(document.querySelectorAll('.quick-start-page')),
            dots: document.getElementById('quick-start-dots'),
            progress: document.getElementById('quick-start-progress-text'),
            back: document.getElementById('quick-start-back'),
            next: document.getElementById('quick-start-next'),
            skip: document.getElementById('quick-start-skip'),
            close: document.getElementById('quick-start-close'),
        };
    }

    function wasSeen() {
        try {
            return localStorage.getItem(STORAGE_KEY) === '1';
        } catch {
            return false;
        }
    }

    function remember() {
        try {
            localStorage.setItem(STORAGE_KEY, '1');
        } catch {
            // The guide still works when browser storage is unavailable.
        }
    }

    function render() {
        const ui = elements();
        if (!ui.modal || !ui.pages.length) return;
        step = Math.max(0, Math.min(ui.pages.length - 1, step));
        ui.pages.forEach((page, index) => {
            const active = index === step;
            page.classList.toggle('active', active);
            page.hidden = !active;
        });
        ui.dots.innerHTML = ui.pages.map((_, index) =>
            `<span class="quick-start-dot${index === step ? ' active' : ''}"></span>`
        ).join('');
        ui.progress.textContent = `Step ${step + 1} of ${ui.pages.length}`;
        ui.back.disabled = step === 0;
        ui.next.textContent = step === ui.pages.length - 1 ? 'Open Settings' : 'Next';
        ui.skip.textContent = openedFromFirstRun ? 'Skip Guide' : 'Close Guide';
    }

    function open(options = {}) {
        const ui = elements();
        if (!ui.modal) return;
        previousFocus = document.activeElement;
        openedFromFirstRun = !!options.firstRun;
        step = 0;
        render();
        ui.modal.style.display = 'flex';
        document.body.classList.add('quick-start-open');
        window.setTimeout(() => ui.close?.focus(), 0);
    }

    function close({ openSettings = false } = {}) {
        const ui = elements();
        if (!ui.modal) return;
        remember();
        ui.modal.style.display = 'none';
        document.body.classList.remove('quick-start-open');
        if (openSettings) {
            document.querySelector('.tab-btn[data-tab="tab-settings"]')?.click();
        } else if (previousFocus?.focus) {
            previousFocus.focus();
        }
    }

    function bind() {
        const ui = elements();
        if (!ui.modal || !ui.pages.length) return;

        ui.back?.addEventListener('click', () => {
            step -= 1;
            render();
        });
        ui.next?.addEventListener('click', () => {
            if (step < ui.pages.length - 1) {
                step += 1;
                render();
                ui.next?.focus();
                return;
            }
            close({ openSettings: true });
        });
        ui.skip?.addEventListener('click', () => close());
        ui.close?.addEventListener('click', () => close());
        ui.modal.addEventListener('click', (event) => {
            if (event.target === ui.modal) close();
        });
        document.getElementById('btn-open-quick-start')?.addEventListener('click', () => open());
        document.getElementById('btn-help-quick-start')?.addEventListener('click', () => {
            const help = document.getElementById('help-modal');
            if (help) help.style.display = 'none';
            open();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || ui.modal.style.display === 'none') return;
            event.preventDefault();
            event.stopImmediatePropagation();
            close();
        }, true);

        if (!wasSeen()) {
            window.setTimeout(() => open({ firstRun: true }), 650);
        }
    }

    window.pvOnboarding = { open };
    document.addEventListener('DOMContentLoaded', bind);
})();
