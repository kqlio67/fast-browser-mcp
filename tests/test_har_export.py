import json
import os
import tempfile
import unittest

from fast_browser.network import (
    NetworkMonitor,
    redact_header_value,
    redact_headers,
    redact_post_data,
    redact_url_params,
)


class TestHarExportAndRedaction(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_har_")
        self.net = NetworkMonitor()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_redact_helpers(self):
        # Header redactions
        self.assertEqual(
            redact_header_value("authorization", "Bearer eyJhbGciOi..."),
            "Bearer [REDACTED]",
        )
        self.assertEqual(
            redact_header_value("Authorization", "Basic YWRtaW46cGFzcw=="),
            "Basic [REDACTED]",
        )
        self.assertEqual(
            redact_header_value("cookie", "sess=123; user=alice"),
            "[REDACTED]",
        )
        self.assertEqual(
            redact_header_value("Set-Cookie", "auth_token=xyz; Path=/"),
            "[REDACTED]",
        )
        self.assertEqual(
            redact_header_value("x-api-key", "secret-key-999"),
            "[REDACTED]",
        )
        self.assertEqual(
            redact_header_value("Content-Type", "application/json"),
            "application/json",
        )

        # Dictionary & list redactions
        hdr_dict = {
            "Authorization": "Bearer 123",
            "Content-Type": "text/html",
        }
        redacted_dict = redact_headers(hdr_dict)
        self.assertEqual(
            redacted_dict["Authorization"], "Bearer [REDACTED]"
        )
        self.assertEqual(redacted_dict["Content-Type"], "text/html")

        # URL query param redactions
        url = "https://example.com/api?user=bob&token=secret123&api_key=456"
        redacted_url = redact_url_params(url)
        self.assertIn("user=bob", redacted_url)
        self.assertIn("token=[REDACTED]", redacted_url)
        self.assertIn("api_key=[REDACTED]", redacted_url)

        # POST data redaction (JSON & Form)
        json_body = json.dumps(
            {"email": "test@example.com", "password": "supersecret", "pin": 1234}
        )
        redacted_json = redact_post_data(json_body)
        self.assertIn("[REDACTED]", redacted_json)
        self.assertNotIn("supersecret", redacted_json)

        form_body = "username=admin&password=secretpassword&remember=true"
        redacted_form = redact_post_data(form_body)
        self.assertIn("password=[REDACTED]", redacted_form)
        self.assertNotIn("secretpassword", redacted_form)

    def test_har_12_structure(self):
        self.net.handle_event(
            "Network.requestWillBeSent",
            {
                "requestId": "req-1",
                "request": {
                    "url": "https://service.local/v1/data?token=tok123",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer tok123",
                        "Cookie": "session_id=abc; role=user",
                        "Content-Type": "application/json",
                    },
                    "postData": json.dumps({"query": "stats", "secret": "s3cr3t"}),
                    "protocol": "HTTP/2.0",
                },
                "type": "Fetch",
                "wallTime": 1700000000.0,
            },
        )
        self.net.handle_event(
            "Network.responseReceived",
            {
                "requestId": "req-1",
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "headers": {
                        "Content-Type": "application/json",
                        "Set-Cookie": "pref=dark; Secure",
                    },
                    "mimeType": "application/json",
                    "protocol": "HTTP/2.0",
                    "encodedDataLength": 256,
                },
            },
        )
        self.net.handle_event(
            "Network.loadingFinished",
            {"requestId": "req-1", "encodedDataLength": 256},
        )

        har = self.net.export_to_har(redact_sensitive_headers=True)

        # Check top-level HAR log
        self.assertIn("log", har)
        log = har["log"]
        self.assertEqual(log["version"], "1.2")
        self.assertEqual(log["creator"]["name"], "fast-browser-mcp")
        self.assertIsInstance(log["entries"], list)
        self.assertEqual(len(log["entries"]), 1)

        entry = log["entries"][0]
        self.assertTrue(entry["startedDateTime"].endswith("Z"))
        self.assertIsInstance(entry["time"], (int, float))

        # Request section
        req = entry["request"]
        self.assertEqual(req["method"], "POST")
        self.assertIn("token=[REDACTED]", req["url"])
        self.assertEqual(req["httpVersion"], "HTTP/2.0")

        auth_h = next(h for h in req["headers"] if h["name"] == "Authorization")
        self.assertEqual(auth_h["value"], "Bearer [REDACTED]")

        cookie_h = next(h for h in req["headers"] if h["name"] == "Cookie")
        self.assertEqual(cookie_h["value"], "[REDACTED]")

        cookie_item = next(
            c for c in req["cookies"] if c["name"] == "session_id"
        )
        self.assertEqual(cookie_item["value"], "[REDACTED]")

        self.assertIsNotNone(req["postData"])
        self.assertIn("[REDACTED]", req["postData"]["text"])

        # Response section
        resp = entry["response"]
        self.assertEqual(resp["status"], 200)
        self.assertEqual(resp["statusText"], "OK")
        self.assertEqual(resp["content"]["mimeType"], "application/json")
        self.assertEqual(resp["content"]["size"], 256)

        set_cookie_h = next(
            h for h in resp["headers"] if h["name"] == "Set-Cookie"
        )
        self.assertEqual(set_cookie_h["value"], "[REDACTED]")

        # Timings
        timings = entry["timings"]
        self.assertIn("send", timings)
        self.assertIn("wait", timings)
        self.assertIn("receive", timings)

    def test_export_to_file_har_format(self):
        import asyncio

        async def run():
            self.net.handle_event(
                "Network.requestWillBeSent",
                {
                    "requestId": "req-2",
                    "request": {
                        "url": "https://example.org/api",
                        "method": "GET",
                        "headers": {"Accept": "*/*"},
                    },
                    "type": "XHR",
                },
            )
            self.net.handle_event(
                "Network.responseReceived",
                {
                    "requestId": "req-2",
                    "response": {
                        "status": 204,
                        "statusText": "No Content",
                        "headers": {},
                        "mimeType": "text/plain",
                    },
                },
            )

            har_path = os.path.join(self.tmpdir, "output.har")
            await self.net.export_to_file(
                har_path, format="har", redact_sensitive_headers=True
            )

            self.assertTrue(os.path.isfile(har_path))
            with open(har_path, encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["log"]["version"], "1.2")
            self.assertEqual(len(data["log"]["entries"]), 1)
            self.assertEqual(data["log"]["entries"][0]["response"]["status"], 204)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
