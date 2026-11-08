"""Independent app processes with local replicas; this is not a cloud-provider test."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import app as appmod

WORKER = """
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.argv.append('--selftest')
import app
app.BASE = app.DATA_DIR = root
app.SELLER_FILE = root / 'seller.json'
app.CUSTOMERS_FILE = root / 'customers.json'
app.OUTPUT_DIR = root / 'output'
app.CONFIG_FILE = root / 'config.json'
app.OUTPUT_DIR.mkdir(exist_ok=True)
fields = json.loads(sys.stdin.read())
response = app.app.test_client().post('/settings/autosave?issuer=default', data=fields)
print(json.dumps({'status': response.status_code, 'seller': app.load_seller()}))
"""


def replicas(tmp_path):
    seller = {"name": "Example Studio", "country": "DE", "address_line": "Original address"}
    folders = [tmp_path / "mac-a", tmp_path / "mac-b"]
    for folder in folders:
        folder.mkdir()
        (folder / "seller.json").write_text(json.dumps(seller))
    return folders, appmod.seller_revision(seller)


def writer(folder):
    return subprocess.Popen([sys.executable, "-c", WORKER, str(folder)],
                            cwd=Path(__file__).resolve().parents[1], text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def save(process, token, address):
    out, err = process.communicate(json.dumps({"seller_revision": token, "address_line": address}), timeout=30)
    assert process.returncode == 0, err
    return json.loads(out)


def test_arrived_sync_update_rejects_stale_write_in_another_process(tmp_path):
    (first, second), token = replicas(tmp_path)
    assert save(writer(first), token, "Address on Mac A")["status"] == 204
    shutil.copy2(first / "seller.json", second / "seller.json")
    response = save(writer(second), token, "Stale address on Mac B")
    assert response["status"] == 409
    assert response["seller"]["address_line"] == "Address on Mac A"


def test_offline_replicas_demonstrate_the_limit_of_local_revision_checks(tmp_path):
    (first, second), token = replicas(tmp_path)
    # Both processes are started before either edit; neither has the other's file.
    process_a, process_b = writer(first), writer(second)
    response_a = save(process_a, token, "Address on Mac A")
    response_b = save(process_b, token, "Address on Mac B")
    assert response_a["status"] == response_b["status"] == 204
    assert response_a["seller"] != response_b["seller"]
    # Delayed synchronization cannot be made safe by a per-file revision alone.
    # Do not simulate a provider's conflict resolution or claim cloud coordination.
