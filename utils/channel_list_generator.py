import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import data_processor as dp

# ── CONFIG ────────────────────────────────────────────────────────────────
BINARY_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE\20260407\APR071133.bin"
OUTPUT_FILE = "tags_cache.txt"
# ─────────────────────────────────────────────────────────────────────────

cfg = dp.get_wbin_metadata(BINARY_PATH)

analog   = cfg.get('analog_channels', [])
digital  = cfg.get('digital_channels', [])

print(f"Analog channels:  {len(analog)}")
print(f"Digital channels: {len(digital)}")
# print(digital)

all_tags = sorted(set(ch['tag'] for ch in analog + digital))
print(f"Total unique tags: {len(all_tags)}")

with open(OUTPUT_FILE, "w") as f:
    f.write("\n".join(all_tags))

print(f"Saved to {OUTPUT_FILE}")
print(f"First 10: {all_tags[:10]}")