"""Native regression for the shared zero-copy MKV page-offset handoff.

Compile the *actual* transport page-data/page-length implementations on the
host; verify that partial staging consumption does not reintroduce old bytes.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def extract(source, name):
    m = re.search(r"(?m)^(?:void\s*\*\s*|int\s+)" + re.escape(name) +
                  r"\([^;]*\)\n\{", source)
    if m is None:
        raise AssertionError("missing production function: " + name)
    start = m.start()
    level = 0
    opened = False
    for pos in range(m.end() - 1, len(source)):
        if source[pos] == '{':
            level += 1
            opened = True
        if source[pos] == '}':
            level -= 1
            if opened and level == 0:
                return source[start:pos+1]
    raise AssertionError("unclosed function")

class SharedMkvIntegrity(unittest.TestCase):
    def test_production_zero_copy_partial_page(self):
        transport = (ROOT / "iso/nova_transport.c").read_text()
        lite = (ROOT / "iso/nova_literange4.inc").read_text()
        self.assertIn("NOVA_SHARED42_MKV_PAGE_VIEW_V1", transport)
        self.assertIn("NOVA_SHARED42_MKV_PAGE_VIEW_V1", lite)
        self.assertNotIn("page->consumed=0;\n                        *out_page=n;", lite)
        data = extract(transport, "nova_transport_page_data")
        length = extract(transport, "nova_transport_page_length")
        harness = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define NOVA_WH_PAGES 3
#define NOVA_WH_PAGE_BYTES 65536
#define NOVA_WH_RAW 2
typedef struct { int next,length,consumed,state; } nova_wh_page;
typedef struct {
  nova_wh_page pages[NOVA_WH_PAGES];
  uint8_t data[NOVA_WH_PAGES * NOVA_WH_PAGE_BYTES];
} nova_shared_warehouse;
static nova_shared_warehouse *nova_shared_warehouse_from_data(void *v) {
  return (nova_shared_warehouse *)((char *)v -
       offsetof(nova_shared_warehouse,data));
}
static uint8_t *nova_wh_page_ptr(nova_shared_warehouse *w,int n) {
  if(n<0 || n>=NOVA_WH_PAGES)return NULL;
  return w->data+(size_t)n*NOVA_WH_PAGE_BYTES;
}
'''
        harness += data + "\n" + length + r'''
int main(void) {
  static nova_shared_warehouse w;
  for(int i=0;i<NOVA_WH_PAGE_BYTES;++i)
    w.data[i]=(uint8_t)(i%251);
  w.pages[0].state=NOVA_WH_RAW;
  w.pages[0].length=NOVA_WH_PAGE_BYTES;
  w.pages[0].consumed=4096; /* first 4 KiB already read via bytewise path */
  int n=nova_transport_page_length(w.data,0);
  uint8_t *ptr=nova_transport_page_data(w.data,0);
  assert(n==61440 && ptr==w.data+4096);
  for(int i=0;i<n;i++)assert(ptr[i]==(uint8_t)((i+4096)%251));
  /* Zero-copy: retain the same original storage identity. */
  w.pages[1].state=NOVA_WH_RAW;
  w.pages[1].length=17000;
  w.pages[1].consumed=1;
  assert(nova_transport_page_length(w.data,1)==16999);
  assert(nova_transport_page_data(w.data,1)==w.data+65536+1);
  w.pages[2].state=NOVA_WH_RAW;
  w.pages[2].length=NOVA_WH_PAGE_BYTES;
  w.pages[2].consumed=0;
  assert(nova_transport_page_data(w.data,2)==w.data+131072);
  assert(nova_transport_page_length(w.data,2)==65536);
  w.pages[0].consumed=w.pages[0].length;
  assert(nova_transport_page_length(w.data,0)<0);
  assert(nova_transport_page_data(w.data,0)==NULL);
  assert(nova_transport_page_length(w.data,-1)<0);
  assert(nova_transport_page_data(w.data,NOVA_WH_PAGES)==NULL);
  puts("NOVA_SHARED42_MKV_PAGE_VIEW_V1: native partial+full page PASS");
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"native.c"
            exe=Path(td)/"native"
            src.write_text(harness)
            cmd=["cc","-std=c11","-Wall","-Wextra","-Werror",
                 "-fsanitize=undefined","-fno-sanitize-recover=all",
                 str(src),"-o",str(exe)]
            built=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
            self.assertEqual(ran.returncode,0,ran.stderr)

if __name__ == "__main__":
    unittest.main()
