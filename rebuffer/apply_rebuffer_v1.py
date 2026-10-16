#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1])
audio = root / "native/avos/Source/stream_audio.c"
player = root / "Video/src/main/java/com/archos/mediacenter/video/player/Player.java"
service = root / "Video/src/main/java/com/archos/mediacenter/video/player/PlayerService.java"
activity = root / "Video/src/main/java/com/archos/mediacenter/video/player/PlayerActivity.java"

s = audio.read_text()
if '#include "avos_mp.h"' not in s:
    s = s.replace('#include "audio_interface.h"\n', '#include "audio_interface.h"\n#include "avos_mp.h"\n#include "avos_mp_priv.h"\n', 1)

anchor = 'static int pcm_channel_cap = 0;\n'
helper = r'''
static int nova_rebuffer_active = 0;
static int nova_rebuffer_saved_video_paused = 0;

static void nova_rebuffer_event(STREAM *s, int info)
{
    avos_mp_t *mp = (avos_mp_t *)stream_get_user_ctx(s);
    if (mp) avos_mp_sendevent(mp, MEDIA_INFO, info, 0);
}

static int nova_rebuffer_ready(STREAM *s)
{
    STREAM_PARSER_STATS st;
    STREAM_PARSER_STATS *p = s->parser && s->parser->get_stats ? s->parser->get_stats(s, &st) : NULL;
    if (!p) return 0;
    if (s->audio_parse_end || s->video_parse_end) return 1;
    if (p->audio_chunks <= 0 && s->audio->valid) return 0;
    if (p->video_chunks <= 0 && s->video->valid) return 0;
    if (p->atime_parsed >= 2000 && (!s->video->valid || p->vtime_parsed >= 2000)) return 1;
    return p->buffer_used >= 16 * 1024 * 1024;
}

static void nova_rebuffer_enter(STREAM *s)
{
    if (nova_rebuffer_active || s->paused || stream_audio_paused) return;
    nova_rebuffer_active = 1;
    nova_rebuffer_saved_video_paused = stream_video_paused;
    stream_video_paused = 1;
    if (s->audio_ctx && s->audio_sink_open) audio_interface_pause(s->audio_ctx);
    stream_audio_mute(s);
    serprintf("NOVA_REBUFFER_START audio=%d video=%d\n", s->audio_time, s->video_time);
    nova_rebuffer_event(s, MEDIA_INFO_BUFFERING_START);
}

static void nova_rebuffer_leave(STREAM *s)
{
    if (!nova_rebuffer_active) return;
    stream_sync_anchor_reset(s);
    stream_sync_restart_after_pause(s);
    if (s->audio_ctx && s->audio_sink_open) audio_interface_unpause(s->audio_ctx);
    stream_video_paused = nova_rebuffer_saved_video_paused;
    if (s->speed == STREAM_SPEED_NORMAL) stream_audio_unmute(s);
    nova_rebuffer_active = 0;
    serprintf("NOVA_REBUFFER_END audio=%d video=%d parsed=%d\n",
        s->audio_time, s->video_time, s->time_parsed);
    nova_rebuffer_event(s, MEDIA_INFO_BUFFERING_END);
}

'''
if "nova_rebuffer_enter" not in s:
    if anchor not in s:
        raise SystemExit("audio helper anchor not found")
    s = s.replace(anchor, anchor + helper, 1)

needle = '''		int starve_start_ms = atime();
		int starve_last_log_ms = starve_start_ms;
		while( !pcm_output_ready && !ac3_output_ready && !s->audio_atempo_draining && s->audio_buffer_size <= 0 && !_abort( s ) ){
'''
replacement = '''		int starve_start_ms = atime();
		int starve_last_log_ms = starve_start_ms;
		while( !pcm_output_ready && !ac3_output_ready && !s->audio_atempo_draining && s->audio_buffer_size <= 0 && !_abort( s ) ){
			if (!nova_rebuffer_active && !s->audio_parse_end && atime() - starve_start_ms >= 250)
				nova_rebuffer_enter(s);
			if (nova_rebuffer_active) {
				if (s->paused || stream_audio_paused) {
					nova_rebuffer_active = 0;
					stream_video_paused = nova_rebuffer_saved_video_paused;
				} else if (nova_rebuffer_ready(s)) {
					nova_rebuffer_leave(s);
				}
			}
'''
if "atime() - starve_start_ms >= 250" not in s:
    if needle not in s:
        raise SystemExit("starvation loop anchor not found")
    s = s.replace(needle, replacement, 1)

