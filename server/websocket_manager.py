"""Bounded browser delivery; radio work never waits for a slow socket."""
import asyncio
import json


class WebSocketManager:
    MAX_CONNECTIONS = 20
    QUEUE_LIMIT = 256
    SEND_TIMEOUT = 5
    REPLACEABLE = {'status', 'stats', 'propagation', 'station_update'}

    def __init__(self):
        self.active_connections = set()
        self._queues = {}
        self._senders = {}
        self._tasks = set()

    async def connect(self, websocket):
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            await websocket.close(code=1013, reason='Too many connections')
            return False
        await websocket.accept()
        self.active_connections.add(websocket)
        queue = asyncio.Queue(maxsize=self.QUEUE_LIMIT)
        self._queues[websocket] = queue
        task = asyncio.create_task(self._send_loop(websocket, queue))
        self._senders[websocket] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    def disconnect(self, websocket):
        connected = websocket in self.active_connections
        self.active_connections.discard(websocket)
        self._queues.pop(websocket, None)
        task = self._senders.pop(websocket, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        if connected:
            closer = asyncio.create_task(self._close_socket(websocket))
            self._tasks.add(closer)
            closer.add_done_callback(self._tasks.discard)

    async def _close_socket(self, websocket):
        try:
            await asyncio.wait_for(websocket.close(code=1013), 1)
        except Exception:
            pass

    async def _send_loop(self, websocket, queue):
        try:
            while True:
                _, data = await queue.get()
                await asyncio.wait_for(websocket.send_text(data), self.SEND_TIMEOUT)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            self.disconnect(websocket)

    def _enqueue(self, websocket, message, data):
        queue = self._queues.get(websocket)
        if queue is None:
            return
        kind = message.get('type')
        key = None
        if kind in self.REPLACEABLE:
            station = message.get('station', {})
            key = (kind, station.get('source'), station.get('callsign'))
        pending = []
        while not queue.empty():
            item = queue.get_nowait()
            if key is None or item[0] != key:
                pending.append(item)
        if len(pending) >= self.QUEUE_LIMIT:
            # Overflow is explicit: disconnect; reconnect retrieves persisted state.
            self.disconnect(websocket)
            return
        for item in pending:
            queue.put_nowait(item)
        queue.put_nowait((key, data))

    async def broadcast(self, message):
        data = json.dumps(message, default=str)
        for websocket in tuple(self.active_connections):
            self._enqueue(websocket, message, data)

    async def send_to(self, websocket, message):
        self._enqueue(websocket, message, json.dumps(message, default=str))

    async def close(self):
        for websocket in tuple(self.active_connections):
            self.disconnect(websocket)
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    @property
    def client_count(self):
        return len(self.active_connections)
