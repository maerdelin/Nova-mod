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

    def test_instruction_boundaries(self):
        import struct
        from build_universal import REMOVABLE_METHOD_CODE
        words=struct.unpack('<88H', REMOVABLE_METHOD_CODE)
        widths={0x20:2,0x38:2,0x55:2,0x71:3,0x0c:1,0x07:1,0x6e:3,0x72:3,0x22:2,0x70:3,0x12:1,0x0a:1,0x1f:2,0x28:1,0x08:2,0x5b:2,0x5c:2,0x0e:1}
        starts=set(); targets=[]; pc=0
        while pc<88:
            starts.add(pc)
            op=words[pc]&255
            self.assertIn(op,widths)
            width=widths[op]
            if op==0x38:
                delta=struct.unpack('<h',struct.pack('<H',words[pc+1]))[0]
                targets.append(pc+delta)
            if op==0x28:
                delta=words[pc]>>8
                targets.append(pc+(delta-256 if delta>=128 else delta))
            pc+=width
        self.assertEqual(pc,88)
        self.assertEqual(len(starts),43)
        self.assertEqual(len(targets),7)
        self.assertTrue(all(t in starts for t in targets))
        self.assertEqual(words[77:79],(0x0b08,0x0002))
