export interface Venue {
  id: string;
  name: string;
  google_place_id?: string;
  location?: {
    type: string;
    coordinates: [number, number]; // [lng, lat]
  };
  address?: string;
  website?: string;
  google_maps_url?: string;
  rating?: number;
  default_image_url?: string;
  schedule_url?: string;
  scraping_strategy?: string;
}

export interface Event {
  id: string;
  venue_id: string;
  venue_name: string;
  title: string;
  date: string;
  time_open?: string;
  time_start?: string;
  price?: number;
  price_text?: string;
  artists: string[];
  image_url?: string;
  detail_url?: string;
}

export interface EventFilters {
  venue_id?: string;
  date_from?: string;
  date_to?: string;
  price_min?: number;
  price_max?: number;
  search?: string;
}
