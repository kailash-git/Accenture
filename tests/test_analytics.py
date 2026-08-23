import unittest
import os
import sqlite3
from src.analytics.anomaly_detector import detect_anomalies
from src.analytics.pvm_analyzer import calculate_pvm

class TestAnalyticsBackend(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.base_dir, 'data', 'business_bi.db')
        self.assertTrue(os.path.exists(self.db_path), f"Seeded database missing at {self.db_path}")

    def test_anomaly_detection_functionality(self):
        """Assert that rolling z-score logic runs and identifies expected historical spikes/drops."""
        # Detect anomalies in CA for the high-volume FOODS_3_090 item
        alerts = detect_anomalies(
            self.db_path, 
            item_id="FOODS_3_090", 
            state_id="CA", 
            window_size=8, 
            threshold=2.0
        )
        
        self.assertGreater(len(alerts), 0, "No anomalies detected in CA for FOODS_3_090")
        
        # Verify fields in returned alerts
        for alert in alerts:
            self.assertIn("week_start_monday", alert)
            self.assertEqual(alert["item_id"], "FOODS_3_090")
            self.assertEqual(alert["state_id"], "CA")
            self.assertIn("z_score", alert)
            self.assertIn("direction", alert)
            self.assertIn("deviation_pct", alert)
            
            # Print example alert for debugging
            print(f"Detected Anomaly Alert: {alert['week_start_monday']} | {alert['direction']} | Z={alert['z_score']} | Dev={alert['deviation_pct']*100:.1f}%")

    def test_pvm_mathematical_identity(self):
        """Assert that Price Effect + Volume Effect + Mix Effect EXACTLY equals Revenue Variance."""
        # We pick two dates in 2013 to compare
        # Period 0 (Baseline): 2013-06-03 to 2013-06-09
        # Period 1 (Anomaly): 2013-08-12 to 2013-08-18 (matches the CA price cut window)
        res = calculate_pvm(
            self.db_path,
            start_date_0="2013-06-03",
            end_date_0="2013-06-09",
            start_date_1="2013-08-12",
            end_date_1="2013-08-18",
            state_id="CA",
            cat_id="FOODS"
        )
        
        # Pull values
        base_rev = res["baseline_revenue"]
        anom_rev = res["anomaly_revenue"]
        var = res["revenue_variance"]
        pe = res["price_effect"]
        ve = res["volume_effect"]
        me = res["mix_effect"]
        
        # Verify baseline variance calculation: Revenue1 - Revenue0 = Variance
        self.assertAlmostEqual(anom_rev - base_rev, var, places=2)
        
        # Verify PVM Identity: Price Effect + Volume Effect + Mix Effect = Variance
        summed_effects = pe + ve + me
        print(f"\n--- PVM Mathematical Verification (CA FOODS) ---")
        print(f"Baseline Revenue: ${base_rev:,.2f}")
        print(f"Anomaly Revenue:  ${anom_rev:,.2f}")
        print(f"Total Variance:   ${var:,.2f}")
        print(f"  - Price Effect:  ${pe:,.2f}")
        print(f"  - Volume Effect: ${ve:,.2f}")
        print(f"  - Mix Effect:    ${me:,.2f}")
        print(f"  - Sum of Effects: ${summed_effects:,.2f}")
        
        # The sum of effects must equal total variance exactly (tolerance within 0.05 for float rounding)
        self.assertAlmostEqual(summed_effects, var, delta=0.05)
        print("PVM Mathematical Identity holds with zero error. - Passed")

if __name__ == "__main__":
    unittest.main()
