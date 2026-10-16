#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1])
avos = root / "native/avos"

def replace_once(path, old, new, label):
    p = avos / path
    s = p.read_text()
    if new in s:
        print(label + ": already applied")
        return
    if old not in s:
        raise SystemExit(f"{label}: anchor not found in {p}")
    p.write_text(s.replace(old, new, 1))
    print("patched", label)

# ---------------------------------------------------------------------------
# Stream state + native buffering events
# ---------------------------------------------------------------------------
replace_once(
    "Include/stream.h",
    """typedef enum {
	STREAM_AUDIO_PROPS_CHANGED = 1,
	STREAM_VIDEO_PROPS_CHANGED,
	STREAM_SUB_PROPS_CHANGED,
	STREAM_SUBTITLE_CHANGED,
	STREAM_DECODER_CHANGED,
} STREAM_MESSAGE;
""",
    """typedef enum {
	STREAM_AUDIO_PROPS_CHANGED = 1,
	STREAM_VIDEO_PROPS_CHANGED,
	STREAM_SUB_PROPS_CHANGED,
	STREAM_SUBTITLE_CHANGED,
	STREAM_DECODER_CHANGED,
	STREAM_BUFFERING_START,
	STREAM_BUFFERING_END,
} STREAM_MESSAGE;
""",
    "stream buffering messages"
)

replace_once(
    "Include/stream.h",
    """	int		paused;
	int		paused_internal;
	int		speed;
""",
    """	int		paused;
	int		paused_internal;
	// Internal network rebuffer state. Unlike user pause, this freezes
	// consumers while the parser/network producer continues filling.
	volatile int	nova_rebuffer_active;
	int64_t		nova_rebuffer_started_ms;
	int		nova_rebuffer_count;
	int		nova_rebuffer_resume_ms;
	int		speed;
""",
    "stream rebuffer state"
)

# ---------------------------------------------------------------------------
# FFmpeg input: real byte-addressed 64 MiB circular file cache in front of demux
# ---------------------------------------------------------------------------
p = avos / "Source/stream_parser_ffmpeg.c"
s = p.read_text()
if '#include "atime.h"' not in s:
    at_anchor = '#include "util.h"\\n'
    if at_anchor not in s:
        raise SystemExit("ffmpeg atime include anchor missing")
    s = s.replace(at_anchor, at_anchor + '#include "atime.h"\\n', 1)

inc_anchor = '#include <signal.h>\n'
inc_new = '#include <signal.h>\n#include <pthread.h>\n#include <unistd.h>\n'
if '#include <pthread.h>' not in s:
    if inc_anchor not in s:
        raise SystemExit("ffmpeg include anchor missing")
    s = s.replace(inc_anchor, inc_new, 1)

