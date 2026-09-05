"use client";

import { ClientChart } from "./ClientChart";
import type { NamedHours } from "@/lib/aggregations";

type Props = {
  data: NamedHours[];
  selectedName?: string | null;
  onSelectName?: (name: string) => void;
};

export function JobChart({ data, selectedName, onSelectName }: Props) {
  return (
    <ClientChart
      title="Hours by job code"
      data={data}
      selectedName={selectedName}
      onSelectName={onSelectName}
    />
  );
}
