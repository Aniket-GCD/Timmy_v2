"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatHoursHM } from "@/lib/hours-format";
import type { DailyTotal } from "@/lib/aggregations";

type Props = {
  data: DailyTotal[];
  selectedDate: string;
  onSelectDate: (date: string) => void;
};

export function WeekChart({ data, selectedDate, onSelectDate }: Props) {
  return (
    <div className="panel">
      <h3>Hours by day</h3>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <BarChart
            data={data}
            margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
            onClick={(state) => {
              const active = state as { activePayload?: { payload?: DailyTotal }[] };
              const payload = active.activePayload?.[0]?.payload;
              if (payload?.date) onSelectDate(payload.date);
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e4e2e0" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "#3e3e3e", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "#6b6b6b", fontSize: 12 }} axisLine={false} tickLine={false} width={36} />
            <Tooltip
              cursor={{ fill: "rgba(95, 139, 85, 0.08)" }}
              contentStyle={{ borderRadius: 8, borderColor: "#d8d6d3", fontFamily: "var(--font-body)" }}
              formatter={(value, name) => [
                formatHoursHM(Number(value ?? 0)),
                name === "admin" ? "Admin" : "Billable & other",
              ]}
              labelFormatter={(_, payload) => {
                const row = payload?.[0]?.payload as DailyTotal | undefined;
                return row ? `${row.label} · ${formatHoursHM(row.total)} total` : "";
              }}
            />
            <Bar dataKey="nonAdmin" stackId="h" fill="#0e5727" style={{ cursor: "pointer" }} />
            <Bar dataKey="admin" stackId="h" fill="#5f8b55" radius={[4, 4, 0, 0]} style={{ cursor: "pointer" }} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="muted" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem" }}>
        Selected: {selectedDate} — click a bar to focus the day table.
      </p>
    </div>
  );
}
