/** Browser-local appearance preferences. User text is rendered only as text. */
(function () {
    'use strict';
    const KEY = 'pvAppearance';
    const VIEWS = ['tab-rf', 'tab-is', 'tab-packets', 'tab-messages', 'tab-prop', 'tab-analytics'];
    const PANELS = {
        event: ['Propagation event', 'prop-event-card'],
        conditions: ['Current conditions', 'prop-conditions-heading', 'prop-conditions-grid'],
        watched: ['Watched VHF paths', 'prop-watched-heading', 'watched-paths-panel'],
        distance: ['Distance distribution', 'prop-distance-heading', 'distance-chart'],
        history: ['Propagation history', 'prop-history-heading', 'prop-history-chart'],
        map: ['External map', 'prop-external-map-heading', 'dxview-map-coords'],
        context: ['Propagation context', 'space-weather-heading', 'space-weather-card', 'external-propagation-heading', 'external-propagation-card'],
        solar: ['Solar-terrestrial data', 'prop-solar-heading', 'prop-solar-widget'],
    };
    function normalize(value) {
        const input = value && typeof value === 'object' ? value : {};
        const order = Array.isArray(input.order) ? input.order.filter(id => VIEWS.includes(id)) : [];
        const unique = [...new Set([...order, ...VIEWS])];
        const hidden = Array.isArray(input.hidden) ? [...new Set(input.hidden.filter(id => VIEWS.includes(id)))] : [];
        return {
            label: typeof input.label === 'string' ? input.label.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 32) : '',
            order: unique,
            panels: [...new Set([...(Array.isArray(input.panels) ? input.panels.filter(id => Object.hasOwn(PANELS, id)) : []), ...Object.keys(PANELS)])],
            hidden: hidden.length < VIEWS.length ? hidden : [],
        };
    }
    document.addEventListener('DOMContentLoaded', () => {
        let state;
        try { state = normalize(JSON.parse(localStorage.getItem(KEY) || '{}')); }
        catch (_) { state = normalize({}); }
        const input = document.getElementById('cfg-station-label');
        const label = document.getElementById('station-custom-label');
        const list = document.getElementById('appearance-tab-order');
        const status = document.getElementById('appearance-layout-status');
        if (!input || !label || !list) return;
        const buttons = new Map(VIEWS.map(id => [id, document.querySelector(`.tab-btn[data-tab="${id}"]`)]));
        function save() {
            try { localStorage.setItem(KEY, JSON.stringify(state)); }
            catch (_) { status.textContent = 'Preferences could not be saved in this browser.'; }
        }
        function applyPanels() {
            const parent = document.querySelector('#tab-prop .prop-detail');
            if (!parent) return;
            state.panels.forEach(id => PANELS[id].slice(1).forEach(elementId => {
                const element = document.getElementById(elementId);
                if (element?.parentElement === parent) parent.appendChild(element);
            }));
        }
        function renderPanels(focusId, direction) {
            const panelList = document.getElementById('appearance-panel-order');
            if (!panelList) return;
            panelList.replaceChildren();
            state.panels.forEach((id, index) => {
                const row = document.createElement('div');
                row.className = 'appearance-order-row';
                const name = document.createElement('span');
                name.className = 'appearance-panel-name';
                name.textContent = PANELS[id][0];
                row.append(name);
                [['up', -1], ['down', 1]].forEach(([move, offset]) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'btn-small';
                    button.textContent = 'Move ' + move;
                    button.setAttribute('aria-label', 'Move ' + PANELS[id][0] + ' ' + move);
                    button.dataset.panel = id;
                    button.dataset.action = move;
                    button.disabled = index + offset < 0 || index + offset >= state.panels.length;
                    button.addEventListener('click', () => {
                        const target = index + offset;
                        [state.panels[index], state.panels[target]] = [state.panels[target], state.panels[index]];
                        applyPanels(); save(); renderPanels(id, move);
                        status.textContent = PANELS[id][0] + ' moved ' + move + '.';
                    });
                    row.append(button);
                });
                panelList.append(row);
            });
            if (focusId) {
                const choices = [...panelList.querySelectorAll('button')].filter(el => el.dataset.panel === focusId && !el.disabled);
                (choices.find(el => el.dataset.action === direction) || choices[0])?.focus();
            }
        }
        function apply() {
            label.textContent = state.label;
            label.hidden = !state.label;
            const parent = buttons.get(VIEWS[0])?.parentElement;
            const anchor = document.querySelector('.tab-btn[data-tab="tab-settings"]');
            state.order.forEach(id => {
                const button = buttons.get(id);
                if (!button || !parent) return;
                button.hidden = state.hidden.includes(id);
                parent.insertBefore(button, anchor);
            });
            if (state.order.some(id => buttons.get(id)?.classList.contains('active') && state.hidden.includes(id))) {
                buttons.get(state.order.find(id => !state.hidden.includes(id)))?.click();
            }
        }
        function render(focusId, action) {
            list.replaceChildren();
            state.order.forEach((id, index) => {
                const row = document.createElement('div');
                row.className = 'appearance-order-row';
                const caption = document.createElement('label');
                const check = document.createElement('input');
                check.type = 'checkbox';
                check.checked = !state.hidden.includes(id);
                check.dataset.localSetting = '';
                check.dataset.view = id;
                check.dataset.action = 'visible';
                const name = buttons.get(id)?.textContent.trim() || id;
                caption.append(check, document.createTextNode(' ' + name));
                check.addEventListener('change', () => {
                    const hidden = new Set(state.hidden);
                    if (check.checked) hidden.delete(id); else hidden.add(id);
                    if (hidden.size === VIEWS.length) {
                        check.checked = true;
                        status.textContent = 'Keep at least one dashboard view visible.';
                        return;
                    }
                    state.hidden = [...hidden];
                    apply(); save();
                    status.textContent = 'Dashboard visibility saved.';
                });
                row.append(caption);
                [['up', -1], ['down', 1]].forEach(([direction, offset]) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'btn-small';
                    button.textContent = 'Move ' + direction;
                    button.setAttribute('aria-label', 'Move ' + name + ' ' + direction);
                    button.dataset.view = id;
                    button.dataset.action = direction;
                    button.disabled = index + offset < 0 || index + offset >= state.order.length;
                    button.addEventListener('click', () => {
                        const target = index + offset;
                        [state.order[index], state.order[target]] = [state.order[target], state.order[index]];
                        apply(); save(); render(id, direction);
                        status.textContent = name + ' moved ' + direction + '.';
                    });
                    row.append(button);
                });
                list.append(row);
            });
            if (focusId) {
                const target = [...list.querySelectorAll('button')].find(el => el.dataset.view === focusId && el.dataset.action === action);
                if (target && !target.disabled) target.focus();
                else list.querySelector(`input[data-view="${focusId}"]`)?.focus();
            }
        }
        input.value = state.label;
        input.addEventListener('input', () => {
            state.label = normalize({label: input.value}).label;
            apply(); save();
        });
        document.getElementById('appearance-layout-reset')?.addEventListener('click', () => {
            state.order = [...VIEWS]; state.hidden = []; state.panels = Object.keys(PANELS);
            applyPanels(); renderPanels();
            apply(); save(); render();
            status.textContent = 'Default tab layout restored.';
        });
        apply(); render(); applyPanels(); renderPanels();
        // Restore a visible active view after the main app attaches tab handlers.
        queueMicrotask(apply);
    });
})();
