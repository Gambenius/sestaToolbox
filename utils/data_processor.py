import re, os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import struct

def get_wbin_metadata(path):
    MARKER = b'[END]'
    MARKER_DIG = '[DIGITAL]'
    
    with open(path, 'rb') as f:
        blob = f.read(2048 * 1024)
    
    cuts = [m.start() for m in re.finditer(re.escape(MARKER), blob)]
    if len(cuts) < 2:
        raise ValueError("Marker [END] non trovati.")

    # ───── HEADER PARTS (CRITICAL) ─────
    part1 = blob[:cuts[0]].decode('latin-1', errors='ignore')
    part2 = blob[cuts[0]:cuts[1]].decode('latin-1', errors='ignore')

    lines = part1.split('\n')   # only \n

    # ───── CAMPAIGN ─────
    campaign_info = {"campaign": "N/A", "customer": "N/A", "coordinator": "N/A"}
    if lines:
        parts = [p.strip() for p in lines[0].split('\t') if p.strip()]
        if len(parts) >= 4:
            campaign_info = {
                "campaign": parts[1],
                "customer": parts[2],
                "coordinator": parts[3]
            }

    # ───── ANALOG ─────
    analog_channels = []
    hdr_map = {}
    parsing_analog = False

    for line in lines:
        cols = [c.strip() for c in line.split('\t')]
        
        if 'Tag' in cols:
            hdr_map = {col: i for i, col in enumerate(cols)}
            parsing_analog = True
            continue
        
        if parsing_analog and len(cols) > 1:
            tag = cols[hdr_map.get('Tag', 0)].upper()
            if tag:
                analog_channels.append({
                    'sid': len(analog_channels),
                    'tag': tag,
                    'unit': cols[hdr_map.get('EU', 1)] if 'EU' in hdr_map else "",
                    'desc': cols[hdr_map.get('Comment', 2)] if 'Comment' in hdr_map else ""
                })

    # ───── DIGITAL (MAPPATURA TAG <-> DESCRIZIONE) ─────
    digital_channels = []
    group_idx = 0

    for line in part2.split('\n'):
        line = line.strip()
        if not line or MARKER_DIG in line.upper() or not line.upper().startswith('DIGITAL'):
            continue
        
        cols = line.split('\t')
        
        # Cerchiamo la colonna dei tag (quella con le virgole)
        try:
            v_col = next((i for i, c in enumerate(cols) if ',' in c), 1)
        except StopIteration:
            continue 

        if v_col < len(cols):
            # Split dei TAG (es. Z50XL108, Z50XU108...)
            tags = [t.strip() for t in cols[v_col].split(',') if t.strip()]
            
            # Split delle DESCRIZIONI (es. Min ecc statica..., Reg ecc...)
            # Usiamo la colonna successiva v_col + 1
            descs = []
            if len(cols) > (v_col + 1):
                descs = [d.strip() for d in cols[v_col + 1].split(',')]

            for bit_idx, tag in enumerate(tags[:32]):
                # Prendiamo la descrizione corrispondente per indice
                # Se per qualche motivo il file ha meno descrizioni dei tag, evitiamo il crash
                current_desc = descs[bit_idx] if bit_idx < len(descs) else ""
                
                digital_channels.append({
                    'tag': tag.upper(),
                    'group': group_idx,
                    'bit': bit_idx,
                    'type': 'D',
                    'desc': current_desc # <--- ECCOLA QUI!
                })
            
            group_idx += 1

    # ───── OFFSET (USE VERSION 2 LOGIC) ─────
    match = re.search(r'#(\d{9})', part1)
    data_offset = int(match.group(1)) if match else 0

    # ───── BLOCK SIZE (CRITICAL FIX) ─────
    n_analog = len(analog_channels)

    # use REAL digital word count (NOT parsed groups)
    n_uint32 = len([l for l in part2.split('\n') if ',' in l and '\t' in l])

    block_size = 13 + (n_analog * 4) + (n_uint32 * 4)

    total_blocks = (os.path.getsize(path) - data_offset) // block_size
    file_size = os.path.getsize(path)

    # 4. Estrazione orari dal binario
    with open(path, 'rb') as f:
        # Orario d'inizio
        f.seek(data_offset)
        s_rec = f.read(7)
        t_start = f"{s_rec[4]:02d}:{s_rec[5]:02d}:{s_rec[6]:02d}"
        
        # Orario di fine (Usa file_size e block_size appena definiti)
        f.seek(file_size - block_size)
        e_rec = f.read(7)
        t_end = f"{e_rec[4]:02d}:{e_rec[5]:02d}:{e_rec[6]:02d}"
    return {
        'path': path,
        'data_offset': data_offset,
        'block_size': block_size,
        'total_blocks': total_blocks,
        'n_analog': n_analog,
        'analog_channels': analog_channels,
        'digital_channels': digital_channels,
        'meta': campaign_info,
        'start_time': t_start,
        'end_time': t_end,
    }

def read_wbin_data(path, sids, config):
    offset = config['data_offset']
    block_size = config['block_size']
    total_blocks = config['total_blocks']

    with open(path, 'rb') as f:
        f.seek(offset)
        blob = f.read(total_blocks * block_size)

    timestamps = []
    data = {sid: [] for sid in sids}

    # Parse header time from first block
    first = blob[0:block_size]
    h0, m0, s0 = first[4], first[5], first[6]
    today = datetime.now().date()
    start_dt = datetime(today.year, today.month, today.day, h0, m0, s0)

    for i in range(total_blocks):
        record = blob[i*block_size:(i+1)*block_size]
        if len(record) < block_size:
            break
        timestamps.append(start_dt + timedelta(seconds=i))
        for sid in sids:
            val = struct.unpack('>f', record[13+(sid*4):13+(sid*4)+4])[0]
            data[sid].append(val if abs(val) < 1e15 else 0.0)

    return pd.DataFrame(data, index=timestamps)

