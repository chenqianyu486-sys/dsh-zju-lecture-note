#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重定向安全（安全审查 P0-3 / 7.2）。

两条下载链路都可能被服务端 302 到别处：
* 课堂 API 只允许同 origin 跳转（scheme + host + port 全等）；
* 投影截图允许浙大媒体主机跳转，但跨 origin 必须剥离
  Cookie / Authorization / Proxy-Authorization，且非浙大域、IP 字面量与
  私网主机一律不跟随（返回 3xx 并写入 diagnostics）。

这里既直接测 handler 的 origin 判定，也用本地 HTTP server 验证
「跨端口目标没有被连接、Cookie 没有出现在目标请求头里」。
"""

import http.server
import threading
import unittest
import urllib.error
import urllib.request

from zju_lecture import client


class TestOriginComparison(unittest.TestCase):

    def test_origin_includes_scheme_host_and_port(self):
        self.assertEqual(
            client._origin("https://classroom.zju.edu.cn/a"),
            ("https", "classroom.zju.edu.cn", 443),
        )
        self.assertNotEqual(
            client._origin("https://classroom.zju.edu.cn/a"),
            client._origin("https://classroom.zju.edu.cn:8443/a"),
        )
        self.assertNotEqual(
            client._origin("https://classroom.zju.edu.cn/a"),
            client._origin("http://classroom.zju.edu.cn/a"),
        )

    def test_private_and_ip_targets_are_forbidden(self):
        for host in (
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.9",
            "169.254.1.1",
            "192.168.1.1",
            "::1",
            "localhost",
            "foo.localhost",
            "",
        ):
            with self.subTest(host=host):
                self.assertTrue(client._is_forbidden_redirect_host(host))
        self.assertFalse(client._is_forbidden_redirect_host("media.cmc.zju.edu.cn"))


class TestSameOriginRedirectHandler(unittest.TestCase):

    def _request(self):
        return urllib.request.Request(
            "https://classroom.zju.edu.cn/livingroom",
            headers={"Cookie": "sid=1", "Authorization": "Bearer tok"},
        )

    def test_same_origin_is_allowed(self):
        follow = client._SameHostRedirectHandler().redirect_request(
            self._request(), None, 302, "Found", {}, "https://classroom.zju.edu.cn/other"
        )
        self.assertIsNotNone(follow)

    def test_same_host_different_port_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            client._SameHostRedirectHandler().redirect_request(
                self._request(),
                None,
                302,
                "Found",
                {},
                "https://classroom.zju.edu.cn:8443/other",
            )

    def test_https_to_http_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            client._SameHostRedirectHandler().redirect_request(
                self._request(), None, 302, "Found", {}, "http://classroom.zju.edu.cn/x"
            )
        self.assertIn("降级", str(caught.exception))

    def test_cross_host_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            client._SameHostRedirectHandler().redirect_request(
                self._request(), None, 302, "Found", {}, "https://evil.example/steal"
            )


class TestStripAuthRedirectHandler(unittest.TestCase):

    def _request(self, url="https://media.cmc.zju.edu.cn/1.jpg"):
        return urllib.request.Request(
            url,
            headers={
                "Cookie": "sid=1",
                "Authorization": "Bearer tok",
                "Proxy-Authorization": "Basic cHJveHk=",
            },
        )

    def _headers(self, request):
        return {
            name: request.get_header(name)
            for name in ("Cookie", "Authorization", "Proxy-Authorization")
        }

    def test_same_origin_keeps_credentials(self):
        diagnostics = []
        follow = client._StripAuthOnCrossHostRedirectHandler(diagnostics).redirect_request(
            self._request(),
            None,
            302,
            "Found",
            {},
            "https://media.cmc.zju.edu.cn/2.jpg",
        )
        self.assertIsNotNone(follow)
        self.assertEqual(diagnostics, [])
        headers = self._headers(follow)
        self.assertEqual(headers["Cookie"], "sid=1")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        # urllib keeps Proxy-Authorization in unredirected_hdrs, so it is not
        # forwarded on any redirect; the removal above is defence in depth.
        self.assertIsNone(headers["Proxy-Authorization"])

    def test_different_port_strips_credentials(self):
        follow = client._StripAuthOnCrossHostRedirectHandler().redirect_request(
            self._request(),
            None,
            302,
            "Found",
            {},
            "https://media.cmc.zju.edu.cn:8443/2.jpg",
        )
        self.assertIsNotNone(follow)
        self.assertEqual(
            self._headers(follow),
            {"Cookie": None, "Authorization": None, "Proxy-Authorization": None},
        )

    def test_cross_zju_host_strips_credentials(self):
        follow = client._StripAuthOnCrossHostRedirectHandler().redirect_request(
            self._request(),
            None,
            302,
            "Found",
            {},
            "https://media2.cmc.zju.edu.cn/2.jpg",
        )
        self.assertIsNotNone(follow)
        self.assertEqual(
            self._headers(follow),
            {"Cookie": None, "Authorization": None, "Proxy-Authorization": None},
        )

    def test_non_zju_redirect_is_not_followed(self):
        diagnostics = []
        follow = client._StripAuthOnCrossHostRedirectHandler(diagnostics).redirect_request(
            self._request(), None, 302, "Found", {}, "https://evil.example/2.jpg"
        )
        self.assertIsNone(follow)
        self.assertTrue(any("非浙大域" in item for item in diagnostics), diagnostics)

    def test_private_ip_and_localhost_are_not_followed(self):
        for target in (
            "https://10.0.0.5/2.jpg",
            "https://169.254.169.254/latest/meta-data",
            "https://127.0.0.1/2.jpg",
            "https://localhost/2.jpg",
            "https://[::1]/2.jpg",
        ):
            with self.subTest(target=target):
                diagnostics = []
                follow = client._StripAuthOnCrossHostRedirectHandler(
                    diagnostics
                ).redirect_request(self._request(), None, 302, "Found", {}, target)
                self.assertIsNone(follow)
                self.assertTrue(diagnostics, target)

    def test_https_downgrade_and_userinfo_are_not_followed(self):
        for target, marker in (
            ("http://media.cmc.zju.edu.cn/2.jpg", "降级"),
            ("https://user:pass@media.cmc.zju.edu.cn/2.jpg", "凭据"),
        ):
            with self.subTest(target=target):
                diagnostics = []
                follow = client._StripAuthOnCrossHostRedirectHandler(
                    diagnostics
                ).redirect_request(self._request(), None, 302, "Found", {}, target)
                self.assertIsNone(follow)
                self.assertTrue(any(marker in item for item in diagnostics), diagnostics)


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        self.server.seen.append(
            {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}}
        )
        if self.path == "/redirect-same":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/redirect-cross":
            self.send_response(302)
            self.send_header("Location", self.server.cross_target)
            self.end_headers()
        else:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):  # keep unittest output clean
        pass


class TestRedirectsOverTheNetwork(unittest.TestCase):
    def setUp(self):
        self.first = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.first.seen = []
        self.second = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.second.seen = []
        self.first.cross_target = (
            f"http://127.0.0.1:{self.second.server_address[1]}/ok"
        )
        self.threads = []
        for server in (self.first, self.second):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for server in (self.first, self.second):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=5)

    def _url(self, server, path):
        return f"http://127.0.0.1:{server.server_address[1]}{path}"

    def test_cross_port_target_is_never_connected(self):
        diagnostics = []
        with self.assertRaises(urllib.error.HTTPError) as caught:
            client._fetch_bytes(
                self._url(self.first, "/redirect-cross"),
                {"Cookie": "sid=1", "Authorization": "Bearer tok"},
                timeout=5,
                allow_cross_host_redirect=True,
                diagnostics=diagnostics,
            )
        self.assertEqual(caught.exception.code, 302)
        self.assertEqual(self.second.seen, [], "跨端口目标不应被连接")
        self.assertTrue(any("受限主机" in item for item in diagnostics), diagnostics)

    def test_same_origin_ip_redirect_is_blocked_before_second_hop(self):
        # The local test server is an IP literal, so even a same-origin hop is
        # refused by the SSRF rule: the second request must never happen.
        diagnostics = []
        with self.assertRaises(urllib.error.HTTPError):
            client._fetch_bytes(
                self._url(self.first, "/redirect-same"),
                {"Cookie": "sid=1", "Authorization": "Bearer tok"},
                timeout=5,
                allow_cross_host_redirect=True,
                diagnostics=diagnostics,
            )
        self.assertEqual(len(self.first.seen), 1)
        self.assertEqual(self.first.seen[0]["headers"].get("cookie"), "sid=1")
        self.assertTrue(any("受限主机" in item for item in diagnostics), diagnostics)

    def test_strict_handler_refuses_redirect_to_ip_literal(self):
        with self.assertRaises(urllib.error.HTTPError):
            client._fetch_bytes(
                self._url(self.first, "/redirect-same"),
                {"Cookie": "sid=1"},
                timeout=5,
            )
        self.assertEqual(len(self.first.seen), 1, "第二跳不应发生")


if __name__ == "__main__":
    unittest.main(verbosity=2)
