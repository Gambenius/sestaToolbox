import sys
import os

from utils import data_processor as dp

# ── CONFIG ────────────────────────────────────────────────────────────────
BINARY_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE\20260407\APR071133.bin"
OUTPUT_FILE = "utils/tags_cache.txt"
# ─────────────────────────────────────────────────────────────────────────

cfg = dp.get_wbin_metadata(BINARY_PATH)

analog  = cfg.get('analog_channels', [])
digital = cfg.get('digital_channels', [])

print(f"Analog channels:  {len(analog)}")
print(f"Digital channels: {len(digital)}")

# Build tag -> desc map (deduplicated)
tag_map = {}
for ch in analog + digital:
    tag = ch['tag']
    if tag not in tag_map:
        tag_map[tag] = ch.get('desc', '')

print(f"Total unique tags: {len(tag_map)}")

with open(OUTPUT_FILE, "w", encoding='utf-8', errors='ignore') as f:
    for tag, desc in sorted(tag_map.items()):
        f.write(f"{tag}; {desc}\n")

print(f"Saved to {OUTPUT_FILE}")
print(f"First 10: {list(tag_map.items())[:10]}")