struct_anchor = """typedef struct AVQueue {
	LinkedList	list;
	pthread_mutex_t mutex;
	int		mem_used;
	int 		packets;
} AVQueue;

"""
cache_code = r'''#define NOVA_FILECACHE_CAPACITY (64 * 1024 * 1024)
#define NOVA_FILECACHE_BACK     (16 * 1024 * 1024)
#define NOVA_FILECACHE_CHUNK    (256 * 1024)

typedef struct NOVA_FILE_CACHE {
	STREAM *s;
	char *url;
	AVDictionary *open_opts;
	AVIOContext *upstream;
	AVIOContext *client;
	unsigned char *client_buffer;
	unsigned char *ring;
	int64_t file_size;
	int64_t window_start;
	int64_t read_pos;
	int64_t write_pos;
	int64_t upstream_pos;
	volatile int generation;
	volatile int source_generation;
	int running;
	int eof;
	int fatal_error;
	pthread_t thread;
	pthread_mutex_t mutex;
	pthread_cond_t cond;
	int64_t stat_bytes;
	int stat_started_ms;
} NOVA_FILE_CACHE;

static int nova_cache_interrupt(void *opaque)
{
	NOVA_FILE_CACHE *c = (NOVA_FILE_CACHE *)opaque;
	if (!c || !c->running) return 1;
	if (c->source_generation != c->generation) return 1;
	return c->s && stream_abort(c->s) ? 1 : 0;
}

static void nova_cache_close_upstream(NOVA_FILE_CACHE *c)
{
	if (c->upstream) {
		avio_closep(&c->upstream);
		c->upstream = NULL;
	}
	c->upstream_pos = -1;
}

static int nova_cache_open_upstream(NOVA_FILE_CACHE *c, int64_t pos)
{
	AVDictionary *opts = NULL;
	av_dict_copy(&opts, c->open_opts, 0);
	AVIOInterruptCB interrupt = { nova_cache_interrupt, c };
	c->source_generation = c->generation;
	int ret = avio_open2(&c->upstream, c->url, AVIO_FLAG_READ, &interrupt, &opts);
	av_dict_free(&opts);
	if (ret < 0) {
		c->upstream = NULL;
		return ret;
	}
	if (c->file_size < 0) {
		int64_t size = avio_size(c->upstream);
		if (size >= 0) c->file_size = size;
	}
	if (pos > 0) {
		int64_t seeked = avio_seek(c->upstream, pos, SEEK_SET);
		if (seeked != pos) {
			nova_cache_close_upstream(c);
			return seeked < 0 ? (int)seeked : AVERROR(EIO);
		}
	}
	c->upstream_pos = pos;
	serprintf("NOVA_FILECACHE_SOURCE_OPEN pos=%lld gen=%d size=%lld\n",
		(long long)pos, c->generation, (long long)c->file_size);
	return 0;
}

static void nova_cache_copy_in(NOVA_FILE_CACHE *c, int64_t pos, const unsigned char *src, int len)
{
	int idx = (int)(pos % NOVA_FILECACHE_CAPACITY);
	int first = MIN(len, NOVA_FILECACHE_CAPACITY - idx);
	memcpy(c->ring + idx, src, first);
	if (first < len) memcpy(c->ring, src + first, len - first);
}

static void nova_cache_copy_out(NOVA_FILE_CACHE *c, int64_t pos, unsigned char *dst, int len)
{
	int idx = (int)(pos % NOVA_FILECACHE_CAPACITY);
	int first = MIN(len, NOVA_FILECACHE_CAPACITY - idx);
	memcpy(dst, c->ring + idx, first);
	if (first < len) memcpy(dst + first, c->ring, len - first);
}

static void *nova_cache_thread(void *opaque)
{
	NOVA_FILE_CACHE *c = (NOVA_FILE_CACHE *)opaque;
	unsigned char *tmp = av_malloc(NOVA_FILECACHE_CHUNK);
	if (!tmp) {
		pthread_mutex_lock(&c->mutex);
		c->fatal_error = AVERROR(ENOMEM);
		pthread_cond_broadcast(&c->cond);
		pthread_mutex_unlock(&c->mutex);
		return NULL;
	}

	while (1) {
		int gen;
		int64_t pos;
		int to_read;

		pthread_mutex_lock(&c->mutex);
		while (c->running) {
			int64_t keep = c->read_pos > NOVA_FILECACHE_BACK ? c->read_pos - NOVA_FILECACHE_BACK : 0;
			if (keep > c->window_start) c->window_start = keep;
			int64_t used = c->write_pos - c->window_start;
			int64_t free_bytes = NOVA_FILECACHE_CAPACITY - used;
			if (!c->eof && free_bytes > 0) {
				gen = c->generation;
				pos = c->write_pos;
				to_read = (int)MIN((int64_t)NOVA_FILECACHE_CHUNK, free_bytes);
				if (c->file_size >= 0)
					to_read = (int)MIN((int64_t)to_read, c->file_size - pos);
				if (to_read > 0) break;
				c->eof = 1;
				pthread_cond_broadcast(&c->cond);
			}
			pthread_cond_wait(&c->cond, &c->mutex);
		}
		if (!c->running) {
			pthread_mutex_unlock(&c->mutex);
			break;
		}
		pthread_mutex_unlock(&c->mutex);

		if (!c->upstream || c->source_generation != gen || c->upstream_pos != pos) {
			nova_cache_close_upstream(c);
			int ret = nova_cache_open_upstream(c, pos);
			if (ret < 0) {
				pthread_mutex_lock(&c->mutex);
				if (c->generation == gen && c->running) {
					serprintf("NOVA_FILECACHE_RECONNECT_FAIL pos=%lld err=%d\n",
						(long long)pos, ret);
				}
				pthread_mutex_unlock(&c->mutex);
				msec_sleep(500);
				continue;
			}
		}

		int ret = avio_read(c->upstream, tmp, to_read);
		if (ret > 0) c->upstream_pos += ret;

		pthread_mutex_lock(&c->mutex);
		if (!c->running) {
			pthread_mutex_unlock(&c->mutex);
			break;
		}
		if (gen != c->generation) {
			pthread_mutex_unlock(&c->mutex);
			nova_cache_close_upstream(c);
			continue;
		}

		if (ret > 0) {
			nova_cache_copy_in(c, pos, tmp, ret);
			c->write_pos += ret;
			c->stat_bytes += ret;
			if (c->stat_started_ms == 0) c->stat_started_ms = atime();
			if (c->stat_bytes >= 8LL * 1024 * 1024) {
				int elapsed = MAX(1, atime() - c->stat_started_ms);
				serprintf("NOVA_FILECACHE_STAT read=%lld write=%lld start=%lld forward=%lld back=%lld rate=%lldBps\n",
					(long long)c->read_pos, (long long)c->write_pos,
					(long long)c->window_start,
					(long long)(c->write_pos - c->read_pos),
					(long long)(c->read_pos - c->window_start),
					(long long)(c->stat_bytes * 1000 / elapsed));
				c->stat_bytes = 0;
				c->stat_started_ms = atime();
			}
			pthread_cond_broadcast(&c->cond);
			pthread_mutex_unlock(&c->mutex);
			continue;
		}

		if (ret == AVERROR_EOF && (c->file_size < 0 || c->write_pos >= c->file_size)) {
			c->eof = 1;
			serprintf("NOVA_FILECACHE_EOF pos=%lld size=%lld\n",
				(long long)c->write_pos, (long long)c->file_size);
			pthread_cond_broadcast(&c->cond);
			pthread_mutex_unlock(&c->mutex);
			nova_cache_close_upstream(c);
			continue;
		}

		// A short/failed localhost HTTP source before logical EOF is recoverable:
		// retain every cached byte and reopen with a Range seek at write_pos.
		serprintf("NOVA_FILECACHE_RECONNECT pos=%lld err=%d gen=%d\n",
			(long long)c->write_pos, ret, c->generation);
		pthread_mutex_unlock(&c->mutex);
		nova_cache_close_upstream(c);
		msec_sleep(250);
	}
	nova_cache_close_upstream(c);
	av_free(tmp);
	return NULL;
}

static int nova_cache_read(void *opaque, uint8_t *buf, int size)
{
	NOVA_FILE_CACHE *c = (NOVA_FILE_CACHE *)opaque;
	if (!c || size <= 0) return AVERROR(EINVAL);
	pthread_mutex_lock(&c->mutex);
	for (;;) {
		if (!c->running || (c->s && stream_abort(c->s))) {
			pthread_mutex_unlock(&c->mutex);
			return AVERROR_EXIT;
		}
		int64_t available = c->write_pos - c->read_pos;
		if (available > 0) {
			int n = (int)MIN((int64_t)size, available);
			nova_cache_copy_out(c, c->read_pos, buf, n);
			c->read_pos += n;
			pthread_cond_broadcast(&c->cond);
			pthread_mutex_unlock(&c->mutex);
			return n;
		}
		if (c->eof) {
			pthread_mutex_unlock(&c->mutex);
			return AVERROR_EOF;
		}
		if (c->fatal_error) {
			int err = c->fatal_error;
			pthread_mutex_unlock(&c->mutex);
			return err;
		}
		pthread_cond_wait(&c->cond, &c->mutex);
	}
}

static int64_t nova_cache_seek(void *opaque, int64_t offset, int whence)
{
	NOVA_FILE_CACHE *c = (NOVA_FILE_CACHE *)opaque;
	if (!c) return AVERROR(EINVAL);
	if (whence == AVSEEK_SIZE) return c->file_size;
	whence &= ~AVSEEK_FORCE;

	pthread_mutex_lock(&c->mutex);
	int64_t base;
	if (whence == SEEK_SET) base = 0;
	else if (whence == SEEK_CUR) base = c->read_pos;
	else if (whence == SEEK_END && c->file_size >= 0) base = c->file_size;
	else {
		pthread_mutex_unlock(&c->mutex);
		return AVERROR(EINVAL);
	}
	int64_t target = base + offset;
	if (target < 0 || (c->file_size >= 0 && target > c->file_size)) {
		pthread_mutex_unlock(&c->mutex);
		return AVERROR(EINVAL);
	}

	if (target >= c->window_start && target <= c->write_pos) {
		serprintf("NOVA_FILECACHE_SEEK_HIT from=%lld to=%lld window=%lld..%lld\n",
			(long long)c->read_pos, (long long)target,
			(long long)c->window_start, (long long)c->write_pos);
		c->read_pos = target;
		pthread_cond_broadcast(&c->cond);
		pthread_mutex_unlock(&c->mutex);
		return target;
	}

	serprintf("NOVA_FILECACHE_SEEK_MISS from=%lld to=%lld window=%lld..%lld\n",
		(long long)c->read_pos, (long long)target,
		(long long)c->window_start, (long long)c->write_pos);
	c->generation++;
	c->window_start = target;
	c->read_pos = target;
	c->write_pos = target;
	c->eof = 0;
	c->fatal_error = 0;
	pthread_cond_broadcast(&c->cond);
	pthread_mutex_unlock(&c->mutex);
	return target;
}

static NOVA_FILE_CACHE *nova_filecache_create(STREAM *s, const char *url, AVDictionary *opts)
{
	NOVA_FILE_CACHE *c = acalloc(1, sizeof(*c));
	if (!c) return NULL;
	c->s = s;
	c->file_size = -1;
	c->upstream_pos = -1;
	c->url = astrdup(url);
	if (!c->url) { afree(c); return NULL; }
	av_dict_copy(&c->open_opts, opts, 0);
	c->ring = av_malloc(NOVA_FILECACHE_CAPACITY);
	c->client_buffer = av_malloc(256 * 1024);
	if (!c->ring || !c->client_buffer) {
		av_free(c->ring);
		av_free(c->client_buffer);
		av_dict_free(&c->open_opts);
		afree(c->url);
		afree(c);
		return NULL;
	}
	pthread_mutex_init(&c->mutex, NULL);
	pthread_cond_init(&c->cond, NULL);
	c->running = 1;
	c->generation = 1;
	c->client = avio_alloc_context(c->client_buffer, 256 * 1024, 0, c,
		nova_cache_read, NULL, nova_cache_seek);
	if (!c->client) {
		pthread_cond_destroy(&c->cond);
		pthread_mutex_destroy(&c->mutex);
		av_free(c->ring);
		av_free(c->client_buffer);
		av_dict_free(&c->open_opts);
		afree(c->url);
		afree(c);
		return NULL;
	}
	c->client->seekable = AVIO_SEEKABLE_NORMAL;
	if (pthread_create(&c->thread, NULL, nova_cache_thread, c) != 0) {
		avio_context_free(&c->client);
		pthread_cond_destroy(&c->cond);
		pthread_mutex_destroy(&c->mutex);
		av_free(c->ring);
		av_dict_free(&c->open_opts);
		afree(c->url);
		afree(c);
		return NULL;
	}
	serprintf("NOVA_FILECACHE_CREATE cap=64MiB back=16MiB front=48MiB url=%s\n", url);
	return c;
}

static void nova_filecache_destroy(NOVA_FILE_CACHE **pc)
{
	NOVA_FILE_CACHE *c = pc ? *pc : NULL;
	if (!c) return;
	pthread_mutex_lock(&c->mutex);
	c->running = 0;
	c->generation++;
	pthread_cond_broadcast(&c->cond);
	pthread_mutex_unlock(&c->mutex);
	pthread_join(c->thread, NULL);
	if (c->client) {
		// avio_context_free also frees client_buffer.
		avio_context_free(&c->client);
		c->client_buffer = NULL;
	}
	av_free(c->ring);
	av_dict_free(&c->open_opts);
	afree(c->url);
	pthread_cond_destroy(&c->cond);
	pthread_mutex_destroy(&c->mutex);
	afree(c);
	*pc = NULL;
	serprintf("NOVA_FILECACHE_DESTROY\n");
}

'''
if "typedef struct NOVA_FILE_CACHE" not in s:
    if struct_anchor not in s:
        raise SystemExit("AVQueue anchor missing")
    s = s.replace(struct_anchor, struct_anchor + cache_code, 1)

