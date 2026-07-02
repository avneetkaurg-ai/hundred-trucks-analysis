#!/usr/bin/env python3
"""
Refresh FASTag data for the 100 trucks in hundred_trucks.db
Calls Zoho API for each truck and updates crossings with latest data.
"""
import json, urllib.request, time, sqlite3, os

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hundred_trucks.db')
ZOHO_URL = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
DELAY    = 3

def get_db():
    return sqlite3.connect(DB_PATH)

def fetch_zoho(vehicle_no):
    body = json.dumps({'vehicle_no': vehicle_no}).encode()
    req  = urllib.request.Request(ZOHO_URL, data=body, headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    return data.get('result', {}).get('data', [])

def save_crossings(vehicle_no, records):
    con = get_db()
    saved = 0
    for r in records:
        plaza      = r.get('tollPlazaName', r.get('toll_plaza_name', '')).strip()
        crossed_at = r.get('readerReadTime', r.get('transaction_date', '')).strip()
        geocode    = r.get('tollPlazaGeocode', '')
        if geocode and ',' in geocode:
            parts = geocode.split(',')
            lat, lng = float(parts[0]), float(parts[1])
        else:
            lat = float(r.get('latitude', 0) or 0)
            lng = float(r.get('longitude', 0) or 0)
        direction  = r.get('laneDirection', r.get('direction', '')).strip()
        seq_no     = str(r.get('seqNo', r.get('seq_no', '')))
        vtype      = r.get('vehicleType', r.get('vehicle_type', '')).strip()

        if not plaza or not crossed_at:
            continue

        # skip if this exact crossing already exists
        exists = con.execute(
            'SELECT 1 FROM crossings WHERE vehicle_no=? AND plaza=? AND crossed_at=?',
            (vehicle_no, plaza, crossed_at)
        ).fetchone()
        if not exists:
            con.execute(
                'INSERT INTO crossings (vehicle_no, plaza, lat, lng, direction, seq_no, vehicle_type, crossed_at) VALUES (?,?,?,?,?,?,?,?)',
                (vehicle_no, plaza, lat, lng, direction, seq_no, vtype, crossed_at)
            )
            saved += 1

    # update fetched_at timestamp
    con.execute('UPDATE trucks SET fetched_at=? WHERE vehicle_no=?',
                (time.strftime('%Y-%m-%d %H:%M:%S'), vehicle_no))
    con.commit()
    con.close()
    return saved

def main():
    con = get_db()
    trucks = [r[0] for r in con.execute('SELECT vehicle_no FROM trucks ORDER BY vehicle_no').fetchall()]
    con.close()

    total = len(trucks)
    print(f'\nRefreshing {total} trucks in hundred_trucks.db')
    print(f'Delay: {DELAY}s per call  →  Est. time: ~{total * DELAY // 60} min\n')

    ok = fail = 0

    for i, vno in enumerate(trucks, 1):
        try:
            records = fetch_zoho(vno)
            if records:
                new_rows = save_crossings(vno, records)
                ok += 1
                print(f'[{i:3d}/{total}] ✓ {len(records):2d} crossings ({new_rows} new)  — {vno}')
            else:
                print(f'[{i:3d}/{total}] — no data   — {vno}')
        except Exception as e:
            fail += 1
            print(f'[{i:3d}/{total}] ✗ ERROR     — {vno}: {e}')

        time.sleep(DELAY)

    con = get_db()
    total_c = con.execute('SELECT COUNT(*) FROM crossings').fetchone()[0]
    latest  = con.execute('SELECT MAX(crossed_at) FROM crossings').fetchone()[0]
    con.close()

    print(f'\nDone! ✓ {ok} refreshed  ✗ {fail} failed')
    print(f'Total crossings in DB: {total_c}')
    print(f'Latest crossing date:  {latest}')

if __name__ == '__main__':
    main()
