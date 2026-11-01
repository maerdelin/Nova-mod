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
        start = C.index('static int64_t nova_startup_fixed_denominator(')
        end = C.index('/* Guard native rebuffer reports by the actual active transport generation. */', start)
        actual = C[start:end]
        mock = r'''
#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#define LOGI(...) ((void)0)
#define LOGE(...) ((void)0)
typedef struct nova_session {
    uint64_t generation;
    volatile int startup_ui_state;
    volatile int startup_buffer_percent;
    volatile int startup_resume_mismatch_reported;
    volatile int64_t startup_resident_bytes;
    volatile int64_t startup_resume_bytes;
    volatile int startup_authoritative_seen;
} nova_session;
static nova_session live = {.generation=42,.startup_ui_state=1};
static nova_session *session_acquire(uint64_t generation) {
    return generation == 42 ? &live : NULL;
}
static void session_release(nova_session *s) { (void)s; }
'''
        assertions = r'''
int main(void) {
    const int64_t threshold = 64LL * 1024 * 1024;
    nova_transport_report_startup_raw(42, 0, threshold);
    nova_transport_report_startup_buffer(42, 0, threshold);
    assert(live.startup_buffer_percent == 0);
    nova_transport_report_startup_buffer(42, threshold/4, threshold/2);
    assert(live.startup_resume_bytes == threshold);
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
