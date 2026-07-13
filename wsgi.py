"""
Render deployment entry point for Toll-Trace.cargo
Clean Flask app with no dependency on server.py
"""
import os, json, time, urllib.request, hmac, hashlib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ZOHO_URL     = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
NEON_URL     = os.environ.get('DATABASE_URL')
TOKEN_SECRET = os.environ.get('TOKEN_SECRET', 'tolltrace-secret-key-2026')
GMAIL_USER   = os.environ.get('GMAIL_USER', 'av.kaor0509@gmail.com')
GMAIL_PASS   = os.environ.get('GMAIL_PASS', 'oxstpgteuyjcavuk')
REPORT_TO    = os.environ.get('REPORT_TO', 'av.kaor0509@gmail.com')

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

# ‚îÄ‚îÄ Static files ‚îÄ‚îÄ
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
    # track.html is public, everything else requires key
    if filename == 'track.html':
        return send_from_directory('.', filename)
    key = request.args.get('key','')
    if key != DASHBOARD_KEY:
        return not_found_page()
    return send_from_directory('.', filename)

# ‚îÄ‚îÄ API routes ‚îÄ‚îÄ

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
        'date_from': dates[0][:10] if dates else '‚Äî',
        'date_to':   dates[-1][:10] if dates else '‚Äî',
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
                       'first_seen': str(crossings[0]['crossed_at'])[:10] if crossings else '‚Äî',
                       'last_seen':  str(crossings[-1]['crossed_at'])[:10] if crossings else '‚Äî'})
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
        'date_from': dates[0][:10] if dates else '‚Äî',
        'date_to':   dates[-1][:10] if dates else '‚Äî',
    })

