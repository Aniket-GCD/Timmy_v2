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
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
};

export function WeekChart({ data, selectedDate, onSelectDate }: Props) {
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
                name === "admin" ? "Admin" : "Billable & other",
              ]}
              labelFormatter={(_, payload) => {
                const row = payload?.[0]?.payload as DailyTotal | undefined;
                return row ? `${row.label} · ${formatHoursHM(row.total)} total` : "";
              }}
            />
            <Bar
              dataKey="nonAdmin"
              stackId="h"
              fill="#0e5727"
              style={{ cursor: "pointer" }}
              onClick={(d) => {
                const row = d as unknown as DailyTotal;
                if (row?.date) onSelectDate(row.date);
              }}
            />
            <Bar
              dataKey="admin"
              stackId="h"
              fill="#5f8b55"
              radius={[4, 4, 0, 0]}
              style={{ cursor: "pointer" }}
              onClick={(d) => {
                const row = d as unknown as DailyTotal;
                if (row?.date) onSelectDate(row.date);
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="muted" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem" }}>
        {selectedDate
          ? `Day filter: ${selectedDate} — click a bar to change; clear chip above table to reset.`
          : "Click a bar to filter Time Entry Detail by day."}
      </p>
    </div>
  );
}
