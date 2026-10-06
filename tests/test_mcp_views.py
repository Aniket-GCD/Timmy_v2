import unittest

from timeassist import mcp_views


FULL_ENTRY = {
    "entry_id": 7, "client_name": "Client A", "task_text": "monthly cleanup",
    "billable": 1, "start_at": "2026-05-28T09:00:00", "end_at": "2026-05-28T09:23:00",
    "duration_minutes": 23, "rounded_minutes": 30, "review_status": "draft",
    "raw_client_name": "client a", "raw_task_text": "monthly cleanup",
    "capture_status": "resolved", "capture_note": None, "clarified_at": None,
    "export_path": None, "created_at": "2026-05-28T09:23:00", "updated_at": "2026-05-28T09:23:00",
}

FULL_SESSION = {
    "session_id": 3, "client_name": "Client B", "task_text": "tax question",
    "billable": 1, "started_at": "2026-05-28T10:00:00", "last_checkin_at": "2026-05-28T10:00:00",
    "snoozed_until": None, "status": "active", "raw_client_name": "Client B",
    "raw_task_text": "tax question", "capture_status": "needs_info",
    "capture_note": "client_not_in_roster", "clarified_at": None,
    "created_at": "2026-05-28T10:00:00", "updated_at": "2026-05-28T10:00:00",
}


class SlimEntryTests(unittest.TestCase):
    def test_keeps_model_relevant_fields_only(self) -> None:
        slim = mcp_views.slim_entry(FULL_ENTRY)
        self.assertEqual(slim["entry_id"], 7)
        self.assertEqual(slim["client"], "Client A")
        self.assertEqual(slim["notes"], "monthly cleanup")
        self.assertNotIn("task", slim)  # renamed to notes
        self.assertNotIn("billable", slim)
        self.assertEqual(slim["minutes"], 30)
        self.assertEqual(slim["entry_date"], "2026-05-28")
        self.assertEqual(slim["status"], "draft")
        self.assertEqual(slim["raw_minutes"], 23)  # differs from rounded -> included
        for dropped in ("created_at", "updated_at", "raw_client_name", "export_path", "capture_status"):
            self.assertNotIn(dropped, slim)

    def test_office_from_entry_or_shape_context(self) -> None:
        slim = mcp_views.slim_entry(dict(FULL_ENTRY, office="MH"))
        self.assertEqual(slim["office"], "MH")
        shaped = mcp_views.shape("edit", dict(FULL_ENTRY), office="GCD")
        self.assertEqual(shaped["office"], "GCD")
        self.assertNotIn("billable", shaped)

    def test_job_type_present_when_non_empty(self) -> None:
        slim = mcp_views.slim_entry(dict(FULL_ENTRY, job_type="Accounts"))
        self.assertEqual(slim["job_type"], "Accounts")
        self.assertEqual(slim["job_code"], "Accounts")
        self.assertEqual(slim["hours"], 0.5)

    def test_empty_job_type_kept_as_blank_string(self) -> None:
        shaped = mcp_views.shape("edit", dict(FULL_ENTRY, job_type=""))
        self.assertEqual(shaped["job_type"], "")
        self.assertEqual(shaped["job_code"], "")
        self.assertEqual(shaped["duration"], "0:30")

    def test_notes_missing_passes_through(self) -> None:
        slim = mcp_views.slim_entry(dict(FULL_ENTRY, notes_missing=True))
        self.assertTrue(slim["notes_missing"])

    def test_notes_missing_absent_when_unset(self) -> None:
        self.assertNotIn("notes_missing", mcp_views.slim_entry(FULL_ENTRY))

    def test_raw_minutes_omitted_when_equal(self) -> None:
        entry = dict(FULL_ENTRY, duration_minutes=30)
        self.assertNotIn("raw_minutes", mcp_views.slim_entry(entry))

    def test_needs_info_surfaces_note(self) -> None:
        entry = dict(FULL_ENTRY, capture_status="needs_info", capture_note="client_not_in_roster")
        self.assertEqual(mcp_views.slim_entry(entry)["needs_info"], "client 'Client A' is not in the roster")


