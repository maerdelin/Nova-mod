#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1])
avos = root / "native/avos"

def patch_file(path, old, new, label):
    p = avos / path
    s = p.read_text()
    if new in s:
        print(label, "already applied")
        return
    if old not in s:
        raise SystemExit(f"{label}: anchor not found in {p}")
    p.write_text(s.replace(old, new, 1))
    print("patched", label)

# 1) Per-stream rebuffer state. No global singleton state.
patch_file(
    "Include/stream.h",
    """	int		paused;
	int		paused_internal;
	int		speed;
""",
    """	int		paused;
	int		paused_internal;
	// Kodi-inspired network rebuffer state. Kept per stream so cache/refill
	// state never leaks between playback sessions.
	int		nova_rebuffer_active;
	int		nova_rebuffer_saved_video_paused;
	int64_t		nova_rebuffer_started_ms;
	int		nova_rebuffer_start_used;
	int		nova_rebuffer_target_ms;
	int		speed;
""",
    "stream rebuffer fields"
)

# 2) Producer must keep filling network media while playback is paused/rebuffering.
patch_file(
    "Source/stream_video.c",
    """			if ( !s->paused || s->play_n_video_frames || s->play_n_audio_frames || s->parser_parse_once ) {
""",
    """			// Kodi CFileCache keeps its producer independent of the consumer.
			// For non-local media keep the parser/network producer running while
			// playback is paused so startup, user pause and rebuffer can fill cache.
			if ( !s->paused || (s->flags & STREAM_FILE_NONLOCAL) ||
			     s->play_n_video_frames || s->play_n_audio_frames || s->parser_parse_once ) {
""",
    "network producer independence"
)

# 3) Use Kodi's current default cache memory scale for non-local playback.
patch_file(
    "Source/avos_mp_video.c",
    """	if (_flags & STREAM_FILE_NONLOCAL) {
		stream_set_buffer_size(video->s, get_default_stream_buffer_size()); // use less memory for NONLOCAL playback
	} else if ( !device_has_hdd() ) {
""",
    """	if (_flags & STREAM_FILE_NONLOCAL) {
		// Kodi defaults its file cache to 64 MiB. Nova historically forces the
		// non-local AVOS buffer down to 24 MiB; keep the cache in AVOS itself,
		// but raise the native compressed-media budget to at least 64 MiB.
		int network_buffer_mib = MAX(get_default_stream_buffer_size(), 64);
		stream_set_buffer_size(video->s, network_buffer_mib);
		serprintf("NOVA_CACHE_CONFIG network=1 size=%dMiB policy=kodi-inspired\\n",
			network_buffer_mib);
	} else if ( !device_has_hdd() ) {
""",
    "64MiB native network cache"
)

