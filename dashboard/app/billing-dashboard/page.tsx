import type { Metadata } from "next";
import { TimeByJobReport } from "@/components/TimeByJobReport";

export const metadata: Metadata = {
  title: { absolute: "Billing Dashboard" },
};

export default function BillingDashboardPage() {
  return <TimeByJobReport />;
}
