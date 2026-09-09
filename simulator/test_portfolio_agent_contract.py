import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortfolioAgentContractTests(unittest.TestCase):
    def test_agent_exposes_read_only_portfolio_tools_and_option_guardrail(self):
        source = (ROOT / "production_director_agent" / "agent.py").read_text()
        for tool in ("get_portfolio_context", "calculate_allocation_options", "verify_portfolio_allocation"):
            self.assertIn(tool, source)
        self.assertIn("Select only an option ID returned by calculate_allocation_options", source)
        self.assertNotIn("execute_portfolio_allocation", source)

    def test_grafana_portfolio_query_requires_both_production_labels(self):
        source = (ROOT / "production_director_agent" / "grafana_tools.py").read_text()
        self.assertIn('production_id=~"project-nova|silverline"', source)
        self.assertIn("GRAFANA_PROMETHEUS_DATASOURCE_UID", source)
        self.assertIn("GRAFANA_LOKI_DATASOURCE_UID", source)
        self.assertIn("GRAFANA_TEMPO_DATASOURCE_UID", source)


if __name__ == "__main__":
    unittest.main()
