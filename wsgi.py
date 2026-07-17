"""
Render deployment entry point for Toll-Trace.cargo
Clean Flask app with no dependency on server.py
"""
import os, json, time, urllib.request, hmac, hashlib
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ZOHO_URL     = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
NEON_URL     = os.environ.get('DATABASE_URL')
TOKEN_SECRET = os.environ.get('TOKEN_SECRET', 'tolltrace-secret-key-2026')
WA_TOKEN     = os.environ.get('WA_TOKEN', 'EAATExmmKoIcBO7OrjLRMFXaVVxmcbkwtuCGuDCcdUdE2GDGSE3YG0xkU0fD3bl3aePQYlEpLHDRgE21nc2fRO2TP7wcJ5S14LFAtNOeDxT7JFa3pZA30V6HzS1c7vvTBr9P3ayvjpdfpjoxFRTGYflLZBONCmGvqzIOBupAgG1bQ3MoZAdtvzox9pOkjhbzjAZDZD')
WA_PHONE_ID  = os.environ.get('WA_PHONE_ID', '351912628011918')
WA_TO        = os.environ.get('WA_TO', '+919518146736')

def make_token(vehicle_no):
    return hmac.new(TOKEN_SECRET.encode(), vehicle_no.encode(), hashlib.sha256).hexdigest()[:16]

def vehicle_from_token(token):
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no FROM trucks', ())
    rows = cur.fetchall(); con.close()
    for (vno,) in rows:
        if make_token(vno) == token:
            return vno
    return None

application = Flask(__name__, static_folder='.', static_url_path='')

def get_db():
    con = psycopg2.connect(NEON_URL)
    return con

def fetchall(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetchone(cur):
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    return dict(zip(cols, row)) if row else None

# ── Static files ──
DASHBOARD_KEY = os.environ.get('DASHBOARD_KEY', 'ml2026secure')

def not_found_page():
    html = '''<!DOCTYPE html><html><head><title>404 Not Found</title>
    <style>body{margin:0;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;background:#f5f7fa;text-align:center;}
    </style></head><body>
    <div><div style="font-size:80px;font-weight:900;color:#e0e0e0;">404</div>
    <div style="font-size:22px;font-weight:700;color:#333;margin-top:8px;">Page Not Found</div>
    <div style="font-size:14px;color:#888;margin-top:10px;">This page does not exist.</div></div>
    </body></html>'''
    return html, 404

@application.route('/')
def index():
    key = request.args.get('key','')
    if key != DASHBOARD_KEY:
        return not_found_page()
    return send_from_directory('.', 'hundred_trucks.html')

@application.route('/<path:filename>')
def static_files(filename):
    if filename.startswith('api/'):
        return not_found_page()
    # track.html is public, everything else requires key
    if filename == 'track.html':
        return send_from_directory('.', filename)
    key = request.args.get('key','')
    if key != DASHBOARD_KEY:
        return not_found_page()
    return send_from_directory('.', filename)

# ── API routes ──

@application.route('/api/hundred-trucks')
def hundred_trucks():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT t.vehicle_no, t.owner, t.state, t.is_connected, t.fetched_at,
               COUNT(DISTINCT c.plaza) as unique_plazas,
               COUNT(c.id) as crossing_count
        FROM trucks t
        LEFT JOIN crossings c ON t.vehicle_no = c.vehicle_no
        GROUP BY t.vehicle_no, t.owner, t.state, t.is_connected, t.fetched_at
        ORDER BY t.state, t.vehicle_no
    ''')
    rows = fetchall(cur)
    cur.execute('SELECT COUNT(*) FROM crossings'); total_crossings = cur.fetchone()[0]
    cur.execute('SELECT COUNT(DISTINCT plaza) FROM crossings'); total_plazas = cur.fetchone()[0]
    con.close()
    return jsonify({'trucks': rows, 'total_crossings': total_crossings, 'total_plazas': total_plazas})

@application.route('/api/hundred-truck-detail')
def hundred_truck_detail():
    vno = request.args.get('vehicle_no', '').strip().upper()
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT * FROM trucks WHERE vehicle_no=%s', (vno,))
    truck = fetchone(cur) or {}
    cur.execute('SELECT plaza, lat, lng, direction, crossed_at FROM crossings WHERE vehicle_no=%s ORDER BY crossed_at', (vno,))
    crossings = fetchall(cur)
    cur.execute('SELECT plaza, lat, lng, COUNT(*) as count FROM crossings WHERE vehicle_no=%s GROUP BY plaza, lat, lng ORDER BY count DESC', (vno,))
    plaza_summary = fetchall(cur)
    dates = [str(c['crossed_at']) for c in crossings if c['crossed_at']]
    con.close()
    return jsonify({
        'truck': truck, 'crossings': crossings, 'plaza_summary': plaza_summary,
        'unique_plazas': len(plaza_summary),
        'date_from': dates[0][:10] if dates else '—',
        'date_to':   dates[-1][:10] if dates else '—',
    })

@application.route('/api/hundred-plazas')
def hundred_plazas():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT plaza, AVG(lat) as lat, AVG(lng) as lng,
               COUNT(DISTINCT vehicle_no) as truck_count,
               COUNT(*) as crossing_count
        FROM crossings
        WHERE lat IS NOT NULL AND lng IS NOT NULL AND lat != 0 AND lng != 0
        GROUP BY plaza ORDER BY truck_count DESC
    ''')
    rows = fetchall(cur); con.close()
    return jsonify({'plazas': rows})

