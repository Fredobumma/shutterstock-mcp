"""A small client for the Shutterstock API, and the compact summaries the tools return."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from mcp.server.mcpserver.exceptions import ToolError

API_URL = 'https://api.shutterstock.com/v2'
USER_AGENT = 'shutterstock-mcp (+https://github.com/fredobumma/shutterstock-mcp)'

AssetType = Literal['image', 'video', 'music', 'editorial']
PATHS: dict[str, str] = {'image': 'images', 'video': 'videos', 'music': 'audio', 'editorial': 'editorial/images'}


class ShutterstockError(ToolError):
    """An error to show the user as it is: what went wrong, and what to do about it. As a ToolError, its message
    reaches the model; anything else that goes wrong stays a generic error, with the details in the server's log."""


@dataclass(frozen=True)
class Credentials:
    token: str | None = None
    key: str | None = None
    secret: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Credentials:
        env = dict(os.environ if env is None else env)
        credentials = cls(
            token=env.get('SHUTTERSTOCK_API_TOKEN') or None,
            key=env.get('SHUTTERSTOCK_API_KEY') or None,
            secret=env.get('SHUTTERSTOCK_API_SECRET') or None,
        )
        if not credentials.token and not (credentials.key and credentials.secret):
            raise ShutterstockError(
                'set SHUTTERSTOCK_API_TOKEN, or SHUTTERSTOCK_API_KEY and SHUTTERSTOCK_API_SECRET: '
                'create an app at https://www.shutterstock.com/account/developers/apps'
            )
        return credentials

    @property
    def has_token(self) -> bool:
        return self.token is not None


class Shutterstock:
    def __init__(
        self,
        credentials: Credentials,
        *,
        base_url: str = API_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials
        headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
        auth: httpx.Auth | None = None
        if credentials.token:
            headers['Authorization'] = f'Bearer {credentials.token}'
        else:
            auth = httpx.BasicAuth(credentials.key or '', credentials.secret or '')
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip('/'), headers=headers, auth=auth, transport=transport, timeout=30
        )
        # previews come from Shutterstock's CDN, which needs no credentials and is not sent them
        self._cdn = httpx.AsyncClient(headers={'User-Agent': USER_AGENT}, transport=transport, timeout=30)

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._cdn.aclose()

    def require_token(self, what: str, scope: str) -> None:
        """Account features need a user's OAuth token, not just an app's key and secret."""
        if not self.credentials.has_token:
            raise ShutterstockError(
                f'{what} needs an OAuth access token with the {scope} scope, in SHUTTERSTOCK_API_TOKEN; '
                'an app key and secret only search. Get a token from your app at '
                'https://www.shutterstock.com/account/developers/apps'
            )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        # booleans as the API spells them, and lists as repeated parameters
        query = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in query.items()}
        try:
            response = await self._http.request(method, path, params=query, json=json)
        except httpx.HTTPError as e:
            raise ShutterstockError(f'could not reach Shutterstock: {e}') from e
        if response.status_code == 429:
            raise ShutterstockError(
                'Shutterstock says too many requests; free accounts allow about 100 an hour. Try again later.'
            )
        if response.status_code in (401, 403):
            raise ShutterstockError(f'Shutterstock refused the request ({response.status_code}): {_message(response)}')
        if response.status_code == 404:
            raise ShutterstockError(f'not found: {_message(response)}')
        if response.status_code >= 400:
            raise ShutterstockError(f'Shutterstock returned {response.status_code}: {_message(response)}')
        return response.json() if response.content else {}

    async def fetch_bytes(self, url: str) -> tuple[bytes, str]:
        """A preview image, from Shutterstock's own CDN."""
        if not url.startswith('https://'):
            raise ShutterstockError(f'not a preview URL: {url}')
        try:
            response = await self._cdn.get(url, headers={'Accept': 'image/*'})
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ShutterstockError(f'could not fetch the preview: {e}') from e
        return response.content, response.headers.get('content-type', 'image/jpeg').split(';')[0]


def _message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if isinstance(data, dict):
        parts = [str(data.get('message', ''))]
        for error in data.get('errors', []) or []:
            if isinstance(error, dict):
                parts.append(str(error.get('message', '')))
        return '; '.join(p for p in parts if p) or response.reason_phrase
    return response.reason_phrase


