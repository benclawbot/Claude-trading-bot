# CLI modules coverage tests

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMainModule:
    """Test main.py module-level functions."""
    
    def test_main_imports(self):
        """Test that main.py module can be imported."""
        import main
        assert hasattr(main, 'TradingBot')
        assert hasattr(main, 'main')
    
    def test_trading_bot_class_exists(self):
        """Test TradingBot class exists."""
        import main
        assert hasattr(main, 'TradingBot')
        assert callable(main.TradingBot)


class TestDashboardModule:
    """Test dashboard/app.py module."""
    
    def test_dashboard_imports(self):
        """Test that dashboard module can be imported."""
        try:
            import dashboard.app as dashboard_app
            assert hasattr(dashboard_app, 'app')
        except ImportError:
            pytest.skip("dashboard module not importable")
    
    def test_dashboard_has_layout(self):
        """Test dashboard has app and rendering functions."""
        try:
            import dashboard.app as dashboard_app
            assert hasattr(dashboard_app, 'app')
            assert hasattr(dashboard_app, 'render_tab')
        except ImportError:
            pytest.skip("dashboard module not importable")


class TestExportDashboardModule:
    """Test export_dashboard.py module."""
    
    def test_export_dashboard_imports(self):
        """Test that export_dashboard.py module can be imported."""
        try:
            import export_dashboard
            assert hasattr(export_dashboard, 'export_data')
        except (ImportError, FileNotFoundError):
            pytest.skip("export_dashboard has path dependency at module level")
