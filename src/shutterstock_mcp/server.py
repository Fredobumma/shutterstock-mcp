"""The MCP server: Shutterstock's images, footage, music and editorial photos, as tools an assistant can use."""

from __future__ import annotations

import base64
import os
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .api import (
    PATHS,
    SUMMARIES,
    Credentials,
    Shutterstock,
    ShutterstockError,
    encode_file,
    summarize_image,
    summarize_page,
)

INSTRUCTIONS = """\
Search Shutterstock's library of photos, illustrations, vectors, video footage, music and editorial (news) photos.

Search results carry ids, short descriptions and preview links. Use view_preview to look at an image before
recommending it. Previews are watermarked; licensing gives the clean file, and spends the user's subscription, so
only license what the user has chosen. Editorial content is for news and commentary, not for advertising.
"""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
SPEND = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

Page = Annotated[int, Field(ge=1, description='Page of results, from 1.')]
PerPage = Annotated[int, Field(ge=1, le=50, description='Results per page, at most 50.')]
Query = Annotated[str, Field(description='What to look for. Use NOT to exclude a word: "beach NOT people".')]


def create_server(client: Shutterstock, *, licensing: bool = False) -> MCPServer:
    server = MCPServer('shutterstock', title='Shutterstock', version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ)
    async def search_images(
        query: Query,
        image_type: Literal['photo', 'illustration', 'vector'] | None = None,
        orientation: Literal['horizontal', 'vertical'] | None = None,
        color: Annotated[
            str | None, Field(description='A hex colour such as "1E90FF", or "grayscale"; finds images that use it.')
        ] = None,
        people_number: Annotated[int | None, Field(ge=0, description='Images with exactly this many people.')] = None,
        people_age: Literal['infants', 'children', 'teenagers', '20s', '30s', '40s', '50s', '60s', 'older']
        | None = None,
        license: Literal['commercial', 'editorial'] | None = None,
        sort: Literal['popular', 'relevance', 'newest', 'random'] = 'popular',
        safe: bool = True,
        page: Page = 1,
        per_page: PerPage = 20,
    ) -> dict[str, Any]:
        """Search Shutterstock photos, illustrations and vectors."""
        data = await client.request(
            'GET',
            '/images/search',
            params={
                'query': query,
                'image_type': image_type,
                'orientation': orientation,
                'color': color,
                'people_number': people_number,
                'people_age': people_age,
                'license': license,
                'sort': sort,
                'safe': safe,
                'page': page,
                'per_page': per_page,
            },
        )
        return summarize_page(data, 'image')

    @server.tool(annotations=READ)
    async def search_videos(
        query: Query,
        orientation: Literal['horizontal', 'vertical'] | None = None,
        resolution: Literal['4k', 'high_definition', 'standard_definition'] | None = None,
        aspect_ratio: Literal['16_9', '4_3', 'nonstandard'] | None = None,
        duration_from: Annotated[int | None, Field(ge=0, description='At least this many seconds long.')] = None,
        duration_to: Annotated[int | None, Field(ge=0, description='At most this many seconds long.')] = None,
        license: Literal['commercial', 'editorial'] | None = None,
        sort: Literal['popular', 'relevance', 'newest', 'random'] = 'popular',
        safe: bool = True,
        page: Page = 1,
        per_page: PerPage = 20,
    ) -> dict[str, Any]:
        """Search Shutterstock video footage."""
        data = await client.request(
            'GET',
            '/videos/search',
            params={
                'query': query,
                'orientation': orientation,
                'resolution': resolution,
                'aspect_ratio': aspect_ratio,
                'duration_from': duration_from,
                'duration_to': duration_to,
                'license': license,
                'sort': sort,
                'safe': safe,
                'page': page,
                'per_page': per_page,
            },
        )
        return summarize_page(data, 'video')

    @server.tool(annotations=READ)
    async def search_music(
        query: Annotated[str | None, Field(description='Words to match in titles, descriptions and keywords.')] = None,
        genre: Annotated[list[str] | None, Field(description='Genres, such as "Cinematic" or "Hip Hop".')] = None,
        moods: Annotated[list[str] | None, Field(description='Moods, such as "Uplifting" or "Dark".')] = None,
        instruments: Annotated[list[str] | None, Field(description='Instruments, such as "Piano".')] = None,
        instrumental: Annotated[bool | None, Field(description='Only tracks without vocals.')] = None,
        bpm_from: Annotated[int | None, Field(ge=1)] = None,
        bpm_to: Annotated[int | None, Field(ge=1)] = None,
        duration_from: Annotated[int | None, Field(ge=0, description='At least this many seconds long.')] = None,
        duration_to: Annotated[int | None, Field(ge=0, description='At most this many seconds long.')] = None,
        vocals: Literal['male', 'female'] | None = None,
        sort: Literal['score', 'ranking_all', 'freshness', 'bpm', 'duration', 'title', 'artist'] = 'score',
        page: Page = 1,
        per_page: PerPage = 20,
    ) -> dict[str, Any]:
        """Search Shutterstock's production music by mood, genre, tempo and length."""
        data = await client.request(
            'GET',
            '/audio/search',
            params={
                'query': query,
                'genre': genre,
                'moods': moods,
                'instruments': instruments,
                'is_instrumental': instrumental,
                'bpm_from': bpm_from,
                'bpm_to': bpm_to,
                'duration_from': duration_from,
                'duration_to': duration_to,
                'vocal_description': vocals,
                'sort': sort,
                'page': page,
                'per_page': per_page,
            },
        )
        return summarize_page(data, 'music')

    @server.tool(annotations=READ)
    async def search_editorial(
        query: Query,
        country: Annotated[
            str,
            Field(
                pattern='^[A-Za-z]{3}$',
                description='Where the images would be published, as a three-letter code such as USA, GBR or NGA; '
                'editorial rights vary by country.',
            ),
        ] = 'USA',
        date_start: Annotated[str | None, Field(description='Taken on or after this date, YYYY-MM-DD.')] = None,
        date_end: Annotated[str | None, Field(description='Taken on or before this date, YYYY-MM-DD.')] = None,
        sort: Literal['relevant', 'newest', 'oldest'] = 'relevant',
        per_page: PerPage = 20,
        cursor: Annotated[str | None, Field(description='The next_cursor of the previous page.')] = None,
    ) -> dict[str, Any]:
        """Search editorial photos of news, sport, entertainment and events, for news and commentary."""
        data = await client.request(
            'GET',
            '/editorial/images/search',
            params={
                'query': query,
                'country': country.upper(),
                'date_start': date_start,
                'date_end': date_end,
                'sort': sort,
                'per_page': per_page,
                'cursor': cursor,
            },
        )
        return summarize_page(data, 'editorial')

    @server.tool(annotations=READ)
    async def get_asset(
        asset_type: Literal['image', 'video', 'music', 'editorial'],
        id: Annotated[str, Field(description='The id from a search result.')],
        country: Annotated[str, Field(description='For editorial: where it would be published.')] = 'USA',
    ) -> dict[str, Any]:
        """Get the full details of one image, video, track or editorial photo."""
        params: dict[str, Any] = {'view': 'full'} if asset_type != 'editorial' else {'country': country.upper()}
        data = await client.request('GET', f'/{PATHS[asset_type]}/{id}', params=params)
        return SUMMARIES[asset_type](data)

    @server.tool(annotations=READ)
    async def find_similar(
        asset_type: Literal['image', 'video'],
        id: Annotated[str, Field(description='The id of the image or video to find more like.')],
        page: Page = 1,
        per_page: PerPage = 20,
    ) -> dict[str, Any]:
        """Find images or videos that look like one you already have from Shutterstock."""
        data = await client.request(
            'GET', f'/{PATHS[asset_type]}/{id}/similar', params={'page': page, 'per_page': per_page}
        )
        return summarize_page(data, asset_type)

    @server.tool(annotations=READ)
    async def reverse_image_search(
        image_path: Annotated[
            str | None, Field(description='A JPEG or PNG file on this computer, up to 10 MB.')
        ] = None,
        image_url: Annotated[str | None, Field(description='Or the URL of a JPEG or PNG.')] = None,
        license: Literal['commercial', 'editorial'] = 'commercial',
        per_page: PerPage = 20,
    ) -> dict[str, Any]:
        """Find Shutterstock images that look like one of your own: a sketch, a mood board, a photo to replace."""
        if bool(image_path) == bool(image_url):
            raise ShutterstockError('give either image_path or image_url')
        if image_path:
            encoded = encode_file(image_path)
        else:
            data, _ = await client.fetch_bytes(str(image_url))
            encoded = base64.b64encode(data).decode()
        upload = await client.request('POST', '/cv/images', json={'base64_image': encoded})
        data = await client.request(
            'GET',
            '/cv/similar/images',
            params={'asset_id': upload['upload_id'], 'license': license, 'per_page': per_page},
        )
        return summarize_page(data, 'image')

    @server.tool(annotations=READ)
    async def view_preview(
        id: Annotated[str, Field(description='The id of an image or editorial photo.')],
        asset_type: Literal['image', 'editorial'] = 'image',
        country: Annotated[str, Field(description='For editorial: where it would be published.')] = 'USA',
    ) -> Image:
        """Look at the watermarked preview of an image, to judge whether it fits."""
        params: dict[str, Any] = {'view': 'full'} if asset_type == 'image' else {'country': country.upper()}
        data = await client.request('GET', f'/{PATHS[asset_type]}/{id}', params=params)
        summary = SUMMARIES[asset_type](data)
        url = summary.get('preview') or summary.get('thumbnail')
        if not url:
            raise ShutterstockError(f'{asset_type} {id} has no preview')
        content, mime = await client.fetch_bytes(str(url))
        return Image(data=content, format=mime.split('/')[-1])

    # ---- the user's account ------------------------------------------------------------------------------------

    @server.tool(annotations=READ)
    async def list_subscriptions() -> dict[str, Any]:
        """List the user's Shutterstock subscriptions: what they can license, and how much is left."""
        client.require_token('Listing subscriptions', 'user.view')
        data = await client.request('GET', '/user/subscriptions')
        subscriptions = []
        for item in data.get('data', []):
            allotment = item.get('allotment') or {}
            subscriptions.append(
                {
                    'id': item.get('id'),
                    'description': item.get('description'),
                    'asset_type': item.get('asset_type'),
                    'license': item.get('license'),
                    'expires': item.get('expiration_time'),
                    'downloads_left': allotment.get('downloads_left'),
                    'downloads_limit': allotment.get('downloads_limit'),
                    'sizes': sorted(
                        {str(f['size']) for f in item.get('formats') or [] if isinstance(f, dict) and f.get('size')}
                    ),
                }
            )
        return {'subscriptions': subscriptions}

    @server.tool(annotations=READ)
    async def list_licenses(
        asset_type: Literal['image', 'video', 'music', 'editorial'] = 'image', page: Page = 1, per_page: PerPage = 20
    ) -> dict[str, Any]:
        """List what the user has licensed before, newest first, to reuse it rather than license it again."""
        client.require_token('Listing licenses', 'licenses.view')
        data = await client.request(
            'GET', f'/{PATHS[asset_type]}/licenses', params={'page': page, 'per_page': per_page}
        )
        licenses = []
        for item in data.get('data', []):
            asset = item.get(asset_type if asset_type != 'music' else 'audio') or item.get('image') or {}
            licenses.append(
                {
                    'license_id': item.get('id'),
                    'asset_id': asset.get('id') if isinstance(asset, dict) else None,
                    'licensed_at': item.get('download_time') or item.get('date'),
                    'license': item.get('license'),
                    'subscription_id': item.get('subscription_id'),
                    'user': (item.get('user') or {}).get('username'),
                }
            )
        return {'total': data.get('total_count'), 'page': data.get('page'), 'licenses': licenses}

    @server.tool(annotations=READ)
    async def list_collections() -> dict[str, Any]:
        """List the user's image collections, the lightboxes a team uses to share picks."""
        client.require_token('Collections', 'collections.view')
        data = await client.request('GET', '/images/collections', params={'per_page': 50})
        return {
            'collections': [
                {'id': c.get('id'), 'name': c.get('name'), 'items': c.get('total_item_count')}
                for c in data.get('data', [])
            ]
        }

    @server.tool(annotations=READ)
    async def get_collection(collection_id: str, page: Page = 1, per_page: PerPage = 50) -> dict[str, Any]:
        """List the images in one of the user's collections."""
        client.require_token('Collections', 'collections.view')
        collection = await client.request('GET', f'/images/collections/{collection_id}')
        items = await client.request(
            'GET', f'/images/collections/{collection_id}/items', params={'page': page, 'per_page': per_page}
        )
        ids = [str(i.get('id')) for i in items.get('data', []) if i.get('id')]
        images: list[dict[str, Any]] = []
        if ids:
            details = await client.request('GET', '/images', params={'id': ids})
            images = [summarize_image(i) for i in details.get('data', [])]
        return {
            'id': collection.get('id'),
            'name': collection.get('name'),
            'total': collection.get('total_item_count'),
            'images': images,
        }

    @server.tool(annotations=WRITE)
    async def create_collection(name: Annotated[str, Field(min_length=1, max_length=100)]) -> dict[str, Any]:
        """Create an image collection."""
        client.require_token('Collections', 'collections.edit')
        data = await client.request('POST', '/images/collections', json={'name': name})
        return {'id': data.get('id'), 'name': name}

    @server.tool(annotations=WRITE)
    async def add_to_collection(
        collection_id: str,
        image_ids: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Add images to one of the user's collections."""
        client.require_token('Collections', 'collections.edit')
        await client.request(
            'POST', f'/images/collections/{collection_id}/items', json={'items': [{'id': i} for i in image_ids]}
        )
        return {'collection_id': collection_id, 'added': image_ids}

    if licensing:

        @server.tool(annotations=SPEND)
        async def license_asset(
            asset_type: Literal['image', 'video', 'music', 'editorial'],
            id: str,
            subscription_id: Annotated[
                str | None, Field(description='Which subscription to charge; see list_subscriptions.')
            ] = None,
            size: Annotated[
                str | None,
                Field(description='Image: small, medium, huge or vector. Video: web, sd, hd or 4k.'),
            ] = None,
            search_id: Annotated[str | None, Field(description='The search_id of the search it came from.')] = None,
            country: Annotated[str, Field(description='For editorial: where it will be published.')] = 'USA',
            editorial_acknowledgement: Annotated[
                bool, Field(description='For editorial: the user confirms it is for news or commentary use.')
            ] = False,
        ) -> dict[str, Any]:
            """
            License an asset with the user's subscription and get the download link. This spends the user's
            downloads or credits and cannot be undone: only license what the user has chosen.
            """
            client.require_token('Licensing', 'licenses.create')
            if asset_type == 'image':
                body: dict[str, Any] = {
                    'images': [
                        _clean(
                            {
                                'image_id': id,
                                'subscription_id': subscription_id,
                                'size': size,
                                'search_id': search_id,
                            }
                        )
                    ]
                }
                path = '/images/licenses'
            elif asset_type == 'video':
                body = {
                    'videos': [
                        _clean(
                            {
                                'video_id': id,
                                'subscription_id': subscription_id,
                                'size': size,
                                'search_id': search_id,
                            }
                        )
                    ]
                }
                path = '/videos/licenses'
            elif asset_type == 'music':
                body = {'audio': [_clean({'audio_id': id, 'search_id': search_id})]}
                path = '/audio/licenses'
            else:
                if not editorial_acknowledgement:
                    raise ShutterstockError(
                        'editorial content is for news and commentary; set editorial_acknowledgement once the user '
                        'has confirmed that is the use'
                    )
                body = {
                    'country': country.upper(),
                    'editorial': [_clean({'editorial_id': id, 'license': 'premier_editorial_comp', 'size': size})],
                }
                path = '/editorial/images/licenses'
            data = await client.request(
                'POST', path, json=body, params={'subscription_id': subscription_id} if subscription_id else None
            )
            results = []
            for item in data.get('data', []):
                results.append(
                    _clean(
                        {
                            'asset_id': id,
                            'license_id': item.get('license_id'),
                            'download_url': (item.get('download') or {}).get('url'),
                            'credits_used': item.get('allotment_charge'),
                            'error': item.get('error'),
                        }
                    )
                )
            return {'licenses': results, 'note': 'Download links expire after a few hours.'}

    return server


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def main() -> None:
    try:
        credentials = Credentials.from_env()
    except ShutterstockError as e:
        raise SystemExit(f'shutterstock-mcp: {e}') from None
    licensing = os.environ.get('SHUTTERSTOCK_ENABLE_LICENSING', '').lower() in ('1', 'true', 'yes')
    create_server(Shutterstock(credentials), licensing=licensing).run('stdio')
