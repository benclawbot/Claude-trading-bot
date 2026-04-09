# Tests for database.py

import pytest
import sqlite3
import tempfile
import os
from unittest.mock import Mock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        yield db_path


@pytest.fixture
def db_with_schema(temp_db):
    """Create a database with the schema initialized."""
    import database as db_module
    
    # Patch config before importing/using
    with patch.object(db_module, 'config') as mock_config:
        mock_config.DB_PATH = temp_db
        mock_config.UTC_NOW_SQL = "datetime('now')"
        mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        
        # Initialize the database
        db_module.init_db()
        
        yield db_module, temp_db


class TestDatabaseSchema:
    """Test database schema creation."""
    
    def test_init_db_creates_tables(self, temp_db):
        """Test that init_db creates all required tables."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            
            conn = db_module.get_conn()
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            
            assert "strategies" in tables
            assert "positions" in tables
            assert "trades" in tables
            assert "journal_entries" in tables


class TestStrategiesTable:
    """Test strategies table operations."""
    
    def test_upsert_strategy(self, temp_db):
        """Test upsert_strategy creates and updates strategies."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            
            # Insert a strategy with required args
            db_module.upsert_strategy("TestStrategy", capital=1000.0, params={})
            
            conn = db_module.get_conn()
            row = conn.execute(
                "SELECT name, is_active, capital FROM strategies WHERE name='TestStrategy'"
            ).fetchone()
            
            assert row is not None
            assert row[0] == "TestStrategy"
            assert row[1] == False  # is_active defaults to 0
            assert row[2] == 1000.0
            
            # Update the strategy
            db_module.upsert_strategy("TestStrategy", capital=1500.0, params={})
            
            row = conn.execute(
                "SELECT capital FROM strategies WHERE name='TestStrategy'"
            ).fetchone()
            
            assert row[0] == 1500.0


class TestPositionsTable:
    """Test positions table operations."""
    
    def test_open_and_close_position(self, temp_db):
        """Test opening and closing positions."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("TestStrategy", capital=1000.0, params={})
            
            # Open a position
            pos_id = db_module.open_position(
                strategy_name="TestStrategy",
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000,
                quantity=0.1,
                stop_loss=49000,
                take_profit=52000,
                order_id="TEST_ORDER_1",
                ml_confidence=0.6,
                metadata={},
            )
            
            assert pos_id is not None
            assert pos_id > 0
            
            # Check open positions
            positions = db_module.get_open_positions()
            assert len(positions) == 1
            assert positions[0]["strategy_name"] == "TestStrategy"
            assert positions[0]["side"] == "LONG"
            
            # Close the position
            db_module.close_position(pos_id)
            
            positions = db_module.get_open_positions()
            assert len(positions) == 0
    
    def test_get_open_positions_for_strategy(self, temp_db):
        """Test getting open positions for a specific strategy."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("Strategy1", capital=1000.0, params={})
            db_module.upsert_strategy("Strategy2", capital=1000.0, params={})
            
            db_module.open_position("Strategy1", "BTCUSDT", "LONG", 50000, 0.1, 49000, 52000, "O1", 0.6, {})
            db_module.open_position("Strategy2", "BTCUSDT", "SHORT", 50000, 0.1, 51000, 48000, "O2", 0.6, {})
            
            pos1 = db_module.get_open_positions("Strategy1")
            assert len(pos1) == 1
            assert pos1[0]["side"] == "LONG"
            
            pos2 = db_module.get_open_positions("Strategy2")
            assert len(pos2) == 1
            assert pos2[0]["side"] == "SHORT"


