"""Execute the production NOVA 994 first-resume-buffer percent calculation on host C.

Unlike a source-string grep, this compiles the actual exported native method
against a generation-scoped transport mock and checks numeric boundaries.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
C = (ROOT / "iso/nova_transport.c").read_text()

class NativeStartupBufferPercentTests(unittest.TestCase):
    def test_actual_native_ratio_and_generation(self):
        start = C.index('void nova_transport_report_startup_buffer(')
        end = C.index('/* Guard native rebuffer reports by the actual active transport generation. */', start)
        actual = C[start:end]
        mock = r'''
#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#define LOGI(...) ((void)0)
typedef struct nova_session {
    volatile int startup_buffer_percent;
} nova_session;
static nova_session live;
static nova_session *session_acquire(uint64_t generation) {
    return generation == 42 ? &live : NULL;
}
static void session_release(nova_session *s) { (void)s; }
'''
        assertions = r'''
int main(void) {
    const int64_t threshold = 64LL * 1024 * 1024;
    nova_transport_report_startup_buffer(42, 0, threshold);
    assert(live.startup_buffer_percent == 0);
    nova_transport_report_startup_buffer(42, threshold/4, threshold);
    assert(live.startup_buffer_percent == 25);
    nova_transport_report_startup_buffer(42, threshold/2, threshold);
    assert(live.startup_buffer_percent == 50);
    nova_transport_report_startup_buffer(42, threshold-1, threshold);
    assert(live.startup_buffer_percent == 99);
    nova_transport_report_startup_buffer(42, threshold, threshold);
    assert(live.startup_buffer_percent == 100);
    nova_transport_report_startup_buffer(42, threshold*2, threshold);
    assert(live.startup_buffer_percent == 100);
    nova_transport_report_startup_buffer(42, -123, threshold);
    assert(live.startup_buffer_percent == 0);
    nova_transport_report_startup_buffer(42, 1, 0);
    assert(live.startup_buffer_percent == 0);
    nova_transport_report_startup_buffer(11, threshold, threshold);
    assert(live.startup_buffer_percent == 0);
    puts("NOVA_994_NATIVE_BUFFER_PERCENT_V1=PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "native_994_percent.c"
            binary = Path(d) / "native_994_percent"
            src.write_text(mock + actual + assertions)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)

if __name__ == "__main__":
    unittest.main()