class SlimSessionTests(unittest.TestCase):
    def test_active_session_shape(self) -> None:
        slim = mcp_views.slim_session(FULL_SESSION)
        self.assertEqual(slim["client"], "Client B")
        self.assertEqual(slim["notes"], "tax question")
        self.assertNotIn("task", slim)  # renamed to notes
        self.assertEqual(slim["started_at"], "2026-05-28T10:00:00")
        self.assertEqual(slim["started_display"], "10:00 AM")
        self.assertEqual(slim["needs_info"], "client 'Client B' is not in the roster")
        self.assertNotIn("status", slim)  # 'active' is implied
        self.assertNotIn("snoozed_until", slim)  # None -> omitted
        slim = mcp_views.slim_session(dict(FULL_SESSION, planned_end_at="2026-05-28T12:00:00"))
        self.assertEqual(slim["planned_end_at"], "2026-05-28T12:00:00")
        self.assertEqual(slim["planned_end_display"], "12:00 PM")

    def test_hard_cap_planned_end_omitted_from_slim_session(self) -> None:
        # Default engine cap is start + 8h — do not surface it to the model.
        slim = mcp_views.slim_session(
            dict(FULL_SESSION, planned_end_at="2026-05-28T18:00:00", capture_status="resolved")
        )
        self.assertNotIn("planned_end_at", slim)
        self.assertNotIn("planned_end_display", slim)

    def test_operator_planned_end_still_surfaced(self) -> None:
        slim = mcp_views.slim_session(
            dict(FULL_SESSION, planned_end_at="2026-05-28T11:30:00", capture_status="resolved")
        )
        self.assertEqual(slim["planned_end_display"], "11:30 AM")

    def test_session_job_type_present_when_non_empty(self) -> None:
        slim = mcp_views.slim_session(dict(FULL_SESSION, job_type="Payroll"))
        self.assertEqual(slim["job_type"], "Payroll")
        self.assertEqual(slim["job_code"], "Payroll")

    def test_session_empty_job_type_kept_as_blank_string(self) -> None:
        shaped = mcp_views.shape("start", dict(FULL_SESSION, job_type="", capture_status="resolved"))
        self.assertEqual(shaped["job_type"], "")
        self.assertEqual(shaped["job_code"], "")

    def test_non_active_status_included(self) -> None:
        slim = mcp_views.slim_session(dict(FULL_SESSION, status="canceled", capture_status="resolved"))
        self.assertEqual(slim["status"], "canceled")

    def test_none_session(self) -> None:
        self.assertIsNone(mcp_views.slim_session(None))


