"""Individual OSINT crawler source modules.

Each module exposes `async def search(query: str, client: httpx.AsyncClient,
limit: int) -> list[dict]` returning a list of
{"title", "url", "snippet", "published_at", "source"} dicts. See
app/crawler/collector.py for how these are fanned out concurrently and
merged.
"""
