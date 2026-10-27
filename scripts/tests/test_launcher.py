import io
import json
from pathlib import Path
import socket
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import run as launcher

class LauncherTests(unittest.TestCase):
    def test_log_rotation_keeps_one_previous_log_and_preserves_small_files(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'launcher.log'
            log.write_bytes(b'new')
            launcher.rotate_log(log,max_bytes=4)
            self.assertEqual(log.read_bytes(),b'new')
            log.with_suffix('.log.1').write_bytes(b'older')
            log.write_bytes(b'latest')
            launcher.rotate_log(log,max_bytes=4)
            self.assertFalse(log.exists())
            self.assertEqual(log.with_suffix('.log.1').read_bytes(),b'latest')
    def test_occupied_port_uses_another(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));port=occupied.getsockname()[1]
            self.assertNotEqual(launcher.available_port(port),port)
    def test_matching_workspace_is_recognized(self):
        data={'status':'ok','service':'refund-operations','workspace_id':launcher.workspace_id('var/test.sqlite3')}
        with patch.object(launcher.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertTrue(launcher.existing_app(8000,'var/test.sqlite3'))
    def test_another_service_is_not_reused(self):
        with patch.object(launcher.urllib.request,'urlopen',return_value=io.BytesIO(b'{"status":"ok","service":"different"}')):
            self.assertFalse(launcher.existing_app(8000,'var/test.sqlite3'))
    def test_unreachable_service_is_not_reused(self):
        with patch.object(launcher.urllib.request,'urlopen',side_effect=OSError('refused')):
            self.assertFalse(launcher.existing_app(8000,'var/test.sqlite3'))
    def test_browser_opt_out(self):
        with patch.object(launcher.webbrowser,'open') as browser:
            launcher.open_browser('http://127.0.0.1:8000',True);browser.assert_not_called()
    def test_repeated_launch_opens_existing_without_installing(self):
        with patch.object(sys,'argv',['run.py']),patch.object(launcher,'app_health',return_value={'backend_revision':launcher.code_revision()}),patch.object(launcher,'frontend_current',return_value=True),patch.object(launcher,'bootstrap') as bootstrap,patch.object(launcher,'open_browser') as browser:
            launcher.main();bootstrap.assert_not_called();browser.assert_called_once_with('http://127.0.0.1:18474',False)
    def test_changed_or_unrecognized_process_is_never_stopped(self):
        for current in (None,{'process_id':456}):
            with patch.object(launcher,'app_health',return_value=current),patch.object(launcher.os,'kill') as kill:
                with self.assertRaises(RuntimeError):launcher.stop_stale_app(8000,'var/test.sqlite3',{'process_id':123})
                kill.assert_not_called()
    def test_verified_stale_process_is_stopped_before_relaunch(self):
        with patch.object(launcher,'app_health',return_value={'process_id':123}),patch.object(launcher,'existing_app',return_value=False),patch.object(launcher.os,'kill') as kill:
            launcher.stop_stale_app(8000,'var/test.sqlite3',{'process_id':123})
            kill.assert_called_once_with(123,launcher.signal.SIGTERM)
    def test_stale_backend_goes_through_build_before_stop(self):
        events=[]
        with patch.object(sys,'argv',['run.py']),patch.object(launcher,'app_health',return_value={'process_id':123}),patch.object(launcher,'bootstrap'),patch.object(launcher,'run',side_effect=lambda *a,**kw:events.append('build')),patch.object(launcher,'stop_stale_app',side_effect=RuntimeError('test stop')) as stop:
            with self.assertRaisesRegex(RuntimeError,'test stop'):launcher.main()
            self.assertEqual(events,['build']);stop.assert_called_once()
    def test_explicit_restart_replaces_even_current_workspace_server(self):
        health={'process_id':123,'backend_revision':launcher.code_revision()}
        with patch.object(sys,'argv',['run.py','--restart']),patch.object(launcher,'app_health',return_value=health),patch.object(launcher,'bootstrap'),patch.object(launcher,'run'),patch.object(launcher,'stop_stale_app',side_effect=RuntimeError('verified restart')) as stop:
            with self.assertRaisesRegex(RuntimeError,'verified restart'):launcher.main()
            stop.assert_called_once_with(18474,unittest.mock.ANY,health)
if __name__=='__main__':unittest.main()