@application.route('/api/hundred-truck-locations-at')
def hundred_truck_locations_at():
    at = request.args.get('at', '')
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               c.plaza as last_plaza, c.lat, c.lng, c.crossed_at as last_seen
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.id IN (
            SELECT id FROM crossings c2
            WHERE c2.vehicle_no = c.vehicle_no AND c2.crossed_at <= %s
            ORDER BY c2.crossed_at DESC LIMIT 1
        )
        AND c.lat IS NOT NULL AND c.lat != 0
    ''', (at,))
    rows = fetchall(cur); con.close()
    return jsonify({'trucks': rows})

@application.route('/api/hundred-truck-locations')
def hundred_truck_locations():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               c.plaza as last_plaza, c.lat, c.lng, c.crossed_at as last_seen
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.id IN (
            SELECT id FROM crossings c2
            WHERE c2.vehicle_no = c.vehicle_no
            ORDER BY c2.crossed_at DESC LIMIT 1
        )
        AND c.lat IS NOT NULL AND c.lat != 0
    ''')
    rows = fetchall(cur); con.close()
    return jsonify({'trucks': rows})

@application.route('/api/hundred-all-crossings')
def hundred_all_crossings():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               c.plaza, c.lat, c.lng, c.crossed_at
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.lat IS NOT NULL AND c.lat != 0
        ORDER BY c.crossed_at
    ''')
    rows = fetchall(cur); con.close()
    return jsonify({'crossings': rows})

@application.route('/api/hundred-routes')
def hundred_routes():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no, owner, state FROM trucks ORDER BY state, vehicle_no')
    trucks = fetchall(cur)
    result = []
    for t in trucks:
        vno = t['vehicle_no']
        cur.execute('SELECT DISTINCT plaza, crossed_at FROM crossings WHERE vehicle_no=%s ORDER BY crossed_at', (vno,))
        crossings = fetchall(cur)
        plazas = []
        for c in crossings:
            if not plazas or plazas[-1] != c['plaza']:
                plazas.append(c['plaza'])
        result.append({'vehicle_no': vno, 'owner': t['owner'] or 'Unknown', 'state': t['state'],
                       'plazas': plazas, 'unique_count': len(set(plazas)),
                       'first_seen': str(crossings[0]['crossed_at'])[:10] if crossings else '—',
                       'last_seen':  str(crossings[-1]['crossed_at'])[:10] if crossings else '—'})
    con.close()
    return jsonify({'routes': result})

@application.route('/api/hundred-plaza-report')
def hundred_plaza_report():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT plaza, COUNT(DISTINCT vehicle_no) as truck_count FROM crossings GROUP BY plaza ORDER BY truck_count DESC')
    plazas = fetchall(cur)
    result = []
    for p in plazas:
        cur.execute('SELECT DISTINCT vehicle_no FROM crossings WHERE plaza=%s ORDER BY vehicle_no', (p['plaza'],))
        trucks = [r['vehicle_no'] for r in fetchall(cur)]
        result.append({'plaza': p['plaza'], 'truck_count': p['truck_count'], 'trucks': trucks})
    con.close()
    return jsonify({'plazas': result})

@application.route('/api/hundred-plaza-detail')
def hundred_plaza_detail():
    plaza = request.args.get('plaza', '').strip()
    con = get_db(); cur = con.cursor()
    cur.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               COUNT(*) as cross_count,
               MIN(crossed_at) as first_cross,
               MAX(crossed_at) as last_cross
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.plaza = %s
        GROUP BY c.vehicle_no, t.owner, t.state ORDER BY cross_count DESC, c.vehicle_no
    ''', (plaza,))
    rows = fetchall(cur); con.close()
    return jsonify({'plaza': plaza, 'trucks': rows})

