#!/usr/bin/env python3
"""
Server for 100 Trucks FASTag Analysis Platform
"""
import http.server, json, urllib.request, webbrowser, threading, os, time
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv()
from urllib.parse import urlparse, parse_qs

PORT = 8081
NEON_URL = os.environ.get('DATABASE_URL')

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

# ||For this plaza, show me which trucks crossed it, how many times, and when first and last||
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/hundred-plaza-detail'):
            qs    = parse_qs(urlparse(self.path).query)
            plaza = qs.get('plaza', [''])[0].strip()
            con   = get_db(); cur = con.cursor()
            cur.execute('''
                SELECT c.vehicle_no, t.owner, t.state,
                       COUNT(*) as cross_count,
                       MIN(crossed_at) as first_cross,
                       MAX(crossed_at) as last_cross
                FROM crossings c
                JOIN trucks t ON c.vehicle_no = t.vehicle_no
                WHERE c.plaza = %s
                GROUP BY c.vehicle_no, t.owner, t.state
                ORDER BY cross_count DESC, c.vehicle_no
            ''', (plaza,))
            rows = fetchall(cur); con.close()
            self._json({'plaza': plaza, 'trucks': rows})

        elif self.path.startswith('/api/hundred-plaza-report'):
            con = get_db(); cur = con.cursor()
            cur.execute('SELECT plaza, COUNT(DISTINCT vehicle_no) as truck_count FROM crossings GROUP BY plaza ORDER BY truck_count DESC')
            plazas = fetchall(cur)
            result = []
            for p in plazas:
                cur.execute('SELECT DISTINCT vehicle_no FROM crossings WHERE plaza=%s ORDER BY vehicle_no', (p['plaza'],))
                trucks = [r['vehicle_no'] for r in fetchall(cur)]
                result.append({'plaza': p['plaza'], 'truck_count': p['truck_count'], 'trucks': trucks})
            con.close()
            self._json({'plazas': result})

        elif self.path.startswith('/api/hundred-routes'):
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
                result.append({
                    'vehicle_no': vno, 'owner': t['owner'] or 'Unknown', 'state': t['state'],
                    'plazas': plazas, 'unique_count': len(set(plazas)),
                    'first_seen': str(crossings[0]['crossed_at'])[:10] if crossings else '—',
                    'last_seen':  str(crossings[-1]['crossed_at'])[:10] if crossings else '—',
                })
            con.close()
            self._json({'routes': result})

        elif self.path.startswith('/api/hundred-truck-locations-at'):
            qs = parse_qs(urlparse(self.path).query)
            at = qs.get('at', [''])[0]
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
            self._json({'trucks': rows})

        elif self.path.startswith('/api/hundred-truck-locations'):
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
            self._json({'trucks': rows})

        elif self.path.startswith('/api/hundred-plazas'):
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
            self._json({'plazas': rows})

        elif self.path.startswith('/api/hundred-truck-detail'):
            qs  = parse_qs(urlparse(self.path).query)
            vno = qs.get('vehicle_no', [''])[0].strip().upper()
            con = get_db(); cur = con.cursor()
            cur.execute('SELECT * FROM trucks WHERE vehicle_no=%s', (vno,))
            truck = fetchone(cur) or {}
            cur.execute('SELECT plaza, lat, lng, direction, crossed_at FROM crossings WHERE vehicle_no=%s ORDER BY crossed_at', (vno,))
            crossings = fetchall(cur)
            cur.execute('SELECT plaza, lat, lng, COUNT(*) as count FROM crossings WHERE vehicle_no=%s GROUP BY plaza, lat, lng ORDER BY count DESC', (vno,))
            plaza_summary = fetchall(cur)
            dates = [str(c['crossed_at']) for c in crossings if c['crossed_at']]
            con.close()
            self._json({
                'truck': truck, 'crossings': crossings, 'plaza_summary': plaza_summary,
                'unique_plazas': len(plaza_summary),
                'date_from': dates[0][:10] if dates else '—',
                'date_to':   dates[-1][:10] if dates else '—',
            })

        elif self.path.startswith('/api/enroute-trips'):
            import urllib.request as _ur
            try:
                url = 'https://www.zohoapis.in/creator/custom/mirchi-lime/Fetch_Enroute_Trips?publickey=2yHyzpgDNmJgHtdJCKR1jCb8b'
                resp = _ur.urlopen(url, timeout=10)
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Access-Control-Allow-Origin','*')
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._json({'error': str(e)})

        elif self.path.startswith('/api/hundred-all-crossings'):
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
            self._json({'crossings': rows})

        elif self.path.startswith('/api/hundred-trucks'):
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
            cur.execute('SELECT COUNT(*) as cnt FROM crossings')
            total_crossings = cur.fetchone()[0]
            cur.execute('SELECT COUNT(DISTINCT plaza) as cnt FROM crossings')
            total_plazas = cur.fetchone()[0]
            con.close()
            self._json({'trucks': rows, 'total_crossings': total_crossings, 'total_plazas': total_plazas})

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
