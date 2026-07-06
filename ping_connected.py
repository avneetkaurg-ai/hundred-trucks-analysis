#!/usr/bin/env python3
"""
Ping connected trucks every 2 hours — fetches latest FASTag data
for is_connected=1 trucks and updates hundred_trucks.db
"""
import json, urllib.request, time, os
import psycopg2

NEON_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_qi10bYGBNPnr@ep-sweet-river-aoofzrdu.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require')
ZOHO_URL = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
DELAY    = 3

PA_USERNAME = 'TruckAnalysis01'
PA_TOKEN    = '5b7733d8f2e4e343eaec2c48e256422a79e777f7'
PA_PATH     = '/home/TruckAnalysis01/hundred_trucks.db'

def upload_to_pythonanywhere():
    try:
        with open(DB_PATH, 'rb') as f:
            db_data = f.read()
        boundary = b'----PAboundary'
        body = (
            b'--' + boundary + b'\r\n' +
            b'Content-Disposition: form-data; name="content"; filename="hundred_trucks.db"\r\n' +
            b'Content-Type: application/octet-stream\r\n\r\n' +
            db_data + b'\r\n' +
            b'--' + boundary + b'--\r\n'
        )
        url = f'https://www.pythonanywhere.com/api/v0/user/{PA_USERNAME}/files/path{PA_PATH}'
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Authorization', f'Token {PA_TOKEN}')
        req.add_header('Content-Type', f'multipart/form-data; boundary=----PAboundary')
        urllib.request.urlopen(req, timeout=30)
        print(f'  ✓ DB uploaded to PythonAnywhere')
    except Exception as e:
        print(f'  ✗ Upload failed: {e}')

def get_db():
    return psycopg2.connect(NEON_URL)

def fetch_zoho(vehicle_no):
    body = json.dumps({'vehicle_no': vehicle_no}).encode()
    req  = urllib.request.Request(ZOHO_URL, data=body, headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    return data.get('result', {}).get('data', [])

def save_crossings(vehicle_no, records):
    con = get_db(); cur = con.cursor()
    saved = 0
    for r in records:
        plaza      = r.get('tollPlazaName', '').strip()
        crossed_at = r.get('readerReadTime', '').strip()
        geocode    = r.get('tollPlazaGeocode', '')
        lat, lng   = 0, 0
        if geocode and ',' in geocode:
            parts = geocode.split(',')
            lat, lng = float(parts[0]), float(parts[1])
        direction = r.get('laneDirection', '').strip()
        seq_no    = str(r.get('seqNo', ''))
        vtype     = r.get('vehicleType', '').strip()
        if not plaza or not crossed_at:
            continue
        cur.execute('SELECT 1 FROM crossings WHERE vehicle_no=%s AND plaza=%s AND crossed_at=%s',
                    (vehicle_no, plaza, crossed_at))
        if not cur.fetchone():
            cur.execute('INSERT INTO crossings (vehicle_no, plaza, lat, lng, direction, seq_no, vehicle_type, crossed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (vehicle_no, plaza, lat, lng, direction, seq_no, vtype, crossed_at))
            saved += 1
    cur.execute('UPDATE trucks SET fetched_at=%s WHERE vehicle_no=%s',
                (time.strftime('%Y-%m-%d %H:%M:%S'), vehicle_no))
    con.commit(); con.close()
    return saved

def main():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no FROM trucks WHERE is_connected=1')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()

    print(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] Pinging {len(trucks)} connected trucks...')

    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            new_rows = save_crossings(vno, records)
            print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)')
        except Exception as e:
            print(f'  ✗ {vno} — ERROR: {e}')
        time.sleep(DELAY)

    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Ping complete.')

if __name__ == '__main__':
    main()
