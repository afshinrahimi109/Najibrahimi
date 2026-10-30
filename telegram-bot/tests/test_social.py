import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from social import SocialPublishError, publish_facebook_page_post, publish_instagram_image


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class SocialPublishingTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            meta_graph_api_version="v26.0",
            facebook_page_id="123456",
            facebook_page_access_token="page-secret",
            instagram_account_id="17840000000000000",
            instagram_access_token="instagram-secret",
        )

    @patch("social.urllib.request.urlopen")
    def test_facebook_text_post_uses_page_feed_with_bearer_token(self, urlopen):
        urlopen.return_value = FakeResponse({"id": "123456_789"})
        post_id = publish_facebook_page_post(self.config, "سلام Facebook")
        request = urlopen.call_args.args[0]
        self.assertEqual(post_id, "123456_789")
        self.assertIn("/v26.0/123456/feed", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer page-secret")
        self.assertEqual(json.loads(request.data), {"message": "سلام Facebook"})
        self.assertNotIn("page-secret", request.full_url)

    @patch("social.urllib.request.urlopen")
    def test_facebook_image_uses_public_url_and_caption(self, urlopen):
        urlopen.return_value = FakeResponse({"id": "789"})
        post_id = publish_facebook_page_post(
            self.config, "کپشن", image_url="https://cdn.example/image.jpg"
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(post_id, "789")
        self.assertIn("/123456/photos", request.full_url)
        self.assertEqual(
            json.loads(request.data),
            {"url": "https://cdn.example/image.jpg", "caption": "کپشن"},
        )

    @patch("social.time.sleep")
    @patch("social.urllib.request.urlopen")
    def test_instagram_creates_checks_and_publishes_image_container(self, urlopen, _sleep):
        urlopen.side_effect = [
            FakeResponse({"id": "container-456"}),
            FakeResponse({"id": "container-456", "status_code": "FINISHED"}),
            FakeResponse({"id": "published-789"}),
        ]
        media_id = publish_instagram_image(
            self.config, "https://cdn.example/image.jpg", "کپشن Instagram"
        )
        self.assertEqual(media_id, "published-789")
        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertIn("https://graph.instagram.com/v26.0/17840000000000000/media", requests[0].full_url)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer instagram-secret")
        self.assertEqual(json.loads(requests[0].data), {
            "image_url": "https://cdn.example/image.jpg", "caption": "کپشن Instagram"
        })
        self.assertIn("fields=status_code", requests[1].full_url)
        self.assertIn("/media_publish", requests[2].full_url)
        self.assertEqual(json.loads(requests[2].data), {"creation_id": "container-456"})
        self.assertTrue(all("instagram-secret" not in req.full_url for req in requests))

    def test_missing_credentials_and_non_https_media_fail_clearly(self):
        self.config.instagram_access_token = ""
        with self.assertRaisesRegex(SocialPublishError, "INSTAGRAM_ACCESS_TOKEN"):
            publish_instagram_image(self.config, "https://cdn.example/image.jpg", "caption")
        self.config.instagram_access_token = "instagram-secret"
        with self.assertRaisesRegex(SocialPublishError, "HTTPS"):
            publish_instagram_image(self.config, "http://cdn.example/image.jpg", "caption")


if __name__ == "__main__":
    unittest.main()
