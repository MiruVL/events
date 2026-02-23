import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchVenues, fetchEvents } from "./api";
import type { Venue, Event, EventFilters } from "./types";
import type { MapBounds } from "./components/VenueMap";
import Filters from "./components/Filters";
import EventList from "./components/EventList";
import VenueMap from "./components/VenueMap";
import { useTranslation } from "./i18n";
import "./App.css";

export default function App() {
  const { t, locale, setLocale } = useTranslation();
  const [venues, setVenues] = useState<Venue[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<EventFilters>(() => {
    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { date_from: today };
  });

  useEffect(() => {
    document.title = t.htmlTitle;
  }, [t.htmlTitle]);

  const [mapOpen, setMapOpen] = useState(false);
  const [mapBounds, setMapBounds] = useState<MapBounds | null>(null);

  useEffect(() => {
    fetchVenues().then(setVenues).catch(console.error);
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchEvents(filters)
      .then(setEvents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filters]);

  // Build a set of venue IDs visible in the current map bounds
  const visibleVenueIds = useMemo(() => {
    if (!mapOpen || !mapBounds) return null; // null = no map filtering
    const ids = new Set<string>();
    for (const v of venues) {
      if (!v.location?.coordinates) continue;
      const [lng, lat] = v.location.coordinates;
      if (
        lat >= mapBounds.south &&
        lat <= mapBounds.north &&
        lng >= mapBounds.west &&
        lng <= mapBounds.east
      ) {
        ids.add(v.id);
      }
    }
    return ids;
  }, [mapOpen, mapBounds, venues]);

  // Filter events by map bounds (client-side)
  const displayedEvents = useMemo(() => {
    if (!visibleVenueIds) return events; // map closed or no bounds yet
    return events.filter((e) => visibleVenueIds.has(e.venue_id));
  }, [events, visibleVenueIds]);

  const handleBoundsChange = useCallback((bounds: MapBounds) => {
    setMapBounds(bounds);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>{t.pageTitle}</h1>
        <div className="lang-toggle">
          <button
            className={locale === "en" ? "lang-active" : ""}
            onClick={() => setLocale("en")}
          >
            EN
          </button>
          <span className="lang-sep">|</span>
          <button
            className={locale === "ja" ? "lang-active" : ""}
            onClick={() => setLocale("ja")}
          >
            JA
          </button>
        </div>
      </header>

      <Filters venues={venues} onApply={setFilters} />

      {/* Map toggle + collapsible map */}
      <div className="map-section">
        <button
          className={`map-toggle ${mapOpen ? "active" : ""}`}
          onClick={() => setMapOpen((v) => !v)}
        >
          {mapOpen ? t.hideMap : t.showMap}
        </button>

        {mapOpen && (
          <div className="map-container">
            <VenueMap venues={venues} onBoundsChange={handleBoundsChange} />
            <div className="map-hint">
              {t.mapHint}
            </div>
          </div>
        )}
      </div>

      <main className="app-main">
        <EventList events={displayedEvents} loading={loading} />
      </main>
    </div>
  );
}
