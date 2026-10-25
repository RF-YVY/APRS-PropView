"""Report native receiver processing cost; no devices, audio output or RF activity."""
import argparse
from array import array
import json
import math
import platform
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.software_modem import AudioDecoder


def benchmark(seconds=10, rate=48000):
    count = round(rate * .02)
    blocks = max(1, round(seconds / .02))
    decoder = AudioDecoder(rate)
    timings = []
    try:
        # Repeatable broadband-ish background with non-APRS tone components.
        # Prepare data outside the measured interval; measure only decoder processing.
        for block in range(blocks):
            offset = block * count
            raw = array('f', (.025 * math.sin((offset + i) * 1.731) +
                              .02 * math.sin((offset + i) * .173) for i in range(count))).tobytes()
            start = time.perf_counter()
            decoder.feed(raw)
            timings.append((time.perf_counter() - start) * 1000)
        return {'architecture': platform.machine(), 'platform': sys.platform,
                'sample_rate': rate, 'block_ms': 20, 'audio_seconds': blocks * .02,
                'mean_processing_ms': statistics.mean(timings),
                'p95_processing_ms': sorted(timings)[min(len(timings)-1, int(len(timings)*.95))],
                'max_processing_ms': max(timings),
                'processing_percent_of_realtime': sum(timings)/(blocks*20)*100,
                'deadline_overruns': sum(value > 20 for value in timings),
                'decoder_lanes': 132, 'receive_engines': 1,
                'note': 'Decoder processing benchmark, not total application CPU or a hardware audio test.'}
    finally:
        decoder.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--rate', type=int, default=48000, choices=[8000, 12000, 44100, 48000])
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 600:
        parser.error('--seconds must be greater than zero and at most 600')
    print(json.dumps(benchmark(args.seconds, args.rate), indent=2))
