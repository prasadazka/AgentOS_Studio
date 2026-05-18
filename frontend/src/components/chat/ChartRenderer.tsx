"use client";

import { useState, useRef, useCallback } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Maximize2, Minimize2, Download } from "lucide-react";

const COLORS = [
  "#4285F4", "#EA4335", "#34A853", "#FBBC04", "#8AB4F8",
  "#F28B82", "#81C995", "#FDD663", "#A8DAB5", "#F6AEA9",
];

interface ChartData {
  type: "bar" | "line" | "area" | "pie" | "scatter";
  title?: string;
  xLabel?: string;
  yLabel?: string;
  data: Record<string, unknown>[];
}

export default function ChartRenderer({ json }: { json: string }) {
  const [expanded, setExpanded] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  const handleDownload = useCallback(() => {
    const container = chartRef.current;
    if (!container) return;
    const svg = container.querySelector("svg");
    if (!svg) return;

    // Get actual rendered dimensions
    const bbox = svg.getBoundingClientRect();
    const svgW = bbox.width;
    const svgH = bbox.height;

    const svgClone = svg.cloneNode(true) as SVGSVGElement;

    // Set explicit dimensions (Recharts uses responsive sizing which is lost on clone)
    svgClone.setAttribute("width", String(svgW));
    svgClone.setAttribute("height", String(svgH));
    svgClone.removeAttribute("style");

    // Inline all computed styles so they survive serialization
    const origElements = svg.querySelectorAll("*");
    const cloneElements = svgClone.querySelectorAll("*");
    origElements.forEach((origEl, i) => {
      const cloneEl = cloneElements[i];
      if (!cloneEl) return;
      const computed = window.getComputedStyle(origEl);
      const important = [
        "fill", "stroke", "stroke-width", "stroke-dasharray",
        "font-family", "font-size", "font-weight", "text-anchor",
        "dominant-baseline", "opacity", "fill-opacity", "stroke-opacity",
        "visibility", "display",
      ];
      for (const prop of important) {
        const val = computed.getPropertyValue(prop);
        if (val) (cloneEl as SVGElement).style.setProperty(prop, val);
      }
    });

    // Add white background
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", String(svgW));
    rect.setAttribute("height", String(svgH));
    rect.setAttribute("fill", "white");
    svgClone.insertBefore(rect, svgClone.firstChild);

    const svgData = new XMLSerializer().serializeToString(svgClone);
    const svgBlob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    const img = new Image();
    img.onload = () => {
      const scale = 2; // retina quality
      const canvas = document.createElement("canvas");
      canvas.width = svgW * scale;
      canvas.height = svgH * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, svgW, svgH);
      URL.revokeObjectURL(url);

      canvas.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement("a");
        link.download = `${chart.title || "chart"}.png`;
        link.href = URL.createObjectURL(blob);
        link.click();
        URL.revokeObjectURL(link.href);
      }, "image/png");
    };
    img.onerror = () => {
      // Fallback: download as SVG if PNG conversion fails
      URL.revokeObjectURL(url);
      const link = document.createElement("a");
      link.download = `${chart.title || "chart"}.svg`;
      link.href = URL.createObjectURL(svgBlob);
      link.click();
      URL.revokeObjectURL(link.href);
    };
    img.src = url;
  }, []);

  let chart: ChartData;
  try {
    chart = JSON.parse(json);
  } catch {
    return (
      <div className="text-xs text-red-500 bg-red-50 rounded-lg p-3">
        Invalid chart data
      </div>
    );
  }

  if (!chart.data || !Array.isArray(chart.data) || chart.data.length === 0) {
    return (
      <div className="text-xs text-gray-400 bg-gray-50 rounded-lg p-3">
        No chart data
      </div>
    );
  }

  // Coerce numeric strings to actual numbers in all data items
  const data = chart.data.map((item) => {
    const cleaned: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(item)) {
      if (k !== "name" && typeof v === "string" && v !== "" && !isNaN(Number(v))) {
        cleaned[k] = Number(v);
      } else {
        cleaned[k] = v;
      }
    }
    return cleaned;
  });
  chart = { ...chart, data };

  // Detect numeric keys (series) from first data item, excluding "name"
  const sampleItem = chart.data[0];
  const numericKeys = Object.keys(sampleItem).filter(
    (k) => k !== "name" && typeof sampleItem[k] === "number"
  );

  const height = expanded ? 420 : 260;
  const width = "100%";

  function renderChart() {
    switch (chart.type) {
      case "pie":
        return (
          <ResponsiveContainer width={width} height={height}>
            <PieChart>
              <Pie
                data={chart.data}
                dataKey={numericKeys[0] || "value"}
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={expanded ? 140 : 90}
                label={(props) =>
                  `${props.name ?? ""}: ${(((props.percent as number) ?? 0) * 100).toFixed(0)}%`
                }
                labelLine={false}
              >
                {chart.data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );

      case "line":
        return (
          <ResponsiveContainer width={width} height={height}>
            <LineChart data={chart.data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8EAED" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} label={chart.xLabel ? { value: chart.xLabel, position: "insideBottom", offset: -5, fontSize: 11 } : undefined} />
              <YAxis tick={{ fontSize: 11 }} label={chart.yLabel ? { value: chart.yLabel, angle: -90, position: "insideLeft", fontSize: 11 } : undefined} />
              <Tooltip />
              {numericKeys.length > 1 && <Legend />}
              {numericKeys.map((key, i) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case "area":
        return (
          <ResponsiveContainer width={width} height={height}>
            <AreaChart data={chart.data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8EAED" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} label={chart.xLabel ? { value: chart.xLabel, position: "insideBottom", offset: -5, fontSize: 11 } : undefined} />
              <YAxis tick={{ fontSize: 11 }} label={chart.yLabel ? { value: chart.yLabel, angle: -90, position: "insideLeft", fontSize: 11 } : undefined} />
              <Tooltip />
              {numericKeys.length > 1 && <Legend />}
              {numericKeys.map((key, i) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        );

      case "scatter":
        return (
          <ResponsiveContainer width={width} height={height}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8EAED" />
              <XAxis dataKey={numericKeys[0] || "x"} name={numericKeys[0] || "x"} tick={{ fontSize: 11 }} label={chart.xLabel ? { value: chart.xLabel, position: "insideBottom", offset: -5, fontSize: 11 } : undefined} />
              <YAxis dataKey={numericKeys[1] || "y"} name={numericKeys[1] || "y"} tick={{ fontSize: 11 }} label={chart.yLabel ? { value: chart.yLabel, angle: -90, position: "insideLeft", fontSize: 11 } : undefined} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} />
              <Scatter data={chart.data} fill={COLORS[0]} />
            </ScatterChart>
          </ResponsiveContainer>
        );

      case "bar":
      default:
        return (
          <ResponsiveContainer width={width} height={height}>
            <BarChart data={chart.data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E8EAED" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} label={chart.xLabel ? { value: chart.xLabel, position: "insideBottom", offset: -5, fontSize: 11 } : undefined} />
              <YAxis tick={{ fontSize: 11 }} label={chart.yLabel ? { value: chart.yLabel, angle: -90, position: "insideLeft", fontSize: 11 } : undefined} />
              <Tooltip />
              {numericKeys.length > 1 && <Legend />}
              {numericKeys.map((key, i) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={COLORS[i % COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );
    }
  }

  return (
    <div className="my-3 bg-white border border-[var(--border-light)] rounded-lg overflow-hidden">
      {/* Chart header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border-light)] bg-gray-50">
        <span className="text-xs font-semibold text-gray-700">
          {chart.title || "Chart"}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleDownload}
            className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
            title="Download as PNG"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
            title={expanded ? "Minimize" : "Expand"}
          >
            {expanded ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Chart body */}
      <div className="p-4" ref={chartRef}>{renderChart()}</div>
    </div>
  );
}