ffpriv_anchor = """typedef struct FF_PRIV 
{
	AVFormatContext *fmt;
        AVDictionary    *fmt_opts;
"""
ffpriv_new = """typedef struct FF_PRIV 
{
	AVFormatContext *fmt;
	NOVA_FILE_CACHE *nova_cache;
        AVDictionary    *fmt_opts;
"""
if "NOVA_FILE_CACHE *nova_cache;" not in s:
    if ffpriv_anchor not in s:
        raise SystemExit("FF_PRIV anchor missing")
    s = s.replace(ffpriv_anchor, ffpriv_new, 1)

open_anchor = """DBGP serprintf("FFMPEG: opening url [%s]\r\n", s->src.url);

	if( avformat_open_input(&ff_p->fmt, s->src.url, NULL, &ff_p->fmt_opts ) != 0) {
serprintf("FFMPEG: cannot open file [%s]\r\n", s->src.url);
		goto ErrorExit4;
	}
"""
open_new = """DBGP serprintf("FFMPEG: opening url [%s]\r\n", s->src.url);

	int nova_cached_input = (ff_p->flags & STREAM_PARSER_FILE_NONLOCAL) &&
		(!strncmp(s->src.url, "http://localhost:", 17) ||
		 !strncmp(s->src.url, "http://127.0.0.1:", 17));
	if (nova_cached_input) {
		ff_p->nova_cache = nova_filecache_create(s, s->src.url, ff_p->fmt_opts);
		if (!ff_p->nova_cache) {
			serprintf("FFMPEG: cannot create Nova file cache [%s]\\n", s->src.url);
			goto ErrorExit4;
		}
		ff_p->fmt->pb = ff_p->nova_cache->client;
		ff_p->fmt->flags |= AVFMT_FLAG_CUSTOM_IO;
		if (avformat_open_input(&ff_p->fmt, NULL, NULL, &ff_p->fmt_opts) != 0) {
			serprintf("FFMPEG: cannot open cached input [%s]\\n", s->src.url);
			goto ErrorExit4;
		}
	} else if( avformat_open_input(&ff_p->fmt, s->src.url, NULL, &ff_p->fmt_opts ) != 0) {
serprintf("FFMPEG: cannot open file [%s]\r\n", s->src.url);
		goto ErrorExit4;
	}
"""
if "int nova_cached_input" not in s:
    if open_anchor not in s:
        raise SystemExit("FFmpeg open anchor missing")
    s = s.replace(open_anchor, open_new, 1)

