from datetime import date

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'round_batch')
class TestRoundBatchValidation(TransactionCase):

    def setUp(self):
        super().setUp()

        self.Round = self.env['round.management.round']
        self.Batch = self.env['round.management.batch']

        self.test_depot = self.env['stock.warehouse'].search([], limit=1)

        self.test_round = self.Round.create({
            'name': 'Test Round A',
        })

        self.active_batch = self.Batch.create({
            'round_id': self.test_round.id,
            'delivery_date': date(2026, 10, 1),
            'state': 'act',
            'depot_id': self.test_depot.id,
            'reference': 'TEST-REF-001',
        })

    def test_active_batch_warning_within_4_weeks_before(self):
        """Test that an active batch within 4 weeks before the delivery date is detected."""
        new_delivery_date = date(2026, 10, 15)

        matching_batches = self.Batch._check_existing_active_batches(
            self.test_round.id,
            new_delivery_date,
        )

        self.assertIn(
            self.active_batch,
            matching_batches,
        )

    def test_active_batch_warning_within_4_weeks_after(self):
        """Test that an active batch within 4 weeks after the delivery date is detected."""
        new_delivery_date = date(2026, 9, 20)

        matching_batches = self.Batch._check_existing_active_batches(
            self.test_round.id,
            new_delivery_date,
        )

        self.assertIn(
            self.active_batch,
            matching_batches,
        )

    def test_active_batch_outside_4_weeks(self):
        """Test that an active batch outside 4 weeks is not detected."""
        new_delivery_date_after = date(2026, 11, 10)
        new_delivery_date_before = date(2026, 8, 20)

        matching_after = self.Batch._check_existing_active_batches(
            self.test_round.id,
            new_delivery_date_after,
        )
        matching_before = self.Batch._check_existing_active_batches(
            self.test_round.id,
            new_delivery_date_before,
        )

        self.assertNotIn(self.active_batch, matching_after)
        self.assertNotIn(self.active_batch, matching_before)