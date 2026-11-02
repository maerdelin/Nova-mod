# NOVA 1064 ISO memory and playback-interruption candidate

**Proven base:** immutable `baseline/1063-20261102`, commit `52563d13e63394f9db1503578f81e7d10d60bfba`, GitHub Actions build #1063 success. `Always-new` points to the same base and is not altered by this fix.

## Log evidence and scope

- The user's repeated 87GB UHD ISO produced FFmpeg `av_read_frame()` `ENOMEM=-12` with `avioError=0` at logical positions 15,595,008 and 26,897,280, without source EOF.
- ISO video CBE startup allocated 12 MiB unsuccessfully (`errno=12`) then successfully retried at 8 MiB. This predates the final future-slot pause.
- `NOVA_SHARED42_PAUSE_V2 slot=1 slotPages=576 future=1` exactly matches a 36MiB quota; it is not evidence that Shared42 ran out of all pages.
- After the last future-slot pause the curl owner produced no more progress logs. The *specific blocked native call* remains unidentified. No proof yet that the pause caused a deadlock.
- 1063 already reuses the 128MiB shared warehouse. ISO also allocates a separate contiguous 24MiB startup replay buffer; those extra 24MiB matter on a 32-bit process.

## Isolated mitigation

1. On 32-bit only, if the selected Blu-ray title is one clip and at least 16GiB, reduce its extra startup replay buffer to 8MiB; keep the prior 24MiB cap for other titles/architectures. The existing exact byte rebase handles out-of-prefix libbluray reads.
2. After verified first video frame, once the physical movie reader has advanced beyond the captured replay prefix, free replay in the current `io_lock` owner. This cannot run during title metadata scanning or before first frame.
3. When an ISO read is not making byte progress after repeated returns from `curl_multi_perform()` for 8 seconds, log slot and page state, stop the epoch, make one exact committed-byte W2 rebase using new TCP connections, then fall back through the existing byte-exact serial path if the retry fails. The non-ISO path is untouched.
4. Log return from curl multi-perform whenever that call itself causes a pause or lasts >=250ms. When PAUSE appears without a matching RETURN, capture a live native stack: this code cannot interrupt a call stuck inside libcurl itself.
5. On ISO-specific FFmpeg ENOMEM, capture process VmSize/VmPeak/VmRSS/VmData/Swap/thread counts, RLIMIT_AS/DATA and stream count at the failure site; keep the prior proper error path intact.

## Acceptance limits

These are optimizations plus source-level evidence and new diagnostics, **not** a proven root-cause fix for the unreturned native call or the internal FFmpeg allocation. GitHub Actions signed APK with Android 11/14 emulator and host regression is required; the Amlogic 87GB real ISO repeated-open and continuous-playback test remains the ultimate acceptance gate.

The unrelated previous Back-return black-screen issue is deliberately not modified.
