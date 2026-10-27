"""ImageHost backed by Vercel Blob (via the `vercel_blob` PyPI package).

Instagram's publishing API fetches media from a public URL, so each image or
video is uploaded here just long enough to publish, then deleted. Auth comes
from the BLOB_READ_WRITE_TOKEN env var (Vercel -> Storage -> Blob -> your store).
"""

from __future__ import annotations

import vercel_blob

from .base import HostedImage

PREFIX = "narovva"


class ImageHostError(RuntimeError):
    """Raised when an upload or delete against the image host fails."""


class VercelBlobImageHost:
    def upload(self, data: bytes, filename: str, content_type: str = "image/png") -> HostedImage:
        pathname = f"{PREFIX}/{filename.lstrip('/')}"
        try:
            resp = vercel_blob.put(pathname, data, options={"addRandomSuffix": "true"})
        except Exception as exc:  # vercel_blob raises its own BlobConfigError/BlobRequestError
            raise ImageHostError(f"failed to upload {pathname!r} to Vercel Blob: {exc}") from exc
        url = resp.get("url")
        if not url:
            raise ImageHostError(f"Vercel Blob upload of {pathname!r} returned no url: {resp}")
        return HostedImage(url=url, pathname=resp.get("pathname", pathname))

    def delete(self, hosted: HostedImage | str) -> None:
        url = hosted.url if isinstance(hosted, HostedImage) else hosted
        try:
            vercel_blob.delete(url)
        except Exception as exc:
            raise ImageHostError(f"failed to delete {url!r} from Vercel Blob: {exc}") from exc
