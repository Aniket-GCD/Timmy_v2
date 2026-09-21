"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatHoursHM } from "@/lib/hours-format";
import type { DailyTotal } from "@/lib/aggregations";

const FILL_CLIENT = "#0e5727";
const FILL_ADMIN = "#5f8b55";
const FILL_GREY_CLIENT = "#c5c0ba";
const FILL_GREY_ADMIN = "#a8a29e";

type Props = {
  data: DailyTotal[];
  selectedDate: string | null;
  /** Days painted in green; empty = all days green. Others with hours use muted grey. */
  highlightDates: string[];
  onSelectDate: (date: string) => void;
};

export function WeekChart({ data, selectedDate, highlightDates, onSelectDate }: Props) {
  const highlight = new Set(highlightDates);
  const useGrey = highlight.size > 0;

  function clientFill(date: string): string {
    if (!useGrey || highlight.has(date)) return FILL_CLIENT;
    return FILL_GREY_CLIENT;
  }

  function adminFill(date: string): string {
    if (!useGrey || highlight.has(date)) return FILL_ADMIN;
    return FILL_GREY_ADMIN;
  }

  return (
    <div className="panel">
      <h3>Hours by day</h3>
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <BarChart
            data={data}
            margin={{ top: 8, right: 8, left: -12, bottom: 48 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e4e2e0" vertical={false} />
            <XAxis
              dataKey="label"
              interval={0}
              angle={-90}
              textAnchor="end"
              height={70}
              tick={{ fill: "#3e3e3e", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tick={{ fill: "#6b6b6b", fontSize: 12 }} axisLine={false} tickLine={false} width={36} />
            <Tooltip
              cursor={{ fill: "rgba(95, 139, 85, 0.08)" }}
              contentStyle={{ borderRadius: 8, borderColor: "#d8d6d3", fontFamily: "var(--font-body)" }}
              formatter={(value, name) => [
                formatHoursHM(Number(value ?? 0)),
                name === "admin" ? "Admin" : "Client work",
              ]}
              labelFormatter={(_, payload) => {
                const row = payload?.[0]?.payload as DailyTotal | undefined;
                return row ? `${row.label} · ${formatHoursHM(row.total)} total` : "";
              }}
            />
            <Bar
              dataKey="nonAdmin"
              stackId="h"
              style={{ cursor: "pointer" }}
              onClick={(d) => {
                const row = d as unknown as DailyTotal;
                if (row?.date) onSelectDate(row.date);
              }}
            >
              {data.map((row) => (
                <Cell key={`na-${row.date}`} fill={clientFill(row.date)} />
              ))}
            </Bar>
            <Bar
              dataKey="admin"
              stackId="h"
              radius={[4, 4, 0, 0]}
              style={{ cursor: "pointer" }}
              onClick={(d) => {
                const row = d as unknown as DailyTotal;
                if (row?.date) onSelectDate(row.date);
              }}
            >
              {data.map((row) => (
                <Cell key={`ad-${row.date}`} fill={adminFill(row.date)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="muted" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem" }}>
        {selectedDate
          ? `Day filter: ${selectedDate} — click a bar to change; clear chip above table to reset.`
          : "Click a bar to filter the dashboard by day."}
      </p>
    </div>
  );
}
