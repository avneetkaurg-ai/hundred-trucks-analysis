#!/usr/bin/env python3
"""
Server for 100 Trucks FASTag Analysis Platform
"""
import http.server, json, urllib.request, webbrowser, threading, os, sqlite3, time
from urllib.parse import urlparse, parse_qs

PORT = 8081
DB100 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hundred_trucks.db')

def get_db():
    con = sqlite3.connect(DB100)
    con.row_factory = sqlite3.Row
    return con

# ||For this plaza, show me which trucks crossed it, how many times, and when first and last||
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/hundred-plaza-detail'):
            qs    = parse_qs(urlparse(self.path).query)
            plaza = qs.get('plaza', [''])[0].strip()
            con   = get_db()
            rows  = con.execute('''
                SELECT c.vehicle_no, t.owner, t.state,
                       COUNT(*) as cross_count,
                       MIN(crossed_at) as first_cross,
                       MAX(crossed_at) as last_cross
                FROM crossings c
                JOIN trucks t ON c.vehicle_no = t.vehicle_no
                WHERE c.plaza = ?
                GROUP BY c.vehicle_no
                ORDER BY cross_count DESC, c.vehicle_no
            ''', (plaza,)).fetchall()
            con.close()
            self._json({'plaza': plaza, 'trucks': [dict(r) for r in rows]})

#||Show all plazas and how many different trucks crossed each one — most busy plaza first||
        elif self.path.startswith('/api/hundred-plaza-report'):
            con = get_db()
            plazas = con.execute('''
                SELECT plaza, COUNT(DISTINCT vehicle_no) as truck_count
                FROM crossings GROUP BY plaza ORDER BY truck_count DESC
            ''').fetchall()
            result = []
            for p in plazas:
                trucks = [r[0] for r in con.execute(
                    'SELECT DISTINCT vehicle_no FROM crossings WHERE plaza=? ORDER BY vehicle_no',
                    (p['plaza'],)).fetchall()]
                result.append({'plaza': p['plaza'], 'truck_count': p['truck_count'], 'trucks': trucks})
            con.close()
            self._json({'plazas': result})

#||Get all trucks, then for each truck get the list of plazas in order of time||
        elif self.path.startswith('/api/hundred-routes'):
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
                result.append({
                    'vehicle_no': vno, 'owner': t['owner'] or 'Unknown', 'state': t['state'],
                    'plazas': plazas, 'unique_count': len(set(plazas)),
                    'first_seen': crossings[0]['crossed_at'][:10] if crossings else '—',
                    'last_seen':  crossings[-1]['crossed_at'][:10] if crossings else '—',
                })
            con.close()
            self._json({'routes': result})

#||For each truck, find the last plaza it crossed before the selected time on the slider||
        elif self.path.startswith('/api/hundred-truck-locations-at'):
            qs = parse_qs(urlparse(self.path).query)
            at = qs.get('at', [''])[0]
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
            self._json({'trucks': [dict(r) for r in rows]})

        
#||For each truck, find its latest crossing — used for current location on map||
        elif self.path.startswith('/api/hundred-truck-locations'):
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
            self._json({'trucks': [dict(r) for r in rows]})

#||Show all plazas with their coordinates, how many trucks crossed and total crossings||
        elif self.path.startswith('/api/hundred-plazas'):
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
            self._json({'plazas': [dict(r) for r in rows]})

#||Get everything about one truck — its info, all its crossings in order, and plaza summary||
        elif self.path.startswith('/api/hundred-truck-detail'):
            qs  = parse_qs(urlparse(self.path).query)
            vno = qs.get('vehicle_no', [''])[0].strip().upper()
            con = get_db()
            truck = dict(con.execute('SELECT * FROM trucks WHERE vehicle_no=?', (vno,)).fetchone() or {})
            crossings = [dict(r) for r in con.execute(
                'SELECT plaza, lat, lng, direction, crossed_at FROM crossings WHERE vehicle_no=? ORDER BY crossed_at', (vno,)).fetchall()]
            plaza_summary = [dict(r) for r in con.execute(
                'SELECT plaza, lat, lng, COUNT(*) as count FROM crossings WHERE vehicle_no=? GROUP BY plaza ORDER BY count DESC', (vno,)).fetchall()]
            dates = [c['crossed_at'] for c in crossings if c['crossed_at']]
            con.close()
            self._json({
                'truck': truck, 'crossings': crossings, 'plaza_summary': plaza_summary,
                'unique_plazas': len(plaza_summary),
                'date_from': dates[0][:10] if dates else '—',
                'date_to':   dates[-1][:10] if dates else '—',
            })

#||Show all 100 trucks with how many unique plazas and total crossings for each||
        elif self.path.startswith('/api/hundred-trucks'):
            con = get_db()
            rows = con.execute('''
                SELECT t.vehicle_no, t.owner, t.state, t.is_connected, t.fetched_at,
                       COUNT(DISTINCT c.plaza) as unique_plazas,
                       COUNT(c.id) as crossing_count
                FROM trucks t
                LEFT JOIN crossings c ON t.vehicle_no = c.vehicle_no
                GROUP BY t.vehicle_no ORDER BY t.state, t.vehicle_no
            ''').fetchall()
            total_crossings = con.execute('SELECT COUNT(*) FROM crossings').fetchone()[0]
            total_plazas    = con.execute('SELECT COUNT(DISTINCT plaza) FROM crossings').fetchone()[0]
            con.close()
            self._json({'trucks': [dict(r) for r in rows], 'total_crossings': total_crossings, 'total_plazas': total_plazas})

        else:
            super().do_GET()

#||converts data to JSON and sends it back to the browser||
    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

# ||tells the browser "yes you are allowed to talk to me||
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

#||keeps the terminal clean by silencing all request logs||
    def log_message(self, format, *args):
        pass

#||This block starts the server, opens the browser and keeps everything running.||
if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = http.server.HTTPServer(('', PORT), Handler)
    print(f'100 Trucks server running at http://localhost:{PORT}')
    threading.Timer(1, lambda: webbrowser.open(f'http://localhost:{PORT}/hundred_trucks.html')).start()
    server.serve_forever()
