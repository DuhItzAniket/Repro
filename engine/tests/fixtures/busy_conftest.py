"""Takes every sys.monitoring tool ID Repro may use (D05 test data, copied into a snapshot)."""

import sys

for tool in (2, 3, 4, 5):
    sys.monitoring.use_tool_id(tool, "busy")
