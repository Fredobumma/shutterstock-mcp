from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client
from mcp.types import CallToolResult, ImageContent, TextContent

from shutterstock_mcp.api import Credentials, Shutterstock
from shutterstock_mcp.server import create_server

pytestmark = pytest.mark.anyio

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)

IMAGE = {
    'id': '1234567',
    'aspect': 1.5,
    'description': 'Sunrise over a calm lake',
    'image_type': 'photo',
    'media_type': 'image',
    'has_model_release': False,
    'contributor': {'id': '42'},
    'keywords': ['lake', 'sunrise', 'calm'],
    'assets': {
        'preview': {'url': 'https://image.shutterstock.com/display_pic_with_logo/1/1234567/stock-photo.jpg'},
        'preview_1000': {'url': 'https://ak.picdn.net/shutterstock/photos/1234567/watermark_1000/x.jpg'},
        'large_thumb': {'url': 'https://thumb7.shutterstock.com/thumb_large/1/1234567/x.jpg'},
    },
}
VIDEO = {
    'id': '9876',
    'description': 'Drone shot of a coastline',
    'duration': 14.5,
    'aspect_ratio': '16:9',
    'media_type': 'video',
    'contributor': {'id': '7'},
    'assets': {
        'preview_mp4': {'url': 'https://ak.picdn.net/shutterstock/videos/9876/preview/stock-footage.mp4'},
        'thumb_jpg': {'url': 'https://ak.picdn.net/shutterstock/videos/9876/thumb/1.jpg'},
        'hd': {'height': 1080},
        '_4k': {'height': 2160},
    },
}
TRACK = {
    'id': '555',
    'title': 'Morning Light',
    'artists': [{'name': 'Lumen'}],
    'duration': 132,
    'bpm': 96,
    'genres': ['Cinematic'],
    'moods': ['Uplifting'],
    'is_instrumental': True,
    'media_type': 'audio',
    'assets': {'preview_mp3': {'url': 'https://ak.picdn.net/shutterstock/audio/555/preview/preview.mp3'}},
}
EDITORIAL = {
    'id': '14567890a',
    'title': 'Champions League final',
    'caption': 'Players celebrate after the final whistle',
    'date_taken': '2026-05-30',
    'byline': 'A Photographer/Shutterstock',
    'assets': {'watermark_1500': {'url': 'https://editorial01.shutterstock.com/wm-preview-1500/14567890a/x.jpg'}},
}