@application.route('/api/make-token')
def api_make_token():
    vno = request.args.get('vehicle_no', '').strip().upper()
    if not vno:
        return jsonify({'error': 'missing vehicle_no'}), 400
    return jsonify({'token': make_token(vno)})

@application.route('/api/track')
def track_by_token():
    token = request.args.get('token', '').strip()
    if not token:
        return jsonify({'error': 'missing token'}), 400
    vno = vehicle_from_token(token)
    if not vno:
        return jsonify({'error': 'invalid token'}), 404
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT * FROM trucks WHERE vehicle_no=%s', (vno,))
    truck = fetchone(cur) or {}
    cur.execute('SELECT plaza, lat, lng, direction, crossed_at FROM crossings WHERE vehicle_no=%s ORDER BY crossed_at', (vno,))
    crossings = fetchall(cur)
    con.close()
    dates = [str(c['crossed_at']) for c in crossings if c['crossed_at']]
    return jsonify({
        'vehicle_no': vno,
        'truck': truck,
        'crossings': crossings,
        'date_from': dates[0][:10] if dates else '—',
        'date_to':   dates[-1][:10] if dates else '—',
    })

def send_whatsapp(to, message):
    url  = f'https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages'
    body = json.dumps({
        'messaging_product': 'whatsapp',
        'to': to,
        'type': 'text',
        'text': {'body': message}
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Authorization': f'Bearer {WA_TOKEN}',
        'Content-Type': 'application/json'
    })
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())

@application.route('/api/send-wa-test')
def send_wa_test():
    try:
        result = send_whatsapp(WA_TO, 'Test message from Hundred Trucks dashboard.')
        print(f'WhatsApp test sent to {WA_TO}', flush=True)
        return jsonify({'status': 'sent', 'result': result})
    except Exception as e:
        print(f'WhatsApp test ERROR: {e}', flush=True)
        return jsonify({'status': 'error', 'error': str(e)})


