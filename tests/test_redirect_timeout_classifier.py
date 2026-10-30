"""Compiled regression of the production redirect/Range error classifier.

Use the actual C function extracted from iso/nova_transport.c; this guards
against 'test passes / implementation still broken' regressions.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "iso" / "nova_transport.c"
PATTERN = re.compile(
    r"(?ms)^static int nova_multi_recoverable_range_error\(long http,CURLcode err\)\n"
    r"\{.*?^\}\n"
)

# Public libcurl CURLE constants used by the production function.
# Stubs allow a fast host-C test without requiring the NDK or libcurl headers.
C_PREAMBLE = r"""
#include <stdio.h>
typedef int CURLcode;
enum {
    CURLE_OK=0,
    CURLE_UNSUPPORTED_PROTOCOL=1,
    CURLE_COULDNT_RESOLVE_HOST=6,
    CURLE_COULDNT_CONNECT=7,
    CURLE_PARTIAL_FILE=18,
    CURLE_OPERATION_TIMEDOUT=28,
    CURLE_SSL_CONNECT_ERROR=35,
    CURLE_GOT_NOTHING=52,
    CURLE_SEND_ERROR=55,
    CURLE_RECV_ERROR=56,
    CURLE_PEER_FAILED_VERIFICATION=60
};
#define EXPECT(http, err, expect) do { \
    int actual=nova_multi_recoverable_range_error((http),(err)); \
    if(actual!=(expect)) { \
        fprintf(stderr, "redirect classifier: http=%ld curl=%d got=%d want=%d\\n", \
                (long)(http),(int)(err),actual,(expect)); \
        return 1; \
    } \
} while(0)
"""

C_CASES = r"""
int main(void) {
    // Proven RUN632 evening regression: HTTP 302 with curl 28 must be
    // classified recoverable so the existing verified W1 -> W2 path can retry.
    EXPECT(302,CURLE_OPERATION_TIMEDOUT,1);
    EXPECT(301,CURLE_OPERATION_TIMEDOUT,1);
    EXPECT(303,CURLE_RECV_ERROR,1);
    EXPECT(307,CURLE_COULDNT_CONNECT,1);
    EXPECT(308,CURLE_GOT_NOTHING,1);
    EXPECT(302,CURLE_SEND_ERROR,1);
    EXPECT(302,CURLE_PARTIAL_FILE,1);
    EXPECT(302,CURLE_COULDNT_RESOLVE_HOST,1);

    // Unsuccessful redirects, without transient transport failure,
    // are not valid media and must not be treated as recoverable success.
    EXPECT(302,CURLE_OK,0);
    EXPECT(302,CURLE_UNSUPPORTED_PROTOCOL,0);
    EXPECT(302,CURLE_PEER_FAILED_VERIFICATION,0);
    EXPECT(302,CURLE_SSL_CONNECT_ERROR,0);
    EXPECT(200,CURLE_OPERATION_TIMEDOUT,0);
    EXPECT(206,CURLE_OPERATION_TIMEDOUT,1);
    EXPECT(0,CURLE_OPERATION_TIMEDOUT,1);
    EXPECT(0,CURLE_OK,0);

    // Preserve explicit HTTP cooldown statuses and terminal security errors.
    EXPECT(403,CURLE_OK,1);
    EXPECT(408,CURLE_OK,1);
    EXPECT(429,CURLE_OK,1);
    EXPECT(500,CURLE_OK,1);
    EXPECT(502,CURLE_OK,1);
    EXPECT(503,CURLE_OK,1);
    EXPECT(504,CURLE_OK,1);
    EXPECT(401,CURLE_OPERATION_TIMEDOUT,0);
    EXPECT(404,CURLE_OPERATION_TIMEDOUT,0);
    EXPECT(416,CURLE_OPERATION_TIMEDOUT,0);
    EXPECT(302,CURLE_PEER_FAILED_VERIFICATION,0);
    return 0;
}
"""

class RedirectTimeoutClassifierTests(unittest.TestCase):
    def test_real_compiled_classifier(self):
        content = TRANSPORT.read_text()
        matches = list(PATTERN.finditer(content))
        self.assertEqual(len(matches),1,"Production classifier was moved/changed")
        self.assertIn("NOVA_REDIRECT_TIMEOUT_RECOVERABLE_V1",matches[0].group())
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"classifier.c"
            program=Path(temporary)/"classifier"
            source.write_text(C_PREAMBLE + matches[0].group() + C_CASES)
            subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",
                            "-o",str(program),str(source)],check=True,
                           capture_output=True,text=True)
            subprocess.run([str(program)],check=True,capture_output=True,text=True)

    def test_bounded_backoff_and_single_verified_retry_unchanged(self):
        content=TRANSPORT.read_text()
        for fragment in (
                'nova_multi_recoverable_range_error(http_status,curl_rc)',
                'nova_multi_stop(s, http403 ? "http403-cooldown" : "range-backoff", 0);',
                'nova_multi_stop(s, "lane-error", 1);',
                'n == 1 ? 4000 : n == 2 ? 15000 : 60000',
                's->multi_range_single_bytes>=NOVA_MULTI_SINGLE_PROBE_BYTES',
                'nova_iso_uptime_ms() >= s->multi_http403_retry_ms',
                '#include "nova_literange4.inc"',
        ):
            self.assertIn(fragment,content)

if __name__ == "__main__":
    unittest.main()
