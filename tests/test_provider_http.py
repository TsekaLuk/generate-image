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
import dataclasses
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

def _capture_openai_generate(provider, ratio, model):
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    with _client(handler) as c:
        seen["out"] = generate.provider_generate(provider, "一只猫", model, ratio, "k", c)
    return seen


def test_openai_generate_sends_exact_aspect_size_and_no_ratio_hint():
    # The aspect rides in `size` now, so the prompt stays clean — saying it in both
    # places is what produced the old mismatch.
    seen = _capture_openai_generate(PROVIDERS["openai"], "16:9", "gpt-image-2.5-flare")
    assert seen["out"] == _TINY_PNG
    assert seen["path"] == "/v1/images/generations"
    assert seen["body"]["size"] == "1680x944"
    assert seen["body"]["prompt"] == "一只猫"
    assert "16:9" not in seen["body"]["prompt"]


def test_ultrawide_reaches_the_api_as_ultrawide():
    # The regression this change exists for: -r 21:9 used to go out as 1536x1024
    # (1.50), nowhere near the 2.33 the caller asked for.
    seen = _capture_openai_generate(PROVIDERS["openai"], "21:9", "gpt-image-2.5-flare")
    w, h = (int(v) for v in seen["body"]["size"].split("x"))
    assert abs((w / h) - (21 / 9)) / (21 / 9) < 0.01


def test_openai_enum_style_still_sends_the_ratio_hint():
    # A relay swapped in via OPENAI_BASE_URL that ignores `size` keeps the old
    # behaviour: 3-value enum plus a prompt hint carrying the aspect.
    p = dataclasses.replace(PROVIDERS["openai"], size_style="openai")
    seen = _capture_openai_generate(p, "16:9", "gpt-image-2")
    assert seen["body"]["size"] == "1536x1024"
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


# --- sensenova img2img: the exact JSON shape the API demands -------------------

def _capture_sensenova_edit(refs, ratio="1:1"):
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    with _client(handler) as c:
        seen["out"] = generate.provider_edit(
            PROVIDERS["sensenova"], "把背景改成雪山", "sensenova-u1-pro",
            refs, ratio, "k", c)
    return seen


def test_sensenova_edit_uses_plural_images_of_objects(tmp_path):
    """The two details the API is strict about, and the two this code got wrong
    for a whole round of black-box probing: the field is plural `images`, and each
    entry is an OBJECT keyed `image_url` — a bare string in the array is refused."""
    ref = tmp_path / "a.png"
    ref.write_bytes(_TINY_PNG)
    seen = _capture_sensenova_edit([str(ref)])
    assert seen["path"] == "/v1/images/edits"
    assert "image" not in seen["body"], "singular `image` is not the field"
    entries = seen["body"]["images"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    assert set(entries[0]) == {"image_url"}


def test_sensenova_edit_wraps_local_files_as_data_urls(tmp_path):
    # Raw base64 with no prefix is refused by the API, so the prefix is mandatory.
    ref = tmp_path / "a.png"
    ref.write_bytes(_TINY_PNG)
    seen = _capture_sensenova_edit([str(ref)])
    url = seen["body"]["images"][0]["image_url"]
    assert url.startswith("data:image/png;base64,"), url[:40]


def test_sensenova_edit_passes_public_urls_through_untouched():
    seen = _capture_sensenova_edit(["https://example.com/source.png"])
    assert seen["body"]["images"][0]["image_url"] == "https://example.com/source.png"


def test_sensenova_edit_keeps_reference_order(tmp_path):
    # The doc says entry 1 is the primary image being edited, so order matters.
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(_TINY_PNG)
    b.write_bytes(_TINY_PNG)
    seen = _capture_sensenova_edit(["https://example.com/first.png", str(b)])
    assert seen["body"]["images"][0]["image_url"] == "https://example.com/first.png"
    assert seen["body"]["images"][1]["image_url"].startswith("data:")


def test_sensenova_edit_sends_the_output_fields_too(tmp_path):
    ref = tmp_path / "a.png"
    ref.write_bytes(_TINY_PNG)
    seen = _capture_sensenova_edit([str(ref)], ratio="16:9")
    assert seen["body"]["watermark"] is False
    assert seen["body"]["prompt_extend"] is False
    assert seen["body"]["size"] == "2720x1536"
    assert seen["body"]["n"] == 1


def test_sensenova_edit_refuses_more_than_five_refs(tmp_path):
    refs = []
    for i in range(6):
        f = tmp_path / f"{i}.png"
        f.write_bytes(_TINY_PNG)
        refs.append(str(f))
    with _client(lambda r: httpx.Response(200, json={})) as c:
        with pytest.raises(generate.ProviderError, match="at most 5"):
            generate.provider_edit(PROVIDERS["sensenova"], "p", "sensenova-u1-pro",
                                   refs, "1:1", "k", c)


def test_sensenova_actually_puts_the_size_on_the_wire():
    """Regression: `sensenova` was added to VALID_SIZE_STYLES and ratio_to_size but
    NOT to the branch that writes `size` into the body, so every call silently fell
    back to the server default — `-r 21:9` came back 2752x1536 (16:9). The map being
    right is worthless if the value never leaves the process."""
    seen = _capture_openai_generate(PROVIDERS["sensenova"], "21:9", "sensenova-u1-pro")
    assert seen["body"]["size"] == "3136x1344"


def test_sensenova_sends_no_ratio_hint():
    # The size carries the aspect for real here, so the prompt stays clean.
    seen = _capture_openai_generate(PROVIDERS["sensenova"], "21:9", "sensenova-u1-pro")
    assert seen["body"]["prompt"] == "一只猫"


def test_sensenova_every_ratio_goes_out_within_the_documented_contract():
    for ratio in sorted(generate.VALID_RATIOS):
        seen = _capture_openai_generate(PROVIDERS["sensenova"], ratio, "sensenova-u1-pro")
        w, h = (int(v) for v in seen["body"]["size"].split("x"))
        assert w % 32 == 0 and h % 32 == 0, f"{ratio}: {w}x{h} not a multiple of 32"
        assert 512 <= w <= 4096 and 512 <= h <= 4096, f"{ratio}: {w}x{h} out of range"


def test_sensenova_generation_disables_watermark_and_prompt_rewriting():
    """Both default to TRUE server-side. A silent vendor watermark on every asset
    is a defect, and a silently rewritten prompt breaks the series-consistency
    contracts this skill is built around."""
    seen = _capture_openai_generate(PROVIDERS["sensenova"], "1:1", "sensenova-u1-pro")
    assert seen["body"]["watermark"] is False
    assert seen["body"]["prompt_extend"] is False


def test_only_sensenova_gets_those_fields():
    # They are SenseNova-specific; sending them elsewhere would be an unknown key.
    seen = _capture_openai_generate(PROVIDERS["302ai"], "1:1", "gpt-image-2.5-flare")
    assert "watermark" not in seen["body"] and "prompt_extend" not in seen["body"]


# --- sensenova img2img: the exact JSON shape the API demands -------------------

def _capture_sensenova_edit(refs, ratio="1:1"):
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = _body(req)
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    with _client(handler) as c:
        seen["out"] = generate.provider_edit(
            PROVIDERS["sensenova"], "把背景改成雪山", "sensenova-u1-pro",
            refs, ratio, "k", c)
    return seen