close_anchor = """	if( ff_p ) {
		if( ff_p->fmt ) {
			// Close the video file
			avformat_close_input(&ff_p->fmt);
		}


		_flush_packets( &ff_p->vq, "VID" );
"""
close_new = """	if( ff_p ) {
		if( ff_p->fmt ) {
			// Close the demuxer first; custom AVIO ownership remains with nova_cache.
			avformat_close_input(&ff_p->fmt);
		}
		if (ff_p->nova_cache) {
			nova_filecache_destroy(&ff_p->nova_cache);
		}

		_flush_packets( &ff_p->vq, "VID" );
"""
if "nova_filecache_destroy(&ff_p->nova_cache)" not in s:
    if close_anchor not in s:
        raise SystemExit("FFmpeg close anchor missing")
    s = s.replace(close_anchor, close_new, 1)

# Error path must release the cache too.
err_anchor = """ErrorExit4:
ErrorExit3:
	av_dict_free(&ff_p->fmt_opts);
"""
err_new = """ErrorExit4:
	if (ff_p && ff_p->nova_cache) nova_filecache_destroy(&ff_p->nova_cache);
ErrorExit3:
	av_dict_free(&ff_p->fmt_opts);
"""
if "if (ff_p && ff_p->nova_cache) nova_filecache_destroy" not in s:
    if err_anchor not in s:
        raise SystemExit("FFmpeg error anchor missing")
    s = s.replace(err_anchor, err_new, 1)

