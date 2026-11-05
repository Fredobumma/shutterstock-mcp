# shutterstock-mcp

<!-- mcp-name: io.github.Fredobumma/shutterstock-mcp -->

An MCP server for [Shutterstock](https://www.shutterstock.com). It lets Claude and other assistants search Shutterstock's photos, illustrations, vectors, video footage, music and editorial news photos, look at previews, find similar images, keep picks in collections, and, if you turn it on, license what you've chosen with your own subscription.

## Why

Finding the right stock asset is slow, manual work: search, scroll, preview, compare, search again. An assistant helping with a design, a deck, a video edit or an article can't reach Shutterstock at all. Shutterstock has no official MCP server, and what exists is a demo that returns page links.

## What you can ask for

- "Find warm, candid photos of a small team in an office, no faces, landscape, that would work on a dark website header." The assistant searches, looks at the previews, and shows you the ones that fit.
- "Find a 15 to 30 second drone shot of a coastline in 4K, and an uplifting instrumental track around 100 BPM to go under it."
- "Find editorial photos of last night's final for the match report."
- "Here's a sketch of the layout we want. Find stock photos that look like it." This is reverse image search, from a file or a URL.
- "Find more like this one." That works for images and video.
- "Put these five in the *Spring campaign* collection" for the team to review.
- "License the second one at full size." This needs licensing turned on; see below.

## Setup

1. Create a free app at [shutterstock.com/account/developers/apps](https://www.shutterstock.com/account/developers/apps). Its **key and secret** are enough to search.
2. For collections, license history and licensing, the server also needs an **OAuth access token** for your account. You can generate one from the same app page, with the scopes you want: `user.view`, `collections.view`, `collections.edit`, `licenses.view` and `licenses.create`.

### Claude Code

```sh
claude mcp add shutterstock -e SHUTTERSTOCK_API_KEY=… -e SHUTTERSTOCK_API_SECRET=… -- uvx shutterstock-mcp
```

### Claude Desktop, Cursor and others

```json
{
  "mcpServers": {
    "shutterstock": {
      "command": "uvx",
      "args": ["shutterstock-mcp"],
      "env": {
        "SHUTTERSTOCK_API_KEY": "…",
        "SHUTTERSTOCK_API_SECRET": "…"
      }
    }
  }
}
```

With an OAuth token, set `SHUTTERSTOCK_API_TOKEN` instead of the key and secret.

### Licensing

Licensing spends your subscription's downloads or credits and can't be undone, so the `license_asset` tool doesn't exist unless you set `SHUTTERSTOCK_ENABLE_LICENSING=true`. When it's on, it's marked as destructive, so clients that respect tool hints ask you before each use. Editorial photos are licensed only once you've confirmed they're for news or commentary.

## Tools

| Tool | Needs | |
| --- | --- | --- |
| `search_images` | key | Photos, illustrations and vectors, by orientation, colour, people, licence and more |
| `search_videos` | key | Footage, by resolution, length, aspect ratio and orientation |
| `search_music` | key | Tracks, by genre, mood, instruments, tempo, length and vocals |
| `search_editorial` | key | News, sport and entertainment photos, by date, cleared for a country |
| `get_asset` | key | Full details of one asset |
| `find_similar` | key | More images or videos like one from Shutterstock |
| `reverse_image_search` | key | Shutterstock images like one of your own |
| `view_preview` | key | The watermarked preview, as an image the assistant can look at |
| `list_subscriptions` | token | Your subscriptions and what's left on them |
| `list_licenses` | token | What you've licensed before |
| `list_collections`, `get_collection` | token | Your collections and what's in them |
| `create_collection`, `add_to_collection` | token | Make and fill collections |
| `license_asset` | token, opt-in | License an image, clip, track or editorial photo |

Free Shutterstock apps search a smaller part of the library, see only the first results of a search, and are limited to about 100 requests an hour.

## Status

Built from Shutterstock's API reference and its official SDK's models, checked against the live API, and tested against a fake of the API that checks what the server sends, through a real MCP client. If something doesn't match, please [open an issue](https://github.com/fredobumma/shutterstock-mcp/issues).

## Development

```sh
uv venv && uv pip install -e . pytest anyio ruff mypy
pytest && ruff check . && mypy
```

## License

MIT. Not affiliated with Shutterstock. Shutterstock is a trademark of Shutterstock, Inc.
