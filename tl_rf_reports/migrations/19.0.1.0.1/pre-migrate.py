# requirement.report.line changed from a TransientModel (one throwaway set
# of lines per View Lines click, linked to the wizard) to a regular Model
# keyed by the report filters (filter_key).


def migrate(cr, version):
    cr.execute("SELECT to_regclass('requirement_report_line')")
    if not cr.fetchone()[0]:
        return

    # Throwaway lines never turned into a Purchase Order: nothing to keep.
    cr.execute("DELETE FROM requirement_report_line WHERE purchase_order_id IS NULL")

    # The old wizard link must go: its FK is ON DELETE CASCADE, so the
    # transient-wizard autovacuum would keep deleting the now-permanent lines.
    cr.execute("ALTER TABLE requirement_report_line DROP COLUMN IF EXISTS wizard_id CASCADE")

    # Lines already on a PO are kept (Purchase Order > Requirement Lines
    # smart button) under a key no wizard produces, so they never mix with
    # newly generated lines.
    cr.execute("ALTER TABLE requirement_report_line ADD COLUMN IF NOT EXISTS filter_key varchar")
    cr.execute("UPDATE requirement_report_line SET filter_key = 'legacy' WHERE filter_key IS NULL")
