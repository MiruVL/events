import type { Venue, Event, EventFilters } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function fetchVenues(): Promise<Venue[]> {
  const res = await fetch(`${API_BASE}/venues`);
  if (!res.ok) throw new Error("Failed to fetch venues");
  return res.json();
}

export async function fetchEvents(filters: EventFilters = {}): Promise<Event[]> {
  const params = new URLSearchParams();
  if (filters.venue_id) params.set("venue_id", filters.venue_id);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.price_min != null) params.set("price_min", String(filters.price_min));
  if (filters.price_max != null) params.set("price_max", String(filters.price_max));
  if (filters.search) params.set("search", filters.search);

  const res = await fetch(`${API_BASE}/events?${params}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}