def encode_file(path: str) -> str:
    try:
        with open(os.path.expanduser(path), 'rb') as f:
            data = f.read()
    except OSError as e:
        raise ShutterstockError(f'could not read {path}: {e.strerror}') from e
    if len(data) > 10 * 1024 * 1024:
        raise ShutterstockError('the image is larger than the 10 MB Shutterstock accepts')
    return base64.b64encode(data).decode()


# ---- summaries -------------------------------------------------------------------------------------------------
# The API's responses are large and deeply nested. The tools hand back what a person choosing an asset needs: what it
# is, a preview to look at, and the ids and links to act on it.


def _asset_url(assets: dict[str, Any], *names: str) -> str | None:
    for name in names:
        asset = assets.get(name)
        if isinstance(asset, dict) and asset.get('url'):
            return str(asset['url'])
    return None


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, [], '')}


def summarize_image(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get('assets') or {}
    return _clean(
        {
            'id': item.get('id'),
            'description': item.get('description'),
            'type': item.get('image_type'),
            'aspect': item.get('aspect'),
            'preview': _asset_url(assets, 'preview_1000', 'preview', 'large_thumb'),
            'thumbnail': _asset_url(assets, 'large_thumb', 'small_thumb'),
            'contributor': (item.get('contributor') or {}).get('id'),
            'editorial': item.get('is_editorial'),
            'model_released': item.get('has_model_release'),
            'keywords': (item.get('keywords') or [])[:15],
            'page': item.get('url'),
        }
    )


def summarize_video(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get('assets') or {}
    return _clean(
        {
            'id': item.get('id'),
            'description': item.get('description'),
            'duration_seconds': item.get('duration'),
            'aspect_ratio': item.get('aspect_ratio'),
            'preview_video': _asset_url(assets, 'preview_mp4', 'thumb_mp4'),
            'preview_image': _asset_url(assets, 'preview_jpg', 'thumb_jpg'),
            'sizes': [s for s in ('web', 'sd', 'hd', '_4k') if s in assets] or None,
            'contributor': (item.get('contributor') or {}).get('id'),
            'editorial': item.get('is_editorial'),
            'keywords': (item.get('keywords') or [])[:15],
            'page': item.get('url'),
        }
    )


def summarize_track(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get('assets') or {}
    return _clean(
        {
            'id': item.get('id'),
            'title': item.get('title'),
            'artists': [a.get('name') for a in item.get('artists') or [] if isinstance(a, dict)],
            'description': item.get('description'),
            'duration_seconds': item.get('duration'),
            'bpm': item.get('bpm'),
            'genres': item.get('genres'),
            'moods': item.get('moods'),
            'instruments': item.get('instruments'),
            'instrumental': item.get('is_instrumental'),
            'preview_audio': _asset_url(assets, 'preview_mp3', 'preview_ogg'),
            'waveform': _asset_url(assets, 'waveform'),
            'page': item.get('url'),
        }
    )


def summarize_editorial(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get('assets') or {}
    return _clean(
        {
            'id': item.get('id'),
            'title': item.get('title'),
            'caption': item.get('caption') or item.get('description'),
            'date_taken': item.get('date_taken'),
            'byline': item.get('byline'),
            'supplier': item.get('supplier_code'),
            'preview': _asset_url(assets, 'watermark_1500', 'watermark_450', 'preview', 'thumb_220', 'thumb_170'),
            'thumbnail': _asset_url(assets, 'thumb_220', 'thumb_170'),
            'aspect': item.get('aspect'),
            'keywords': (item.get('keywords') or [])[:15],
        }
    )


SUMMARIES = {
    'image': summarize_image,
    'video': summarize_video,
    'music': summarize_track,
    'editorial': summarize_editorial,
}


def summarize_page(data: dict[str, Any], asset_type: str) -> dict[str, Any]:
    summarize = SUMMARIES[asset_type]
    return _clean(
        {
            'total': data.get('total_count'),
            'page': data.get('page'),
            'per_page': data.get('per_page'),
            'search_id': data.get('search_id'),
            'next_cursor': data.get('next'),
            'did_you_mean': (data.get('spellcheck_info') or {}).get('spellchecked_query')
            if isinstance(data.get('spellcheck_info'), dict)
            else None,
            'results': [summarize(item) for item in data.get('data') or []],
        }
    )
