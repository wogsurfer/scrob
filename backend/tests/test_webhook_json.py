import unittest

from routers.webhooks import _webhook_json


class WebhookJsonTests(unittest.TestCase):
    def test_plain_json_body(self):
        # Jellyfin and newer Emby send JSON as the whole body.
        self.assertEqual(_webhook_json(b'{"Event": "playback.start"}'), {"Event": "playback.start"})

    def test_multipart_body(self):
        # Older Emby wraps the JSON in multipart/form-data.
        body = (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="data"\r\n\r\n'
            b'{"Event": "playback.stop"}\r\n'
            b"--boundary--\r\n"
        )
        self.assertEqual(_webhook_json(body), {"Event": "playback.stop"})

    def test_garbage(self):
        self.assertIsNone(_webhook_json(b"not json at all"))


if __name__ == "__main__":
    unittest.main()
