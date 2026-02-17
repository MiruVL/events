"""Custom venue scraping scripts.

Each script in this directory handles a venue that requires site-specific
logic (JS execution, special auth, image enrichment, etc.).

Convention
----------
Every script must expose an async ``run`` function with this signature::

    async def run(venue: dict, *, use_cache: bool = True, **kwargs) -> list[Event]:
        ...

- ``venue``: the raw MongoDB venue document (dict).
- ``use_cache``: honour the crawl cache when True.
- ``**kwargs``: extra keyword arguments from ``venue["custom_kwargs"]``.

The function must return a ``list[app.models.Event]``.

Scripts have full access to ``app.scraper``, ``app.extractor``, and any
third-party library installed in the project.
"""
