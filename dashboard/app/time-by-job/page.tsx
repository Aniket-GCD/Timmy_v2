import type { Metadata } from "next";
import { TimeByJobReport } from "@/components/TimeByJobReport";

export const metadata: Metadata = {
  title: "Timmy Billing",
};

export default function TimeByJobPage() {
  return <TimeByJobReport />;
}
