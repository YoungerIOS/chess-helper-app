import unittest
from unittest.mock import patch

from app.main import check_screen_recording_permission


class ScreenRecordingPermissionTests(unittest.TestCase):
    @patch("Quartz.CGRequestScreenCaptureAccess")
    @patch("Quartz.CGPreflightScreenCaptureAccess", return_value=True)
    def test_authorized_screen_capture_does_not_request_again(self, preflight, request):
        with patch("app.main.sys.platform", "darwin"):
            check_screen_recording_permission()

        preflight.assert_called_once_with()
        request.assert_not_called()

    @patch("Quartz.CGRequestScreenCaptureAccess", return_value=False)
    @patch("Quartz.CGPreflightScreenCaptureAccess", return_value=False)
    def test_missing_permission_uses_core_graphics_request(self, preflight, request):
        with patch("app.main.sys.platform", "darwin"):
            check_screen_recording_permission()

        preflight.assert_called_once_with()
        request.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
