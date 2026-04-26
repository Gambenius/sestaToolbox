import os
import struct
import re

def debug_wbin_reader_full(path, n_samples=5):
    """
    Debug avanzato: associa metadati dell'header ai valori binari.
    """
    MARKER = b'[END]'
    with open(path, 'rb') as f:
        # Leggiamo abbastanza per coprire l'header (es. 2MB)
        content = f.read(2048 * 1024)
        
    cuts = [m.start() for m in re.finditer(re.escape(MARKER), content)]
    if len(cuts) < 2:
        print("❌ Errore: Marker [END] non trovati.")
        return

    # --- 1. PARSING HEADER ANALOGICO ---
    part1 = content[:cuts[0]].decode('latin-1', errors='ignore')
    lines = part1.splitlines()
    
    # Estrazione data_offset dalla regex
    match = re.search(r'#(\d{9})', lines[0])
    data_offset = int(match.group(1)) if match else 0
    
    # Cerchiamo la riga che contiene le intestazioni delle colonne
    channels = []
    start_parsing = False
    for line in lines:
        cols = [c.strip() for c in line.split('\t')]
        if 'Tag' in cols:
            # Abbiamo trovato la riga di intestazione: Tag, EU, Comment, etc.
            hdr_map = {col: i for i, col in enumerate(cols)}
            start_parsing = True
            continue
        
        if start_parsing and len(cols) > 1:
            # Estraiamo i metadati usando la mappa delle colonne
            tag = cols[hdr_map.get('Tag', 0)]
            unit = cols[hdr_map.get('EU', 1)] if 'EU' in hdr_map else "N/A"
            desc = cols[hdr_map.get('Comment', 2)] if 'Comment' in hdr_map else ""
            
            if tag: # Evitiamo righe vuote
                channels.append({'tag': tag, 'unit': unit, 'desc': desc})

    n_analog = len(channels)
    
    # --- 2. PARSING HEADER DIGITALE (per calcolare blockSize) ---
    part2 = content[cuts[0]+len(MARKER):cuts[1]].decode('latin-1', errors='ignore')
    # Contiamo quante "word" digitali (righe) ci sono
    digital_words = [l for l in part2.splitlines() if ',' in l and '\t' in l]
    n_digital_words = len(digital_words)

    # --- 3. CALCOLO STRUTTURA RECORD ---
    # Formula: 13 byte (TS) + (nA * 4) + (nDW * 4)
    block_size = 13 + (n_analog * 4) + (n_digital_words * 4)
    
    print(f"--- CONFIGURAZIONE RILEVATA ---")
    print(f"File: {os.path.basename(path)}")
    print(f"Data Offset: {data_offset} byte")
    print(f"Block Size:  {block_size} byte")
    print(f"Canali Analogici trovati: {n_analog}\n")

    # --- 4. LETTURA DATI CON METADATI ---
    with open(path, 'rb') as f:
        for r in range(n_samples):
            current_record_pos = data_offset + (r * block_size)
            f.seek(current_record_pos)
            record = f.read(block_size)
            
            if len(record) < block_size:
                print(f"Fine del file raggiunta al record {r}")
                break
            
            # Orario (byte 4,5,6)
            h, m, s = record[4], record[5], record[6]
            print(f"=== RECORD {r} | TIME {h:02d}:{m:02d}:{s:02d} ===")
            
            # Leggiamo i primi 5 canali analogici per non intasare il terminale
            for i in range(min(5, n_analog)):
                ch = channels[i]
                # Calcolo offset: 13 byte TS + (indice canale * 4 byte)
                val_offset = 13 + (i * 4)
                raw_val = record[val_offset : val_offset + 4]
                
                # Unpack Big Endian
                try:
                    val = struct.unpack('>f', raw_val)[0]
                    print(f"TAG: {ch['tag']:<12} | DESC: {ch['desc']:<20} | VAL: {val:>10.4f} {ch['unit']}")
                except Exception as e:
                    print(f"TAG: {ch['tag']} | Errore unpack: {e}")
            print("-" * 60)

# Esempio di utilizzo:
# debug_wbin_reader_full("tuo_file.bin")
# Esegui il debug
debug_wbin_reader_full("/home/edoardo/Documenti/sestaToolbox/data/APR240832.bin")

