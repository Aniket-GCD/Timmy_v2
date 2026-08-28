"use client";

import { ClientChart } from "./ClientChart";
import type { NamedHours } from "@/lib/aggregations";

type Props = {
  data: NamedHours[];
};

export function JobChart({ data }: Props) {
  return <ClientChart title="Hours by job type" data={data} />;
}
