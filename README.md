# Live-house Event Aggregator

Scrapes live-house (music venue) websites to collect event information. Filter events by date, location, and price to see what's going on around you.

## Architecture

- **Crawl4AI** crawls venue schedule pages into markdown
- **Local LLM** (Qwen3-14B via LM Studio) extracts structured event data from the markdown
- **MongoDB** stores venues and events
- **FastAPI** serves a REST API
- **React + Leaflet** frontend for browsing and filtering events on a map

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- MongoDB (running locally or remote)
- LLM openAI API
- Node.js 20+ and npm (for the frontend)
- Google Maps API key (Places API enabled)

## Setup

### 1. Install Python dependencies

```bash
uv sync
```

This creates a `.venv` and installs everything from `pyproject.toml`.

### 2. Install Playwright browser (required by Crawl4AI)

```bash
uv run crawl4ai-setup
uv run python -m playwright install chromium
```

### 3. Configure environment

Copy the example and fill in your values:

```bash
cp .env.example .env
```

`.env` fields:

| Variable | Description |
|---|---|
| `MONGODB_URI` | MongoDB connection string (default: `mongodb://localhost:27017`) |
| `MONGODB_DB` | Database name (default: `events_app`) |
| `GOOGLE_MAPS_API_KEY` | Google Cloud API key with Places API enabled |
| `LLM_BASE_URL` | LM Studio server URL (e.g. `http://192.168.1.100:1234/v1`) |
| `LLM_MODEL` | Model identifier as shown in LM Studio (e.g. `qwen/qwen3-14b`) |

### 4. Install frontend dependencies

```bash
cd frontend
npm install
```

### 5. LM Studio setup

1. Download **Qwen3-14B** (Q4_K_M quantization) in LM Studio
2. Set context length to **32768** and GPU offload to max
3. Load the model and start the server
4. Enable "Allow remote connections" if running on a different PC

## Usage

### Adding a venue

Search Google Maps and save to MongoDB:

```bash
uv run python -m app.venue_loader "新宿SAMURAI"
```

### Configuring a venue

List all venues and their IDs:

```bash
uv run python -m app.venue_config list
```

Set scraping config for a venue (interactive prompts):

```bash
uv run python -m app.venue_config configure <venue_id>
```

You will be asked for:
- **Schedule URL** -- the page listing events by month
- **Strategy** -- `schedule_only` if all event info is on the schedule page, `schedule_and_detail` if you need to follow links to individual event pages
- **Extra instructions** -- optional notes for the LLM about site-specific quirks
- **Default image URL** -- fallback image for events without a flyer

### Testing a crawl

Crawl a URL and inspect the markdown output:

```bash
uv run python -m app.scraper "https://example.com/schedule/"
```

Cached results are saved in `crawl_cache/`.

### Testing LLM extraction

Run extraction on a cached crawl file:

```bash
uv run python -m app.extractor crawl_cache/some_file.md "Venue Name"
```

### Running the scraping pipeline

Scrape all configured venues:

```bash
uv run python -m app.pipeline
```

Scrape a specific venue (partial name match):

```bash
uv run python -m app.pipeline "SAMURAI"
```

Use `--no-cache` to force re-crawling:

```bash
uv run python -m app.pipeline --no-cache
```

Scrape current and next month (e.g. for venues with JS month switch):

```bash
uv run python -m app.pipeline "BREATH" --months 2
```

### Starting the app

Backend (API on port 8000):

```bash
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Frontend (dev server on port 5173):

```bash
cd frontend
npm run dev
```

API docs are at http://localhost:8000/docs.

## Project structure

```
app/
  config.py          Settings from .env
  models.py          Pydantic models (Venue, Event)
  db.py              MongoDB connection and indexes
  venue_loader.py    Google Maps -> MongoDB
  venue_config.py    CLI to configure venue scraping fields
  scraper.py         Crawl4AI page crawler
  extractor.py       LLM event extraction (LM Studio / OpenAI-compatible API)
  pipeline.py        Full scrape pipeline (crawl + extract + save)
  api.py             FastAPI REST API
frontend/
  src/
    App.tsx          Main app with list/map toggle
    api.ts           API client
    types.ts         TypeScript interfaces
    components/
      Filters.tsx    Date/price/venue/search filters
      EventList.tsx  Event cards with images
      VenueMap.tsx   Leaflet map with venue markers
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/venues` | List venues (optional geo filter: `lat`, `lng`, `radius_km`) |
| GET | `/venues/:id` | Single venue |
| GET | `/events` | List events (filters: `venue_id`, `date_from`, `date_to`, `price_min`, `price_max`, `search`) |
| GET | `/events/:id` | Single event |