@application.route('/api/send-report')
def send_report_now():
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Test Email from Hundred Trucks'
        msg['From']    = GMAIL_USER
        msg['To']      = REPORT_TO
        msg.attach(MIMEText('<p>This is a test email.</p>', 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, REPORT_TO, msg.as_string())
        print(f'Test email sent to {REPORT_TO}', flush=True)
        return jsonify({'status': 'sent', 'to': REPORT_TO})
    except Exception as e:
        print(f'Test email ERROR: {e}', flush=True)
        return jsonify({'status': 'error', 'error': str(e)})

@application.route('/api/ping-truck')
def ping_truck():
    vno = request.args.get('vehicle_no', '').strip().upper()
    if not vno:
        return jsonify({'error': 'missing vehicle_no'}), 400
    try:
        records = fetch_zoho(vno)
        new_rows = save_crossings(vno, records)
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Manual ping: {vno} ‚Äî {len(records)} crossings ({new_rows} new)', flush=True)
        return jsonify({'vehicle_no': vno, 'total': len(records), 'new': new_rows})
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
        # Full replace ‚Äî delete all, insert current
        cur.execute('DELETE FROM credit_trips')
        for t in trips:
            cur.execute('''
                INSERT INTO credit_trips (truck_no, pickup, drop_pin, tranco, lr_number, lr_date, synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ''', (
                t.get('truck_no','').strip(),
                t.get('pickup','').strip(),
                t.get('drop','').strip(),
                t.get('tranco','').strip(),
                t.get('lr_number','').strip(),
                t.get('lr_date','').strip(),
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
        # Rename drop_pin ‚Üí drop for frontend compatibility
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
    # Add reporting_time column if it doesn't exist (for existing tables)
    cur.execute("ALTER TABLE enroute_trips ADD COLUMN IF NOT EXISTS reporting_time TEXT")
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

        cur.execute('DELETE FROM enroute_trips')
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
                    print(f'  ‚ö† Destination changed: {vno} ‚Äî {old_map[vno]["drop"]} ‚Üí {new_drop}', flush=True)
                if old_map[vno]['pickup'] != new_pickup:
                    print(f'  ‚ö† Pickup changed: {vno} ‚Äî {old_map[vno]["pickup"]} ‚Üí {new_pickup}', flush=True)

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
                print(f'  ‚úì {vno} ‚Äî {len(records)} crossings ({new_rows} new)', flush=True)
            else:
                print(f'  ‚Äî {vno} ‚Äî no data', flush=True)
        except Exception as e:
            fail += 1
            print(f'  ‚úó {vno} ‚Äî ERROR: {e}', flush=True)
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Refresh complete. ‚úì {ok} done  ‚úó {fail} failed', flush=True)

def ping_connected():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no FROM trucks WHERE is_connected=1')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: pinging {len(trucks)} connected trucks...', flush=True)
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            new_rows = save_crossings(vno, records)
            print(f'  ‚úì {vno} ‚Äî {len(records)} crossings ({new_rows} new)', flush=True)
        except Exception as e:
            print(f'  ‚úó {vno} ‚Äî ERROR: {e}', flush=True)
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: ping complete.', flush=True)

def send_morning_report():
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Sending morning email report...', flush=True)
    try:
        con = get_db(); cur = con.cursor()
        # Get all enroute trucks with their latest crossing
        cur.execute('''
            SELECT e.truck_no, e.tranco, e.shipper, e.loading_point, e.drop_pin,
                   c.plaza as last_plaza, c.crossed_at as last_seen
            FROM enroute_trips e
            LEFT JOIN LATERAL (
                SELECT plaza, crossed_at FROM crossings
                WHERE vehicle_no = e.truck_no
                ORDER BY crossed_at DESC LIMIT 1
            ) c ON true
            ORDER BY e.truck_no
        ''')
        trucks = fetchall(cur); con.close()

        if not trucks:
            print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] No enroute trucks to report.', flush=True)
            return

        today = time.strftime('%d %b %Y')
        base_url = 'https://hundred-trucks-analysis.onrender.com'

        # Build HTML email
        rows_html = ''
        for t in trucks:
            token = make_token(t['truck_no'])
            link  = f"{base_url}/track.html?token={token}"
            last  = t['last_seen'].strftime('%d %b, %I:%M %p') if t['last_seen'] else '‚Äî'
            plaza = t['last_plaza'] or '‚Äî'
            rows_html += (
                '<tr>'
                '<td style="padding:10px;border-bottom:1px solid #eee;font-weight:700;">' + t['truck_no'] + '</td>'
                '<td style="padding:10px;border-bottom:1px solid #eee;color:#555;">' + (t['tranco'] or '‚Äî') + '</td>'
                '<td style="padding:10px;border-bottom:1px solid #eee;color:#555;">' + (t['loading_point'] or '‚Äî') + '</td>'
                '<td style="padding:10px;border-bottom:1px solid #eee;color:#555;">' + plaza + '<br><span style="font-size:11px;color:#aaa;">' + last + '</span></td>'
                '<td style="padding:10px;border-bottom:1px solid #eee;">'
                '<a href="' + link + '" style="background:#2f6fd4;color:#fff;padding:5px 12px;border-radius:5px;text-decoration:none;font-size:12px;">Track Live</a>'
                '</td></tr>'
            )

        html = (
            '<div style="font-family:Arial,sans-serif;max-width:700px;margin:auto;">'
            '<div style="background:#1a1a2e;padding:20px;border-radius:8px 8px 0 0;">'
            '<h2 style="color:#fff;margin:0;">Daily Truck Report</h2>'
            '<p style="color:#aaa;margin:4px 0 0;">' + today + ' &nbsp;&middot;&nbsp; ' + str(len(trucks)) + ' trucks enroute</p>'
            '</div>'
            '<table style="width:100%;border-collapse:collapse;background:#fff;">'
            '<thead><tr style="background:#f5f5f5;">'
            '<th style="padding:10px;text-align:left;font-size:12px;color:#888;">TRUCK</th>'
            '<th style="padding:10px;text-align:left;font-size:12px;color:#888;">TRANSPORTER</th>'
            '<th style="padding:10px;text-align:left;font-size:12px;color:#888;">LOADING POINT</th>'
            '<th style="padding:10px;text-align:left;font-size:12px;color:#888;">LAST LOCATION</th>'
            '<th style="padding:10px;text-align:left;font-size:12px;color:#888;">LINK</th>'
            '</tr></thead>'
            '<tbody>' + rows_html + '</tbody>'
            '</table>'
            '<div style="background:#f9f9f9;padding:12px;border-radius:0 0 8px 8px;text-align:center;">'
            '<a href="' + base_url + '/hundred_trucks.html" style="color:#2f6fd4;font-size:12px;">Open Full Dashboard</a>'
            '</div></div>'
        )

        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Daily Truck Report ‚Äî ' + today
        msg['From']    = GMAIL_USER
        msg['To']      = REPORT_TO
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, REPORT_TO, msg.as_string())

        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Morning report sent to {REPORT_TO}.', flush=True)
    except Exception as e:
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Morning report ERROR: {e}', flush=True)

# Start background scheduler (only once, not in debug reloader child process)
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    ensure_credit_trips_table()
    ensure_enroute_trips_table()
    sync_credit_trips()    # sync on startup
    sync_enroute_trips()   # sync on startup
    scheduler = BackgroundScheduler()
    scheduler.add_job(ping_connected, 'cron', minute=30)                         # every hour at :30 UTC = :00 IST
    scheduler.add_job(refresh_all_trucks, 'cron', hour=1,  minute=0)            # 6:30 AM IST
    scheduler.add_job(refresh_all_trucks, 'cron', hour=5,  minute=0)            # 10:30 AM IST
    scheduler.add_job(refresh_all_trucks, 'cron', hour=12, minute=0)            # 5:30 PM IST
    scheduler.add_job(refresh_all_trucks, 'cron', hour=18, minute=0)            # 11:30 PM IST
    scheduler.add_job(sync_credit_trips,  'cron', hour=18, minute=30)           # midnight IST (18:30 UTC)
    scheduler.add_job(sync_enroute_trips, 'cron', hour=18, minute=30)           # midnight IST (18:30 UTC)
    scheduler.add_job(send_morning_report, 'cron', hour=1, minute=0)            # 6:30 AM IST (1:00 UTC)
    scheduler.start()
    print('APScheduler started ‚Äî pinging connected trucks every hour.', flush=True)

if __name__ == '__main__':
    application.run(debug=True, port=8080)