# Ensure rebuffer is released when audio data arrives even if thresholds were crossed between polls.
needle2 = '''			if( cdata.valid ) {
'''
repl2 = '''			if (nova_rebuffer_active && nova_rebuffer_ready(s))
				nova_rebuffer_leave(s);

			if( cdata.valid ) {
'''
if repl2 not in s:
    if needle2 not in s:
        raise SystemExit("cdata anchor not found")
    s = s.replace(needle2, repl2, 1)

audio.write_text(s)

s = player.read_text()
old = '''        case IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_APPLIED:
        case IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_FAILED:
            if (mPlayerListener != null) {
                mPlayerListener.onSubtitleTrackSelectionCompleted(extra,
                        what == IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_APPLIED);
            }
            return true;
        default:
'''
new = '''        case IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_APPLIED:
        case IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_FAILED:
            if (mPlayerListener != null) {
                mPlayerListener.onSubtitleTrackSelectionCompleted(extra,
                        what == IMediaPlayer.MEDIA_INFO_SUBTITLE_TRACK_APPLIED);
            }
            return true;
        case IMediaPlayer.MEDIA_INFO_BUFFERING_START:
            if (mPlayerListener != null) mPlayerListener.onBufferingStart();
            return true;
        case IMediaPlayer.MEDIA_INFO_BUFFERING_END:
            if (mPlayerListener != null) mPlayerListener.onBufferingEnd();
            return true;
        default:
'''
if "onBufferingStart();" not in s:
    if old not in s: raise SystemExit("Player onInfo anchor not found")
    s = s.replace(old,new,1)
listener_anchor='''        void onBufferingUpdate(int percent);
        void onSubtitle(Subtitle subtitle);
'''
listener_new='''        void onBufferingUpdate(int percent);
        default void onBufferingStart() {}
        default void onBufferingEnd() {}
        void onSubtitle(Subtitle subtitle);
'''
if "default void onBufferingStart()" not in s:
    if listener_anchor not in s: raise SystemExit("Player Listener anchor not found")
    s=s.replace(listener_anchor,listener_new,1)
player.write_text(s)

s = service.read_text()
anchor = '''    @Override
    public void onBufferingUpdate(int percent) {
        if(mPlayerFrontend!=null) {
            mPlayerFrontend.onBufferingUpdate(percent);
        }
    }
'''
extra = anchor + '''
    @Override
    public void onBufferingStart() {
        if (mPlayerFrontend != null) mPlayerFrontend.onBufferingStart();
    }

    @Override
    public void onBufferingEnd() {
        if (mPlayerFrontend != null) mPlayerFrontend.onBufferingEnd();
    }
'''
if "public void onBufferingStart()" not in s:
    if anchor not in s: raise SystemExit("PlayerService anchor not found")
    s=s.replace(anchor,extra,1)
service.write_text(s)

s = activity.read_text()
anchor = '''        @SuppressLint("SetTextI18n")
        public void onBufferingUpdate(int percent) {
            if (!mPlayer.isInPlaybackState()) {
                mBufferView.setText(" "+percent+"%");
            }
        }
'''
extra = anchor + '''
        @Override
        public void onBufferingStart() {
            mHandler.removeMessages(MSG_PROGRESS_VISIBLE);
            if (mBufferView != null) mBufferView.setText("");
            if (mProgressView != null) mProgressView.setVisibility(View.VISIBLE);
            Log.i("NovaRebuffer", "BUFFERING_START");
        }

        @Override
        public void onBufferingEnd() {
            mHandler.removeMessages(MSG_PROGRESS_VISIBLE);
            if (mProgressView != null) mProgressView.setVisibility(View.GONE);
            if (mBufferView != null) mBufferView.setText("");
            Log.i("NovaRebuffer", "BUFFERING_END");
        }
'''
if 'Log.i("NovaRebuffer", "BUFFERING_START")' not in s:
    if anchor not in s: raise SystemExit("PlayerActivity buffering anchor not found")
    s=s.replace(anchor,extra,1)
activity.write_text(s)

print("Applied AVOS native rebuffer state machine + UI buffering events")
