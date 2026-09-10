/**
 * WebSocket client — manages real-time connection to the PropView server.
 */

class PropViewWebSocket {
    constructor() {
        this.ws = null;
        this.handlers = {};
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.currentDelay = this.reconnectDelay;
        this.isConnected = false;
        this.reconnectTimer = null;
    }

    connect() {
        if (this.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.ws.readyState)) return;
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(url);
            const socket = this.ws;

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.isConnected = true;
                this.currentDelay = this.reconnectDelay;
                this._updateStatus(true);
                this._emit('connected');
            };

            this.ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    this._emit(msg.type, msg);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };

            this.ws.onclose = () => {
                if (this.ws !== socket) return;
                console.log('WebSocket disconnected');
                this.isConnected = false;
                this._updateStatus(false);
                this._emit('disconnected');
                this._reconnect();
            };

            this.ws.onerror = (err) => {
                console.error('WebSocket error:', err);
                socket.close();
            };
        } catch (e) {
            console.error('WebSocket connection failed:', e);
            this._reconnect();
        }
    }

    on(event, handler) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(handler);
    }

    _emit(event, data) {
        const handlers = this.handlers[event];
        if (handlers) {
            handlers.forEach(h => {
                try {
                    h(data);
                } catch (e) {
                    console.error(`Handler error for ${event}:`, e);
                }
            });
        }
    }

    _reconnect() {
        if (this.reconnectTimer) return;
        const delay = this.currentDelay;
        this.currentDelay = Math.min(this.currentDelay * 2, this.maxReconnectDelay);
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, delay);
    }

    _updateStatus(connected) {
        const chip = document.getElementById('ws-chip');
        const chipText = document.getElementById('ws-chip-text');
        if (!chip || !chipText) return;
        chip.classList.remove('online', 'partial', 'read-only', 'reconnecting', 'offline');
        chip.classList.add(connected ? 'online' : 'reconnecting');
        chipText.textContent = connected ? 'Connected' : 'Retrying';
    }
}

// Global instance
window.pvWebSocket = new PropViewWebSocket();