# Add startup high-water helper in avos_mp_video.c.
p = avos / "Source/avos_mp_video.c"
s = p.read_text()
anchor = """void stream_un_pause_from_jni( STREAM *s, int was_paused );

int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
"""
helper = r'''void stream_un_pause_from_jni( STREAM *s, int was_paused );

static int nova_network_buffered_ms(STREAM *s, STREAM_PARSER_STATS *st)
{
	int ms = INT_MAX;
	int have = 0;
	if (s->audio->valid && !s->audio_parse_end) {
		ms = st->atime_parsed;
		have = 1;
	}
	if (s->video->valid && !s->video_parse_end) {
		ms = have ? MIN(ms, st->vtime_parsed) : st->vtime_parsed;
		have = 1;
	}
	return have ? MAX(ms, 0) : 0;
}

static int nova_network_high_water_ready(STREAM *s, int target_ms)
{
	if (!s || !s->parser || !s->parser->get_stats)
		return 1;
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = s->parser->get_stats(s, &st);
	if (!pst)
		return 1;
	if (s->parser_error || s->video_error != VE_NO_ERROR)
		return 1;
	if (s->audio_parse_end && s->video_parse_end)
		return 1;
	int buffered_ms = nova_network_buffered_ms(s, pst);
	int byte_high = pst->buffer_size > 0 &&
		(int64_t)pst->buffer_used * 4 >= (int64_t)pst->buffer_size * 3;
	return buffered_ms >= target_ms || byte_high;
}

static void nova_network_startup_prefill(avos_mp_video_t *video)
{
	STREAM *s = video ? video->s : NULL;
	if (!s || !(s->flags & STREAM_FILE_NONLOCAL) || !s->parser || !s->parser->get_stats)
		return;
	const int target_ms = 4000;
	int64_t start = atime64();
	serprintf("NOVA_STARTUP_BUFFER_START target=%dms\\n", target_ms);
	while (!nova_network_high_water_ready(s, target_ms) &&
	       !__atomic_load_n(&video->abort, __ATOMIC_ACQUIRE) &&
	       !stream_abort(s)) {
		msec_sleep(10);
	}
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = s->parser->get_stats(s, &st);
	serprintf("NOVA_STARTUP_BUFFER_END waited=%lldms buffered=%dms used=%d/%d\\n",
		(long long)(atime64() - start),
		pst ? nova_network_buffered_ms(s, pst) : -1,
		pst ? pst->buffer_used : -1, pst ? pst->buffer_size : -1);
}

int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
'''
if "nova_network_startup_prefill" not in s:
    if anchor not in s:
        raise SystemExit("startup helper anchor not found")
    s = s.replace(anchor, helper, 1)

old_start = """int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
{
	if (stream_is_paused(video->s))
		stream_un_pause_from_jni(video->s, 0);
"""
new_start = """int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
{
	if (stream_is_paused(video->s)) {
		nova_network_startup_prefill(video);
		stream_un_pause_from_jni(video->s, 0);
	}
"""
if "nova_network_startup_prefill(video);" not in s:
    if old_start not in s:
        raise SystemExit("avos_mp_video_start anchor not found")
    s = s.replace(old_start, new_start, 1)
p.write_text(s)
print("patched startup high-water buffering")

# 4) AVOS audio consumer: proactive low-water detection + real rebuffer high-water.
p = avos / "Source/stream_audio.c"
s = p.read_text()
if '#include "avos_mp.h"' not in s:
    inc = '#include "audio_interface.h"\n'
    if inc not in s:
        raise SystemExit("stream_audio include anchor not found")
    s = s.replace(inc, inc + '#include "avos_mp.h"\n#include "avos_mp_priv.h"\n', 1)

if "extern int stream_video_paused;" not in s:
    old = "extern int stream_audio_paused;\n"
    if old not in s:
        raise SystemExit("stream_audio paused extern anchor not found")
    s = s.replace(old, old + "extern int stream_video_paused;\n", 1)

