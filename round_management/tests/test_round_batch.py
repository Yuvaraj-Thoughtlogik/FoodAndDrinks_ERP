from datetime import date, timedelta
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

@tagged('post_install', '-at_install', 'round_batch')
class TestRoundBatchValidation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Round = self.env['round.management']
        self.Batch = self.env['round.management.batch']

        # Sample Round
        self.test_round = self.Round.create({'name': 'Test Round A'})

        # Active base batch on Oct 1, 2026
        self.active_batch = self.Batch.create({
            'round_id': self.test_round.id,
            'delivery_date': date(2026, 10, 1),
            'state': 'act',
        })

    def test_active_batch_warning_within_4_weeks(self):
        """Test batch created within 4 weeks returns wizard action."""
        new_delivery_date = date(2026, 10, 15)  # 14 days after active_batch
        
        # Call helper method directly
        matching_batches = self.Batch._check_existing_active_batches(
            self.test_round.id, new_delivery_date
        )
        self.assertIn(self.active_batch, matching_batches)

        # Simulating record creation triggers wizard action dictionary
        res = self.Batch.create({
            'round_id': self.test_round.id,
            'delivery_date': new_delivery_date,
            'state': 'pln',
        })
        
        # Verify action returned is wizard
        self.assertEqual(res.get('res_model'), 'round.batch.warning.wizard')

    def test_active_batch_outside_4_weeks(self):
        """Test batch created outside 4-week window does not trigger warning."""
        new_delivery_date = date(2026, 11, 10)  # > 28 days after active_batch
        
        matching_batches = self.Batch._check_existing_active_batches(
            self.test_round.id, new_delivery_date
        )
        self.assertNotIn(self.active_batch, matching_batches)
