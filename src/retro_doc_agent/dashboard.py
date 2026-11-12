"""Read-only loopback dashboard; never serves source or arbitrary output files."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .pipeline import linked

PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Retro Lab · Execution</title>
<style>body{margin:0;background:#10151e;color:#e5eaf2;font:16px system-ui}main{max-width:1100px;margin:55px auto;padding:24px}small{color:#93a8c2}h1{font-size:40px;margin:12px 0}section{background:#1a2331;border:1px solid #344154;border-radius:14px;padding:24px;margin:22px 0}.metrics{display:flex;gap:35px;flex-wrap:wrap}.metric{font-size:30px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:14px 8px;border-bottom:1px solid #344154}button{background:#a7f0cd;color:#10151e;padding:10px 18px;border:0;border-radius:8px;cursor:pointer}.partial{color:#ffcd7d}#message{color:#ffcd7d}a{color:#a7f0cd}</style>
<main><small>RETRO DOCUMENTATION LAB / LOCAL EXECUTION</small><h1>Evidence before conclusions.</h1><p>Track preparation, review stages, and documentation uncertainty.</p><button id="refresh">Refresh runs</button><p id="message" role="status"></p><section class="metrics" id="metrics"></section><section><h2>Execution history</h2><table><thead><tr><th>Run</th><th>Status</th><th>Files</th><th>Finished</th></tr></thead><tbody id="runs"></tbody></table></section><section><h2>Stage checkpoints</h2><div id="detail">Select a run to inspect progress.</div></section><small>Read-only dashboard · Loopback only · No source contents served · Unknown coverage remains unknown</small></main>
<script>
function showImpact(detail, run) {
    if (run.revision) detail.append(el('p', 'Resolved revision: ' + run.revision));
    if (run.declared_revision) detail.append(el('p', 'Declared local revision: ' + run.declared_revision));
    for (const impact of run.impacts || []) {
        const box = el('section', '');
        box.append(el('h3', 'Changes from ' + impact.baseline));
        const labels = {added:'Added', modified:'Modified', removed:'Removed', unchanged:'Unchanged', unknown:'Unknown'};
        const total = Object.keys(labels).reduce((sum, key) => sum + impact.counts[key], 0);
        for (const [key, label] of Object.entries(labels)) {
            const row = el('p', label + ' · ' + impact.counts[key] + ' ');
            const meter = el('meter', '');
            meter.max = Math.max(total, 1);
            meter.value = impact.counts[key];
            meter.setAttribute('aria-label', label);
            row.append(meter);
            box.append(row);
        }
        box.append(el('p', impact.review_actions + ' review actions'));
        detail.append(box);
    }
}
</script>
<script>let data=[];function el(tag,text){let e=document.createElement(tag);e.textContent=text;return e}function details(r){let d=document.getElementById('detail');d.replaceChildren();showImpact(d,r);for(let [stage,status] of Object.entries(r.stages||{}))d.append(el('p',stage+' — '+status));d.append(el('p','Limitations: '+(r.limitations||[]).join(' ')));for(let error of r.errors||[])d.append(el('p',error))}async function refresh(){try{let response=await fetch('/api/runs',{cache:'no-store'});if(!response.ok)throw Error();data=await response.json();let body=document.getElementById('runs');body.replaceChildren();for(let r of data){let row=el('tr','');let cell=el('td','');let b=el('button',r.id);b.onclick=()=>details(r);cell.append(b);row.append(cell,el('td',r.status),el('td',String(r.files)),el('td',r.finished_at||'In progress'));body.append(row)}let m=document.getElementById('metrics');m.replaceChildren();for(let text of [data.length+' runs',data.filter(r=>r.status==='running').length+' running',data.filter(r=>r.status==='partial').length+' awaiting review'])m.append(el('div',text));document.getElementById('message').textContent=data.length?'Updated '+new Date().toLocaleTimeString():'No runs yet. Start a synthetic run using the CLI.'}catch{document.getElementById('message').textContent='Dashboard disconnected. Retrying automatically.'}}document.getElementById('refresh').onclick=refresh;refresh();setInterval(refresh,3000);</script></html>'''

def impact_summaries(folder):
    summaries = []
    for path in sorted(folder.glob('impact-from-*.json'))[:20]:
        try:
            if linked(path) or path.stat().st_size > 25_000_000:
                continue
            report = json.loads(path.read_text(encoding='utf-8'))
            if report['schema_version'] != 1 or report['current_run'] != folder.name:
                continue
            counts = report['counts']
            if not all(type(counts[key]) is int and counts[key] >= 0
                       for key in ('added', 'removed', 'modified', 'unchanged', 'unknown')):
                continue
            summaries.append({
                'baseline': report['baseline_run'], 'counts': counts,
                'review_actions': len(report['review_actions']),
            })
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return summaries


def snapshot(output):
    result = []
    if not output.exists():
        return result
    for folder in sorted(output.iterdir(), reverse=True):
        if linked(folder) or not folder.is_dir():
            continue
        path = folder / 'run.json'
        try:
            if linked(path) or path.stat().st_size > 25_000_000:
                continue
            r = json.loads(path.read_text(encoding='utf-8'))
            result.append({'id': folder.name, 'status': r['status'], 'files': len(r['inspected_files']),
                           'finished_at': r['finished_at'], 'stages': r['stages'],
                           'limitations': r['limitations'], 'errors': r['errors'],
                           'revision': r.get('source_revision'),
                           'declared_revision': r.get('declared_revision'),
                           'impacts': impact_summaries(folder)})
        except (OSError, ValueError, KeyError):
            continue
    return result

def handler(output):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                body, kind = PAGE.encode(), 'text/html; charset=utf-8'
            elif self.path == '/api/runs':
                body, kind = json.dumps(snapshot(output)).encode(), 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    return Handler

def serve_dashboard(output, port):
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(Path(output)))
    print(f'Dashboard: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