p.write_text(s)
print("patched FFmpeg byte-addressed file cache")

# ---------------------------------------------------------------------------
# Rebuffer state machine: parser producer continues; consumers freeze;
# resume only when both active queues hold Kodi's default 4.0 s.
# ---------------------------------------------------------------------------
p = avos / "Source/stream_video.c"
s = p.read_text()

parser_anchor = """		if( thread_state_get( &s->parser_tstate ) == THREAD_RUNNING ) {
			// call parser if needed
			if ( !s->paused || s->play_n_video_frames || s->play_n_audio_frames || s->parser_parse_once ) {
"""
parser_new = """		if( thread_state_get( &s->parser_tstate ) == THREAD_RUNNING ) {
			// Keep the producer independent from playback consumption for network files.
			// This mirrors Kodi's cache producer/consumer separation and lets a paused
			// or rebuffering player refill instead of starving itself.
			if ( !s->paused || (s->flags & STREAM_FILE_NONLOCAL) ||
			     s->play_n_video_frames || s->play_n_audio_frames || s->parser_parse_once ) {
"""
if "(s->flags & STREAM_FILE_NONLOCAL)" not in s[s.find("stream_parser_thread::Starting"):s.find("stream_parser_thread::Exiting")+200]:
    if parser_anchor not in s:
        raise SystemExit("parser-thread anchor missing")
    s = s.replace(parser_anchor, parser_new, 1)

