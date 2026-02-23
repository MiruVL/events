import { useCallback } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Venue } from "../types";
import { useTranslation } from "../i18n";

// Fix default marker icons (Leaflet + bundler issue)
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

export interface MapBounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

interface VenueMapProps {
  venues: Venue[];
  onBoundsChange: (bounds: MapBounds) => void;
}

// Default center: Shibuya/Shinjuku area
const DEFAULT_CENTER: [number, number] = [35.664, 139.698];

/** Inner component that listens to map events */
function BoundsWatcher({ onBoundsChange }: { onBoundsChange: (bounds: MapBounds) => void }) {
  const emitBounds = useCallback(
    (map: L.Map) => {
      const b = map.getBounds();
      onBoundsChange({
        north: b.getNorth(),
        south: b.getSouth(),
        east: b.getEast(),
        west: b.getWest(),
      });
    },
    [onBoundsChange]
  );

  useMapEvents({
    moveend(e) {
      emitBounds(e.target);
    },
    zoomend(e) {
      emitBounds(e.target);
    },
    // Emit initial bounds when map loads
    load(e) {
      emitBounds(e.target);
    },
  });

  return null;
}

export default function VenueMap({ venues, onBoundsChange }: VenueMapProps) {
  const { t } = useTranslation();
  const venuesWithLocation = venues.filter(
    (v) => v.location && v.location.coordinates
  );

  const center: [number, number] =
    venuesWithLocation.length > 0
      ? [
          venuesWithLocation[0].location!.coordinates[1],
          venuesWithLocation[0].location!.coordinates[0],
        ]
      : DEFAULT_CENTER;

  return (
    <MapContainer
      center={center}
      zoom={13}
      className="venue-map"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      />
      <BoundsWatcher onBoundsChange={onBoundsChange} />
      {venuesWithLocation.map((venue) => (
        <Marker
          key={venue.id}
          position={[
            venue.location!.coordinates[1],
            venue.location!.coordinates[0],
          ]}
        >
          <Popup>
            <strong>{venue.name}</strong>
            {venue.address && <br />}
            {venue.address}
            {venue.rating && (
              <>
                <br />
                {t.rating} {venue.rating}
              </>
            )}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
