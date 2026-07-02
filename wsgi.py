"""
Render deployment entry point for Toll-Trace.cargo
Clean Flask app with no dependency on server.py
"""
import os, json, time, sqlite3, urllib.request
from flask import Flask, request, jsonify, send_from_directory

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ZOHO_URL = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Fast_Tag_Data?publickey=m2H9YHHA901WRUOAAFRY04WzD'
DB100 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hundred_trucks.db')

application = Flask(__name__, static_folder='.', static_url_path='')

def get_db():
    con = sqlite3.connect(DB100)
    con.row_factory = sqlite3.Row
    return con

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
    con = get_db()
    rows = con.execute('''
        SELECT t.vehicle_no, t.owner, t.state, t.is_connected, t.fetched_at,
               COUNT(DISTINCT c.plaza) as unique_plazas,
               COUNT(c.id) as crossing_count
        FROM trucks t
        LEFT JOIN crossings c ON t.vehicle_no = c.vehicle_no
        GROUP BY t.vehicle_no
        ORDER BY t.state, t.vehicle_no
    ''').fetchall()
    total_crossings = con.execute('SELECT COUNT(*) FROM crossings').fetchone()[0]
    total_plazas    = con.execute('SELECT COUNT(DISTINCT plaza) FROM crossings').fetchone()[0]
    con.close()
    return jsonify({'trucks': [dict(r) for r in rows], 'total_crossings': total_crossings, 'total_plazas': total_plazas})

@application.route('/api/hundred-truck-detail')
def hundred_truck_detail():
    vno = request.args.get('vehicle_no', '').strip().upper()
    con = get_db()
    truck = dict(con.execute('SELECT * FROM trucks WHERE vehicle_no=?', (vno,)).fetchone() or {})
    crossings = [dict(r) for r in con.execute(
        'SELECT plaza, lat, lng, direction, crossed_at FROM crossings WHERE vehicle_no=? ORDER BY crossed_at', (vno,)).fetchall()]
    plaza_summary = [dict(r) for r in con.execute(
        'SELECT plaza, lat, lng, COUNT(*) as count FROM crossings WHERE vehicle_no=? GROUP BY plaza ORDER BY count DESC', (vno,)).fetchall()]
    dates = [c['crossed_at'] for c in crossings if c['crossed_at']]
    con.close()
    return jsonify({
        'truck': truck, 'crossings': crossings, 'plaza_summary': plaza_summary,
        'unique_plazas': len(plaza_summary),
        'date_from': dates[0][:10] if dates else '—',
        'date_to':   dates[-1][:10] if dates else '—',
    })

@application.route('/api/hundred-plazas')
def hundred_plazas():
    con = get_db()
    rows = con.execute('''
        SELECT plaza, AVG(lat) as lat, AVG(lng) as lng,
               COUNT(DISTINCT vehicle_no) as truck_count,
               COUNT(*) as crossing_count
        FROM crossings
        WHERE lat IS NOT NULL AND lng IS NOT NULL AND lat != 0 AND lng != 0
        GROUP BY plaza ORDER BY truck_count DESC
    ''').fetchall()
    con.close()
    return jsonify({'plazas': [dict(r) for r in rows]})

@application.route('/api/hundred-truck-locations-at')
def hundred_truck_locations_at():
    at = request.args.get('at', '')
    con = get_db()
    rows = con.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               c.plaza as last_plaza, c.lat, c.lng, c.crossed_at as last_seen
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.id IN (
            SELECT id FROM crossings c2
            WHERE c2.vehicle_no = c.vehicle_no AND c2.crossed_at <= ?
            ORDER BY c2.crossed_at DESC LIMIT 1
        )
        AND c.lat IS NOT NULL AND c.lat != 0
    ''', (at,)).fetchall()
    con.close()
    return jsonify({'trucks': [dict(r) for r in rows]})

@application.route('/api/hundred-truck-locations')
def hundred_truck_locations():
    con = get_db()
    rows = con.execute('''
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
    ''').fetchall()
    con.close()
    return jsonify({'trucks': [dict(r) for r in rows]})

@application.route('/api/hundred-all-crossings')
def hundred_all_crossings():
    con = get_db()
    rows = con.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               c.plaza, c.lat, c.lng, c.crossed_at
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.lat IS NOT NULL AND c.lat != 0
        ORDER BY c.crossed_at
    ''').fetchall()
    con.close()
    return jsonify({'crossings': [dict(r) for r in rows]})

@application.route('/api/hundred-routes')
def hundred_routes():
    con = get_db()
    trucks = con.execute('SELECT vehicle_no, owner, state FROM trucks ORDER BY state, vehicle_no').fetchall()
    result = []
    for t in trucks:
        vno = t['vehicle_no']
        crossings = con.execute(
            'SELECT DISTINCT plaza, crossed_at FROM crossings WHERE vehicle_no=? ORDER BY crossed_at', (vno,)).fetchall()
        plazas = []
        for c in crossings:
            if not plazas or plazas[-1] != c['plaza']:
                plazas.append(c['plaza'])
        first_seen = crossings[0]['crossed_at'][:10] if crossings else '—'
        last_seen  = crossings[-1]['crossed_at'][:10] if crossings else '—'
        result.append({'vehicle_no': vno, 'owner': t['owner'] or 'Unknown', 'state': t['state'],
                       'plazas': plazas, 'unique_count': len(set(plazas)),
                       'first_seen': first_seen, 'last_seen': last_seen})
    con.close()
    return jsonify({'routes': result})

@application.route('/api/hundred-plaza-report')
def hundred_plaza_report():
    con = get_db()
    plazas = con.execute('''
        SELECT plaza, COUNT(DISTINCT vehicle_no) as truck_count
        FROM crossings GROUP BY plaza ORDER BY truck_count DESC
    ''').fetchall()
    result = []
    for p in plazas:
        trucks = [r[0] for r in con.execute(
            'SELECT DISTINCT vehicle_no FROM crossings WHERE plaza=? ORDER BY vehicle_no', (p['plaza'],)).fetchall()]
        result.append({'plaza': p['plaza'], 'truck_count': p['truck_count'], 'trucks': trucks})
    con.close()
    return jsonify({'plazas': result})

@application.route('/api/hundred-plaza-detail')
def hundred_plaza_detail():
    plaza = request.args.get('plaza', '').strip()
    con = get_db()
    rows = con.execute('''
        SELECT c.vehicle_no, t.owner, t.state,
               COUNT(*) as cross_count,
               MIN(crossed_at) as first_cross,
               MAX(crossed_at) as last_cross
        FROM crossings c
        JOIN trucks t ON c.vehicle_no = t.vehicle_no
        WHERE c.plaza = ?
        GROUP BY c.vehicle_no ORDER BY cross_count DESC, c.vehicle_no
    ''', (plaza,)).fetchall()
    con.close()
    return jsonify({'plaza': plaza, 'trucks': [dict(r) for r in rows]})

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

if __name__ == '__main__':
    application.run(debug=True, port=8080)