helper_anchor = """static int _handle_video_codec_error( STREAM *s );

// *****************************************************************************
"""
helper_code = r'''static int _handle_video_codec_error( STREAM *s );

#define NOVA_REBUFFER_RESUME_MS 4000

static int nova_queue_ready_ms(STREAM *s, STREAM_PARSER_STATS *st)
{
	int ready = 0x7fffffff;
	int have = 0;
	if (s->audio->valid && !s->audio_parse_end) {
		ready = st->atime_parsed;
		have = 1;
	}
	if (s->video->valid && !s->video_parse_end) {
		ready = have ? MIN(ready, st->vtime_parsed) : st->vtime_parsed;
		have = 1;
	}
	return have ? MAX(0, ready) : NOVA_REBUFFER_RESUME_MS;
}

static int nova_rebuffer_can_resume(STREAM *s)
{
	if (!s || !s->parser || !s->parser->get_stats) return 1;
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = s->parser->get_stats(s, &st);
	if (!pst) return 1;
	if (s->parser_error || s->video_error != VE_NO_ERROR) return 1;
	if (s->audio_parse_end && s->video_parse_end) return 1;
	return nova_queue_ready_ms(s, pst) >= NOVA_REBUFFER_RESUME_MS;
}

static void nova_rebuffer_enter(STREAM *s, const char *reason)
{
	if (!s || s->nova_rebuffer_active || s->paused || !(s->flags & STREAM_FILE_NONLOCAL))
		return;
	s->nova_rebuffer_active = 1;
	s->nova_rebuffer_started_ms = atime();
	s->nova_rebuffer_resume_ms = NOVA_REBUFFER_RESUME_MS;
	s->nova_rebuffer_count++;
	stream_audio_mute(s);
	if (s->audio_ctx && s->audio_sink_open)
		audio_interface_pause(s->audio_ctx);
	sfdec2_android_sync_on_pause(s, 1);
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = s->parser && s->parser->get_stats ? s->parser->get_stats(s, &st) : NULL;
	serprintf("NOVA_REBUFFER_START reason=%s count=%d aq=%d vq=%d buffered=%dms used=%d/%d\n",
		reason ? reason : "unknown", s->nova_rebuffer_count,
		pst ? pst->audio_chunks : -1, pst ? pst->video_chunks : -1,
		pst ? nova_queue_ready_ms(s, pst) : -1,
		pst ? pst->buffer_used : -1, pst ? pst->buffer_size : -1);
	if (s->message_cb) s->message_cb(s, STREAM_BUFFERING_START);
}

static void nova_rebuffer_poll(STREAM *s)
{
	if (!s || !s->nova_rebuffer_active || !nova_rebuffer_can_resume(s))
		return;
	STREAM_PARSER_STATS st;
	STREAM_PARSER_STATS *pst = s->parser && s->parser->get_stats ? s->parser->get_stats(s, &st) : NULL;
	_stream_resync(s);
	sfdec2_android_sync_on_pause(s, 0);
	if (s->audio_ctx && s->audio_sink_open)
		audio_interface_unpause(s->audio_ctx);
	if (s->speed == STREAM_SPEED_NORMAL)
		stream_audio_unmute(s);
	s->nova_rebuffer_active = 0;
	serprintf("NOVA_REBUFFER_END waited=%dms buffered=%dms aq=%d vq=%d used=%d/%d\n",
		atime() - (int)s->nova_rebuffer_started_ms,
		pst ? nova_queue_ready_ms(s, pst) : -1,
		pst ? pst->audio_chunks : -1, pst ? pst->video_chunks : -1,
		pst ? pst->buffer_used : -1, pst ? pst->buffer_size : -1);
	if (s->message_cb) s->message_cb(s, STREAM_BUFFERING_END);
}

// *****************************************************************************
'''
if "NOVA_REBUFFER_RESUME_MS" not in s:
    if helper_anchor not in s:
        raise SystemExit("video helper anchor missing")
    s = s.replace(helper_anchor, helper_code, 1)