class TestTradesTable:
    """Test trades table operations."""
    
    def test_record_trade(self, temp_db):
        """Test recording a trade."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("TestStrategy", capital=1000.0, params={})
            db_module.open_position("TestStrategy", "BTCUSDT", "LONG", 50000, 0.1, 49000, 52000, "O1", 0.6, {})
            
            trade_id = db_module.record_trade(
                strategy_name="TestStrategy",
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000,
                exit_price=51000,
                quantity=0.1,
                pnl=100,
                pnl_pct=0.02,
                fees_paid=1.0,
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-01T02:00:00Z",
                duration_hours=2.0,
                exit_reason="TAKE_PROFIT",
                entry_features={},
            )
            
            assert trade_id is not None
            assert trade_id > 0
            
            # Verify trade is recorded
            conn = db_module.get_conn()
            row = conn.execute("SELECT pnl, pnl_pct FROM trades WHERE id=?", (trade_id,)).fetchone()
            assert row[0] == 100
            assert row[1] == 0.02
    
    def test_get_trade_stats(self, temp_db):
        """Test getting trade statistics."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("StatsTestStrategy", capital=1000.0, params={})
            
            # Record some trades
            for i, pnl in enumerate([100, -50, 200, -30, 150]):
                db_module.record_trade(
                    strategy_name="StatsTestStrategy",
                    symbol="BTCUSDT",
                    side="LONG",
                    entry_price=50000,
                    exit_price=50000 + pnl,
                    quantity=0.1,
                    pnl=pnl,
                    pnl_pct=pnl / 5000,
                    fees_paid=1.0,
                    entry_time="2024-01-01T00:00:00Z",
                    exit_time="2024-01-01T02:00:00Z",
                    duration_hours=2.0,
                    exit_reason="TAKE_PROFIT",
                    entry_features={},
                )
            
            stats = db_module.get_trade_stats("StatsTestStrategy")
            
            assert stats["total_trades"] == 5
            assert stats["wins"] == 3
            assert stats["losses"] == 2
            assert stats["total_pnl"] == 370  # 100-50+200-30+150


class TestJournalEntries:
    """Test journal entries table operations."""
    
    def test_record_and_get_journal_entries(self, temp_db):
        """Test recording and retrieving journal entries."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("TestStrategy", capital=1000.0, params={})
            
            trade_id = db_module.record_trade(
                strategy_name="TestStrategy",
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000,
                exit_price=51000,
                quantity=0.1,
                pnl=100,
                pnl_pct=0.02,
                fees_paid=1.0,
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-01T02:00:00Z",
                duration_hours=2.0,
                exit_reason="TAKE_PROFIT",
                entry_features={},
            )
            
            db_module.record_journal_entry(
                trade_id=trade_id,
                strategy_name="TestStrategy",
                entry_price=50000,
                exit_price=51000,
                pnl=100,
                pnl_pct=0.02,
                side="LONG",
                duration_hours=2.0,
                market_regime="RANGING",
                setup_summary="Test setup",
                outcome_analysis="Test outcome",
                reflection="Test reflection",
                lessons="Test lesson",
            )
            
            entries = db_module.get_journal_entries(strategy_name="TestStrategy", limit=10)
            
            assert len(entries) == 1
            assert entries[0]["strategy_name"] == "TestStrategy"
            assert entries[0]["market_regime"] == "RANGING"
            assert "reflection" in entries[0]


class TestMLFeatures:
    """Test ML features table operations."""
    
    def test_record_and_get_ml_features(self, temp_db):
        """Test recording and retrieving ML features."""
        import database as db_module
        
        with patch.object(db_module, 'config') as mock_config:
            mock_config.DB_PATH = temp_db
            mock_config.UTC_NOW_SQL = "datetime('now')"
            mock_config.UTC_NOW_ISO_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            
            db_module.init_db()
            db_module.upsert_strategy("MLStrategy", capital=1000.0, params={})
            
            trade_id = db_module.record_trade(
                strategy_name="MLStrategy",
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000,
                exit_price=51000,
                quantity=0.1,
                pnl=100,
                pnl_pct=0.02,
                fees_paid=1.0,
                entry_time="2024-01-01T00:00:00Z",
                exit_time="2024-01-01T02:00:00Z",
                duration_hours=2.0,
                exit_reason="TAKE_PROFIT",
                entry_features={},
            )
            
            features = [0.5] * 12
            db_module.record_ml_features(
                trade_id=trade_id,
                strategy_name="MLStrategy",
                features=features,
                outcome=1.0,
                pnl_pct=0.02,
            )
            
            # Verify it was recorded
            conn = db_module.get_conn()
            count = conn.execute("SELECT COUNT(*) FROM ml_features").fetchone()[0]
            assert count == 1
