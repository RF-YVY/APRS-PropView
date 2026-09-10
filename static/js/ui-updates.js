/** Shared, incremental updates for long-lived live dashboards. */
window.pvUI = {
    validPosition(lat, lon) {
        return lat != null && lon != null && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))
            && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lon)) <= 180;
    },
    directPath(path) {
        return !(path || '').split(',').some(h => {
            h = h.trim();
            return h.endsWith('*') && !/^(WIDE|RELAY|TRACE)/i.test(h.slice(0, -1));
        });
    },
    reconcile(list, rows) {
        const scroll = list.scrollTop;
        const focused = document.activeElement;
        const focusKey = focused?.closest('[data-live-key]')?.dataset.liveKey;
        const focusClass = focused?.className;
        const existing = new Map(Array.from(list.children).map(el => [el.dataset.liveKey, el]));
        const wanted = new Set();
        rows.forEach(([key, html], index) => {
            wanted.add(key);
            let el = existing.get(key);
            if (!el) {
                const template = document.createElement('template');
                template.innerHTML = html.trim();
                el = template.content.firstElementChild;
                el.dataset.liveKey = key;
            } else if (el._liveHTML !== html) {
                const template = document.createElement('template');
                template.innerHTML = html.trim();
                const next = template.content.firstElementChild;
                // Keep the row node, only update changed contents/attributes.
                for (const attr of Array.from(next.attributes)) el.setAttribute(attr.name, attr.value);
                el.innerHTML = next.innerHTML;
            }
            el._liveHTML = html;
            if (list.children[index] !== el) list.insertBefore(el, list.children[index] || null);
        });
        for (const el of Array.from(list.children)) if (!wanted.has(el.dataset.liveKey)) el.remove();
        list.scrollTop = scroll;
        if (focusKey && !focused?.isConnected) {
            const row = Array.from(list.children).find(el => el.dataset.liveKey === focusKey);
            const target = row && [row, ...row.querySelectorAll('button, a, input')].find(el => el.className === focusClass);
            target?.focus({preventScroll: true});
        }
    }
};