# Poll from parser thread after every parse/rate update.
poll_anchor = """					if( stream_parser_sleep ) {
						msec_sleep( stream_parser_sleep );
					}
"""
poll_new = """					if (s->nova_rebuffer_active)
						nova_rebuffer_poll(s);
					if( stream_parser_sleep ) {
						msec_sleep( stream_parser_sleep );
					}
"""
if "nova_rebuffer_poll(s);" not in s[s.find("stream_parser_thread::Starting"):s.find("stream_parser_thread::Exiting")+200]:
    if poll_anchor not in s:
        raise SystemExit("parser poll anchor missing")
    s = s.replace(poll_anchor, poll_new, 1)

# Video starvation must enter rebuffer too, important for video-only files.
video_empty_anchor = """	if( !s->cdata_now.valid ) {
DBGV serprintf("!" );				
		msec_sleep( 10 );
		return;
	}
"""
video_empty_new = """	if( !s->cdata_now.valid ) {
DBGV serprintf("!" );				
		if (!s->video_parse_end)
			nova_rebuffer_enter(s, "video-starved");
		msec_sleep( 10 );
		return;
	}
"""
if 'nova_rebuffer_enter(s, "video-starved")' not in s:
    if video_empty_anchor not in s:
        raise SystemExit("video empty anchor missing")
    s = s.replace(video_empty_anchor, video_empty_new, 1)

# Freeze video consumer during rebuffer before fetching/submitting any more frames.
sync_anchor = """static void _stream_player_sync( STREAM *s )
{
DECODE_AGAIN:
"""
sync_new = """static void _stream_player_sync( STREAM *s )
{
	if (s->nova_rebuffer_active) {
		msec_sleep(10);
		return;
	}
DECODE_AGAIN:
"""
if "if (s->nova_rebuffer_active)" not in s[s.find("static void _stream_player_sync"):s.find("static void _stream_player_sync")+500]:
    if sync_anchor not in s:
        raise SystemExit("sync player anchor missing")
    s = s.replace(sync_anchor, sync_new, 1)

async_anchor = """static void _stream_player_async( STREAM *s )
{
"""
async_new = """static void _stream_player_async( STREAM *s )
{
	if (s->nova_rebuffer_active) {
		msec_sleep(10);
		return;
	}
"""
if s.count("if (s->nova_rebuffer_active)") < 2:
    if async_anchor not in s:
        raise SystemExit("async player anchor missing")
    s = s.replace(async_anchor, async_new, 1)

p.write_text(s)
print("patched AVOS rebuffer state machine")

# Audio starvation entry + freeze.
p = avos / "Source/stream_audio.c"
s = p.read_text()
audio_loop_anchor = """		// no more audio in this chunk, then look for next
		while( s->audio_buffer_size <= 0 && !_abort( s ) ){
			
			STREAM_CDATA cdata = { 0 };
"""
audio_loop_new = """		// no more audio in this chunk, then look for next

		while( s->audio_buffer_size <= 0 && !_abort( s ) ){
			STREAM_CDATA cdata = { 0 };
"""
if "int nova_audio_starve_started" not in s:
    if audio_loop_anchor not in s:
        raise SystemExit("audio loop anchor missing")
    s = s.replace(audio_loop_anchor, audio_loop_new, 1)

fail_anchor = """			if ( s->parser->get_audio_cdata( s, &s->audio_now, &cdata  ) ) {
				if ( s->audio_parse_end ) {
"""
fail_new = """			if ( s->parser->get_audio_cdata( s, &s->audio_now, &cdata  ) ) {
				if (!s->audio_parse_end && (s->flags & STREAM_FILE_NONLOCAL))
					nova_rebuffer_enter(s, "audio-starved");
				if ( s->audio_parse_end ) {
"""
if 'nova_rebuffer_enter(s, "audio-starved")' not in s:
    if fail_anchor not in s:
        raise SystemExit("audio starvation anchor missing")
    s = s.replace(fail_anchor, fail_new, 1)

valid_anchor = """			if( cdata.valid ) {
"""
valid_new = """
			if( cdata.valid ) {
"""
if "nova_audio_starve_started = 0;" not in s[s.find("int nova_audio_starve_started"):s.find("int nova_audio_starve_started")+8000]:
    if valid_anchor not in s:
        raise SystemExit("audio valid anchor missing")
    s = s.replace(valid_anchor, valid_new, 1)

# Need declarations for helper from stream_video.c.
decl_anchor = """extern int DEBUG_delay;
void _stream_resync( STREAM *s );
"""
decl_new = """extern int DEBUG_delay;
void _stream_resync( STREAM *s );
void nova_rebuffer_enter(STREAM *s, const char *reason);
"""
# helper was static above; make it externally visible first.
vp = avos / "Source/stream_video.c"
vs = vp.read_text().replace("static void nova_rebuffer_enter(STREAM *s, const char *reason)",
                            "void nova_rebuffer_enter(STREAM *s, const char *reason)", 1)
