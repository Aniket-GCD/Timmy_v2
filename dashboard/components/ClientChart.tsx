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
import type { NamedHours } from "@/lib/aggregations";

type Props = {
  title: string;
  data: NamedHours[];
};

export function ClientChart({ title, data }: Props) {
  const chartData = data.map((d) => ({
    ...d,
    short: d.name.length > 22 ? `${d.name.slice(0, 20)}…` : d.name,
  }));

  return (
    <div className="panel">
      <h3>{title}</h3>
      {chartData.length === 0 ? (
        <p className="muted">No hours in this range.</p>
      ) : (
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <BarChart
              layout="vertical"
              data={chartData}
              margin={{ top: 4, right: 12, left: 4, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e2e0" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#6b6b6b", fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis
                type="category"
                dataKey="short"
                width={108}
                tick={{ fill: "#3e3e3e", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  borderColor: "#d8d6d3",
                  fontFamily: "var(--font-body)",
                }}
                formatter={(value) => [`${value ?? 0}h`, "Hours"]}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as NamedHours | undefined;
                  return row?.name ?? "";
                }}
              />
              <Bar dataKey="hours" fill="#5f8b55" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