class FakeShutterstock:
    """The Shutterstock API and its CDN, recording what they were sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.override: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host != 'api.shutterstock.com':
            # the CDN: must never see the user's credentials
            assert 'authorization' not in request.headers
            return httpx.Response(200, content=PNG, headers={'content-type': 'image/png'})
        for prefix, respond in self.override.items():
            if path.startswith(prefix):
                return respond(request)
        page = {'page': 1, 'per_page': 20, 'search_id': 'srch-1'}
        routes: dict[tuple[str, str], Any] = {
            ('GET', '/v2/images/search'): {**page, 'total_count': 1, 'data': [IMAGE]},
            ('GET', '/v2/images/1234567'): IMAGE,
            ('GET', '/v2/images/1234567/similar'): {**page, 'total_count': 1, 'data': [IMAGE]},
            ('GET', '/v2/videos/search'): {**page, 'total_count': 1, 'data': [VIDEO]},
            ('GET', '/v2/videos/9876'): VIDEO,
            ('GET', '/v2/audio/search'): {**page, 'total_count': 1, 'data': [TRACK]},
            ('GET', '/v2/editorial/images/search'): {
                'per_page': 20,
                'total_count': 1,
                'next': 'cur-2',
                'data': [EDITORIAL],
            },
            ('GET', '/v2/editorial/images/14567890a'): EDITORIAL,
            ('POST', '/v2/cv/images'): {'upload_id': 'up-1'},
            ('GET', '/v2/cv/similar/images'): {**page, 'total_count': 1, 'data': [IMAGE]},
            ('GET', '/v2/user/subscriptions'): {
                'data': [
                    {
                        'id': 'sub-1',
                        'description': 'Annual Subscription',
                        'asset_type': 'images',
                        'license': 'standard',
                        'expiration_time': '2027-01-01T00:00:00Z',
                        'allotment': {'downloads_left': 740, 'downloads_limit': 750},
                        'formats': [{'size': 'huge'}, {'size': 'medium'}],
                    }
                ]
            },
            ('GET', '/v2/images/licenses'): {
                'total_count': 1,
                'page': 1,
                'data': [
                    {'id': 'lic-0', 'image': {'id': '1234567'}, 'download_time': '2026-10-01', 'license': 'standard'}
                ],
            },
            ('POST', '/v2/images/licenses'): {
                'data': [
                    {
                        'image_id': '1234567',
                        'license_id': 'lic-1',
                        'allotment_charge': 1,
                        'download': {'url': 'https://download.shutterstock.com/x'},
                    }
                ]
            },
            ('POST', '/v2/editorial/images/licenses'): {
                'data': [
                    {
                        'editorial_id': '14567890a',
                        'license_id': 'lic-2',
                        'download': {'url': 'https://download.shutterstock.com/e'},
                    }
                ]
            },
            ('GET', '/v2/images/collections'): {
                'data': [{'id': 'col-1', 'name': 'Lake campaign', 'total_item_count': 1}]
            },
            ('GET', '/v2/images/collections/col-1'): {'id': 'col-1', 'name': 'Lake campaign', 'total_item_count': 1},
            ('GET', '/v2/images/collections/col-1/items'): {'data': [{'id': '1234567'}]},
            ('GET', '/v2/images'): {'data': [IMAGE]},
            ('POST', '/v2/images/collections'): {'id': 'col-2'},
            ('POST', '/v2/images/collections/col-1/items'): {},
        }
        body = routes.get((request.method, path))
        if body is None:
            return httpx.Response(404, json={'message': f'no route {request.method} {path}'})
        return httpx.Response(200, json=body)

    def last(self, method: str, path: str) -> httpx.Request:
        return next(r for r in reversed(self.requests) if r.method == method and r.url.path == path)


@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'


@pytest.fixture
def api() -> FakeShutterstock:
    return FakeShutterstock()


async def connect(api: FakeShutterstock, credentials: Credentials, *, licensing: bool = False) -> AsyncIterator[Client]:
    client = Shutterstock(credentials, transport=httpx.MockTransport(api.handler))
    async with Client(create_server(client, licensing=licensing)) as mcp:
        yield mcp
    await client.aclose()


@pytest.fixture
async def basic(api: FakeShutterstock) -> AsyncIterator[Client]:
    async for mcp in connect(api, Credentials(key='app-key', secret='app-secret')):
        yield mcp


@pytest.fixture
async def oauth(api: FakeShutterstock) -> AsyncIterator[Client]:
    async for mcp in connect(api, Credentials(token='user-token')):
        yield mcp


@pytest.fixture
async def licensing(api: FakeShutterstock) -> AsyncIterator[Client]:
    async for mcp in connect(api, Credentials(token='user-token'), licensing=True):
        yield mcp


def data(result: CallToolResult) -> Any:
    assert not result.is_error, result.content
    first = result.content[0]
    assert isinstance(first, TextContent)
    return json.loads(first.text)


def error(result: CallToolResult) -> str:
    assert result.is_error
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


async def test_the_tools_and_their_hints(basic: Client, licensing: Client) -> None:
    tools = {t.name: t for t in (await basic.list_tools()).tools}
    assert 'license_asset' not in tools
    for name in ('search_images', 'search_videos', 'search_music', 'search_editorial', 'get_asset', 'view_preview'):
        hints = tools[name].annotations
        assert hints is not None and hints.read_only_hint, name
    hints = tools['add_to_collection'].annotations
    assert hints is not None and hints.read_only_hint is False

    licensed = {t.name: t for t in (await licensing.list_tools()).tools}
    spend = licensed['license_asset'].annotations
    assert spend and spend.destructive_hint is True and spend.read_only_hint is False


async def test_search_images(basic: Client, api: FakeShutterstock) -> None:
    result = data(
        await basic.call_tool(
            'search_images', {'query': 'lake sunrise NOT people', 'orientation': 'horizontal', 'image_type': 'photo'}
        )
    )
    assert result['total'] == 1
    assert result['search_id'] == 'srch-1'
    first = result['results'][0]
    assert first['id'] == '1234567'
    assert first['preview'].endswith('watermark_1000/x.jpg')
    assert first['keywords'] == ['lake', 'sunrise', 'calm']

    request = api.last('GET', '/v2/images/search')
    assert request.url.params['query'] == 'lake sunrise NOT people'
    assert request.url.params['orientation'] == 'horizontal'
    assert request.url.params['safe'] == 'true'
    assert 'color' not in request.url.params
    assert request.headers['authorization'] == 'Basic ' + base64.b64encode(b'app-key:app-secret').decode()


async def test_search_videos_music_and_editorial(basic: Client, api: FakeShutterstock) -> None:
    video = data(await basic.call_tool('search_videos', {'query': 'coastline', 'resolution': '4k'}))['results'][0]
    assert video == {
        'id': '9876',
        'description': 'Drone shot of a coastline',
        'duration_seconds': 14.5,
        'aspect_ratio': '16:9',
        'preview_video': VIDEO['assets']['preview_mp4']['url'],  # type: ignore[index]
        'preview_image': VIDEO['assets']['thumb_jpg']['url'],  # type: ignore[index]
        'sizes': ['hd', '_4k'],
        'contributor': '7',
    }

    track = data(
        await basic.call_tool('search_music', {'moods': ['Uplifting'], 'genre': ['Cinematic'], 'instrumental': True})
    )['results'][0]
    assert track['title'] == 'Morning Light'
    assert track['artists'] == ['Lumen']
    assert track['preview_audio'].endswith('preview.mp3')
    request = api.last('GET', '/v2/audio/search')
    assert request.url.params.get_list('moods') == ['Uplifting']
    assert request.url.params['is_instrumental'] == 'true'

    editorial = data(await basic.call_tool('search_editorial', {'query': 'final', 'country': 'gbr'}))
    assert editorial['next_cursor'] == 'cur-2'
    assert editorial['results'][0]['byline'] == 'A Photographer/Shutterstock'
    assert api.last('GET', '/v2/editorial/images/search').url.params['country'] == 'GBR'


async def test_details_and_similar(basic: Client, api: FakeShutterstock) -> None:
    detail = data(await basic.call_tool('get_asset', {'asset_type': 'image', 'id': '1234567'}))
    assert detail['description'] == 'Sunrise over a calm lake'
    assert api.last('GET', '/v2/images/1234567').url.params['view'] == 'full'

    similar = data(await basic.call_tool('find_similar', {'asset_type': 'image', 'id': '1234567'}))
    assert similar['results'][0]['id'] == '1234567'


async def test_reverse_image_search_from_a_file(basic: Client, api: FakeShutterstock, tmp_path: Path) -> None:
    picture = tmp_path / 'moodboard.png'
    picture.write_bytes(PNG)
    result = data(await basic.call_tool('reverse_image_search', {'image_path': str(picture)}))
    assert result['results'][0]['id'] == '1234567'
    upload = json.loads(api.last('POST', '/v2/cv/images').content)
    assert base64.b64decode(upload['base64_image']) == PNG
    assert api.last('GET', '/v2/cv/similar/images').url.params['asset_id'] == 'up-1'

    assert 'either' in error(await basic.call_tool('reverse_image_search', {}))
    assert 'could not read' in error(
        await basic.call_tool('reverse_image_search', {'image_path': str(tmp_path / 'none.png')})
    )


async def test_view_preview_returns_the_image_without_sending_credentials(basic: Client, api: FakeShutterstock) -> None:
    result = await basic.call_tool('view_preview', {'id': '1234567'})
    assert not result.is_error
    image = result.content[0]
    assert isinstance(image, ImageContent)
    assert image.mime_type == 'image/png'
    assert base64.b64decode(image.data) == PNG
    cdn = [r for r in api.requests if r.url.host != 'api.shutterstock.com']
    assert cdn and cdn[-1].url.host == 'ak.picdn.net'


async def test_account_tools_need_an_oauth_token(basic: Client) -> None:
    for name, arguments in (
        ('list_subscriptions', {}),
        ('list_licenses', {}),
        ('list_collections', {}),
        ('create_collection', {'name': 'x'}),
    ):
        message = error(await basic.call_tool(name, arguments))
        assert 'OAuth access token' in message, name


async def test_subscriptions_licenses_and_collections(oauth: Client, api: FakeShutterstock) -> None:
    subscriptions = data(await oauth.call_tool('list_subscriptions', {}))['subscriptions']
    assert subscriptions == [
        {
            'id': 'sub-1',
            'description': 'Annual Subscription',
            'asset_type': 'images',
            'license': 'standard',
            'expires': '2027-01-01T00:00:00Z',
            'downloads_left': 740,
            'downloads_limit': 750,
            'sizes': ['huge', 'medium'],
        }
    ]
    assert api.last('GET', '/v2/user/subscriptions').headers['authorization'] == 'Bearer user-token'

    licenses = data(await oauth.call_tool('list_licenses', {}))['licenses']
    assert licenses[0]['asset_id'] == '1234567'

    collections = data(await oauth.call_tool('list_collections', {}))
    assert collections == {'collections': [{'id': 'col-1', 'name': 'Lake campaign', 'items': 1}]}
    collection = data(await oauth.call_tool('get_collection', {'collection_id': 'col-1'}))
    assert collection['images'][0]['id'] == '1234567'

    assert data(await oauth.call_tool('create_collection', {'name': 'Spring'})) == {'id': 'col-2', 'name': 'Spring'}
    await oauth.call_tool('add_to_collection', {'collection_id': 'col-1', 'image_ids': ['1', '2']})
    assert json.loads(api.last('POST', '/v2/images/collections/col-1/items').content) == {
        'items': [{'id': '1'}, {'id': '2'}]
    }


async def test_licensing(licensing: Client, api: FakeShutterstock) -> None:
    result = data(
        await licensing.call_tool(
            'license_asset',
            {'asset_type': 'image', 'id': '1234567', 'subscription_id': 'sub-1', 'size': 'huge', 'search_id': 'srch-1'},
        )
    )
    assert result['licenses'] == [
        {
            'asset_id': '1234567',
            'license_id': 'lic-1',
            'download_url': 'https://download.shutterstock.com/x',
            'credits_used': 1,
        }
    ]
    request = api.last('POST', '/v2/images/licenses')
    assert json.loads(request.content) == {
        'images': [{'image_id': '1234567', 'subscription_id': 'sub-1', 'size': 'huge', 'search_id': 'srch-1'}]
    }
    assert request.url.params['subscription_id'] == 'sub-1'

    # editorial needs the user's word that it is for news or commentary
    refused = error(await licensing.call_tool('license_asset', {'asset_type': 'editorial', 'id': '14567890a'}))
    assert 'news and commentary' in refused
    licensed = data(
        await licensing.call_tool(
            'license_asset',
            {'asset_type': 'editorial', 'id': '14567890a', 'country': 'nga', 'editorial_acknowledgement': True},
        )
    )
    assert licensed['licenses'][0]['license_id'] == 'lic-2'
    assert json.loads(api.last('POST', '/v2/editorial/images/licenses').content)['country'] == 'NGA'


async def test_errors_say_what_happened(api: FakeShutterstock, basic: Client) -> None:
    api.override['/v2/images/search'] = lambda r: httpx.Response(429, json={'message': 'Too many requests'})
    assert '100 an hour' in error(await basic.call_tool('search_images', {'query': 'x'}))

    api.override['/v2/images/search'] = lambda r: httpx.Response(
        403, json={'message': 'Forbidden', 'errors': [{'message': 'Your plan does not include this'}]}
    )
    assert 'Your plan does not include this' in error(await basic.call_tool('search_images', {'query': 'x'}))

    assert 'not found' in error(await basic.call_tool('get_asset', {'asset_type': 'image', 'id': 'nope'}))


def test_credentials_from_the_environment() -> None:
    assert Credentials.from_env({'SHUTTERSTOCK_API_TOKEN': 't'}).has_token
    assert not Credentials.from_env({'SHUTTERSTOCK_API_KEY': 'k', 'SHUTTERSTOCK_API_SECRET': 's'}).has_token
    from shutterstock_mcp.api import ShutterstockError

    with pytest.raises(ShutterstockError, match='developers/apps'):
        Credentials.from_env({'SHUTTERSTOCK_API_KEY': 'k'})
