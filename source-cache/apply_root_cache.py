#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

field_anchor = "private final Object mSessionLock = new Object();\n"
field_insert = """private final Object mSessionLock = new Object();
	private final Object mPlaybackCacheLock = new Object();
	private PlaybackFileCache mPlaybackCache;
"""
if "mPlaybackCache;" not in s:
    if field_anchor not in s:
        raise SystemExit("StreamOverHttp field anchor missing")
    s = s.replace(field_anchor, field_insert, 1)

helper_anchor = "\tprivate boolean isResourcePoster(Uri posterLocalUri) {\n"
helpers = r'''
	private boolean shouldUsePersistentPlaybackCache(Uri target, FileEditor editor, boolean primaryMedia) {
		if (!primaryMedia || mReadMode != ReadMode.PLAYBACK || target == null || editor == null)
			return false;
		String scheme = target.getScheme();
		return ("webdav".equalsIgnoreCase(scheme) || "webdavs".equalsIgnoreCase(scheme))
				&& length > 0;
	}

	private PlaybackFileCache playbackCache(Uri target) throws IOException {
		synchronized (mPlaybackCacheLock) {
			if (mClosed) throw new IOException("StreamOverHttp closed");
			if (mPlaybackCache == null) {
				final Uri sourceUri = target;
				final long sourceLength = length;
				mPlaybackCache = PlaybackFileCache.create(sourceLength, offset -> {
					FileEditor sourceEditor = getFileEditor(sourceUri);
					ReadOptions options = new ReadOptions(ReadOptions.Purpose.PLAYBACK, -1, false);
					return sourceEditor.getInputStream(offset, options);
				});
			}
			return mPlaybackCache;
		}
	}

	private InputStream openPlaybackInput(Uri target, FileEditor editor) throws Exception {
		if (!shouldUsePersistentPlaybackCache(target, editor, supersedableMediaRequest))
			return editor.getInputStream(requestedStart, readOptions());
		long end = partialResponse ? requestedEnd : length - 1;
		long span = end - requestedStart + 1;
		boolean openEnded = !partialResponse || requestedEnd >= length - 1;
		boolean prefill = openEnded || span >= 16L * 1024 * 1024;
		return playbackCache(target).open(requestedStart, end, prefill);
	}

'''
if "shouldUsePersistentPlaybackCache(" not in s:
    if helper_anchor not in s:
        raise SystemExit("StreamOverHttp helper anchor missing")
    s = s.replace(helper_anchor, helpers + helper_anchor, 1)

old_open = "publishInput(editor.getInputStream(requestedStart, readOptions()));"
if "publishInput(openPlaybackInput(target, editor));" not in s:
    if s.count(old_open) < 1:
        raise SystemExit("primary editor open anchor missing")
    s = s.replace(old_open, "publishInput(openPlaybackInput(target, editor));", 1)

# The second open after learning HTTP length must use the same persistent cache path too.
if s.count(old_open):
    s = s.replace(old_open, "publishInput(openPlaybackInput(target, editor));", 1)

close_anchor = """		try { serverSocket.close(); } catch (IOException ignored) { }
		for (HttpSession session : sessions) session.cancel();
	}
"""
close_new = """		try { serverSocket.close(); } catch (IOException ignored) { }
		for (HttpSession session : sessions) session.cancel();
		PlaybackFileCache cache;
		synchronized (mPlaybackCacheLock) {
			cache = mPlaybackCache;
			mPlaybackCache = null;
		}
		if (cache != null) cache.close();
	}
"""
if "if (cache != null) cache.close();" not in s:
    if close_anchor not in s:
        raise SystemExit("StreamOverHttp close anchor missing")
    s = s.replace(close_anchor, close_new, 1)

p.write_text(s)
print("Applied persistent playback cache to", p)
