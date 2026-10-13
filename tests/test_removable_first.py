import hashlib,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_universal import REMOVABLE_METHOD_CODE,REMOVABLE_METHOD_SHA,REMOVABLE_CODE_UNITS

class TestRemovableRootCode(unittest.TestCase):
    def test_in_place_len(self):
        self.assertEqual(len(REMOVABLE_METHOD_CODE),REMOVABLE_CODE_UNITS*2)
        self.assertEqual(REMOVABLE_CODE_UNITS,88)
        self.assertEqual(hashlib.sha256(REMOVABLE_METHOD_CODE).hexdigest(),REMOVABLE_METHOD_SHA)
    def test_root_specific_and_all_types(self):
        v=REMOVABLE_METHOD_CODE
        self.assertTrue(v.startswith(bytes.fromhex('20a09b0b3800')))
        self.assertEqual(v.count(bytes.fromhex('6e10a92e0800')),1) # other
        self.assertEqual(v.count(bytes.fromhex('6e10aa2e0800')),1) # SD
        self.assertEqual(v.count(bytes.fromhex('6e10ac2e0800')),1) # USB
        self.assertEqual(v.count(bytes.fromhex('722094a89000')),2) # List.addAll
        self.assertIn(bytes.fromhex('6e3099a74207'),v) # ArrayList.add(0,folder)
        self.assertEqual(v[-2:],bytes.fromhex('0e00'))
