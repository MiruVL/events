import { useState } from "react";
import type { Event } from "../types";

interface EventListProps {
  events: Event[];
  loading: boolean;
}

export default function EventList({ events, loading }: EventListProps) {
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  if (loading) {
    return <div className="loading">Loading events...</div>;
  }

  if (events.length === 0) {
    return <div className="empty">No events found.</div>;
  }

  // Group events by date
  const grouped = events.reduce<Record<string, Event[]>>((acc, event) => {
    (acc[event.date] ??= []).push(event);
    return acc;
  }, {});

  return (
    <>
      {/* Lightbox overlay */}
      {lightboxUrl && (
        <div className="lightbox" onClick={() => setLightboxUrl(null)}>
          <img src={lightboxUrl} alt="" />
          <button
            className="lightbox-close"
            onClick={() => setLightboxUrl(null)}
          >
            &times;
          </button>
        </div>
      )}

      <div className="event-grid-wrapper">
        {Object.entries(grouped).map(([date, dateEvents]) => (
          <div key={date} className="date-group">
            <h2 className="date-heading">{formatDateHeading(date)}</h2>
            <div className="event-grid">
              {dateEvents.map((event) => (
                <div key={event.id} className="event-card">
                  {/* Date badge */}
                  <div className="card-date-badge">
                    <span className="card-date-year">
                      {event.date.slice(0, 4)}
                    </span>
                    <span className="card-date-month">
                      {String(Number(event.date.slice(5, 7))).padStart(2, "0")}
                    </span>
                    <span className="card-date-day">
                      {String(Number(event.date.slice(8, 10))).padStart(2, "0")}
                    </span>
                    <span className="card-date-dow">
                      {getDow(event.date)}
                    </span>
                  </div>

                  {/* Image */}
                  {event.image_url ? (
                    <div
                      className="card-image"
                      onClick={() => setLightboxUrl(event.image_url!)}
                    >
                      <img src={event.image_url} alt={event.title} loading="lazy" />
                    </div>
                  ) : (
                    <div className="card-image card-image-empty" />
                  )}

                  {/* Info */}
                  <div className="card-info">
                    <h3 className="card-title">
                      {event.detail_url ? (
                        <a
                          href={event.detail_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {event.title}
                        </a>
                      ) : (
                        event.title
                      )}
                    </h3>
                    <div className="card-venue">{event.venue_name}</div>
                    {event.artists.length > 0 && (
                      <div className="card-artists">
                        {event.artists.slice(0, 3).map((artist, i) => (
                          <span key={i} className="card-artist">
                            {artist}
                          </span>
                        ))}
                        {event.artists.length > 3 && (
                          <span className="card-artist card-artist-more">...</span>
                        )}
                      </div>
                    )}
                    <div className="card-meta">
                      {event.time_open && (
                        <span className="card-time">
                          OPEN {event.time_open}
                          {event.time_start && ` / START ${event.time_start}`}
                        </span>
                      )}
                      {event.price_text && (
                        <span className="card-price">{event.price_text}</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function getDow(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][d.getDay()];
}

function formatDateHeading(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const days = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")} ${days[d.getDay()]}`;
}
