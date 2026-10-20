"""Behavioral regression for the autonomous four-lane Java WebDAV producer.

Run on the same source compiled into the APK, not a Python reimplementation.
Only android.util.Log is stubbed; the producer and threading are real.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "parallel_range4/src/com/archos/filecorelibrary/NovaParallelRangeInputStream.java"

LOG_STUB = r"""
package android.util;
public final class Log {
    public static int i(String tag, String message) { return 0; }
    public static int w(String tag, String message) { return 0; }
    public static int w(String tag, String message, Throwable cause) { return 0; }
    public static int e(String tag, String message) { return 0; }
    public static int e(String tag, String message, Throwable cause) { return 0; }
}
"""

HARNESS = r"""
import com.archos.filecorelibrary.NovaParallelRangeInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

public final class Range4BehaviorHarness {
    static final long MiB = 1024L * 1024L;

    static final class SyntheticWebDAV implements NovaParallelRangeInputStream.Source {
        final long fileLength;
        final AtomicInteger opened = new AtomicInteger();
        final AtomicInteger active = new AtomicInteger();
        final AtomicInteger maxConcurrent = new AtomicInteger();
        final AtomicLong received = new AtomicLong();
        final AtomicBoolean failOnce = new AtomicBoolean(false);
        volatile long failAt = -1;
        volatile boolean cancelled;

        SyntheticWebDAV(long size) { fileLength = size; }

        public boolean cancelled() { return cancelled; }

        public InputStream openRange(final long offset) throws IOException {
            if (offset < 0 || offset > fileLength) throw new IOException("out of bounds " + offset);
            opened.incrementAndGet();
            int now = active.incrementAndGet();
            while (true) {
                int old = maxConcurrent.get();
                if (old >= now || maxConcurrent.compareAndSet(old, now)) break;
            }
            return new InputStream() {
                long next = offset;
                final AtomicBoolean finished = new AtomicBoolean(false);
                public int read() throws IOException {
                    byte[] one = new byte[1];
                    int n = read(one, 0, 1);
                    return n < 0 ? -1 : one[0] & 255;
                }
                public int read(byte[] b, int off, int len) throws IOException {
                    if (finished.get()) throw new IOException("connection closed");
                    if (len == 0) return 0;
                    if (next >= fileLength) return -1;
                    if (failAt >= 0 && next >= failAt && failOnce.compareAndSet(false, true)) {
                        throw new IOException("injected transient mid-segment disconnect");
                    }
                    int n = (int) Math.min(Math.min((long) len, 64 * 1024L), fileLength - next);
                    for (int i = 0; i < n; ++i) b[off + i] = (byte) ((next + i) % 251);
                    next += n;
                    received.addAndGet(n);
                    try { Thread.sleep(1L); }
                    catch (InterruptedException ex) {
                        Thread.currentThread().interrupt();
                        throw new IOException("interrupted GET", ex);
                    }
                    return n;
                }
                public void close() {
                    if (finished.compareAndSet(false, true)) active.decrementAndGet();
                }
            };
        }
    }

    static void expect(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }

    static void eventuallyIdle(SyntheticWebDAV src) throws Exception {
        long end = System.nanoTime() + 2_000_000_000L;
        while (src.active.get() != 0 && System.nanoTime() < end) Thread.sleep(5L);
        expect(src.active.get() == 0, "GET connections leaked: " + src.active.get());
    }

    static void verifyAutonomousAndBounded() throws Exception {
        SyntheticWebDAV src = new SyntheticWebDAV(192 * MiB);
        InputStream original = src.openRange(0);
        InputStream stream = NovaParallelRangeInputStream.maybeWrap(src, original, 0, 192 * MiB);
        // No stream.read() calls here. Downloaders must still run and refill.
        Thread.sleep(1500);
        expect(src.maxConcurrent.get() >= 4, "did not run four simultaneous HTTP connections");
        expect(src.opened.get() >= 12, "requests gated by consumer: " + src.opened.get());
        expect(src.received.get() <= 128 * MiB,
                "network stage exceeded memory bound: " + src.received.get());
        stream.close();
        eventuallyIdle(src);
        System.out.println("PASS autonomous: maxConnections=" + src.maxConcurrent.get()
                + " GETs=" + src.opened.get() + " bytes=" + src.received.get());
    }

    static void verifyByteExactRetryAndSeek() throws Exception {
        final long start = 7 * MiB + 67;
        final long length = 48 * MiB + 1337;
        SyntheticWebDAV src = new SyntheticWebDAV(start + length);
        src.failAt = start + 12 * MiB + 512 * 1024;
        InputStream original = src.openRange(start);
        InputStream stream = NovaParallelRangeInputStream.maybeWrap(src, original, start, length);
        byte[] bytes = new byte[64 * 1024];
        long delivered = 0;
        while (true) {
            int n = stream.read(bytes, 0, bytes.length);
            if (n < 0) break;
            expect(n > 0, "zero-length read");
            for (int i = 0; i < n; ++i) {
                int expected = (int) ((start + delivered + i) % 251);
                int actual = bytes[i] & 255;
                expect(actual == expected, "corruption at " + (start + delivered + i)
                        + " expected=" + expected + " actual=" + actual);
            }
            delivered += n;
        }
        expect(delivered == length, "wrong bytes delivered: " + delivered);
        expect(src.failOnce.get(), "transient failure was not injected");
        stream.close();
        eventuallyIdle(src);
        System.out.println("PASS byte-exact + retry + nonzero-range: bytes=" + delivered);
    }

    static void verifyBypass() throws Exception {
        SyntheticWebDAV src = new SyntheticWebDAV(8 * MiB);
        InputStream original = src.openRange(0);
        InputStream wrapped = NovaParallelRangeInputStream.maybeWrap(src, original, 0, 8 * MiB);
        expect(wrapped == original, "small request should bypass four-lane");
        original.close();
        eventuallyIdle(src);
        System.out.println("PASS small-file bypass");
    }

    public static void main(String[] args) throws Exception {
        verifyAutonomousAndBounded();
        verifyByteExactRetryAndSeek();
        verifyBypass();
    }
}
"""

class JavaRange4RuntimeTests(unittest.TestCase):
    def test_java_four_lane_behavior(self):
        self.assertTrue(SOURCE.is_file(), "Range4 class missing")
        with tempfile.TemporaryDirectory(prefix="range4-behavior-") as td:
            root = Path(td)
            log = root / "android/util/Log.java"
            log.parent.mkdir(parents=True)
            log.write_text(LOG_STUB, encoding="utf-8")
            runner = root / "Range4BehaviorHarness.java"
            runner.write_text(HARNESS, encoding="utf-8")
            out = root / "classes"
            out.mkdir()
            subprocess.run(["javac", "-source", "8", "-target", "8", "-d", str(out),
                            str(log), str(SOURCE), str(runner)],
                           check=True, timeout=30)
            result = subprocess.run(["java", "-Xmx384m", "-cp", str(out),
                                     "Range4BehaviorHarness"],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS autonomous", result.stdout)
            self.assertIn("PASS byte-exact", result.stdout)
            self.assertIn("PASS small-file bypass", result.stdout)
            print(result.stdout.strip())

if __name__ == "__main__":
    unittest.main()