@application.route('/api/ping-truck')
def ping_truck():
    vno = request.args.get('vehicle_no', '').strip().upper()
    if not vno:
        return jsonify({'error': 'missing vehicle_no'}), 400
    try:
        records = fetch_zoho(vno)
        new_rows = save_crossings(vno, records)
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Manual ping: {vno} — {len(records)} crossings ({new_rows} new)', flush=True)
        return jsonify({'vehicle_no': vno, 'total': len(records), 'new': new_rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@application.route('/api/add-enroute')
def add_enroute():
    vno = request.args.get('vehicle_no', '').strip().upper()
    if not vno:
        return jsonify({'error': 'missing vehicle_no'}), 400
    try:
        con = get_db(); cur = con.cursor()
        # Add to enroute_trips if not already there
        cur.execute('SELECT 1 FROM enroute_trips WHERE truck_no=%s', (vno,))
        if cur.fetchone():
            con.close()
            return jsonify({'status': 'already exists', 'vehicle_no': vno})
        cur.execute('''
            INSERT INTO enroute_trips (truck_no, tranco, shipper, trip_id, indent_number, pickup_pin, drop_pin, loading_point, reporting_date, reporting_time, is_manual, synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW())
        ''', (vno, '', '', '', '', '', '', '', '', ''))
        # Add to trucks table if not there
        cur.execute('SELECT 1 FROM trucks WHERE vehicle_no=%s', (vno,))
        if not cur.fetchone():
            state = vno[:2].upper()
            cur.execute('INSERT INTO trucks (vehicle_no, owner, state, is_connected) VALUES (%s, %s, %s, 1)', (vno, '', state))
        else:
            cur.execute('UPDATE trucks SET is_connected=1 WHERE vehicle_no=%s', (vno,))
        con.commit(); con.close()
        # Ping FASTag immediately
        records = fetch_zoho(vno)
        new_rows = save_crossings(vno, records)
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Manually added {vno} to enroute — {len(records)} crossings ({new_rows} new)', flush=True)
        return jsonify({'status': 'added', 'vehicle_no': vno, 'crossings': len(records), 'new': new_rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

CREDIT_TRIPS_URL  = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Live_ML_Credit_Trips?publickey=u0nbdmwSP912Bdfm3DkFaqVB6'
ENROUTE_TRIPS_URL = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Enroute_Trips?publickey=2yHyzpgDNmJgHtdJCKR1jCb8b'

def ensure_credit_trips_table():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS credit_trips (
            id SERIAL PRIMARY KEY,
            truck_no   TEXT NOT NULL,
            pickup     TEXT,
            drop_pin   TEXT,
            tranco     TEXT,
            lr_number  TEXT,
            lr_date    TEXT,
            synced_at  TIMESTAMP DEFAULT NOW()
        )
    ''')
    con.commit(); con.close()

def sync_credit_trips():
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Syncing credit trips from Zoho...', flush=True)
    try:
        req  = urllib.request.Request(CREDIT_TRIPS_URL)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        trips = data.get('result', {}).get('data', [])
        con = get_db(); cur = con.cursor()
        # Full replace — delete all, insert current
        cur.execute('DELETE FROM credit_trips')
        for t in trips:
            cur.execute('''
                INSERT INTO credit_trips (truck_no, pickup, drop_pin, tranco, lr_number, lr_date, synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ''', (
                str(t.get('truck_no','')).strip(),
                str(t.get('pickup','')).strip(),
                str(t.get('drop','')).strip(),
                str(t.get('tranco','')).strip(),
                str(t.get('lr_number','')).strip(),
                str(t.get('lr_date','')).strip(),
            ))
        con.commit(); con.close()
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Credit trips synced: {len(trips)} trips.', flush=True)
    except Exception as e:
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Credit trips sync ERROR: {e}', flush=True)

@application.route('/api/credit-trips')
def credit_trips():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute('SELECT truck_no, pickup, drop_pin, tranco, lr_number, lr_date, synced_at FROM credit_trips ORDER BY lr_date DESC, truck_no')
        rows = fetchall(cur); con.close()
        # Rename drop_pin → drop for frontend compatibility
        trips = [{'truck_no': r['truck_no'], 'pickup': r['pickup'], 'drop': r['drop_pin'],
                   'tranco': r['tranco'], 'lr_number': r['lr_number'], 'lr_date': r['lr_date']} for r in rows]
        return jsonify({'result': {'data': trips, 'code': '200'}, 'code': 3000})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def ensure_enroute_trips_table():
    con = get_db(); cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS enroute_trips (
            id            SERIAL PRIMARY KEY,
            truck_no      TEXT NOT NULL,
            tranco        TEXT,
            shipper       TEXT,
            trip_id       TEXT,
            indent_number TEXT,
            pickup_pin    TEXT,
            drop_pin      TEXT,
            loading_point TEXT,
            reporting_date TEXT,
            reporting_time TEXT,
            synced_at     TIMESTAMP DEFAULT NOW()
        )
    ''')
    # Add columns if they don't exist (for existing tables)
    cur.execute("ALTER TABLE enroute_trips ADD COLUMN IF NOT EXISTS reporting_time TEXT")
    cur.execute("ALTER TABLE enroute_trips ADD COLUMN IF NOT EXISTS is_manual BOOLEAN DEFAULT FALSE")
    con.commit(); con.close()

def sync_enroute_trips():
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Syncing enroute trips from Zoho...', flush=True)
    try:
        req  = urllib.request.Request(ENROUTE_TRIPS_URL)
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        trips = data.get('result', {}).get('data', [])
        con = get_db(); cur = con.cursor()
        # Snapshot existing data before replace for change detection
        cur.execute('SELECT truck_no, pickup_pin, drop_pin FROM enroute_trips')
        old_map = {r[0]: {'pickup': r[1], 'drop': r[2]} for r in cur.fetchall()}

        cur.execute('DELETE FROM enroute_trips WHERE is_manual IS NOT TRUE')
        zoho_vnos = set()
        new_trucks = removed_trucks = 0
        for t in trips:
            vno    = t.get('truck_number','').strip()
            tranco = t.get('tranco','').strip()
            lp     = t.get('loading_points', [{}])[0]
            if not vno:
                continue
            zoho_vnos.add(vno)
            cur.execute('''
                INSERT INTO enroute_trips (truck_no, tranco, shipper, trip_id, indent_number, pickup_pin, drop_pin, loading_point, reporting_date, reporting_time, synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ''', (
                vno, tranco,
                t.get('shipper','').strip(),
                t.get('trip_id','').strip(),
                t.get('indent_number','').strip(),
                t.get('pickup_pincode','').strip(),
                t.get('drop_pincode','').strip(),
                lp.get('loading_point','').strip(),
                lp.get('reporting_date','').strip(),
                lp.get('reporting_time', {}).get('SQLTime', '') if isinstance(lp.get('reporting_time'), dict) else str(lp.get('reporting_time','')).strip(),
            ))
            # Detect pickup/drop changes
            new_pickup = t.get('pickup_pincode','').strip()
            new_drop   = t.get('drop_pincode','').strip()
            if vno in old_map:
                if old_map[vno]['drop'] != new_drop:
                    print(f'  ⚠ Destination changed: {vno} — {old_map[vno]["drop"]} → {new_drop}', flush=True)
                if old_map[vno]['pickup'] != new_pickup:
                    print(f'  ⚠ Pickup changed: {vno} — {old_map[vno]["pickup"]} → {new_pickup}', flush=True)

            # Auto-add new trucks
            cur.execute('SELECT 1 FROM trucks WHERE vehicle_no=%s', (vno,))
            if not cur.fetchone():
                state = vno[:2].upper() if len(vno) >= 2 else 'TN'
                cur.execute(
                    'INSERT INTO trucks (vehicle_no, owner, state, is_connected) VALUES (%s, %s, %s, 1)',
                    (vno, tranco, state)
                )
                new_trucks += 1
                print(f'  + Auto-added: {vno} ({tranco})', flush=True)
            else:
                # Re-enable if it was previously disconnected
                cur.execute('UPDATE trucks SET is_connected=1, owner=%s WHERE vehicle_no=%s', (tranco, vno))

        # Disconnect trucks no longer in Zoho
        cur.execute('SELECT vehicle_no FROM trucks WHERE is_connected=1')
        for (db_vno,) in cur.fetchall():
            if db_vno not in zoho_vnos:
                cur.execute('UPDATE trucks SET is_connected=0 WHERE vehicle_no=%s', (db_vno,))
                removed_trucks += 1
                print(f'  - Disconnected: {db_vno} (no longer in Zoho)', flush=True)

        con.commit(); con.close()
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Enroute trips synced: {len(trips)} trips, +{new_trucks} added, -{removed_trucks} disconnected.', flush=True)
    except Exception as e:
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Enroute trips sync ERROR: {e}', flush=True)

@application.route('/api/enroute-trips')
def enroute_trips():
    try:
        con = get_db(); cur = con.cursor()
        cur.execute('SELECT truck_no, tranco, shipper, trip_id, indent_number, pickup_pin, drop_pin, loading_point, reporting_date, reporting_time, synced_at FROM enroute_trips ORDER BY truck_no')
        rows = fetchall(cur); con.close()
        trips = [{
            'truck_number':  r['truck_no'],
            'tranco':        r['tranco'],
            'shipper':       r['shipper'],
            'trip_id':       r['trip_id'],
            'indent_number': r['indent_number'],
            'pickup_pincode': r['pickup_pin'],
            'drop_pincode':  r['drop_pin'],
            'loading_points': [{'loading_point': r['loading_point'], 'reporting_date': r['reporting_date'], 'reporting_time': r['reporting_time']}],
        } for r in rows]
        return jsonify({'result': {'code': '200', 'data': trips}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@application.route('/api/credit-truck-route')
def credit_truck_route():
    vno = request.args.get('vehicle_no', '').strip().upper()
    if not vno:
        return jsonify({'crossings': []})
    try:
        records = fetch_zoho(vno)
        crossings = []
        for r in records:
            plaza    = r.get('tollPlazaName', '').strip()
            crossed_at = r.get('readerReadTime', '').strip()
            geocode  = r.get('tollPlazaGeocode', '')
            lat, lng = 0.0, 0.0
            if geocode and ',' in geocode:
                parts = geocode.split(',')
                try: lat, lng = float(parts[0]), float(parts[1])
                except: pass
            if plaza and crossed_at and lat and lng:
                crossings.append({'plaza': plaza, 'crossed_at': crossed_at, 'lat': lat, 'lng': lng})
        crossings.sort(key=lambda x: x['crossed_at'])
        return jsonify({'vehicle_no': vno, 'crossings': crossings})
    except Exception as e:
        return jsonify({'crossings': [], 'error': str(e)})

@application.route('/api/fasttag', methods=['POST'])
def fasttag():
    body = request.get_data()
    try:
        req  = urllib.request.Request(ZOHO_URL, data=body, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read()
        return application.response_class(data, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

def refresh_all_trucks():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no FROM trucks ORDER BY vehicle_no')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: refreshing all {len(trucks)} trucks...', flush=True)
    ok = fail = 0
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            if records:
                new_rows = save_crossings(vno, records)
                ok += 1
                print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)', flush=True)
            else:
                print(f'  — {vno} — no data', flush=True)
        except Exception as e:
            fail += 1
            print(f'  ✗ {vno} — ERROR: {e}', flush=True)
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Refresh complete. ✓ {ok} done  ✗ {fail} failed', flush=True)

def ping_enroute():
    # First sync fresh trip list from Zoho, then ping FASTag for each truck
    sync_enroute_trips()
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT DISTINCT truck_no FROM enroute_trips')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Ping enroute: {len(trucks)} trucks...', flush=True)
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            new_rows = save_crossings(vno, records)
            print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)', flush=True)
        except Exception as e:
            print(f'  ✗ {vno} — ERROR: {e}', flush=True)
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Ping enroute complete.', flush=True)

def ping_credit():
    # First sync fresh trip list from Zoho, then ping FASTag for each truck
    sync_credit_trips()
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT DISTINCT truck_no FROM credit_trips')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Ping credit: {len(trucks)} trucks...', flush=True)
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            new_rows = save_crossings(vno, records)
            print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)', flush=True)
        except Exception as e:
            print(f'  ✗ {vno} — ERROR: {e}', flush=True)
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Ping credit complete.', flush=True)


# Start background scheduler (only once, not in debug reloader child process)
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    ensure_credit_trips_table()
    ensure_enroute_trips_table()
    sync_credit_trips()    # sync on startup
    sync_enroute_trips()   # sync on startup
    scheduler = BackgroundScheduler(timezone='Asia/Kolkata')
    scheduler.add_job(ping_enroute,       'cron', minute=0)                      # every hour :00 IST
    scheduler.add_job(ping_credit,        'cron', hour=6,  minute=0)            # 6:00 AM IST (syncs Zoho + pings FASTag)
    scheduler.add_job(ping_credit,        'cron', hour=18, minute=0)            # 6:00 PM IST (syncs Zoho + pings FASTag)
    scheduler.add_job(sync_credit_trips,  'cron', hour=0,  minute=0)            # midnight IST (silent sync only)
    scheduler.add_job(sync_enroute_trips, 'cron', hour=0,  minute=0)            # midnight IST
    scheduler.start()
    print('APScheduler started — pinging enroute every hour, credit 3x/day.', flush=True)

if __name__ == '__main__':
    application.run(debug=True, port=8090)
