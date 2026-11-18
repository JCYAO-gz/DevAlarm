from __future__ import annotations

import sys
import unittest
from unittest import mock

from devalarm import autostart


class LaunchCommandTests(unittest.TestCase):
    def test_frozen_uses_executable_path(self) -> None:
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", r"C:\Apps\DevAlarm V1.1.exe"),
        ):
            self.assertEqual(
                autostart.launch_command(), '"C:\\Apps\\DevAlarm V1.1.exe"'
            )

    def test_source_run_points_to_main_py(self) -> None:
        command = autostart.launch_command()
        self.assertIn("main.py", command)
        self.assertTrue(command.startswith('"'))
        # 解释器与脚本路径各带一组引号，路径含空格也能正常解析
        self.assertEqual(command.count('"'), 4)

    def test_non_windows_is_safe(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(autostart.is_enabled())
            autostart.set_enabled(True)
            autostart.set_enabled(False)


if __name__ == "__main__":
    unittest.main()
