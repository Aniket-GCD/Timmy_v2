# TimeAssist Stakeholder Demo Transcript

This is a synthetic walkthrough. It does not contain real client data, private work context, credentials, exports, or internal URLs.

## Talk track

1. The business problem is not that accountants refuse to track time. The problem is that the current workflow makes short interruptions and task switching easy to lose.
2. This prototype keeps the user in control. It creates draft entries, not final billing records.
3. Every mutation writes an event log. That gives the workflow accountability without screen recording or keystroke monitoring.
4. Only approved entries export to a QuickBooks-ready CSV. Direct QuickBooks writeback is intentionally out of scope for v1.
5. Before any real pilot, the stakeholder needs to confirm approved data classes, rounding rules, service codes, and the exact QuickBooks handoff route.

## Demo commands run

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite init --at 2026-05-28T08:55:00`

```json
{
  "action": "init",
  "details": {
    "created_at": "2026-05-28T08:55:00",
    "database": "demo/generated/timeassist-demo.sqlite",
    "export_folder": {
      "confirmed_at": null,
      "custom_user_export_dir": null,
      "default_user_export_dir": "~/Documents/TimeAssist Exports",
      "preference": "default_unconfirmed",
      "prompt": "TimeAssist will keep the official export inside Claude plugin data for audit safety, then copy the same CSV to Documents/TimeAssist Exports so it is easy to find. Keep that default, or choose a different export copy folder.",
      "survey_required": true,
      "user_export_dir": "~/Documents/TimeAssist Exports"
    }
  },
  "message": "Local TimeAssist state is ready.",
  "ok": true,
  "status": "initialized"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite import-clients --file demo/generated/demo-clients.csv --mode replace --confirm-replace --at 2026-05-28T08:56:00`

```json
{
  "action": "import-clients",
  "details": {
    "clients": [
      {
        "aliases": "",
        "billable_locked": 0,
        "client_key": "client_a",
        "default_billable": 1,
        "default_job_type": "Bookkeeping",
        "display_name": "Client A",
        "updated_at": "2026-05-28T08:56:00"
      },
      {
        "aliases": "",
        "billable_locked": 0,
        "client_key": "client_b",
        "default_billable": 1,
        "default_job_type": "Tax",
        "display_name": "Client B",
        "updated_at": "2026-05-28T08:56:00"
      }
    ],
    "imported_count": 2,
    "mode": "replace"
  },
  "message": "Imported 2 client(s).",
  "ok": true,
  "status": "clients-imported"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite start --client Client A --task monthly cleanup --billable yes --at 2026-05-28T09:00:00`

```json
{
  "action": "start",
  "details": {
    "active_session": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client A",
      "created_at": "2026-05-28T09:00:00",
      "job_type": "Bookkeeping",
      "last_checkin_at": "2026-05-28T09:00:00",
      "raw_client_name": null,
      "raw_task_text": "monthly cleanup",
      "session_id": 1,
      "snoozed_until": null,
      "started_at": "2026-05-28T09:00:00",
      "status": "active",
      "task_text": "monthly cleanup",
      "updated_at": "2026-05-28T09:00:00"
    }
  },
  "message": "Started draft time for Client A.",
  "ok": true,
  "status": "started"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite switch --client Client B --task tax question --billable yes --at 2026-05-28T09:24:00`

```json
{
  "action": "switch",
  "details": {
    "closed_entry": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client A",
      "created_at": "2026-05-28T09:24:00",
      "duration_minutes": 24,
      "end_at": "2026-05-28T09:24:00",
      "entry_id": 1,
      "export_path": null,
      "job_type": "Bookkeeping",
      "raw_client_name": null,
      "raw_task_text": "monthly cleanup",
      "review_status": "draft",
      "rounded_minutes": 24,
      "start_at": "2026-05-28T09:00:00",
      "task_text": "monthly cleanup",
      "updated_at": "2026-05-28T09:24:00"
    },
    "new_active_session": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client B",
      "created_at": "2026-05-28T09:24:00",
      "job_type": "Tax",
      "last_checkin_at": "2026-05-28T09:24:00",
      "raw_client_name": null,
      "raw_task_text": "tax question",
      "session_id": 2,
      "snoozed_until": null,
      "started_at": "2026-05-28T09:24:00",
      "status": "active",
      "task_text": "tax question",
      "updated_at": "2026-05-28T09:24:00"
    }
  },
  "message": "Switched draft time to Client B.",
  "ok": true,
  "status": "switched"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite end --at 2026-05-28T09:42:00`

```json
{
  "action": "end",
  "details": {
    "closed_entry": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client B",
      "created_at": "2026-05-28T09:42:00",
      "duration_minutes": 18,
      "end_at": "2026-05-28T09:42:00",
      "entry_id": 2,
      "export_path": null,
      "job_type": "Tax",
      "raw_client_name": null,
      "raw_task_text": "tax question",
      "review_status": "draft",
      "rounded_minutes": 18,
      "start_at": "2026-05-28T09:24:00",
      "task_text": "tax question",
      "updated_at": "2026-05-28T09:42:00"
    }
  },
  "message": "Ended the active session and created a draft entry.",
  "ok": true,
  "status": "ended"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite add-missing --client Client A --task call notes and follow-up --start 2026-05-28T10:00:00 --end 2026-05-28T10:18:00 --billable yes`

```json
{
  "action": "add-missing",
  "details": {
    "entry": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client A",
      "created_at": "2026-05-28T10:18:00",
      "duration_minutes": 18,
      "end_at": "2026-05-28T10:18:00",
      "entry_id": 3,
      "export_path": null,
      "job_type": "Bookkeeping",
      "raw_client_name": null,
      "raw_task_text": "call notes and follow-up",
      "review_status": "draft",
      "rounded_minutes": 18,
      "start_at": "2026-05-28T10:00:00",
      "task_text": "call notes and follow-up",
      "updated_at": "2026-05-28T10:18:00"
    }
  },
  "message": "Added a missing draft time entry.",
  "ok": true,
  "status": "added"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite review --date 2026-05-28 --format html --output demo/generated/review-before-approval.html`

```json
{
  "action": "review",
  "details": {
    "active_session": null,
    "active_timer_warning": {
      "client_name": null,
      "has_active_timer": false,
      "is_stale": false,
      "last_checkin_at": null,
      "open_minutes": null,
      "prompt_reason": "idle",
      "session": null,
      "snoozed_until": null,
      "started_at": null,
      "suggested_actions": [],
      "task_text": null
    },
    "date": "2026-05-28",
    "entries": [
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T09:24:00",
        "duration_minutes": 24,
        "end_at": "2026-05-28T09:24:00",
        "entry_id": 1,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "monthly cleanup",
        "review_status": "draft",
        "rounded_minutes": 24,
        "start_at": "2026-05-28T09:00:00",
        "task_text": "monthly cleanup",
        "updated_at": "2026-05-28T09:24:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client B",
        "created_at": "2026-05-28T09:42:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T09:42:00",
        "entry_id": 2,
        "export_path": null,
        "job_type": "Tax",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "tax question",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T09:24:00",
        "task_text": "tax question",
        "updated_at": "2026-05-28T09:42:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T10:18:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T10:18:00",
        "entry_id": 3,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "call notes and follow-up",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T10:00:00",
        "task_text": "call notes and follow-up",
        "updated_at": "2026-05-28T10:18:00"
      }
    ],
    "event_count": 7,
    "html_output": "demo/generated/review-before-approval.html",
    "last_activity_at": "2026-05-28T10:18:00",
    "missing_notes_count": 0,
    "review_token": "f1cf7d2b992603186e1bbec6d9d4ef5be49a34fc8facdccf1162bde14736fbc4",
    "skipped_needs_info_count": 0,
    "skipped_needs_info_minutes": 0,
    "totals": {
      "approved_minutes": 0,
      "draft_minutes": 60,
      "exported_minutes": 0,
      "needs_info_minutes": 0,
      "skipped_needs_info_minutes": 0
    }
  },
  "message": "Review is ready. Nothing has been exported.",
  "ok": true,
  "status": "review-ready"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite approve --entry-id 1 --at 2026-05-28T10:45:00 --review-token f1cf7d2b992603186e1bbec6d9d4ef5be49a34fc8facdccf1162bde14736fbc4`

```json
{
  "action": "approve",
  "details": {
    "entry": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client A",
      "created_at": "2026-05-28T09:24:00",
      "duration_minutes": 24,
      "end_at": "2026-05-28T09:24:00",
      "entry_id": 1,
      "export_path": null,
      "job_type": "Bookkeeping",
      "raw_client_name": null,
      "raw_task_text": "monthly cleanup",
      "review_status": "approved",
      "rounded_minutes": 24,
      "start_at": "2026-05-28T09:00:00",
      "task_text": "monthly cleanup",
      "updated_at": "2026-05-28T10:45:00"
    }
  },
  "message": "Approved entry 1.",
  "ok": true,
  "status": "approved"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite review --date 2026-05-28`

```json
{
  "action": "review",
  "details": {
    "active_session": null,
    "active_timer_warning": {
      "client_name": null,
      "has_active_timer": false,
      "is_stale": false,
      "last_checkin_at": null,
      "open_minutes": null,
      "prompt_reason": "idle",
      "session": null,
      "snoozed_until": null,
      "started_at": null,
      "suggested_actions": [],
      "task_text": null
    },
    "date": "2026-05-28",
    "entries": [
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T09:24:00",
        "duration_minutes": 24,
        "end_at": "2026-05-28T09:24:00",
        "entry_id": 1,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "monthly cleanup",
        "review_status": "approved",
        "rounded_minutes": 24,
        "start_at": "2026-05-28T09:00:00",
        "task_text": "monthly cleanup",
        "updated_at": "2026-05-28T10:45:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client B",
        "created_at": "2026-05-28T09:42:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T09:42:00",
        "entry_id": 2,
        "export_path": null,
        "job_type": "Tax",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "tax question",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T09:24:00",
        "task_text": "tax question",
        "updated_at": "2026-05-28T09:42:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T10:18:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T10:18:00",
        "entry_id": 3,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "call notes and follow-up",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T10:00:00",
        "task_text": "call notes and follow-up",
        "updated_at": "2026-05-28T10:18:00"
      }
    ],
    "event_count": 8,
    "last_activity_at": "2026-05-28T10:45:00",
    "missing_notes_count": 0,
    "review_token": "96a21fc9c226aff77bf6bfa274bf0fc282102e326df6291987ed198cb0be84f4",
    "skipped_needs_info_count": 0,
    "skipped_needs_info_minutes": 0,
    "totals": {
      "approved_minutes": 24,
      "draft_minutes": 36,
      "exported_minutes": 0,
      "needs_info_minutes": 0,
      "skipped_needs_info_minutes": 0
    }
  },
  "message": "Review is ready. Nothing has been exported.",
  "ok": true,
  "status": "review-ready"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite approve --entry-id 2 --at 2026-05-28T10:46:00 --review-token 96a21fc9c226aff77bf6bfa274bf0fc282102e326df6291987ed198cb0be84f4`

```json
{
  "action": "approve",
  "details": {
    "entry": {
      "billable": 1,
      "capture_note": null,
      "capture_status": "resolved",
      "clarified_at": null,
      "client_name": "Client B",
      "created_at": "2026-05-28T09:42:00",
      "duration_minutes": 18,
      "end_at": "2026-05-28T09:42:00",
      "entry_id": 2,
      "export_path": null,
      "job_type": "Tax",
      "raw_client_name": null,
      "raw_task_text": "tax question",
      "review_status": "approved",
      "rounded_minutes": 18,
      "start_at": "2026-05-28T09:24:00",
      "task_text": "tax question",
      "updated_at": "2026-05-28T10:46:00"
    }
  },
  "message": "Approved entry 2.",
  "ok": true,
  "status": "approved"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite review --date 2026-05-28`

```json
{
  "action": "review",
  "details": {
    "active_session": null,
    "active_timer_warning": {
      "client_name": null,
      "has_active_timer": false,
      "is_stale": false,
      "last_checkin_at": null,
      "open_minutes": null,
      "prompt_reason": "idle",
      "session": null,
      "snoozed_until": null,
      "started_at": null,
      "suggested_actions": [],
      "task_text": null
    },
    "date": "2026-05-28",
    "entries": [
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T09:24:00",
        "duration_minutes": 24,
        "end_at": "2026-05-28T09:24:00",
        "entry_id": 1,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "monthly cleanup",
        "review_status": "approved",
        "rounded_minutes": 24,
        "start_at": "2026-05-28T09:00:00",
        "task_text": "monthly cleanup",
        "updated_at": "2026-05-28T10:45:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client B",
        "created_at": "2026-05-28T09:42:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T09:42:00",
        "entry_id": 2,
        "export_path": null,
        "job_type": "Tax",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "tax question",
        "review_status": "approved",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T09:24:00",
        "task_text": "tax question",
        "updated_at": "2026-05-28T10:46:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T10:18:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T10:18:00",
        "entry_id": 3,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "call notes and follow-up",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T10:00:00",
        "task_text": "call notes and follow-up",
        "updated_at": "2026-05-28T10:18:00"
      }
    ],
    "event_count": 9,
    "last_activity_at": "2026-05-28T10:46:00",
    "missing_notes_count": 0,
    "review_token": "2dfc7c64f6c172e7143892b0b0cb85d81335f0117695dae6c4e5fe7b4d0ddd3e",
    "skipped_needs_info_count": 0,
    "skipped_needs_info_minutes": 0,
    "totals": {
      "approved_minutes": 42,
      "draft_minutes": 18,
      "exported_minutes": 0,
      "needs_info_minutes": 0,
      "skipped_needs_info_minutes": 0
    }
  },
  "message": "Review is ready. Nothing has been exported.",
  "ok": true,
  "status": "review-ready"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite export --date 2026-05-28 --format quickbooks-csv --output demo/generated/quickbooks-time-export.csv --at 2026-05-28T10:50:00 --review-token 2dfc7c64f6c172e7143892b0b0cb85d81335f0117695dae6c4e5fe7b4d0ddd3e`

```json
{
  "action": "export",
  "details": {
    "backup": "demo/generated/backups/timeassist-20260528-105000.sqlite",
    "date": "2026-05-28",
    "entries": [
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T09:24:00",
        "duration_minutes": 24,
        "end_at": "2026-05-28T09:24:00",
        "entry_id": 1,
        "export_path": "demo/generated/quickbooks-time-export.csv",
        "job_type": "Bookkeeping",
        "raw_client_name": null,
        "raw_task_text": "monthly cleanup",
        "review_status": "exported",
        "rounded_minutes": 24,
        "start_at": "2026-05-28T09:00:00",
        "task_text": "monthly cleanup",
        "updated_at": "2026-05-28T10:50:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client B",
        "created_at": "2026-05-28T09:42:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T09:42:00",
        "entry_id": 2,
        "export_path": "demo/generated/quickbooks-time-export.csv",
        "job_type": "Tax",
        "raw_client_name": null,
        "raw_task_text": "tax question",
        "review_status": "exported",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T09:24:00",
        "task_text": "tax question",
        "updated_at": "2026-05-28T10:50:00"
      }
    ],
    "exported_count": 2,
    "format": "quickbooks-csv",
    "output": "demo/generated/quickbooks-time-export.csv",
    "skipped_locked_count": 0,
    "skipped_locked_minutes": 0,
    "skipped_needs_info_count": 0,
    "skipped_needs_info_minutes": 0,
    "user_export_dir": "~/Documents/TimeAssist Exports",
    "user_visible_copy_error": null,
    "user_visible_output": "~/Documents/TimeAssist Exports/quickbooks-time-export.csv"
  },
  "message": "Exported 2 approved entries.",
  "ok": true,
  "status": "exported"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite review --date 2026-05-28 --format html --output demo/generated/stakeholder-review.html`

```json
{
  "action": "review",
  "details": {
    "active_session": null,
    "active_timer_warning": {
      "client_name": null,
      "has_active_timer": false,
      "is_stale": false,
      "last_checkin_at": null,
      "open_minutes": null,
      "prompt_reason": "idle",
      "session": null,
      "snoozed_until": null,
      "started_at": null,
      "suggested_actions": [],
      "task_text": null
    },
    "date": "2026-05-28",
    "entries": [
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T09:24:00",
        "duration_minutes": 24,
        "end_at": "2026-05-28T09:24:00",
        "entry_id": 1,
        "export_path": "demo/generated/quickbooks-time-export.csv",
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "monthly cleanup",
        "review_status": "exported",
        "rounded_minutes": 24,
        "start_at": "2026-05-28T09:00:00",
        "task_text": "monthly cleanup",
        "updated_at": "2026-05-28T10:50:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client B",
        "created_at": "2026-05-28T09:42:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T09:42:00",
        "entry_id": 2,
        "export_path": "demo/generated/quickbooks-time-export.csv",
        "job_type": "Tax",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "tax question",
        "review_status": "exported",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T09:24:00",
        "task_text": "tax question",
        "updated_at": "2026-05-28T10:50:00"
      },
      {
        "billable": 1,
        "capture_note": null,
        "capture_status": "resolved",
        "clarified_at": null,
        "client_name": "Client A",
        "created_at": "2026-05-28T10:18:00",
        "duration_minutes": 18,
        "end_at": "2026-05-28T10:18:00",
        "entry_id": 3,
        "export_path": null,
        "job_type": "Bookkeeping",
        "needs_review_reason": null,
        "raw_client_name": null,
        "raw_task_text": "call notes and follow-up",
        "review_status": "draft",
        "rounded_minutes": 18,
        "start_at": "2026-05-28T10:00:00",
        "task_text": "call notes and follow-up",
        "updated_at": "2026-05-28T10:18:00"
      }
    ],
    "event_count": 11,
    "html_output": "demo/generated/stakeholder-review.html",
    "last_activity_at": "2026-05-28T10:50:00",
    "missing_notes_count": 0,
    "review_token": "aa54c4a2e1ffabeed5ac65bc7558ad898ee1c7e427357d9fbf5ac6aeebecf08c",
    "skipped_needs_info_count": 0,
    "skipped_needs_info_minutes": 0,
    "totals": {
      "approved_minutes": 0,
      "draft_minutes": 18,
      "exported_minutes": 42,
      "needs_info_minutes": 0,
      "skipped_needs_info_minutes": 0
    }
  },
  "message": "Review is ready. Nothing has been exported.",
  "ok": true,
  "status": "review-ready"
}
```

### `python scripts/timeassist.py --db demo/generated/timeassist-demo.sqlite sanitize-packet --date 2026-05-28 --output demo/generated/sanitized-collaboration-packet.md`

```json
{
  "action": "sanitize-packet",
  "details": {
    "client_label_count": 2,
    "entry_count": 3,
    "output": "demo/generated/sanitized-collaboration-packet.md"
  },
  "message": "Created sanitized collaboration packet.",
  "ok": true,
  "status": "packet-created"
}
```

## Generated artifacts

- `demo/generated/stakeholder-review.html` — stakeholder-friendly review screen.
- `demo/generated/quickbooks-time-export.csv` — synthetic approved-entry export.
- `demo/generated/sanitized-collaboration-packet.md` — anonymized packet for outside design review.
