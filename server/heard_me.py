"""Session-local evidence that a recently transmitted RF packet was heard elsewhere."""
import hashlib
import re
import time
from collections import OrderedDict

CALL = re.compile(r'[A-Z0-9]{1,9}(?:-(?:[0-9]|1[0-5]))?\Z')


def valid_position(lat, lon):
    return (isinstance(lat, (float, int)) and isinstance(lon, (float, int)) and
            -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0, 0))


class HeardMe:
    MATCH_SECONDS = 180
    HISTORY_SECONDS = 3600
    MAX_TRANSMISSIONS = 512
    MAX_OBSERVATIONS = 128

    def __init__(self, config, clock=time.time):
        self.config, self.clock = config, clock
        self.transmissions = OrderedDict()
        self.observations = OrderedDict()
        self.positions = OrderedDict()

    @staticmethod
    def _packet(raw):
        if not isinstance(raw, str) or '\r' in raw or '\n' in raw or len(raw) > 4096:
            return None
        header, sep, info = raw.partition(':')
        source, arrow, rest = header.partition('>')
        source = source.upper()
        if not sep or not arrow or not CALL.fullmatch(source) or not info or info[0] in ':}?':
            return None  # Never retain message contents, third-party wrappers or queries.
        parts = rest.split(',')
        destination = parts[0].split('-')[0].upper()
        try:
            encoded = (source + '>' + destination + ':' + info).encode('latin-1')
        except UnicodeEncodeError:
            return None
        fingerprint = hashlib.sha256(encoded).hexdigest()
        return source, parts[1:], fingerprint

    def _own(self, source):
        base = self.config.station.callsign.upper()
        return source.split('-')[0] == base

    def _purge(self):
        now = self.clock()
        for entries, seconds in ((self.transmissions, self.MATCH_SECONDS), (self.observations, self.HISTORY_SECONDS)):
            for key in list(entries):
                if now - entries[key]['last_heard'] > seconds:
                    del entries[key]

    def transmitted(self, raw, latitude, longitude):
        parsed = self._packet(raw)
        if not parsed or not self._own(parsed[0]):
            return
        self._purge()
        source, _, fingerprint = parsed
        self.transmissions[fingerprint] = {'source': source, 'last_heard': self.clock(),
            'latitude': latitude, 'longitude': longitude}
        self.transmissions.move_to_end(fingerprint)
        while len(self.transmissions) > self.MAX_TRANSMISSIONS:
            self.transmissions.popitem(last=False)

    def observe(self, raw, transport, packet=None):
        self._purge()
        if (packet and packet.packet_type in {'position', 'weather', 'mic_e'} and
                CALL.fullmatch(packet.from_call.upper()) and valid_position(packet.latitude, packet.longitude)):
            self.positions[packet.from_call.upper()] = (packet.latitude, packet.longitude, self.clock())
            self.positions.move_to_end(packet.from_call.upper())
            while len(self.positions) > 1024:
                self.positions.popitem(last=False)
        parsed = self._packet(raw)
        if not parsed:
            return None
        source, path, fingerprint = parsed
        transmission = self.transmissions.get(fingerprint)
        if not transmission or not self._own(source):
            return None
        gate = None
        if transport == 'aprs_is':
            q_index = next((i for i, hop in enumerate(path) if hop in {'qAR', 'qAO', 'qAr'}), None)
            if q_index is None or q_index + 1 >= len(path):
                return None
            gate = path[q_index + 1].upper()
            path = path[:q_index]
            if not CALL.fullmatch(gate) or self._own(gate):
                return None
        elif transport != 'rf':
            return None
        forbidden = {'TCPIP', 'TCPXX'} | ({'NOGATE', 'RFONLY'} if transport == 'aprs_is' else set())
        if any(hop.rstrip('*').upper() in forbidden for hop in path):
            return None
        used_end = max((i for i, hop in enumerate(path) if hop.endswith('*')), default=-1)
        used = [hop.rstrip('*').upper() for hop in path[:used_end + 1]]
        unresolved = any(hop.startswith(('WIDE', 'TRACE', 'RELAY')) or not CALL.fullmatch(hop) for hop in used)
        calls = [hop for hop in used if CALL.fullmatch(hop) and not hop.startswith(('WIDE', 'TRACE', 'RELAY'))]
        if not gate and not calls:
            return None  # A local echo, or an anonymous/non-traceable repeater.
        if gate:
            calls.append(gate)
        route = []
        for call in calls:
            if self._own(call) or call == source:
                return None
            if not route or route[-1] != call:
                route.append(call)
        if len(set(route)) != len(route) or len(route) > 9:
            return None
        key = (source, tuple(route), unresolved)
        previous = self.observations.get(key, {})
        now = self.clock()
        # Count distinct transmissions, not duplicate copies of the same report.
        transmission_id = (fingerprint, transmission['last_heard'])
        count = previous.get('packet_count', 0) + (previous.get('_transmission') != transmission_id)
        transports = sorted(set(previous.get('transports', [])) | {transport})
        observation = {'source_call': source, 'receiver': route[-1], 'route_calls': route,
            'direct': used_end == -1, 'path_known': not unresolved, 'transport': transport, 'transports': transports,
            'last_heard': now, 'packet_count': count, 'latitude': transmission['latitude'],
            'longitude': transmission['longitude'], '_transmission': transmission_id}
        self.observations[key] = observation
        self.observations.move_to_end(key)
        while len(self.observations) > self.MAX_OBSERVATIONS:
            self.observations.popitem(last=False)
        return observation

    def snapshot(self):
        self._purge()
        observations = []
        for entry in reversed(self.observations.values()):
            if not self._own(entry['source_call']):
                continue
            hops = []
            for call in entry['route_calls']:
                position = self.positions.get(call)
                if position and self.clock() - position[2] <= 86400:
                    lat, lon = position[:2]
                else:
                    lat = lon = None
                hops.append({'callsign': call, 'latitude': lat, 'longitude': lon})
            observations.append({key: value for key, value in entry.items() if not key.startswith('_')} | {'hops': hops})
        return {'observations': observations, 'history_seconds': self.HISTORY_SECONDS,
                'match_seconds': self.MATCH_SECONDS, 'timestamp': self.clock()}