vp.write_text(vs)
if "void nova_rebuffer_enter(STREAM *s" not in s:
    if decl_anchor not in s:
        raise SystemExit("audio declaration anchor missing")
    s = s.replace(decl_anchor, decl_new, 1)

p.write_text(s)
print("patched audio starvation detection")

# ---------------------------------------------------------------------------
# AVOS -> Android buffering events + 64 MiB demux packet budget for network
# ---------------------------------------------------------------------------
p = avos / "Source/avos_mp_video.c"
s = p.read_text()
if "void nova_rebuffer_arm_startup(STREAM *s);" not in s:
    proto_anchor = 'extern int libavos_get_ac3_recoding_enabled(void);\\n'
    proto_text = proto_anchor + 'void nova_rebuffer_arm_startup(STREAM *s);\\nvoid nova_rebuffer_hold_outputs(STREAM *s);\\n'
    if proto_anchor not in s:
        raise SystemExit("avos startup prototype anchor missing")
    s = s.replace(proto_anchor, proto_text, 1)

msg_anchor = """	case STREAM_SUBTITLE_CHANGED:
		send_subtitle(mp, video);
		break;
	default:
"""
msg_new = """	case STREAM_SUBTITLE_CHANGED:
		send_subtitle(mp, video);
		break;
	case STREAM_BUFFERING_START:
		avos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_START, 0);
		// Existing Java buffering callback is used as a deterministic UI bridge.
		avos_mp_sendevent(mp, MEDIA_BUFFERING_UPDATE, -1, 0);
		break;
	case STREAM_BUFFERING_END:
		avos_mp_sendevent(mp, MEDIA_INFO, MEDIA_INFO_BUFFERING_END, 0);
		avos_mp_sendevent(mp, MEDIA_BUFFERING_UPDATE, -2, 0);
		break;
	default:
"""
if "MEDIA_INFO_BUFFERING_START" not in s:
    if msg_anchor not in s:
        raise SystemExit("avos message anchor missing")
    s = s.replace(msg_anchor, msg_new, 1)

buf_anchor = """	if (_flags & STREAM_FILE_NONLOCAL) {
		stream_set_buffer_size(video->s, get_default_stream_buffer_size()); // use less memory for NONLOCAL playback
	} else if ( !device_has_hdd() ) {
"""
buf_new = """	if (_flags & STREAM_FILE_NONLOCAL) {
		// Kodi current defaults: 64 MiB file cache, 256 MiB player queue data,
		// and 4.0 s player queue time. Keep those budgets distinct.
		stream_set_buffer_size(video->s, MAX(get_default_stream_buffer_size(), 256));
		serprintf("NOVA_REBUFFER_POLICY filecache=64MiB back=16MiB queue=256MiB resume=4000ms\\n");
	} else if ( !device_has_hdd() ) {
"""
if "NOVA_REBUFFER_POLICY" not in s:
    if buf_anchor not in s:
        raise SystemExit("network buffer anchor missing")
    s = s.replace(buf_anchor, buf_new, 1)

start_anchor = """int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
{
	if (stream_is_paused(video->s))
		stream_un_pause_from_jni(video->s, 0);
	else if (!is_stream_pauseable(mp, video))
		stream_audio_unmute(video->s);
	return AVOS_ERR_OK;
}
"""
start_new = """int avos_mp_video_start(avos_mp_t *mp, avos_mp_video_t *video)
{
	if (stream_is_paused(video->s)) {
		if (video->s->flags & STREAM_FILE_NONLOCAL)
			nova_rebuffer_arm_startup(video->s);
		stream_un_pause_from_jni(video->s, 0);
		if (video->s->nova_rebuffer_active)
			nova_rebuffer_hold_outputs(video->s);
	} else if (!is_stream_pauseable(mp, video)) {
		stream_audio_unmute(video->s);
	}
	return AVOS_ERR_OK;
}
"""
if "nova_rebuffer_arm_startup(video->s);" not in s:
    if start_anchor not in s:
        raise SystemExit("avos start anchor missing")
    s = s.replace(start_anchor, start_new, 1)

p.write_text(s)
print("patched Android buffering events, startup gate, and Kodi queue budgets")

print("FILECACHE_REBUFFER_V3_PATCH=PASS")
