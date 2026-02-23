import { useState } from "react";
import type { EventFilters, Venue } from "../types";
import { useTranslation } from "../i18n";

interface FiltersProps {
  venues: Venue[];
  onApply: (filters: EventFilters) => void;
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Filters({ venues, onApply }: FiltersProps) {
  const { t } = useTranslation();
  const [venueId, setVenueId] = useState("");
  const [dateFrom, setDateFrom] = useState(todayStr());
  const [dateTo, setDateTo] = useState("");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [search, setSearch] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onApply({
      venue_id: venueId || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      price_min: priceMin ? Number(priceMin) : undefined,
      price_max: priceMax ? Number(priceMax) : undefined,
      search: search || undefined,
    });
  }

  function handleReset() {
    const today = todayStr();
    setVenueId("");
    setDateFrom(today);
    setDateTo("");
    setPriceMin("");
    setPriceMax("");
    setSearch("");
    onApply({ date_from: today });
  }

  return (
    <form className="filters" onSubmit={handleSubmit}>
      <div className="filter-row">
        <input
          type="text"
          placeholder={t.searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="filter-search"
        />
      </div>

      <div className="filter-row">
        <select value={venueId} onChange={(e) => setVenueId(e.target.value)}>
          <option value="">{t.allVenues}</option>
          {venues.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>

        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          placeholder={t.from}
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          placeholder={t.to}
        />
      </div>

      <div className="filter-row">
        <input
          type="number"
          placeholder={t.minPrice}
          value={priceMin}
          onChange={(e) => setPriceMin(e.target.value)}
          min={0}
          step={500}
        />
        <input
          type="number"
          placeholder={t.maxPrice}
          value={priceMax}
          onChange={(e) => setPriceMax(e.target.value)}
          min={0}
          step={500}
        />
        <button type="submit">{t.filter}</button>
        <button type="button" onClick={handleReset} className="btn-reset">
          {t.reset}
        </button>
      </div>
    </form>
  );
}