anchor = "static int pcm_channel_cap = 0;\n"
helpers = r'''
#define NOVA_REBUFFER_LOW_MS 750
#define NOVA_REBUFFER_HIGH_MS 4000
#define NOVA_REBUFFER_SLOW_HIGH_MS 8000

static int nova_rebuffer_buffered_ms(STREAM *s, STREAM_PARSER_STATS *st)
{
	int ms = INT_MAX;
	int have = 0;
	if (s->audio->valid && !s->audio_parse_end) {
		ms = st->atime_parsed;
		have = 1;
	}
	if (s->video->valid && !s->video_parse_end) {
		ms = have ? MIN(ms, st->vtime_parsed) : st->vtime_parsed;
		have = 1;
	}
	return have ? MAX(ms, 0) : 0;
}

static STREAM_PARSER_STATS *nova_rebuffer_stats(STREAM *s, STREAM_PARSER_STATS *st)
{
	return s && s->parser && s->parser->get_stats ? s->parser->get_stats(s, st) : NULL;
}

static void nova_rebuffer_send(STREAM *s, int info, int sentinel)
{
	avos_mp_t *mp = (avos_mp_t *)stream_get_user_ctx(s);
	if (!mp) return;
	avos_mp_sendevent(mp, MEDIA_INFO, info, 0);
	// Existing Nova Java already forwards buffering-update callbacks all the
	// way to PlayerActivity. Negative values are reserved by this test build
	// for start/end so UI glue can show/hide the existing spinner.
	avos_mp_sendevent(mp, MEDIA_BUFFERING_UPDATE, sentinel, 0);
}

static int nova_rebuffer_high_water(STREAM *s)
{
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = nova_rebuffer_stats(s, &st);
	if (!pst) return 1;
	if (s->parser_error || s->video_error != VE_NO_ERROR) return 1;
	if (s->audio_parse_end && s->video_parse_end) return 1;

	int buffered_ms = nova_rebuffer_buffered_ms(s, pst);
	int64_t elapsed = MAX((int64_t)1, atime64() - s->nova_rebuffer_started_ms);
	int64_t growth = MAX(0, pst->buffer_used - s->nova_rebuffer_start_used);
	int64_t fill_rate = growth * 1000 / elapsed;
	int64_t media_rate = MAX(pst->acurrent_rate, pst->vcurrent_rate);

	// Kodi's adaptive read factor becomes more conservative when the cache
	// level/rate margin is poor. Equivalent behavior here: if refill speed is
	// under 1.5x media rate, require a deeper 8s reservoir before resuming.
	int target = NOVA_REBUFFER_HIGH_MS;
	if (elapsed >= 1000 && media_rate > 0 && fill_rate * 2 < media_rate * 3)
		target = NOVA_REBUFFER_SLOW_HIGH_MS;
	s->nova_rebuffer_target_ms = target;

	// Kodi's 64 MiB circular cache reserves 1/4 for back cache, leaving 3/4
	// forward. AVOS has no retained back-cache packets, so use 75% as a hard
	// byte high-water alternative to avoid deadlock on very high bitrate media.
	int byte_high = pst->buffer_size > 0 &&
		(int64_t)pst->buffer_used * 4 >= (int64_t)pst->buffer_size * 3;

	if (buffered_ms >= target || byte_high) {
		serprintf("NOVA_REBUFFER_READY buffered=%dms target=%dms used=%d/%d fill=%lldBps media=%lldBps\\n",
			buffered_ms, target, pst->buffer_used, pst->buffer_size,
			(long long)fill_rate, (long long)media_rate);
		return 1;
	}
	return 0;
}

static int nova_rebuffer_low_water(STREAM *s)
{
	if (!s || !(s->flags & STREAM_FILE_NONLOCAL) || s->seek ||
	    s->paused || stream_audio_paused || s->nova_rebuffer_active ||
	    s->audio_time < 0 || (s->video->valid && s->video_time < 0))
		return 0;
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = nova_rebuffer_stats(s, &st);
	if (!pst) return 0;
	int buffered_ms = nova_rebuffer_buffered_ms(s, pst);
	return buffered_ms >= 0 && buffered_ms < NOVA_REBUFFER_LOW_MS &&
	       !s->audio_parse_end && (!s->video->valid || !s->video_parse_end);
}

static void nova_rebuffer_enter(STREAM *s, const char *reason)
{
	if (!s || s->nova_rebuffer_active || s->paused || stream_audio_paused)
		return;
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = nova_rebuffer_stats(s, &st);
	s->nova_rebuffer_active = 1;
	s->nova_rebuffer_saved_video_paused = stream_video_paused;
	s->nova_rebuffer_started_ms = atime64();
	s->nova_rebuffer_start_used = pst ? pst->buffer_used : 0;
	s->nova_rebuffer_target_ms = NOVA_REBUFFER_HIGH_MS;

	// Freeze consumer clocks/output but deliberately DO NOT set s->paused:
	// the network/parser producer continues filling in the background.
	stream_video_paused = 1;
	stream_audio_mute(s);
	if (s->audio_ctx && s->audio_sink_open)
		audio_interface_pause(s->audio_ctx);

	serprintf("NOVA_REBUFFER_START reason=%s buffered=%dms used=%d/%d audio=%d video=%d\\n",
		reason ? reason : "unknown",
		pst ? nova_rebuffer_buffered_ms(s, pst) : -1,
		pst ? pst->buffer_used : -1, pst ? pst->buffer_size : -1,
		s->audio_time, s->video_time);
	nova_rebuffer_send(s, MEDIA_INFO_BUFFERING_START, -1);
}

static void nova_rebuffer_leave(STREAM *s)
{
	if (!s || !s->nova_rebuffer_active) return;

	// Re-anchor after a discontinuous wall-clock hold so the resumed frames are
	// scheduled from fresh A/V time rather than trying to catch up in bursts.
	_stream_resync(s);
	if (s->audio_ctx && s->audio_sink_open)
		audio_interface_unpause(s->audio_ctx);
	stream_video_paused = s->nova_rebuffer_saved_video_paused;
	if (s->speed == STREAM_SPEED_NORMAL)
		stream_audio_unmute(s);

	s->nova_rebuffer_active = 0;
	serprintf("NOVA_REBUFFER_END waited=%lldms target=%dms audio=%d video=%d\\n",
		(long long)(atime64() - s->nova_rebuffer_started_ms),
		s->nova_rebuffer_target_ms, s->audio_time, s->video_time);
	nova_rebuffer_send(s, MEDIA_INFO_BUFFERING_END, -2);
}

'''
if "NOVA_REBUFFER_LOW_MS" not in s:
    if anchor not in s:
        raise SystemExit("rebuffer helper anchor not found")
    s = s.replace(anchor, anchor + helpers, 1)

