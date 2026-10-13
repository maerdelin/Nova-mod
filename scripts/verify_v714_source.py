#!/usr/bin/env python3
"""Fail CI on Leanback 14TV blank-home or startup-focus regressions."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
source = (root / "src/main/java/com/archos/mediacenter/video/leanback/MainFragment.java").read_text()
on_create = source.index("    public void onCreate(Bundle savedInstanceState) {")
on_view = source.index("    public void onViewCreated(View view, Bundle savedInstanceState)")
state = source.index("setHeadersState(HEADERS_DISABLED)", on_create, on_view)
assert on_create < state < on_view, "Headers disabled too late: Rows Fragment can be absent"
assert "setHeadersTransitionOnBackEnabled(false)" in source, "Back may open hidden sidebar"
assert "homeRoot.post(() ->" in source, "Focus request must be deferred"
assert "getRowsSupportFragment()" in source, "Must focus Rows Fragment directly"
assert "rows.setSelectedPosition(0, false," in source, "Network first-card focus missing"
assert "setSelectedPosition(0, false, new ListRowPresenter.SelectItemViewHolderTask(0));" not in source, "Illegal synchronous headers transition"
assert "mFileBrowsingRowAdapter.add(new Box(Box.ID.PREFERENCES" in source, "Fourth card missing"
print("V7.14_SOURCE_GUARD_PASS")
