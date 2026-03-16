#!/usr/bin/env python3
"""
Test script to verify portfolio manager capital calculations are consistent
and don't have any missing links.
"""

import sqlite3
import config
from database import get_conn, init_db
from portfolio_manager import PortfolioManager
from binance_client import BinanceClient
from strategies import EMA5MomentumStrategy

def test_capital_consistency():
    """Test that total capital = free_capital + committed + unrealized"""

    print("\n" + "="*70)
    print("TEST: Capital Calculation Consistency")
    print("="*70)

    try:
        # Initialize database
        init_db()

        # Create a test strategy
        strat = EMA5MomentumStrategy()

        # Create portfolio manager
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])

        # Get initial balance
        initial_bal = pm.total_balance(current_price)

        print(f"\n1. Initial Balance")
        print(f"   Total Balance: ${initial_bal['total_balance']:,.2f}")
        print(f"   Free Capital:  ${initial_bal['free_capital']:,.2f}")
        print(f"   Realized P&L:  ${initial_bal['realized_pnl']:,.2f}")
        print(f"   Unrealized P&L: ${initial_bal['unrealized_pnl']:,.2f}")

        # Check strategy breakdown
        breakdown = initial_bal.get('breakdown', {})
        for strat_name, strat_info in breakdown.items():
            cap = strat_info['capital']
            free = strat_info['free_capital']
            committed = strat_info['committed_notional']
            realized = strat_info['realized_pnl']
            unrealized = strat_info['unrealized_pnl']

            print(f"\n2. Strategy: {strat_name}")
            print(f"   Total Capital:    ${cap:,.2f}")
            print(f"   Free Capital:     ${free:,.2f}")
            print(f"   Committed:        ${committed:,.2f}")
            print(f"   Realized P&L:     ${realized:,.2f}")
            print(f"   Unrealized P&L:   ${unrealized:,.2f}")

            # Verify: total = free + committed + unrealized
            calculated_total = free + committed + unrealized
            print(f"\n   Consistency Check:")
            print(f"   Total Capital = {cap:,.2f}")
            print(f"   Free + Committed + Unrealized = {calculated_total:,.2f}")

            if abs(cap - calculated_total) < 0.01:
                print(f"   ✓ PASS: Capital values are consistent")
            else:
                print(f"   ✗ FAIL: Capital mismatch! Difference = ${cap - calculated_total:,.2f}")
                return False

        print(f"\n3. Total Balance Consistency")
        # Verify: total_balance = free_capital + unrealized_pnl + committed_in_positions
        total_free = initial_bal['free_capital']
        total_unrealized = initial_bal['unrealized_pnl']
        total_committed = sum(strat_info['committed_notional']
                             for strat_info in breakdown.values())

        calculated_total = total_free + total_unrealized + total_committed
        actual_total = initial_bal['total_balance']

        print(f"   Total Balance:                           ${actual_total:,.2f}")
        print(f"   Free + Unrealized + Committed Notional:  ${calculated_total:,.2f}")

        if abs(actual_total - calculated_total) < 0.01:
            print(f"   ✓ PASS: Total balance is consistent")
        else:
            print(f"   ✗ FAIL: Total balance mismatch! Difference = ${actual_total - calculated_total:,.2f}")
            return False

        print(f"\n" + "="*70)
        print("✓ ALL TESTS PASSED!")
        print("="*70)
        return True

    except Exception as e:
        print(f"\n✗ TEST FAILED WITH ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_reallocate_method():
    """Test that reallocate() method accepts current_price parameter"""

    print("\n" + "="*70)
    print("TEST: Reallocate Method Signature")
    print("="*70)

    try:
        init_db()
        strat = EMA5MomentumStrategy()
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])

        # Test that reallocate() can be called with current_price
        print("\nCalling reallocate(current_price)...")
        pm.reallocate(current_price)
        print("✓ PASS: reallocate() accepts current_price parameter")

        return True
    except TypeError as e:
        print(f"✗ FAIL: reallocate() signature error: {e}")
        return False
    except Exception as e:
        print(f"✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_allocate_capital_signature():
    """Test that _allocate_capital() accepts current_price parameter"""

    print("\n" + "="*70)
    print("TEST: _allocate_capital Method Signature")
    print("="*70)

    try:
        init_db()
        strat = EMA5MomentumStrategy()
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])

        # Test that _allocate_capital() can be called with current_price
        print("\nCalling _allocate_capital(current_price)...")
        pm._allocate_capital(current_price)
        print("✓ PASS: _allocate_capital() accepts current_price parameter")

        # Test default parameter
        print("\nCalling _allocate_capital() with default parameter...")
        pm._allocate_capital()
        print("✓ PASS: _allocate_capital() works with default parameter")

        return True
    except TypeError as e:
        print(f"✗ FAIL: _allocate_capital() signature error: {e}")
        return False
    except Exception as e:
        print(f"✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n" + "█"*70)
    print("PORTFOLIO MANAGER INTEGRITY TEST SUITE")
    print("█"*70)

    results = []

    # Run all tests
    results.append(("Capital Consistency", test_capital_consistency()))
    results.append(("Reallocate Signature", test_reallocate_method()))
    results.append(("Allocate Capital Signature", test_allocate_capital_signature()))

    # Print summary
    print("\n" + "█"*70)
    print("TEST SUMMARY")
    print("█"*70)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "█"*70)
    if all_passed:
        print("✓ ALL TESTS PASSED - Portfolio integrity verified!")
    else:
        print("✗ SOME TESTS FAILED - Please review the errors above")
    print("█"*70 + "\n")

    exit(0 if all_passed else 1)
