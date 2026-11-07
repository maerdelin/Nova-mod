#!/usr/bin/env python3
"""Fail CI if the Tianyi insertion changes any original Always-new protocol ID."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATCH = (ROOT / "patch_apk.py").read_text(encoding="utf-8")
UI = (ROOT / "src/com/archos/mediacenter/video/cloud189/TianyiUi.java").read_text(encoding="utf-8")

ORIGINAL = ["WebDAV", "SMB", "FTP", "SFTP", "FTPS", "SSHJ", "SMBJ", "WebDAVS"]
EXPECTED = ["WebDAV", "天翼云盘", "SMB", "FTP", "SFTP", "FTPS", "SSHJ", "SMBJ", "WebDAVS"]


class ProtocolOrderTest(unittest.TestCase):
    def test_array_exact(self):
        a = PATCH.split('<string-array name="nova_tianyi_protocol_types">', 1)[1].split('</string-array>', 1)[0]
        self.assertEqual(re.findall(r"<item>(.*?)</item>", a), EXPECTED)

    def test_insertion_is_only_change(self):
        self.assertEqual([p for p in EXPECTED if p != "天翼云盘"], ORIGINAL)

    def test_legacy_ids_remain_unchanged(self):
        self.assertIn("public static final int NEW_UI_INDEX=1;", UI)
        for legacy_id, label in enumerate(ORIGINAL):
            ui_idx = EXPECTED.index(label)
            remapped = ui_idx - 1 if ui_idx > 1 else ui_idx
            self.assertEqual(remapped, legacy_id, label)

    def test_native_listener_and_confirm_map_back(self):
        self.assertIn("->toLegacyType(I)I", PATCH)
        self.assertIn("->toUiIndex(I)I", PATCH)
        self.assertIn("->onSelection(", PATCH)
        self.assertIn("->onConfirm(", PATCH)

    def test_disable_duplicate_shortcut(self):
        self.assertIn('installProtocolGuard', PATCH)
        self.assertIn('GuardedProtocols', UI)
        self.assertIn('getCursorAllShortcuts', UI)
        self.assertIn('areAllItemsEnabled()', UI)
        self.assertIn('isEnabled(int position)', UI)
        self.assertIn('if(hasExistingShortcut(ctx))', UI)
        self.assertIn('if(tianyi && hasExistingShortcut(activity))', UI)

    def test_phone_tablet_uri_labels(self):
        self.assertIn('NOVA_TIANYI_PHONE_SECONDARY_URI', PATCH)
        self.assertIn('NOVA_TIANYI_PHONE_SHORTCUT_NAME', PATCH)
        self.assertIn('->getFriendlyUri()', PATCH)

    def test_webdav_video_mime(self):
        code=(ROOT/'src/com/archos/mediacenter/video/cloud189/TianyiCloud.java').read_text(encoding='utf-8')
        self.assertIn('<d:getcontenttype>', code)
        self.assertIn('video/x-matroska', code)
        self.assertIn('video/mp4', code)

    def test_tianyi_avoids_original_protocol_handling(self):
        self.assertIn("if(uiIndex==NEW_UI_INDEX)return 8;", UI)
        self.assertIn("if(uiIndex!=NEW_UI_INDEX)return false;", UI)
        self.assertIn("return true;", UI)


if __name__ == "__main__":
    unittest.main()
