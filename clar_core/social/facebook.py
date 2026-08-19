from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from clar_core.contracts import PublicationReceipt, Story


class FacebookPublishError(RuntimeError):
    pass


class FacebookAuthError(FacebookPublishError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_response(response: Any) -> dict[str, Any]:
    payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise FacebookPublishError("Meta returned a non-object response")
    return payload


def _graph_get(
    *,
    path: str,
    token: str,
    version: str,
    request_fn: Callable[..., Any],
) -> dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    endpoint += ("&" if "?" in endpoint else "?") + "access_token=" + urllib.parse.quote(token, safe="")
    request = urllib.request.Request(endpoint, method="GET", headers={"User-Agent": "CLAR-Core-Facebook/1.0"})
    try:
        with request_fn(request, timeout=30) as response:
            return _json_response(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FacebookAuthError(f"Meta GET HTTP {exc.code}: {detail[:800]}") from exc


def resolve_page_token(
    *,
    page_id: str,
    supplied_token: str,
    version: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[str, Mapping[str, Any]]:
    identity = _graph_get(path="me?fields=id,name", token=supplied_token, version=version, request_fn=request_fn)
    if str(identity.get("id") or "") == page_id:
        return supplied_token, {
            "source": "page_token",
            "page_id": page_id,
            "page_name": identity.get("name"),
        }
    page = _graph_get(
        path=f"{page_id}?fields=id,name,access_token",
        token=supplied_token,
        version=version,
        request_fn=request_fn,
    )
    derived = str(page.get("access_token") or "").strip()
    if str(page.get("id") or "") != page_id or not derived:
        raise FacebookAuthError("Meta did not return an access token for the configured Page")
    check = _graph_get(path="me?fields=id,name", token=derived, version=version, request_fn=request_fn)
    if str(check.get("id") or "") != page_id:
        raise FacebookAuthError("Derived token does not identify the configured Page")
    return derived, {
        "source": "derived_from_identity_token",
        "page_id": page_id,
        "page_name": check.get("name"),
    }


def _download_real_media(
    media: Mapping[str, Any],
    request_fn: Callable[..., Any],
) -> tuple[bytes, str, str]:
    if media.get("rights_status") != "VERIFIED_REUSABLE":
        raise FacebookPublishError("Facebook media is not rights-cleared")
    url = str(media.get("image_url") or "").strip()
    if not url.startswith("https://"):
        raise FacebookPublishError("Facebook media must use an HTTPS source")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "CLAR-Core-Facebook-Media/1.0"})
    try:
        with request_fn(request, timeout=30) as response:
            body = response.read()
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    except urllib.error.HTTPError as exc:
        raise FacebookPublishError(f"Media download HTTP {exc.code}") from exc
    if body.startswith(b"\xff\xd8\xff"):
        return body, "image/jpeg", "story.jpg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return body, "image/png", "story.png"
    if content_type in {"image/jpeg", "image/png"} and len(body) > 1024:
        ext = mimetypes.guess_extension(content_type) or ".img"
        return body, content_type, "story" + ext
    raise FacebookPublishError("Downloaded media is not a supported image")


def _multipart(fields: Mapping[str, str], *, image: bytes, mime: str, filename: str) -> tuple[bytes, str]:
    boundary = f"----CLAR{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="source"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def format_caption(story: Story, site_receipt: PublicationReceipt) -> str:
    if site_receipt.status != "published_verified":
        raise FacebookPublishError("Facebook publication requires a verified public-site receipt")
    bits = [story.headline, story.dek, site_receipt.canonical_url]
    media = story.metadata.get("media") if isinstance(story.metadata, Mapping) else None
    if isinstance(media, Mapping):
        creator = str(media.get("creator") or "").strip()
        license_name = str(media.get("license") or "").strip()
        source_page = str(media.get("source_page") or "").strip()
        if creator or license_name:
            credit = "Foto: " + " · ".join(x for x in (creator, license_name) if x)
            if source_page:
                credit += f" · {source_page}"
            bits.append(credit)
        caption = str(media.get("caption") or "").strip()
        if caption:
            bits.append(caption)
    return "\n\n".join(bit.strip() for bit in bits if bit and bit.strip())


class FacebookPagePublisher:
    """Single-path, fail-closed Facebook Page publisher.

    A story may be posted only after its website PublicationReceipt is externally
    verified. A successful Meta POST is immediately read back through Graph API.
    If POST succeeds but readback cannot prove the object, the returned receipt is
    ``submitted_unverified`` and carries the external id so callers can retry
    verification without reposting.
    """

    def __init__(
        self,
        *,
        page_id: str,
        access_token: str,
        graph_version: str,
        request_fn: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.page_id = page_id.strip()
        self.access_token = access_token.strip()
        self.graph_version = graph_version.strip()
        self.request_fn = request_fn
        if not self.page_id or not self.access_token or not self.graph_version:
            raise FacebookAuthError("Facebook Page id, access token and Graph version are required")

    def verify_existing(self, *, story_id: str, canonical_url: str, external_id: str) -> PublicationReceipt:
        token, resolution = resolve_page_token(
            page_id=self.page_id,
            supplied_token=self.access_token,
            version=self.graph_version,
            request_fn=self.request_fn,
        )
        try:
            value = _graph_get(
                path=f"{urllib.parse.quote(external_id, safe='')}?fields=id,permalink_url",
                token=token,
                version=self.graph_version,
                request_fn=self.request_fn,
            )
        except FacebookPublishError as exc:
            return PublicationReceipt(
                story_id=story_id,
                canonical_url=canonical_url,
                published_at=_now(),
                destination="facebook_page",
                status="submitted_unverified",
                external_id=external_id,
                metadata={"verification_error": str(exc), "auth_resolution": dict(resolution)},
            )
        verified_id = str(value.get("id") or "").strip()
        permalink = str(value.get("permalink_url") or "").strip()
        if verified_id != external_id or not permalink:
            return PublicationReceipt(
                story_id=story_id,
                canonical_url=canonical_url,
                published_at=_now(),
                destination="facebook_page",
                status="submitted_unverified",
                external_id=external_id,
                metadata={"auth_resolution": dict(resolution)},
            )
        return PublicationReceipt(
            story_id=story_id,
            canonical_url=canonical_url,
            published_at=_now(),
            destination="facebook_page",
            status="published_verified",
            external_id=external_id,
            metadata={"permalink_url": permalink, "auth_resolution": dict(resolution)},
        )

    def __call__(self, story: Story, site_receipt: PublicationReceipt) -> PublicationReceipt:
        if site_receipt.status != "published_verified":
            raise FacebookPublishError("Site publication must be published_verified before Facebook")
        media = story.metadata.get("media") if isinstance(story.metadata, Mapping) else None
        if not isinstance(media, Mapping):
            raise FacebookPublishError("Facebook publication requires real rights-cleared media")
        image, mime, filename = _download_real_media(media, self.request_fn)
        page_token, resolution = resolve_page_token(
            page_id=self.page_id,
            supplied_token=self.access_token,
            version=self.graph_version,
            request_fn=self.request_fn,
        )
        caption = format_caption(story, site_receipt)
        fields = {
            "caption": caption,
            "published": "true",
            "access_token": page_token,
            "alt_text_custom": str(media.get("alt") or story.headline),
        }
        body, content_type = _multipart(fields, image=image, mime=mime, filename=filename)
        request = urllib.request.Request(
            f"https://graph.facebook.com/{self.graph_version}/{urllib.parse.quote(self.page_id, safe='')}/photos",
            data=body,
            method="POST",
            headers={"Content-Type": content_type, "User-Agent": "CLAR-Core-Facebook/1.0"},
        )
        try:
            with self.request_fn(request, timeout=60) as response:
                payload = _json_response(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FacebookPublishError(f"Meta photo POST HTTP {exc.code}: {detail[:1000]}") from exc
        external_id = str(payload.get("post_id") or payload.get("id") or "").strip()
        if not external_id:
            raise FacebookPublishError("Meta photo POST returned no object id")
        receipt = self.verify_existing(
            story_id=story.story_id,
            canonical_url=site_receipt.canonical_url,
            external_id=external_id,
        )
        metadata = dict(receipt.metadata)
        metadata.update({
            "media_asset_id": media.get("asset_id"),
            "media_rights_status": media.get("rights_status"),
            "post_response_received": True,
            "auth_resolution": dict(resolution),
        })
        return PublicationReceipt(
            story_id=receipt.story_id,
            canonical_url=receipt.canonical_url,
            published_at=receipt.published_at,
            destination=receipt.destination,
            status=receipt.status,
            external_id=receipt.external_id,
            metadata=metadata,
        )
