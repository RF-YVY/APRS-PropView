/* Maidenhead locator conversion and a zoom-aware Leaflet grid overlay. */
(function () {
    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWX';

    function normalizeLongitude(lon) {
        return Math.max(-180, Math.min(179.999999, Number(lon)));
    }

    function normalizeLatitude(lat) {
        return Math.max(-90, Math.min(89.999999, Number(lat)));
    }

    function locator(lat, lon, precision = 6) {
        const y = normalizeLatitude(lat) + 90;
        const x = normalizeLongitude(lon) + 180;
        const fieldLon = Math.floor(x / 20);
        const fieldLat = Math.floor(y / 10);
        let value = letters[fieldLon] + letters[fieldLat];
        if (precision < 4) return value;
        const squareLon = Math.floor((x % 20) / 2);
        const squareLat = Math.floor(y % 10);
        value += String(squareLon) + String(squareLat);
        if (precision < 6) return value;
        const subLon = Math.floor(((x % 2) / 2) * 24);
        const subLat = Math.floor((y % 1) * 24);
        return value + letters[subLon].toLowerCase() + letters[subLat].toLowerCase();
    }

    function cellFor(lat, lon, precision) {
        const width = precision === 2 ? 20 : precision === 4 ? 2 : 2 / 24;
        const height = precision === 2 ? 10 : precision === 4 ? 1 : 1 / 24;
        const west = Math.floor((normalizeLongitude(lon) + 180) / width) * width - 180;
        const south = Math.floor((normalizeLatitude(lat) + 90) / height) * height - 90;
        return {
            locator: locator(south + height / 2, west + width / 2, precision),
            west,
            east: west + width,
            south,
            north: south + height,
            center: [south + height / 2, west + width / 2],
        };
    }

    class MaidenheadGrid {
        constructor(map) {
            this.map = map;
            this.layer = L.layerGroup();
            this.visible = false;
            this.selecting = false;
            this._renderTimer = null;
            map.on('moveend zoomend resize', () => this.scheduleRender());
            map.on('click', (event) => {
                if (!this.visible || !this.selecting) return;
                const precision = this.precision();
                const selected = cellFor(event.latlng.lat, event.latlng.lng, precision);
                window.dispatchEvent(new CustomEvent('pvgridselect', { detail: selected }));
            });
        }

        precision() {
            const zoom = this.map.getZoom();
            return zoom >= 9 ? 6 : zoom >= 5 ? 4 : 2;
        }

        toggle() {
            this.visible = !this.visible;
            this.selecting = this.visible;
            if (this.visible) {
                this.layer.addTo(this.map);
                this.render();
            } else {
                this.map.removeLayer(this.layer);
            }
            this.map.getContainer().classList.toggle('maidenhead-selecting', this.selecting);
            return this.visible;
        }

        scheduleRender() {
            if (!this.visible) return;
            clearTimeout(this._renderTimer);
            this._renderTimer = setTimeout(() => this.render(), 80);
        }

        render() {
            if (!this.visible) return;
            this.layer.clearLayers();
            const precision = this.precision();
            const width = precision === 2 ? 20 : precision === 4 ? 2 : 2 / 24;
            const height = precision === 2 ? 10 : precision === 4 ? 1 : 1 / 24;
            const bounds = this.map.getBounds().pad(0.05);
            const west = Math.max(-180, bounds.getWest());
            const east = Math.min(180, bounds.getEast());
            const south = Math.max(-90, bounds.getSouth());
            const north = Math.min(90, bounds.getNorth());
            const firstLon = Math.floor((west + 180) / width) * width - 180;
            const firstLat = Math.floor((south + 90) / height) * height - 90;
            const columns = Math.ceil((east - firstLon) / width) + 1;
            const rows = Math.ceil((north - firstLat) / height) + 1;
            if (columns * rows > 900) return;

            for (let x = firstLon; x <= east + width; x += width) {
                L.polyline([[south, x], [north, x]], { className: 'maidenhead-grid-line', interactive: false }).addTo(this.layer);
            }
            for (let y = firstLat; y <= north + height; y += height) {
                L.polyline([[y, west], [y, east]], { className: 'maidenhead-grid-line', interactive: false }).addTo(this.layer);
            }
            for (let y = firstLat; y < north; y += height) {
                for (let x = firstLon; x < east; x += width) {
                    const center = [y + height / 2, x + width / 2];
                    const name = locator(center[0], center[1], precision);
                    L.marker(center, {
                        interactive: false,
                        keyboard: false,
                        icon: L.divIcon({ className: 'maidenhead-grid-label', html: name, iconSize: null }),
                    }).addTo(this.layer);
                }
            }
        }
    }

    window.Maidenhead = { locator, cellFor };
    window.MaidenheadGrid = MaidenheadGrid;
})();
