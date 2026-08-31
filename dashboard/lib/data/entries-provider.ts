import { validateEntryWrite } from "../validate-entry";
import { createMockSeed, MOCK_STAFF } from "../mock-data";
import { MOCK_CLIENTS, MOCK_JOB_CODES } from "../mock-reference";
import type { ClientOption, JobCodeOption } from "../types/reference-data";
import type { EntryWritePayload, TimeEntry } from "../types/time-entry";

export type FetchEntriesParams = {
  staffName: string;
  dateFrom: string;
  dateTo: string;
};

export interface EntriesProvider {
  fetchEntries(params: FetchEntriesParams): Promise<TimeEntry[]>;
  createEntry(payload: EntryWritePayload): Promise<TimeEntry>;
  updateEntry(id: number, payload: EntryWritePayload): Promise<TimeEntry>;
  fetchClients(): Promise<ClientOption[]>;
  fetchJobCodes(): Promise<JobCodeOption[]>;
}

let mockStore: TimeEntry[] | null = null;
let mockNextId = 1000;

function getMockStore(): TimeEntry[] {
  if (!mockStore) mockStore = createMockSeed();
  return mockStore;
}

export function resetMockStore(): void {
  mockStore = createMockSeed();
  mockNextId = 1000;
}

export const mockProvider: EntriesProvider = {
  async fetchEntries({ staffName, dateFrom, dateTo }) {
    return getMockStore().filter(
      (e) =>
        e.staff_name === staffName &&
        e.entry_date >= dateFrom &&
        e.entry_date <= dateTo,
    );
  },
  async fetchClients() {
    return MOCK_CLIENTS;
  },
  async fetchJobCodes() {
    return MOCK_JOB_CODES;
  },
  async createEntry(payload) {
    const result = validateEntryWrite(payload, { clients: MOCK_CLIENTS, jobCodes: MOCK_JOB_CODES }, MOCK_STAFF.staff_name);
    if (!result.ok) throw new Error(result.error);
    const job = MOCK_JOB_CODES.find((j) => j.job_code === result.payload.job_code)!;
    const entry: TimeEntry = {
      id: mockNextId++,
      staff_name: MOCK_STAFF.staff_name,
      office: MOCK_STAFF.office,
      account: job.account,
      source_file: "timmy-dashboard-mock",
      ...result.payload,
    };
    getMockStore().push(entry);
    return entry;
  },
  async updateEntry(id, payload) {
    const result = validateEntryWrite(payload, { clients: MOCK_CLIENTS, jobCodes: MOCK_JOB_CODES }, MOCK_STAFF.staff_name);
    if (!result.ok) throw new Error(result.error);
    const store = getMockStore();
    const idx = store.findIndex((e) => e.id === id);
    if (idx < 0) throw new Error("Entry not found");
    const job = MOCK_JOB_CODES.find((j) => j.job_code === result.payload.job_code)!;
    store[idx] = { ...store[idx], ...result.payload, account: job.account };
    return store[idx];
  },
};

export function getEntriesProvider(): EntriesProvider {
  const source = process.env.NEXT_PUBLIC_DASHBOARD_DATA_SOURCE ?? "mock";
  if (source === "supabase") {
    return liveProvider;
  }
  return mockProvider;
}

const liveProvider: EntriesProvider = {
  async fetchEntries(params) {
    const q = new URLSearchParams({
      from: params.dateFrom,
      to: params.dateTo,
      staff: params.staffName,
    });
    const res = await fetch(`/api/entries?${q}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async createEntry(payload) {
    const res = await fetch("/api/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async updateEntry(id, payload) {
    const res = await fetch(`/api/entries/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async fetchClients() {
    const res = await fetch("/api/clients");
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async fetchJobCodes() {
    const res = await fetch("/api/job-codes");
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};
