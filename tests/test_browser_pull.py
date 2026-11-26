"""
The browser side of a pull (browser/yad2_pull.js) has its own tests in
Node (browser/yad2_pull.test.js). This runs them with the Python suite
when Node is installed, and says so plainly when it isn't.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js isn't installed: run `node --test browser/yad2_pull.test.js` where it is")
class TestBrowserPull(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run([NODE, "--test", str(ROOT / "browser" / "yad2_pull.test.js"), str(ROOT / "browser" / "runner.test.js"), str(ROOT / "browser" / "store.test.js"), str(ROOT / "browser" / "i18n.test.js"), str(ROOT / "browser" / "sites.test.js"), str(ROOT / "browser" / "hoodmap.test.js"), str(ROOT / "browser" / "compare.test.js"), str(ROOT / "browser" / "setup_lib.test.js"), str(ROOT / "browser" / "share.test.js")],
                           capture_output=True, text=True, timeout=180, cwd=ROOT)
        fails = [line for line in r.stdout.splitlines() if line.startswith("not ok")]
        self.assertEqual(r.returncode, 0, "\n".join(fails) or r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn("# fail 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
