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
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(url);

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
                console.log('WebSocket disconnected');
                this.isConnected = false;
                this._updateStatus(false);
                this._emit('disconnected');
                this._reconnect();
            };

            this.ws.onerror = (err) => {
                console.error('WebSocket error:', err);
                this.ws.close();
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
        setTimeout(() => {
            console.log(`Reconnecting in ${this.currentDelay}ms...`);
            this.connect();
            this.currentDelay = Math.min(this.currentDelay * 2, this.maxReconnectDelay);
        }, this.currentDelay);
    }

    _updateStatus(connected) {
        const el = document.getElementById('ws-status');
        if (el) {
            el.classList.toggle('connected', connected);
            el.classList.toggle('disconnected', !connected);
        }
    }
}

// Global instance
window.pvWebSocket = new PropViewWebSocket();
