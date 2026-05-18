"use client";

import { useEffect, useCallback, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, useMap } from "react-leaflet";
import L from "leaflet";

// Fix Leaflet default marker icon (webpack breaks asset URLs)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

interface MapViewerProps {
  geoData: GeoJSON.FeatureCollection;
}

/** Invalidate map size after mount so tiles render correctly */
function InvalidateSize() {
  const map = useMap();
  useEffect(() => {
    // Small delay to let the container fully render
    const timer = setTimeout(() => map.invalidateSize(), 200);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

/** Auto-fit map bounds to data extent */
function FitBounds({
  geoData,
  onBoundsReady,
}: {
  geoData: GeoJSON.FeatureCollection;
  onBoundsReady: (bounds: L.LatLngBounds) => void;
}) {
  const map = useMap();
  useEffect(() => {
    if (geoData?.features?.length > 0) {
      const layer = L.geoJSON(geoData);
      const bounds = layer.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50] });
        onBoundsReady(bounds);
      }
    }
  }, [geoData, map, onBoundsReady]);
  return null;
}

/** Map control buttons (zoom, reset) */
function MapControls({
  dataBounds,
}: {
  dataBounds: L.LatLngBounds | null;
}) {
  const map = useMap();

  const zoomIn = () => map.zoomIn();
  const zoomOut = () => map.zoomOut();
  const resetView = () => {
    if (dataBounds && dataBounds.isValid()) {
      map.fitBounds(dataBounds, { padding: [50, 50] });
    } else {
      map.setView([32.0, -100.0], 5);
    }
  };

  const btnClass =
    "w-8 h-8 flex items-center justify-center bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 active:bg-gray-100 text-base font-bold leading-none select-none";

  return (
    <div className="absolute top-3 left-3 z-[1000] flex flex-col rounded-lg overflow-hidden shadow">
      <button type="button" onClick={zoomIn} title="Zoom in" className={`${btnClass} rounded-t-lg border-b-0`}>
        +
      </button>
      <button type="button" onClick={zoomOut} title="Zoom out" className={`${btnClass} border-b-0`}>
        &minus;
      </button>
      <button type="button" onClick={resetView} title="Reset view" className={`${btnClass} rounded-b-lg text-sm`}>
        &#8962;
      </button>
    </div>
  );
}

export default function MapViewer({ geoData }: MapViewerProps) {
  const featureCount = geoData?.features?.length ?? 0;
  const [dataBounds, setDataBounds] = useState<L.LatLngBounds | null>(null);

  const handleBoundsReady = useCallback((bounds: L.LatLngBounds) => {
    setDataBounds(bounds);
  }, []);

  const onEachFeature = (
    feature: GeoJSON.Feature,
    layer: L.Layer
  ) => {
    if (feature.properties) {
      const rows = Object.entries(feature.properties)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .slice(0, 20)
        .map(
          ([k, v]) =>
            `<tr><td style="font-weight:600;padding-right:8px;white-space:nowrap">${k}</td><td>${v}</td></tr>`
        )
        .join("");
      layer.bindPopup(`<table style="font-size:12px">${rows}</table>`, {
        maxWidth: 320,
        maxHeight: 250,
      });
    }
  };

  const pointToLayer = (_: GeoJSON.Feature, latlng: L.LatLng) => {
    return L.circleMarker(latlng, {
      radius: 5,
      fillColor: "#3b82f6",
      color: "#1e40af",
      weight: 1,
      opacity: 1,
      fillOpacity: 0.7,
    });
  };

  return (
    <div className="relative w-full h-full">
      {/* Point count badge */}
      <div className="absolute top-3 right-3 z-[1000] bg-white/90 backdrop-blur px-3 py-1.5 rounded-lg shadow text-xs font-medium text-gray-700">
        {featureCount.toLocaleString()} features
      </div>

      <MapContainer
        center={[32.0, -100.0]}
        zoom={5}
        zoomControl={false}
        className="w-full h-full"
        style={{ minHeight: "500px", background: "#f8fafc" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {geoData && (
          <GeoJSON
            key={JSON.stringify(geoData).slice(0, 100)}
            data={geoData}
            onEachFeature={onEachFeature}
            pointToLayer={pointToLayer}
          />
        )}
        <InvalidateSize />
        <FitBounds geoData={geoData} onBoundsReady={handleBoundsReady} />
        <MapControls dataBounds={dataBounds} />
      </MapContainer>
    </div>
  );
}
