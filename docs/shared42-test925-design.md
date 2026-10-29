# Test #925 — shared 128 MiB warehouse, 42 MiB W2 staging (design gate)

**Base:** successful Actions run #925, commit `1ad100cb63af08b47f8ff4af41b1011032027895`.

**Status:** DESIGN / UNSHIPPPABLE WIP. Do not publish APK or merge into Test/Always-new without passing gates below.

## User-approved memory budget

- One 128 MiB backing allocation across transport and FFmpeg RAW source, not 128+42.
- Up to 42 MiB received but uncommitted ("stage"); retain at least 6 MiB guaranteed for the in-order head when future lane is ahead, allowing up to 36 MiB future data. These are *role quotas* that move as A/B roles change, not fixed lane IDs or storage partitions.
- No more than 86 MiB committed/unconsumed playback queue; no separate 86 MiB memcpy destination.
- The 42+86 split must be enforced with counters **and page ownership**. A static 42 MiB byte array followed by a static 86 MiB array that copies between them **does not satisfy zero-copy**. Pages must transfer from STAGED to COMMITTED by descriptor move only.
- A page in COMMITTED state is still resident within the same backing memory. Pages of partial chunks require valid byte start/length; either immutable after publish or with per-chunk produced/visible offsets.

## Required implementation, not yet completed

1. Refcounted shared 128 MiB allocation lifetime must outlive both the transport session and the libavos reader. Never derive session pointer from freed generation. All mapping get/release calls must be paired on *all* failures.
2. 64 KiB page descriptors, free queue, lane A/B ordered staging chains and committed queue. `FREE -> STAGED -> COMMITTED -> FREE` only; epoch ownership on every descriptor. Unread queued bytes must not be overwritten or freed at seek.
3. libcurl write callback may receive arbitrary chunk sizes; split incoming chunks across pages; verify HTTP 206 Content-Range, identity and segment bounds before accepting pages. If insufficient uncommitted pages, return CURL_WRITEFUNC_PAUSE (must not open a new GET). Unpause only when enough capacity for the retry, not on partial release that can cause a callback livelock.
4. A/B role is decided by next logical byte cursor, not slot index; reserve 6 MiB equivalent free pages for head; future lane may occupy at most 36 MiB. Once head slot fully committed (not necessarily HTTP complete), release its slot and start C, while B becomes head. Keep W2 in-order gate and 4X segment sizing.
5. For non-ISO only, RAW producer receives committed page descriptors, not byte copies via `avio_read(...raw->ring + write_off...)`. Consumer `nova_raw_read` may still copy bytes into FFmpeg demux buffer: this is the necessary consumer copy, NOT the eliminated stage-to-RAW copy. Queue capacity 86 MiB. Preserve existing demux AVIO, RAW rebuffer thresholds (clamp to <=86), size/seek callbacks and input error semantics.
6. Blu-ray ISO is NOT a raw byte identity transform. Existing `bd_read` and `upstream_read_blocks` traverse libbluray/UDF and may perform nonsequential reads. Direct descriptor publication from raw ISO Range data to the **main.m2ts** playback queue is incorrect. Needs an ISO-specific materialization step or verified fallback; do not claim universal zero-copy. ISO may share the physical backing allocation only after proving the raw stage and resulting m2ts playback pages do not alias; metadata scan must preserve its separate semantics.
7. On seek, hold existing source_mutex/io_lock order, retire transport generation, cancel libcurl handles, invalidate all previous epoch pages, reset RAW cursor and decoder output. Reader cannot observe stale pages. Seek failure must not falsely publish queued preseek data. Observe MKV logical seek guard and ISO LBA jump behavior.
8. On 403/429/503/fallback, current committed data may be consumed, but buffered partial future chunks must be discarded safely if file cursor switches to Java single GET. Keep retry cooldown and connection reuse exactly as #925.
9. On EOF/abort/close, drain and release descriptor references safely; ensure shutdown wakes the producer and demuxer, no wait under libcurl owner, never double free. No background curl threads.
10. Keep RAW fallback original behaviour for local files or non-direct streams. Allocating 128 MiB legacy RAW in addition to the shared pool is forbidden on paths claiming the memory reduction.

## Validation gates required BEFORE an APK can be called delivered

- Compile all four ABI architectures; APK signing; Actions job status SUCCESS, artifact downloadable and signature valid.
- Static test: one 128 MiB allocation only on direct routes; no `malloc(32 MiB)` stage arrays; queue 86 MiB; staging quota 42 MiB; 6/36 role quotas; no stage-to-RAW memcpy; prove pointer ownership and build symbol availability.
- Runtime deterministic tests for A slow / B fast / B slow / A fast / both equal; 100 Mbps four-second pieces; delayed 206; curl pause-unpause and same-socket keepalive; backpressure near 6 MiB reserve.
- First start, repeated seeks, paused buffering, tail seeks, stream end, rapid stop/reopen; guard generation/page reuse; inspect native logs and Android malloc/PSS.
- Native/WebDAV files: MKV, MP4 (including moov-at-tail), TS, non-ISO generic; ISO movie data, ISO metadata, ISO seek, subtitle/audio selection; range error 403/429, retry, redirect expiry.
- Compare #925 benchmark: RAW delivery rate, seek latency, frame output, stalls, decoded bytes match, HTTP requests, memory usage. No delivery on only a green compile.

## Current WIP reality

`iso/nova_transport.c` on this branch has an **unfinished** refcounted warehouse allocation API. It does not yet wire up the libavos reader or replace the two existing per-slot 32 MiB buffers and therefore **does not achieve the goal**, must not be called tested or delivered. This file is a design safety record, not release notes.