class ShapeTests(unittest.TestCase):
    def test_review_view_slims_entries_and_drops_audit_fields(self) -> None:
        result = {
            "date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, needs_review_reason=None)],
            "active_session": FULL_SESSION,
            "active_timer_warning": {
                "has_active_timer": True, "session": {}, "client_name": "Client B",
                "task_text": "tax question", "started_at": "2026-05-28T10:00:00",
                "last_checkin_at": "2026-05-28T10:00:00", "snoozed_until": None,
                "open_minutes": 47, "is_stale": False, "prompt_reason": "active_timer_open",
                "suggested_actions": ["checkin", "end", "switch", "snooze", "cancel"],
            },
            "totals": {"draft_minutes": 30, "approved_minutes": 0, "exported_minutes": 0,
                       "needs_info_minutes": 0, "skipped_needs_info_minutes": 0},
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "event_count": 12,
            "last_activity_at": "2026-05-28T10:00:00",
            "review_token": "abc123",
        }
        shaped = mcp_views.shape("review", result)
        self.assertEqual(shaped["review_token"], "abc123")
        self.assertEqual(shaped["entries"][0]["minutes"], 30)
        self.assertNotIn("event_count", shaped)
        self.assertNotIn("last_activity_at", shaped)
        self.assertNotIn("active_session", shaped)
        self.assertNotIn("active_timer_warning", shaped)
        timer = shaped["active_timer"]
        self.assertEqual(timer["open_minutes"], 47)
        self.assertFalse(timer["is_stale"])
        self.assertEqual(timer["session"]["client"], "Client B")
        self.assertEqual(timer["suggested_actions"], ["checkin", "end", "switch", "snooze", "cancel"])

    def test_review_view_surfaces_missing_notes_count(self) -> None:
        result = {
            "date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, notes_missing=True)],
            "active_session": None,
            "active_timer_warning": {"has_active_timer": False},
            "totals": {"draft_minutes": 30},
            "skipped_needs_info_count": 0,
            "missing_notes_count": 1,
            "review_token": "abc123",
        }
        shaped = mcp_views.shape("review", result)
        self.assertEqual(shaped["missing_notes_count"], 1)
        self.assertTrue(shaped["entries"][0]["notes_missing"])

    def test_review_view_omits_zero_missing_notes_count(self) -> None:
        result = {
            "date": "2026-05-28",
            "entries": [],
            "active_session": None,
            "active_timer_warning": {"has_active_timer": False},
            "totals": {"draft_minutes": 0},
            "skipped_needs_info_count": 0,
            "missing_notes_count": 0,
            "review_token": "t",
        }
        shaped = mcp_views.shape("review", result)
        self.assertNotIn("missing_notes_count", shaped)

    def test_switch_view_surfaces_notes_missing_on_closed_entry(self) -> None:
        shaped = mcp_views.shape("switch", {
            "closed_entry": dict(FULL_ENTRY, notes_missing=True),
            "new_active_session": FULL_SESSION,
        })
        self.assertTrue(shaped["closed_entry"]["notes_missing"])

    def test_end_view_surfaces_notes_missing(self) -> None:
        shaped = mcp_views.shape("end", dict(FULL_ENTRY, notes_missing=True))
        self.assertTrue(shaped["notes_missing"])

    def test_review_view_omits_timer_when_idle(self) -> None:
        result = {
            "date": "2026-05-28", "entries": [], "active_session": None,
            "active_timer_warning": {"has_active_timer": False, "session": None,
                                     "prompt_reason": "idle", "suggested_actions": []},
            "totals": {"draft_minutes": 0}, "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0, "event_count": 1,
            "last_activity_at": None, "review_token": "t",
        }
        shaped = mcp_views.shape("review", result)
        self.assertNotIn("active_timer", shaped)

    def test_approve_all_view_returns_counts_not_row_bodies(self) -> None:
        shaped = mcp_views.shape("approve_all", {
            "date": "2026-05-28", "approved_count": 3,
            "skipped_needs_info_count": 1, "skipped_needs_info_minutes": 12,
            "skipped_missing_job_code_count": 1, "skipped_missing_job_code_minutes": 30,
            "skipped_missing_job_code": [{"entry_id": 9, "client": "Acme", "notes": "call"}],
            "submitted_count": 2, "submit_failed_count": 1,
            "entries": [dict(FULL_ENTRY, job_type="Tax")] * 3,
            "submit_results": [{"entry_id": 7, "ok": True}],
        })
        self.assertEqual(shaped["approved_count"], 3)
        self.assertNotIn("entries", shaped)
        self.assertNotIn("submit_results", shaped)
        self.assertEqual(shaped["skipped_missing_job_code_count"], 1)
        self.assertEqual(shaped["skipped_missing_job_code"][0]["entry_id"], 9)
        self.assertEqual(shaped["submitted_count"], 2)

    def test_approve_all_view_surfaces_skipped_locked_counts(self) -> None:
        shaped = mcp_views.shape("approve_all", {
            "date": "2026-05-28", "approved_count": 1,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "skipped_locked_count": 2, "skipped_locked_minutes": 45,
            "entries": [FULL_ENTRY],
        })
        self.assertEqual(shaped["skipped_locked_count"], 2)
        self.assertEqual(shaped["skipped_locked_minutes"], 45)

    def test_approve_all_view_omits_zero_skipped_locked_counts(self) -> None:
        shaped = mcp_views.shape("approve_all", {
            "date": "2026-05-28", "approved_count": 1,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "skipped_locked_count": 0, "skipped_locked_minutes": 0,
            "entries": [FULL_ENTRY],
        })
        self.assertNotIn("skipped_locked_count", shaped)
        self.assertNotIn("skipped_locked_minutes", shaped)

    def test_reround_view_returns_total_instead_of_entries(self) -> None:
        shaped = mcp_views.shape("reround", {
            "date": "2026-05-28", "rule": "nearest_15_minutes", "rerounded_count": 2,
            "entries": [dict(FULL_ENTRY, rounded_minutes=30), dict(FULL_ENTRY, rounded_minutes=15)],
        })
        self.assertEqual(shaped["total_draft_minutes"], 45)
        self.assertNotIn("entries", shaped)

    def test_import_clients_view_returns_counts_only(self) -> None:
        shaped = mcp_views.shape("import_clients", {
            "mode": "merge", "imported_count": 2,
            "clients": [{"client_key": "a", "display_name": "A", "aliases": "",
                         "default_billable": 1, "default_job_type": "",
                         "billable_locked": 0, "updated_at": "2026-05-28T09:00:00"}],
        })
        self.assertEqual(shaped, {"mode": "merge", "imported_count": 2})

    def test_add_client_view_keeps_essentials_and_drops_empties(self) -> None:
        shaped = mcp_views.shape("add_client", {
            "client": {"client_key": "acme", "display_name": "Acme Co", "aliases": "",
                       "default_billable": 0, "default_job_type": "",
                       "billable_locked": 0, "updated_at": "2026-05-28T09:00:00"},
            "client_count": 7,
        })
        self.assertEqual(shaped, {
            "client": {"client_key": "acme", "display_name": "Acme Co"},
            "client_count": 7,
        })

    def test_export_view_consolidates_paths(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv",
            "output": "/data/exports/q.csv", "exported_count": 2,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY] * 2, "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertEqual(shaped["csv"], "/home/u/Documents/TimeAssist Exports/q.csv")
        self.assertEqual(shaped["official_csv"], "/data/exports/q.csv")
        self.assertEqual(shaped["exported_count"], 2)
        self.assertNotIn("entries", shaped)
        self.assertNotIn("backup", shaped)
        self.assertNotIn("backup_warning", shaped)

    def test_export_view_warns_when_backup_failed(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv", "output": "/data/exports/q.csv",
            "exported_count": 1, "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY], "backup": None,
            "user_export_dir": "/d", "user_visible_output": None,
            "user_visible_copy_error": "disk full",
        })
        self.assertEqual(shaped["csv"], "/data/exports/q.csv")
        self.assertEqual(shaped["copy_error"], "disk full")
        self.assertIn("backup_warning", shaped)

    def test_export_view_surfaces_skipped_locked_counts(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv",
            "output": "/data/exports/q.csv", "exported_count": 1,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "skipped_locked_count": 1, "skipped_locked_minutes": 30,
            "entries": [FULL_ENTRY], "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/d", "user_visible_output": "/data/exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertEqual(shaped["skipped_locked_count"], 1)
        self.assertEqual(shaped["skipped_locked_minutes"], 30)

    def test_export_view_omits_zero_skipped_locked_counts(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28", "format": "quickbooks-csv",
            "output": "/data/exports/q.csv", "exported_count": 1,
            "skipped_needs_info_count": 0, "skipped_needs_info_minutes": 0,
            "skipped_locked_count": 0, "skipped_locked_minutes": 0,
            "entries": [FULL_ENTRY], "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/d", "user_visible_output": "/data/exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertNotIn("skipped_locked_count", shaped)
        self.assertNotIn("skipped_locked_minutes", shaped)

    def test_checkin_status_idle_is_tiny(self) -> None:
        shaped = mcp_views.shape("checkin_status", {
            "active": False, "session": None, "open_minutes": None,
            "minutes_since_checkin": None, "snoozed_until": None, "should_prompt": False,
            "prompt_reason": "idle", "is_stale": False, "checkin_interval_minutes": 45,
            "stale_session_minutes": 480, "suggested_actions": [],
        })
        self.assertEqual(shaped, {"active": False, "should_prompt": False})

    def test_checkin_status_active_slims_session(self) -> None:
        shaped = mcp_views.shape("checkin_status", {
            "active": True,
            "session": {"client_name": "Client A", "task_text": "monthly cleanup",
                        "started_at": "2026-05-28T09:00:00", "last_checkin_at": "2026-05-28T09:45:00"},
            "open_minutes": 47, "minutes_since_checkin": 45, "snoozed_until": None,
            "should_prompt": True, "prompt_reason": "interval_elapsed", "is_stale": False,
            "checkin_interval_minutes": 45, "stale_session_minutes": 480,
            "suggested_actions": ["still", "switched", "done", "snooze", "cancel"],
        })
        self.assertEqual(shaped["session"]["client"], "Client A")
        self.assertEqual(shaped["session"]["notes"], "monthly cleanup")
        self.assertEqual(shaped["session"]["last_checkin_at"], "2026-05-28T09:45:00")
        self.assertNotIn("client_name", shaped["session"])
        self.assertNotIn("suggested_actions", shaped)
        self.assertNotIn("checkin_interval_minutes", shaped)
        self.assertTrue(shaped["should_prompt"])

    def test_status_view_drops_db_path(self) -> None:
        shaped = mcp_views.shape("status", {"db_path": "/x.sqlite", "size_bytes": 1, "size_human": "1 B"})
        self.assertNotIn("db_path", shaped)

    def test_unknown_tool_passes_through_with_nones_dropped(self) -> None:
        shaped = mcp_views.shape("config", {"settings": {"rounding_rule": "exact"}, "noise": None})
        self.assertEqual(shaped, {"settings": {"rounding_rule": "exact"}})

    # --- range review view ---

    def test_review_range_shape_has_days_not_entries(self) -> None:
        day_summary = {
            "date": "2026-05-28", "entry_count": 1,
            "draft_minutes": 30, "approved_minutes": 0,
            "exported_minutes": 0, "needs_info_count": 0,
        }
        result = {
            "date": "2026-05-27",
            "end_date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, needs_review_reason=None)],
            "active_session": None,
            "active_timer_warning": {"has_active_timer": False},
            "totals": {"draft_minutes": 30, "approved_minutes": 0, "exported_minutes": 0,
                       "needs_info_minutes": 0, "skipped_needs_info_minutes": 0},
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "event_count": 5,
            "last_activity_at": "2026-05-28T09:23:00",
            "review_token": "rangetok",
            "days": [day_summary],
        }
        shaped = mcp_views.shape("review", result)
        self.assertEqual(shaped["date"], "2026-05-27")
        self.assertEqual(shaped["end_date"], "2026-05-28")
        self.assertEqual(shaped["review_token"], "rangetok")
        self.assertIn("days", shaped)
        self.assertEqual(shaped["days"][0]["draft_minutes"], 30)
        self.assertNotIn("entries", shaped)
        self.assertIn("totals", shaped)
        self.assertIn("skipped_needs_info_count", shaped)

    def test_review_range_shape_includes_conditional_keys(self) -> None:
        result = {
            "date": "2026-05-27",
            "end_date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, notes_missing=True, needs_review_reason=None)],
            "active_session": FULL_SESSION,
            "active_timer_warning": {
                "has_active_timer": True, "session": {},
                "open_minutes": 10, "is_stale": False,
                "suggested_actions": ["end"],
            },
            "totals": {"draft_minutes": 30},
            "skipped_needs_info_count": 1,
            "skipped_needs_info_minutes": 30,
            "missing_notes_count": 1,
            "event_count": 3,
            "last_activity_at": "2026-05-28T09:00:00",
            "review_token": "rangetok2",
            "days": [],
        }
        shaped = mcp_views.shape("review", result)
        self.assertEqual(shaped["missing_notes_count"], 1)
        self.assertIn("active_timer", shaped)
        self.assertNotIn("entries", shaped)

    def test_review_single_day_shape_is_unchanged(self) -> None:
        """Single-day result (no end_date) must keep the entries key."""
        result = {
            "date": "2026-05-28",
            "entries": [dict(FULL_ENTRY, needs_review_reason=None)],
            "active_session": None,
            "active_timer_warning": {"has_active_timer": False},
            "totals": {"draft_minutes": 30},
            "skipped_needs_info_count": 0,
            "review_token": "singletok",
        }
        shaped = mcp_views.shape("review", result)
        self.assertIn("entries", shaped)
        self.assertNotIn("end_date", shaped)
        self.assertNotIn("days", shaped)

    # --- export view: end_date and operator_code pass-through ---

    def test_export_view_passes_through_end_date_when_present(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-27",
            "end_date": "2026-05-28",
            "format": "quickbooks-csv",
            "output": "/data/exports/q.csv",
            "exported_count": 3,
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY] * 3,
            "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertEqual(shaped["end_date"], "2026-05-28")
        self.assertEqual(shaped["exported_count"], 3)

    def test_export_view_omits_end_date_when_absent(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28",
            "format": "quickbooks-csv",
            "output": "/data/exports/q.csv",
            "exported_count": 1,
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY],
            "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertNotIn("end_date", shaped)

    def test_export_view_passes_through_operator_code_when_present(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28",
            "operator_code": "JW",
            "format": "quickbooks-csv",
            "output": "/data/exports/q.csv",
            "exported_count": 1,
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY],
            "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertEqual(shaped["operator_code"], "JW")

    def test_export_view_omits_operator_code_when_absent(self) -> None:
        shaped = mcp_views.shape("export", {
            "date": "2026-05-28",
            "format": "quickbooks-csv",
            "output": "/data/exports/q.csv",
            "exported_count": 1,
            "skipped_needs_info_count": 0,
            "skipped_needs_info_minutes": 0,
            "entries": [FULL_ENTRY],
            "backup": "/data/backups/b.sqlite",
            "user_export_dir": "/home/u/Documents/TimeAssist Exports",
            "user_visible_output": "/home/u/Documents/TimeAssist Exports/q.csv",
            "user_visible_copy_error": None,
        })
        self.assertNotIn("operator_code", shaped)


if __name__ == "__main__":
    unittest.main()