decode_anchor = """static void _audio_decode( STREAM *s )
{
	static int out_of_audio;
	
"""
decode_new = """static void _audio_decode( STREAM *s )
{
	static int out_of_audio;
	
	// Do not wait for AudioTrack to underrun. Enter rebuffer while there is
	// still a small safety reservoir, then keep the parser/network producer on.
	if (nova_rebuffer_low_water(s))
		nova_rebuffer_enter(s, "low-water");
	if (s->nova_rebuffer_active) {
		if (s->paused || stream_audio_paused) {
			// User pause supersedes automatic rebuffer state.
			s->nova_rebuffer_active = 0;
			stream_video_paused = s->nova_rebuffer_saved_video_paused;
		} else if (nova_rebuffer_high_water(s)) {
			nova_rebuffer_leave(s);
		} else {
			stream_yield_RT();
			return;
		}
	}
	
"""
if 'nova_rebuffer_enter(s, "low-water")' not in s:
    if decode_anchor not in s:
        raise SystemExit("_audio_decode anchor not found")
    s = s.replace(decode_anchor, decode_new, 1)

loop_anchor = """		while( s->audio_buffer_size <= 0 && !_abort( s ) ){
			
			STREAM_CDATA cdata = { 0 };
"""
loop_new = """		int nova_starve_start_ms = atime();
		while( s->audio_buffer_size <= 0 && !_abort( s ) ){
			if (!s->nova_rebuffer_active && !s->audio_parse_end &&
		    (s->flags & STREAM_FILE_NONLOCAL) &&
		    atime() - nova_starve_start_ms >= 250)
				nova_rebuffer_enter(s, "starved");
			if (s->nova_rebuffer_active) {
				if (nova_rebuffer_high_water(s))
					nova_rebuffer_leave(s);
				else {
					stream_yield_RT();
					continue;
				}
			}
			
			STREAM_CDATA cdata = { 0 };
"""
if 'nova_rebuffer_enter(s, "starved")' not in s:
    if loop_anchor not in s:
        raise SystemExit("audio starvation loop anchor not found")
    s = s.replace(loop_anchor, loop_new, 1)

p.write_text(s)
print("patched low/high-water AVOS rebuffer state machine")
