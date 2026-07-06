"""
Render deployment entry point for Toll-Trace.cargo
Clean Flask app with no dependency on server.py
"""
import os, json, time, urllib.request
import psycopg2, psycopg2.extras
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ZOHO_URL = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
NEON_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_pnc9sKCDVo8X@ep-sweet-river-aoofzrdu.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require')

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
@application.route('/')
def index():
    return send_from_directory('.', 'hundred_trucks.html')

@application.route('/<path:filename>')
def static_files(filename):
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

@application.route('/api/enroute-trips')
def enroute_trips():
    try:
        url = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Enroute_Trips?publickey=2yHyzpgDNmJgHtdJCKR1jCb8b'
        req  = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read()
        return application.response_class(data, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: refreshing all {len(trucks)} trucks...')
    ok = fail = 0
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            if records:
                new_rows = save_crossings(vno, records)
                ok += 1
                print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)')
            else:
                print(f'  — {vno} — no data')
        except Exception as e:
            fail += 1
            print(f'  ✗ {vno} — ERROR: {e}')
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Refresh complete. ✓ {ok} done  ✗ {fail} failed')

def ping_connected():
    con = get_db(); cur = con.cursor()
    cur.execute('SELECT vehicle_no FROM trucks WHERE is_connected=1')
    trucks = [r[0] for r in cur.fetchall()]
    con.close()
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: pinging {len(trucks)} connected trucks...')
    for vno in trucks:
        try:
            records = fetch_zoho(vno)
            new_rows = save_crossings(vno, records)
            print(f'  ✓ {vno} — {len(records)} crossings ({new_rows} new)')
        except Exception as e:
            print(f'  ✗ {vno} — ERROR: {e}')
        time.sleep(3)
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Scheduler: ping complete.')

# Start background scheduler (only once, not in debug reloader child process)
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    scheduler = BackgroundScheduler()
    scheduler.add_job(ping_connected, 'cron', hour='*/2', minute=30)   # every even hour IST (UTC+5:30)
    scheduler.add_job(refresh_all_trucks, 'cron', hour=18, minute=30)  # daily at 12:00 AM IST (midnight)
    scheduler.start()
    print('APScheduler started — pinging connected trucks every 2 hours.')

if __name__ == '__main__':
    application.run(debug=True, port=8080)
