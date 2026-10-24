"""APSPOT command profiles and validation, based on apspot.radio/getting-started/."""
import re
from decimal import Decimal, InvalidOperation

MODES = ('SSB', 'CW', 'FM', 'AM', 'DATA', 'FT8')
ACTIVITY_PROFILES = {
    'POTA': dict(label='Park reference', example='US-1234', modes=list(MODES)),
    'SOTA': dict(label='Summit reference', example='W4C/CM-001', modes=list(MODES[:-1])),
    'WWFF': dict(label='Flora / fauna reference', example='VKFF-1929', modes=list(MODES[:-1])),
    'SIOTA': dict(label='Silo reference', example='VK-0001', modes=list(MODES[:-1])),
}
ACTIVITIES = tuple(ACTIVITY_PROFILES)
LOOKUP_ACTIVITIES = ('POTA', 'SOTA', 'WWFF')
HELP_TYPES = ('aprs', 'sms', 'winlink')


def operator_callsign(value):
    call = value.strip().upper() if isinstance(value, str) else ''
    if (not re.fullmatch(r'[A-Z0-9]{1,6}', call) or not any(c.isalpha() for c in call)
            or not any(c.isdigit() for c in call) or call in {'N0CALL', 'NOCALL', 'MYCALL', 'TEST'}):
        raise ValueError('Enter an operator callsign without an SSID (for example N2UGS).')
    return call


def select_spot_route(handler, source):
    """Choose one usable route; never fall back after attempting transmission."""
    rf_ready = handler._can_send_via('rf')
    client = handler.aprs_is
    is_ready = bool(client and client.connected and client.verified)
    if source == 'auto':
        return 'rf' if rf_ready else ('aprs_is' if is_ready else None)
    return source if (rf_ready if source == 'rf' else is_ready) else None


def build_spot(body, station_callsign):
    if not isinstance(body, dict):
        raise ValueError('An APSPOT form is required.')
    def field(name, default=''):
        value = body.get(name, default)
        if not isinstance(value, str):
            raise ValueError(f'Invalid {name}.')
        return value.strip()
    callsign = operator_callsign(field('callsign', station_callsign.split('-')[0]))
    action = field('action', 'post')
    activity = field('activity').upper()
    test = body.get('test', False)
    if not isinstance(test, bool):
        raise ValueError('Invalid test selection.')
    if action == 'post':
        if activity not in ACTIVITIES:
            raise ValueError('Choose POTA, SOTA, WWFF or SIOTA.')
        reference, mode = field('reference').upper(), field('mode').upper()
        if not re.fullmatch(r'[A-Z0-9]+(?:[/-][A-Z0-9]+)*-[0-9]+', reference):
            raise ValueError('Enter a reference such as ' + ACTIVITY_PROFILES[activity]['example'] + '.')
        if mode not in ACTIVITY_PROFILES[activity]['modes']:
            raise ValueError('Choose a supported mode. FT8 is available for POTA only.')
        frequency = field('frequency')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,6})?', frequency):
            raise ValueError('Enter frequency in MHz, for example 14.310.')
        try:
            mhz = Decimal(frequency)
        except InvalidOperation:
            raise ValueError('Invalid frequency in MHz.')
        if not Decimal('0.1') <= mhz <= Decimal('1300'):
            raise ValueError('Use MHz (0.1-1300), not kHz; for example 14.310.')
        frequency = format(mhz.normalize(), 'f')
        comment = field('comment')
        if any(ord(c) < 32 or ord(c) > 126 or c in '{|~' for c in comment):
            raise ValueError('Use plain ASCII text without APRS delimiters {, | or ~ in the comment.')
        if test and 'test' not in comment.lower():
            comment = (comment + ' aptest').strip()
        text = f'! {activity} {reference} {frequency} {mode}' + (f' {comment}' if comment else '')
    elif action == 'spots':
        if activity not in LOOKUP_ACTIVITIES:
            raise ValueError('Current spot lookup supports POTA, SOTA and WWFF.')
        mode = field('filter_mode').upper()
        if mode and mode not in ACTIVITY_PROFILES[activity]['modes']:
            raise ValueError('Choose a supported mode filter for this activity.')
        count = field('count')
        if count and (not re.fullmatch(r'[0-9]{1,3}', count) or not 1 <= int(count) <= 999):
            raise ValueError('Enter a result count from 1 to 999, or leave it blank for the service default.')
        text = f'spots {activity}' + (f' {mode}' if mode else '') + (f' {int(count)}' if count else '')
    elif action == 'usage':
        kind = field('help_type').lower()
        help_activity = field('help_activity').upper()
        if kind and kind not in HELP_TYPES:
            raise ValueError('Choose APRS, SMS or Winlink help.')
        if help_activity and (not kind or help_activity not in ACTIVITIES):
            raise ValueError('Choose a help type before an activity example.')
        text = 'usage' + (f' {kind}' if kind else '') + (f' {help_activity}' if help_activity else '')
    else:
        raise ValueError('Choose post spot, current spots or service help.')
    if len(text) > 67:
        raise ValueError(f'Message is {len(text)} characters; shorten the comment to fit the 67-character APRS limit.')
    source = field('source', 'auto')
    if source not in ('auto', 'rf', 'aprs_is'):
        raise ValueError('Choose automatic, RF or APRS-IS routing.')
    return dict(to='APSPOT', callsign=callsign, text=text, source=source, action=action,
                characters=len(text), test=action == 'post' and 'test' in text.lower())
