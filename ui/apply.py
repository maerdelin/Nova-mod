#!/usr/bin/env python3
"""Nova V7.11 Android-TV UI overlay on the pinned, unmodified upstream source.

Edits only front-end Java/XML.  Refuses unknown upstream baselines.  This is a
source-level adaptation of the user-approved V7.11 UI, NOT an APK byte patch.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

# SHA-1 Git blob IDs for the pinned aos-Video revision.
BLOBS = {
    'src/main/java/com/archos/mediacenter/video/leanback/adapter/object/Box.java': 'fffbee1e25f726963214caa62db7c085b9067400',
    'src/main/java/com/archos/mediacenter/video/leanback/filebrowsing/ListingFragment.java': 'a40392614bd4110a33fef60c7ebfb5bce31cf478',
    'res/layout/lb_my_title_view.xml': 'fc8c39e6881143a2e7ad3a6312daff4acd2502fe',
    'src/main/java/com/archos/mediacenter/video/leanback/adapter/GenericNetworkShortcutMapper.java': '10fe2f3b44ecda2f5723e95fec7df26333bce19b',
    'src/main/java/com/archos/mediacenter/video/leanback/network/NetworkRootFragment.java': 'fb81e7b91bda5e3bdebb285db69c316bb15d3c09',
    'src/main/java/com/archos/mediacenter/video/leanback/MainFragment.java': '0174070af1b1856fbcb0edfee7086c349f1454a4',
    'src/main/java/com/archos/mediacenter/video/leanback/network/NetworkServerCredentialsDialog.java': '06d544e1f35ecfaeb37f396d3ef5344fe9c6498f',
    'res/values/arrays.xml': 'e3f0e5f4c10e4bf0aeca3d37fe946f5ee99dde7e',
    'res/values-zh-rCN/strings.xml': '478624cf4c9dd3e9ee5f10dce0c08527fb9d2904',
    'res/layout/network_credential_layout.xml': '437abf42bee78671a7fd14ff85be805cf62e8bcb',
}


def replace_one(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise ValueError(f'{label}: expected one anchor; found {count}: {old[:100]!r}')
    return src.replace(old, new, 1)


def process(path: str, src: str) -> str:
    if path.endswith('adapter/object/Box.java'):
        return replace_one(src, '        NETWORK,\n', '        NETWORK,\n        PREFERENCES, // Nova single-row preferences card\n', path)

    if path.endswith('filebrowsing/ListingFragment.java'):
        return replace_one(src,
            '                } else if (item instanceof Video) {\n                    openDetailsActivity((Video) item, itemViewHolder);\n',
            '                } else if (item instanceof Video) {\n'
            '                    // Play directly from directory, bypass details page.\n'
            '                    PlayUtils.startVideo(getActivity(), (Video) item,\n'
            '                            com.archos.mediacenter.video.player.PlayerActivity.RESUME_NO,\n'
            '                            false, -1, null, -1L);\n', path)

    if path == 'res/layout/lb_my_title_view.xml':
        return replace_one(src,
            '        android:layout_alignTop="@id/title_orb"\n'
            '        android:layout_alignBottom="@id/title_orb"\n',
            '        android:layout_alignTop="@id/title_orb"\n'
            '        android:translationY="-5.2dp"\n', path)

    if path.endswith('adapter/GenericNetworkShortcutMapper.java'):
        return replace_one(src,
            '        String name = c.getString(mNameColumn);\n'
            '        String friendlyUri = c.getString(mFriendlyUriColumn);\n'
            '        if (friendlyUri == null)\n'
            '            return new GenericNetworkShortcut(id, path, name, path);\n'
            '        else\n'
            '            return new GenericNetworkShortcut(id, path, name, friendlyUri);',
            '        // Display endpoint-relative full path; never rewrite actual saved URI.\n'
            '        android.net.Uri parsed = android.net.Uri.parse(path);\n'
            '        String decodedPath = parsed.getPath();\n'
            '        String name = c.getString(mNameColumn);\n'
            '        if (decodedPath != null && !decodedPath.isEmpty()) {\n'
            '            int secondSlash = decodedPath.indexOf(\'/\', 1);\n'
            '            if (secondSlash >= 0 && secondSlash + 1 < decodedPath.length()) {\n'
            '                name = decodedPath.substring(secondSlash + 1);\n'
            '            } else if (decodedPath.startsWith("/") && decodedPath.length() > 1) {\n'
            '                name = decodedPath.substring(1);\n'
            '            }\n'
            '        }\n'
            '        return new GenericNetworkShortcut(id, path, name, path);', path)

    if path.endswith('network/NetworkRootFragment.java'):
        src = replace_one(src,
            '            if (item instanceof GenericNetworkShortcut) { // network shortcuts are for now only *ftp*\n'
            '                if (log.isDebugEnabled()) log.debug("onItemClicked: GenericNetworkShortcut");\n'
            '                Intent intent = new Intent(getActivity(), NetworkShortcutDetailsActivity.class);\n'
            '                intent.putExtra(NetworkShortcutDetailsFragment.EXTRA_SHORTCUT, (Serializable) item);\n'
            '                detailsLauncher.launch(intent, ActivityOptionsCompat.makeSceneTransitionAnimation(getActivity(),\n'
            '                        ((NetworkShortcutPresenter.NetworkShortcutViewHolder) itemViewHolder).getImageView(),\n'
            '                        NetworkShortcutDetailsFragment.SHARED_ELEMENT_NAME));\n'
            '            }',
            '            if (item instanceof GenericNetworkShortcut) {\n'
            '                // Open the saved folder directly.\n'
            '                GenericNetworkShortcut shortcut = (GenericNetworkShortcut) item;\n'
            '                Uri uri = shortcut.getUri();\n'
            '                Intent intent = new Intent(getActivity(), ListingActivity.getActivityForUri(uri));\n'
            '                intent.putExtra(ListingActivity.EXTRA_ROOT_URI, uri);\n'
            '                intent.putExtra(ListingActivity.EXTRA_ROOT_NAME, shortcut.getName());\n'
            '                browsingLauncher.launch(intent);\n'
            '            }', path)
        src = replace_one(src,
            '                    mShortcutsLoaderTask = new ShortcutsLoaderTask();\n'
            '                    mShortcutsLoaderTask.execute();\n'
            '                }\n            });\n\n    // temp debug flag',
            '                    mShortcutsLoaderTask = new ShortcutsLoaderTask();\n'
            '                    mShortcutsLoaderTask.execute();\n'
            '                    // Shortcuts saved from a nested network directory also need refresh.\n'
            '                    mNetworkShortcutsLoaderTask = new NetworkShortcutsLoaderTask();\n'
            '                    mNetworkShortcutsLoaderTask.execute();\n'
            '                }\n            });\n\n    // temp debug flag', path)
        src = replace_one(src,
            '                                    mNetworkShortcutsAdapter.clear();\n'
            '                                    mNetworkShortcutsAdapter.add(new NetworkBrowse(getString(R.string.browse_net_server)));\n'
            '                                    if (cursor.getCount() > 0) {\n'
            '                                        cursor.moveToFirst();\n'
            '                                        do {\n'
            '                                            GenericNetworkShortcutMapper shortcutMapper = new GenericNetworkShortcutMapper();\n'
            '                                            shortcutMapper.bindColumns(cursor);\n'
            '                                            mNetworkShortcutsAdapter.add(shortcutMapper.bind(cursor));\n'
            '                                        } while (cursor.moveToNext());\n'
            '                                    }',
            '                                    mNetworkShortcutsAdapter.clear();\n'
            '                                    if (cursor.getCount() > 0) {\n'
            '                                        cursor.moveToFirst();\n'
            '                                        do {\n'
            '                                            GenericNetworkShortcutMapper shortcutMapper = new GenericNetworkShortcutMapper();\n'
            '                                            shortcutMapper.bindColumns(cursor);\n'
            '                                            mNetworkShortcutsAdapter.add(shortcutMapper.bind(cursor));\n'
            '                                        } while (cursor.moveToNext());\n'
            '                                    }\n'
            '                                    // Saved folders first; add-network-address card last.\n'
            '                                    mNetworkShortcutsAdapter.add(new NetworkBrowse(getString(R.string.browse_net_server)));\n'
            '                                    if (getView() != null) {\n'
            '                                        getView().post(() -> setSelectedPosition(3, false,\n'
            '                                                new ListRowPresenter.SelectItemViewHolderTask(0)));\n'
            '                                    }', path)
        return src

    if path.endswith('network/NetworkServerCredentialsDialog.java'):
        src = replace_one(src, 'if (UriUtils.requiresDomain(position)) v.findViewById(R.id.domain).setVisibility(View.VISIBLE);',
            'if (position == 1 || position == 6) v.findViewById(R.id.domain).setVisibility(View.VISIBLE);', path)
        src = replace_one(src, 'typeSp.setSelection(type);', 'typeSp.setSelection(0); // default: WebDAV', path)
        src = replace_one(src, 'final int type = typeSp.getSelectedItemPosition();',
            'final int type = (new int[] {6, 4, 0, 1, 2, 3, 5, 7})[typeSp.getSelectedItemPosition()];', path)
        return src

    if path == 'res/values/arrays.xml':
        src = replace_one(src,
            '    <string-array name="protocol_types">\n'
            '        <item>FTP</item>\n        <item>SFTP</item>\n'
            '        <item>FTPS</item>\n        <item>SSHJ</item>\n'
            '        <item>SMB</item>\n        <item>SMBJ</item>\n'
            '        <item>WebDAV</item>\n        <item>WebDAVS</item>\n'
            '    </string-array>',
            '    <string-array name="protocol_types">\n'
            '        <item>WebDAV</item>\n        <item>SMB</item>\n'
            '        <item>FTP</item>\n        <item>SFTP</item>\n'
            '        <item>FTPS</item>\n        <item>SSHJ</item>\n'
            '        <item>SMBJ</item>\n        <item>WebDAVS</item>\n'
            '    </string-array>', path)
        return src

    if path == 'res/values-zh-rCN/strings.xml':
        return replace_one(src, '<string name="browse_net_server">浏览网络共享</string>',
            '<string name="browse_net_server">添加网络地址</string>', path)

    if path == 'res/layout/network_credential_layout.xml':
        return replace_one(src, '            android:layout_width="105dip"',
            '            android:layout_width="160dip"', path)

    if path.endswith('/MainFragment.java'):
        src = replace_one(src, '        setHeadersState(HEADERS_ENABLED);',
            '        setHeadersState(HEADERS_HIDDEN); // Show rows from initial layout; avoid focus-triggered headers transition on 14TV', path)
        src = replace_one(src, '        setHeadersTransitionOnBackEnabled(true);',
            '        setHeadersTransitionOnBackEnabled(false); // Keep hidden 0dp header from reopening', path)
        search_start = '        setOnSearchClickedListener(new View.OnClickListener() {'
        search_end = '        if (mActivity != null) setOnItemViewClickedListener'
        pos = src.index(search_start, src.index('    private void setupEventListeners() {'))
        end = src.index(search_end, pos)
        assert 'VideoSearchActivity' in src[pos:end] and src[pos:end].endswith('        });\n')
        src = src[:pos] + (
            '        // Home search icon hidden; retain branding and click handlers.\n'
            '        androidx.leanback.widget.TitleView titleView =\n'
            '                (androidx.leanback.widget.TitleView) getTitleView();\n'
            '        if (titleView.getSearchAffordanceView() != null)\n'
            '            titleView.getSearchAffordanceView().setVisibility(View.GONE);\n') + src[end:]
        # Retain one row and no other categories, including when scanners finish.
        for name, signature in [
            ('updateWatchingUpNextRow', 'Cursor cursor'),
            ('updateLastAddedRow', 'Cursor cursor'),
            ('updateLastPlayedRow', 'Cursor cursor'),
            ('updateMoviesRow', 'Cursor cursor, Boolean updateBox'),
            ('updateTvShowsRow', 'Cursor cursor, Boolean updateBox'),
            ('updateAnimesRow', 'Cursor cursor, Boolean updateBox'),
        ]:
            anchor = f'    private void {name}({signature}) {{\n'
            src = replace_one(src, anchor, anchor +
                '        if (true) return; // V7.11: only the Files four-card row is visible\n', path)
        prefs_row = '        mRowsAdapter.add(new IconListRow(ROW_ID_PREFERENCES,\n'
        # Keep the preference Icon objects for other internal features, but not their own row.
        src = replace_one(src,
            prefs_row + '                new HeaderItem(getString(R.string.preferences)),\n'
            '                mPreferencesRowAdapter));',
            '        // Standalone preferences row hidden; settings stays accessible via fourth card.', path)
        # First initialization AND USB hotplug update both rebuild the same adapter.
        playlist = '        mFileBrowsingRowAdapter.add(new Box(Box.ID.VIDEOS_BY_LISTS, getString(R.string.video_lists), R.drawable.filetype_new_playlist));'
        if src.count(playlist) != 2:
            raise ValueError('Expected exactly two playlist appends in MainFragment')
        src = src.replace(playlist,
            playlist + '\n        mFileBrowsingRowAdapter.add(new Box(Box.ID.PREFERENCES, getString(R.string.preferences), R.drawable.ic_cog_outline));')
        src = replace_one(src, '        setAdapter(mRowsAdapter);\n',
            '        setAdapter(mRowsAdapter);\n'
            '        // Default focus on Network, not on invisible Leanback headers.\n'
            '        setSelectedPosition(0, false, new ListRowPresenter.SelectItemViewHolderTask(0));\n', path)
        src = replace_one(src, '                    case NETWORK ->\n'
            '                            vActivity.startActivity(new Intent(vActivity, NetworkRootActivity.class));',
            '                    case NETWORK ->\n'
            '                            vActivity.startActivity(new Intent(vActivity, NetworkRootActivity.class));\n'
            '                    case PREFERENCES -> {\n'
            '                        if (vActivity instanceof MainActivityLeanback)\n'
            '                            ((MainActivityLeanback)vActivity).startPreferencesActivity();\n'
            '                    }', path)
        return src

    raise ValueError(f'Unexpected upstream path: {path}')


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def main() -> None:
    cli = argparse.ArgumentParser()
    cli.add_argument('root', type=Path, help='Source root directory: <repo synced workspace>/Video')
    cli.add_argument('--verify-only', action='store_true', help='Only verify upstream SHA and patches')
    a = cli.parse_args()
    root = a.root.resolve()
    updated = {}
    for relative, expected in BLOBS.items():
        src = root / relative
        data = src.read_bytes()
        got = git_blob(data)
        if got != expected:
            raise SystemExit(f'REFUSED: upstream changed {relative}: expected {expected}, got {got}')
        out = process(relative, data.decode('utf-8'))
        if out == data.decode('utf-8'):
            raise SystemExit(f'REFUSED: no UI change applied to {relative}')
        updated[src] = out.encode('utf-8')
    # Validate all files before ANY filesystem change.
    if not a.verify_only:
        override = root / 'res/values/nova_ui_override.xml'
        if override.exists():
            raise SystemExit(f'REFUSED: upstream now contains {override}')
        for file, output in updated.items():
            file.write_bytes(output)
        override.write_text('''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- Keep Leanback HEADERS_ENABLED, but give its sidebar zero width. -->
    <dimen name="lb_browse_headers_width">0dp</dimen>
    <dimen name="lb_browse_rows_margin_start">0dp</dimen>
</resources>
''', encoding='utf-8')
    print(f'PASS: verified {len(updated)} pinned upstream files; V7.11 UI overlay '+
          ('ready' if a.verify_only else 'applied'))

if __name__ == '__main__':
    main()
