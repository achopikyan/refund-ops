"""One-command local development, verification and evaluation runner."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import socket
import time
import threading
import signal
import urllib.request
import urllib.error
import webbrowser
from backend.refundops.runtime import code_revision

ROOT=Path(__file__).resolve().parent
PY=ROOT/(".venv/Scripts/python.exe" if os.name=="nt" else ".venv/bin/python")
NPM=shutil.which("npm.cmd" if os.name=="nt" else "npm")
def workspace_id(database):
    return hashlib.sha256(str(Path(database).resolve()).encode()).hexdigest()[:16]
def app_health(port,database):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=.6) as response:data=json.load(response)
        if data.get("service")=="refund-operations" and data.get("workspace_id")==workspace_id(database) and data.get("status")=="ok":return data
    except (OSError,ValueError):pass
    return None
def existing_app(port,database):return app_health(port,database) is not None
def frontend_current():
    built=ROOT/'frontend/dist/index.html'
    sources=list((ROOT/'frontend/src').rglob('*'))+[ROOT/'frontend/package-lock.json',ROOT/'frontend/index.html']
    return built.exists() and all(not p.is_file() or p.stat().st_mtime<=built.stat().st_mtime for p in sources)
def stop_stale_app(port,database,expected):
    current=app_health(port,database)
    pid=expected.get('process_id')
    if not current or current.get('process_id')!=pid or type(pid) is not int or pid<=0 or pid==os.getpid():
        raise RuntimeError('The running app changed during the update. Run the launcher again.')
    print('Updating the running Refund Operations server to the current code...',flush=True)
    os.kill(pid,signal.SIGTERM)
    for _ in range(100):
        if not existing_app(port,database):return
        time.sleep(.1)
    raise RuntimeError('The old server did not stop. Close its server window and run the launcher again.')
def available_port(preferred):
    for port in range(preferred,min(preferred+20,65536)):
        with socket.socket() as sock:
            try:sock.bind(("127.0.0.1",port));return port
            except OSError:continue
    raise RuntimeError("No free local port nearby. Try --port 8100.")
def open_browser(url,disabled=False):
    if disabled:return
    try:
        if not webbrowser.open(url,new=2):print("Open this address in your browser:",url,flush=True)
    except OSError:print("Open this address in your browser:",url,flush=True)

def rotate_log(path,max_bytes=5*1024*1024):
    """Keep the last complete log when the current file exceeds its local limit."""
    path=Path(path)
    if path.exists() and path.stat().st_size>=max_bytes:
        path.replace(path.with_suffix(path.suffix+'.1'))
def run(command,cwd=ROOT,**kwargs):
    print("Running:"," ".join(map(str,command)),flush=True)
    subprocess.run(list(map(str,command)),cwd=cwd,check=True,**kwargs)
def bootstrap():
    if not PY.exists() and not (3,12)<=sys.version_info[:2]<(3,14):raise RuntimeError("Use Python 3.12 or 3.13.")
    if not NPM:raise SystemExit("Install Node.js 22.12+ or 24 LTS (npm is required).")
    version=subprocess.check_output([shutil.which("node"),"--version"],text=True).strip().lstrip("v").split(".")
    if tuple(map(int,version[:2]))<(22,12):raise SystemExit("Use Node.js 22.12+ or 24 LTS.")
    uv=shutil.which("uv")
    if not PY.exists():
        if uv:run([uv,"venv",str(ROOT/".venv"),"--python",sys.executable])
        else:run([sys.executable,"-m","venv",ROOT/".venv"])
    compatible = subprocess.run([str(PY), '-c', 'import sys; sys.exit(0 if (3,12)<=sys.version_info[:2]<(3,14) else 1)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if compatible.returncode:
        raise RuntimeError('The local .venv needs Python 3.12 or 3.13. Rename .venv and launch with a supported Python. Do not copy virtual environments between operating systems.')
    # Compare installed versions, so local restarts need neither a registry nor a lock resolver.
    check="from importlib.metadata import version;from pathlib import Path;"+f"lines=Path({str(ROOT/'requirements.lock')!r}).read_text().splitlines();"+"assert all(version(x.split('==')[0])==x.split('==')[1] for x in lines if x and not x.startswith('#'))"
    if subprocess.run([str(PY),"-c",check],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        run([uv,"pip","sync","--python",PY,"requirements.lock"] if uv else [PY,"-m","pip","install","-r","requirements.lock"])
    lock=(ROOT/"frontend/package-lock.json").read_bytes()
    stamp=ROOT/"frontend/node_modules/.refundops-lock"
    digest=hashlib.sha256(lock).hexdigest()
    if not stamp.exists() or stamp.read_text()!=digest:
        run([NPM,"ci","--no-audit","--no-fund"],ROOT/"frontend")
        stamp.write_text(digest)
    os.environ["PYTHONPATH"]=str(ROOT/"backend")
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Run backend tests and production frontend build")
    parser.add_argument("--csv",type=Path,help="Seed this pending CSV instead of the sample pending file")
    parser.add_argument("--db",type=Path,help="Isolated SQLite database path")
    parser.add_argument("--port",type=int,default=18474)
    parser.add_argument("--no-browser",action="store_true",help="Start without opening the browser")
    parser.add_argument("--restart",action="store_true",help="Replace this workspace's server, including one started from a restricted session")
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error("Choose a port from 1024 to 65535.")
    if args.csv:args.csv=args.csv.resolve()
    if args.db:args.db=args.db.resolve()
    os.chdir(ROOT)
    if args.csv and not args.db:
        if not args.csv.is_file(): raise SystemExit('CSV file not found.')
        args.db=ROOT/'var'/('import-'+hashlib.sha256(args.csv.read_bytes()).hexdigest()[:16]+'.sqlite3')
    database=args.db or Path(os.environ.get("REFUNDOPS_DB",str(ROOT/"var/refundops.sqlite3")))
    launch_state_path=ROOT/"var/launcher-state.json"
    try:launch_state=json.loads(launch_state_path.read_text(encoding="utf-8"))
    except (OSError,ValueError):launch_state={}
    stale=None
    if not args.check:
        ports=[args.port];previous=launch_state.get(workspace_id(database))
        explicit_port=any(x=='--port' or x.startswith('--port=') for x in sys.argv[1:])
        if not explicit_port and type(previous) is int and 1024<=previous<=65535 and previous not in ports:ports.append(previous)
        for port in ports:
            health=app_health(port,database)
            if health:
                if args.restart or health.get('backend_revision')!=code_revision():
                    stale=(port,health);args.port=port;break
                if not frontend_current():
                    bootstrap();run([NPM,'run','build'],ROOT/'frontend')
                url=f"http://127.0.0.1:{port}";print("Refund Operations is already running with current code:",url,flush=True)
                open_browser(url,args.no_browser);return
    bootstrap()
    if args.check:
        run([PY,"-m","unittest","discover","-s","scripts/tests","-v"])
        run([PY,"-m","pytest","-q","--tb=short","--junitxml=var/reports/tests.xml"])
        run([NPM,"run","build"],ROOT/"frontend");return
    if args.csv:
        if not args.csv.is_file():raise SystemExit("CSV file not found.")
        os.environ["REFUNDOPS_PENDING_CSV"]=str(args.csv.resolve())
    if args.db:os.environ["REFUNDOPS_DB"]=str(args.db.resolve())
    os.environ['REFUNDOPS_SOURCE_POLICIES']='1'
    run([NPM,"run","build"],ROOT/"frontend")
    if stale:stop_stale_app(stale[0],database,stale[1])
    reset_request=ROOT/'var/source-rebuild-request.json'
    if reset_request.exists() and database.resolve()==(ROOT/'var/refundops.sqlite3').resolve():
        request=json.loads(reset_request.read_text(encoding='utf-8'))
        staged=Path(request['staged_database']).resolve()
        if not staged.is_relative_to(ROOT/'var') or hashlib.sha256(staged.read_bytes()).hexdigest()!=request['sha256']:
            raise RuntimeError('The prepared source rebuild changed. Prepare it again before resetting.')
        from scripts.rebuild_from_sources import apply_stage
        backup=apply_stage(staged,database)
        print('Source workspace restored. Previous state backed up to:',backup,flush=True)
        reset_request.unlink()
    port=available_port(args.port);url=f"http://127.0.0.1:{port}"
    if port!=args.port:print(f"Port {args.port} is occupied. Using {port}.",flush=True)
    print(f"\nStarting Refund Operations at {url}\nKeep this window open. Press Ctrl+C to stop.\n",flush=True)
    logpath=ROOT/"var/launcher.log";logpath.parent.mkdir(exist_ok=True)
    rotate_log(logpath)
    with logpath.open("a",encoding="utf-8") as logfile:
        process=subprocess.Popen([str(PY),"-m","uvicorn","refundops.main:app","--host","127.0.0.1","--port",str(port)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        def log_output():
            for line in process.stdout:
                logfile.write(line);logfile.flush();print(line,end="",flush=True)
        reader=threading.Thread(target=log_output,daemon=True);reader.start()
        try:
            for _ in range(120):
                if process.poll() is not None:raise RuntimeError(f"Server did not start. Details: {logpath}")
                if existing_app(port,database):break
                time.sleep(.25)
            else:raise RuntimeError(f"The server did not become ready. Details: {logpath}")
            launch_state[workspace_id(database)]=port
            launch_state_path.write_text(json.dumps(launch_state),encoding="utf-8")
            print(f"\nREADY: {url}\n",flush=True);open_browser(url,args.no_browser)
            process.wait()
        except KeyboardInterrupt:print("\nStopping Refund Operations...",flush=True)
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=10);reader.join(timeout=3)
if __name__=="__main__":
    try:main()
    except subprocess.CalledProcessError as ex:raise SystemExit(ex.returncode)
    except (RuntimeError,OSError) as ex:
        print("\nCould not start Refund Operations:",str(ex),file=sys.stderr)
        raise SystemExit(1)
