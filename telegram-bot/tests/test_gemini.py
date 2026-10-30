import json
import unittest
from unittest.mock import patch

from holo import HoloError, gemini_completion, gemini_transcribe, pollinations_completion


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload


class GeminiTests(unittest.TestCase):
    @patch("holo.urllib.request.urlopen")
    def test_text_generation_uses_gemini_rest_payload(self, urlopen):
        urlopen.return_value = FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "سلام!"}]}}]
        })
        answer = gemini_completion(
            api_key="not-a-real-key",
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "به فارسی جواب بده."},
                {"role": "user", "content": "سلام"},
            ],
            max_tokens=100,
        )
        self.assertEqual(answer, "سلام!")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertIn("systemInstruction", payload)
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 100)

    @patch("holo.urllib.request.urlopen")
    def test_audio_transcription_sends_inline_audio(self, urlopen):
        urlopen.return_value = FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "متن ویس"}]}}]
        })
        self.assertEqual(gemini_transcribe("fake", "gemini-2.5-flash", b"ogg-bytes"), "متن ویس")
        payload = json.loads(urlopen.call_args.args[0].data)
        inline_audio = payload["contents"][0]["parts"][1]["inlineData"]
        self.assertEqual(inline_audio["mimeType"], "audio/ogg")
        self.assertTrue(inline_audio["data"])

    @patch("holo.urllib.request.urlopen")
    def test_public_no_key_text_fallback_works(self, urlopen):
        urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "پاسخ عمومی"}}]
        })
        answer = pollinations_completion(messages=[{"role": "user", "content": "سلام"}])
        self.assertEqual(answer, "پاسخ عمومی")
        request = urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))

    @patch("holo.urllib.request.urlopen")
    def test_invalid_key_has_clear_error(self, urlopen):
        from urllib.error import HTTPError

        urlopen.side_effect = HTTPError("https://example.invalid", 403, "Forbidden", {}, None)
        with self.assertRaisesRegex(HoloError, "کلید Gemini معتبر نیست"):
            gemini_completion(
                api_key="invalid", model="gemini-2.5-flash",
                messages=[{"role": "user", "content": "سلام"}],
            )


if __name__ == "__main__":
    unittest.main()
