"""Per-provider request shaping + response normalization (the dialect matrix).

Uses httpx.MockTransport to capture the outgoing request and serve a canned
response for each provider's generation and edit paths, asserting:
  * correct endpoint path (esp. OpenRouter /v1/images vs others /v1/images/generations)
  * correct size dialect (openai `size` / siliconflow `image_size` / none)
  * correct img2img shape (multipart / chat image_url / image_prompt)
  * extract_image_bytes normalizes b64 / url-download / chat-images / markdown.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from generate_image import cli as generate
from generate_image.providers import PROVIDERS
from generate_image.reliability import ProviderError, build_client

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_B64 = base64.b64encode(_TINY_PNG).decode("ascii")
_FIXTURE = Path(__file__).parent / "fixtures" / "volcengine_seedream_5_response.json"


def _client(handler) -> httpx.Client:
    return build_client(transport=httpx.MockTransport(handler))


def _body(req) -> dict:
    return json.loads(req.content.decode("utf-8"))


# --- generation: endpoint + size dialect --------------------------------------

def test_openai_generate_uses_openai_size_and_ratio_hint():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    p = PROVIDERS["openai"]
    with _client(handler) as c:
        out = generate.provider_generate(p, "一只猫", "gpt-image-2", "16:9", "k", c)

    assert out == _TINY_PNG
    assert seen["path"] == "/v1/images/generations"
    assert seen["body"]["size"] == "1536x1024"          # openai WxH
    assert "16:9" in seen["body"]["prompt"] or "landscape" in seen["body"]["prompt"]


def test_openrouter_generate_hits_images_path_without_size():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    p = PROVIDERS["openrouter"]
    with _client(handler) as c:
        out = generate.provider_generate(p, "cyberpunk cat", p.default_model, "16:9", "k", c)

    assert out == _TINY_PNG
    # base_url is openrouter.ai/api, so full path is /api/v1/images (NOT .../generations)
    assert seen["path"] == "/api/v1/images"
    assert "size" not in seen["body"]
    assert "image_size" not in seen["body"]


def test_siliconflow_generate_uses_image_size_and_no_hint():
    seen = {}

    def handler(req):
        seen["body"] = _body(req)
        return httpx.Response(200, json={"images": [{"url": "https://cdn.sf/out.png"}]})  # url shape
    # download of the hosted url:
    def dispatch(req):
        if req.method == "GET" and req.url.path == "/out.png":
            return httpx.Response(200, content=_TINY_PNG)
        return handler(req)

    p = PROVIDERS["siliconflow"]
    with _client(dispatch) as c:
        out = generate.provider_generate(p, "海边灯塔", p.default_model, "16:9", "k", c)

    assert out == _TINY_PNG
    assert seen["body"]["image_size"] == "1664x928"     # siliconflow WxH for 16:9
    # wxh providers control size for real -> no ratio hint appended to the prompt
    assert "landscape" not in seen["body"]["prompt"]


def test_volcengine_generate_matches_live_ark_shape_and_dialect():
    seen = {}
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, content=_TINY_PNG)
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json=fixture)

    p = PROVIDERS["volcengine"]
    with _client(handler) as c:
        out = generate.provider_generate(p, "minimal poster", p.default_model,
                                         "16:9", "k", c, seed=42)

    assert out == _TINY_PNG
    assert seen["path"] == "/api/v3/images/generations"
    assert seen["body"]["model"] == "doubao-seedream-5-0-260128"
    assert seen["body"]["size"] == "2K"
    assert seen["body"]["sequential_image_generation"] == "disabled"
    assert seen["body"]["response_format"] == "url"
    assert seen["body"]["seed"] == 42
    assert "n" not in seen["body"]


def test_volcengine_pro_omits_unsupported_sequential_field():
    seen = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, content=_TINY_PNG)
        seen["body"] = _body(req)
        return httpx.Response(200, json={
            "created": 1784799168,
            "data": [{"size": "1536x1536", "url": "https://ark.test/pro.png"}],
            "model": "doubao-seedream-5-0-pro-260628",
            "usage": {"generated_images": 1},
        })

    p = PROVIDERS["volcengine"]
    with _client(handler) as c:
        out = generate.provider_generate(
            p, "minimal poster", "doubao-seedream-5-0-pro-260628", "1:1", "k", c)

    assert out == _TINY_PNG
    assert "sequential_image_generation" not in seen["body"]


# --- extract_image_bytes normalization ----------------------------------------

def test_extract_data_b64():
    with _client(lambda r: httpx.Response(200)) as c:
        assert generate.extract_image_bytes({"data": [{"b64_json": _B64}]}, c) == _TINY_PNG


def test_extract_data_url_downloads():
    def handler(req):
        return httpx.Response(200, content=_TINY_PNG)

    with _client(handler) as c:
        out = generate.extract_image_bytes({"data": [{"url": "https://x.test/a.png"}]}, c)
    assert out == _TINY_PNG


def test_extract_images_url_downloads():
    def handler(req):
        return httpx.Response(200, content=_TINY_PNG)

    with _client(handler) as c:
        out = generate.extract_image_bytes({"images": [{"url": "https://x.test/b.png"}]}, c)
    assert out == _TINY_PNG


def test_extract_chat_images_data_url():
    d = {"choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{_B64}"}}]}}]}
    with _client(lambda r: httpx.Response(200)) as c:
        assert generate.extract_image_bytes(d, c) == _TINY_PNG


def test_extract_chat_markdown_data_url():
    d = {"choices": [{"message": {"content": f"here you go ![img](data:image/png;base64,{_B64})"}}]}
    with _client(lambda r: httpx.Response(200)) as c:
        assert generate.extract_image_bytes(d, c) == _TINY_PNG


def test_extract_no_image_raises():
    from generate_image.reliability import ProviderError
    with _client(lambda r: httpx.Response(200)) as c:
        with pytest.raises(ProviderError):
            generate.extract_image_bytes({"weird": 1}, c)


# --- img2img: per-provider edit shaping ---------------------------------------

def test_openai_edit_is_multipart(tmp_path):
    ref = tmp_path / "face.png"
    ref.write_bytes(_TINY_PNG)
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["ctype"] = req.headers.get("content-type", "")
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    p = PROVIDERS["openai"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "梵高风格", "gpt-image-2", [str(ref)], "1:1", "k", c)

    assert out == _TINY_PNG
    assert seen["path"] == "/v1/images/edits"
    assert seen["ctype"].startswith("multipart/form-data")


def test_openrouter_edit_is_chat_image(tmp_path):
    ref = tmp_path / "face.png"
    ref.write_bytes(_TINY_PNG)
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={
            "choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{_B64}"}}]}}]
        })

    p = PROVIDERS["openrouter"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "restyle", p.default_model, [str(ref)], "1:1", "k", c)

    assert out == _TINY_PNG
    assert seen["path"] == "/api/v1/chat/completions"
    content = seen["body"]["messages"][0]["content"]
    kinds = {part["type"] for part in content}
    assert kinds == {"text", "image_url"}
    img_part = next(p for p in content if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert "image" in seen["body"]["modalities"]


def test_openai_edit_multi_image_sends_image_array(tmp_path):
    refs = []
    for i in range(3):
        r = tmp_path / f"r{i}.png"
        r.write_bytes(_TINY_PNG)
        refs.append(str(r))
    seen = {}

    def handler(req):
        seen["ctype"] = req.headers.get("content-type", "")
        seen["parts"] = req.content.count(b'name="image[]"')
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    p = PROVIDERS["openai"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "combine", "gpt-image-2", refs, "1:1", "k", c)

    assert out == _TINY_PNG
    assert seen["ctype"].startswith("multipart/form-data")
    assert seen["parts"] == 3  # three repeated image[] parts for compositing


def test_openrouter_edit_multi_image_multiple_image_url(tmp_path):
    refs = []
    for i in range(2):
        r = tmp_path / f"r{i}.png"
        r.write_bytes(_TINY_PNG)
        refs.append(str(r))
    seen = {}

    def handler(req):
        seen["body"] = _body(req)
        return httpx.Response(200, json={
            "choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{_B64}"}}]}}]
        })

    p = PROVIDERS["openrouter"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "merge", p.default_model, refs, "1:1", "k", c)

    assert out == _TINY_PNG
    content = seen["body"]["messages"][0]["content"]
    img_parts = [part for part in content if part["type"] == "image_url"]
    text_parts = [part for part in content if part["type"] == "text"]
    assert len(img_parts) == 2 and len(text_parts) == 1
    assert content[0]["type"] == "text"  # text first, then images


def test_edit_rejects_more_refs_than_provider_allows(tmp_path):
    # siliconflow accepts only 1 reference image -> 2 must raise, before any network
    r1 = tmp_path / "a.png"; r1.write_bytes(_TINY_PNG)
    r2 = tmp_path / "b.png"; r2.write_bytes(_TINY_PNG)

    def handler(req):
        raise AssertionError("must not reach network when ref count exceeds the cap")

    from generate_image.reliability import ProviderError
    p = PROVIDERS["siliconflow"]
    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            generate.provider_edit(p, "x", p.default_model, [str(r1), str(r2)], "1:1", "k", c)
    assert ei.value.retryable is False
    assert "at most 1" in str(ei.value)


def test_siliconflow_edit_uses_image_prompt(tmp_path):
    ref = tmp_path / "face.png"
    ref.write_bytes(_TINY_PNG)
    seen = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, content=_TINY_PNG)
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"images": [{"url": "https://cdn.sf/e.png"}]})

    p = PROVIDERS["siliconflow"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "edit it", p.default_model, [str(ref)], "16:9", "k", c)

    assert out == _TINY_PNG
    assert seen["path"] == "/v1/images/generations"
    assert seen["body"]["image_prompt"] == _B64
    assert seen["body"]["image_size"] == "1664x928"


def test_volcengine_edit_embeds_local_refs_as_data_urls(tmp_path):
    refs = []
    for name in ("subject.png", "style.png"):
        path = tmp_path / name
        path.write_bytes(_TINY_PNG)
        refs.append(str(path))
    seen = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, content=_TINY_PNG)
        seen["body"] = _body(req)
        return httpx.Response(200, json={
            "created": 1784797893,
            "data": [{"size": "2048x2048", "url": "https://ark.test/edit.png"}],
            "model": "doubao-seedream-5-0-260128",
            "usage": {"generated_images": 1, "output_tokens": 16384, "total_tokens": 16384},
        })

    p = PROVIDERS["volcengine"]
    with _client(handler) as c:
        out = generate.provider_edit(p, "combine them", p.default_model, refs,
                                     "1:1", "k", c)

    assert out == _TINY_PNG
    assert len(seen["body"]["image"]) == 2
    assert all(value.startswith("data:image/png;base64,")
               for value in seen["body"]["image"])
    assert seen["body"]["sequential_image_generation"] == "disabled"


def test_volcengine_sequence_extracts_every_image_and_options():
    seen = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, content=_TINY_PNG)
        seen["body"] = _body(req)
        return httpx.Response(200, json={
            "created": 1784797893,
            "data": [
                {"size": "2048x2048", "url": "https://ark.test/1.png"},
                {"size": "2048x2048", "url": "https://ark.test/2.png"},
            ],
            "model": "doubao-seedream-5-0-260128",
            "usage": {"generated_images": 2, "output_tokens": 32768, "total_tokens": 32768},
        })

    p = PROVIDERS["volcengine"]
    with _client(handler) as c:
        out = generate.provider_generate_sequence(
            p, "two-panel storyboard", p.default_model, [], "16:9", "k", c,
            max_images=2,
        )

    assert out == [_TINY_PNG, _TINY_PNG]
    assert seen["body"]["sequential_image_generation"] == "auto"
    assert seen["body"]["sequential_image_generation_options"] == {"max_images": 2}


def test_volcengine_pro_rejects_sequence_before_network():
    def handler(req):
        raise AssertionError("Pro sequence must fail before network")

    p = PROVIDERS["volcengine"]
    with _client(handler) as c:
        with pytest.raises(ProviderError, match="not supported by Ark model"):
            generate.provider_generate_sequence(
                p, "storyboard", "doubao-seedream-5-0-pro-260628", [], "16:9", "k", c)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
